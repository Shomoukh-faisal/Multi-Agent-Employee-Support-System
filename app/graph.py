"""LangGraph workflow that orchestrates the support agents.

Flow:
    START
      -> load_memory
      -> query_handler
      -> route_request  (conditional)
           -> support_resolution | complaint_handler | escalation_agent | clarification
      -> final_decision
      -> update_memory
    END
"""

from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents import (
    complaint_handler,
    escalation_agent,
    memory_manager,
    query_handler,
    support_resolution,
)


class SupportState(TypedDict, total=False):
    customer_id: str
    message: str
    memory: dict
    intent_result: dict
    selected_agent: str
    tool_result: dict
    final_response: dict
    escalated: bool


# --- Nodes ------------------------------------------------------------------
def node_load_memory(state: SupportState) -> SupportState:
    state["memory"] = memory_manager.load(state.get("customer_id", ""))
    return state


def node_query_handler(state: SupportState) -> SupportState:
    result = query_handler.classify(state.get("message", ""), state.get("memory", {}))
    state["intent_result"] = result
    return state


def node_support_resolution(state: SupportState) -> SupportState:
    ir = state["intent_result"]
    state["selected_agent"] = "support_resolution"
    state["tool_result"] = support_resolution.handle(
        ir["intent"], ir["entities"], state.get("customer_id", "")
    )
    return state


def node_complaint_handler(state: SupportState) -> SupportState:
    ir = state["intent_result"]
    state["selected_agent"] = "complaint_handler"
    state["tool_result"] = complaint_handler.handle(
        ir["entities"], state.get("customer_id", "")
    )
    return state


def node_escalation_agent(state: SupportState) -> SupportState:
    ir = state["intent_result"]
    state["selected_agent"] = "escalation_agent"
    state["tool_result"] = escalation_agent.handle(
        ir["intent"],
        ir["entities"],
        ir.get("confidence", 0.0),
        state.get("customer_id", ""),
        state.get("message", ""),
    )
    return state


def node_clarification(state: SupportState) -> SupportState:
    ir = state["intent_result"]
    state["selected_agent"] = "query_handler"
    question = ir.get("clarification_question") or (
        "Could you give me a bit more detail so I can help — for example an "
        "order ID or product name?"
    )
    state["tool_result"] = {
        "action": "clarification_requested",
        "message": question,
        "tool_used": None,
        "data": {},
        "escalated": False,
        "escalation_reason": None,
        "needs_clarification": True,
        "clarification_question": question,
    }
    return state


def node_final_decision(state: SupportState) -> SupportState:
    """Assemble the structured SupportResponse-shaped dict."""
    ir = state["intent_result"]
    tr = state.get("tool_result", {})
    escalated = bool(tr.get("escalated", False))
    state["escalated"] = escalated

    selected = state.get("selected_agent", "query_handler")
    pipeline = [
        "load_memory",
        "query_handler",
        "route_request",
        selected,
        "final_decision",
        "update_memory",
    ]

    state["final_response"] = {
        "customer_id": state.get("customer_id", ""),
        "intent": ir.get("intent", "unknown"),
        "agent": selected,
        "action": tr.get("action", "no_action"),
        "message": tr.get("message", "I'm here to help."),
        "tool_used": tr.get("tool_used"),
        "data": tr.get("data", {}),
        "escalated": escalated,
        "escalation_reason": tr.get("escalation_reason"),
        "memory_updated": False,  # set by update_memory node
        "confidence": float(ir.get("confidence", 0.0)),
        "entities": ir.get("entities", {}),
        "pipeline": pipeline,
    }
    return state


def node_update_memory(state: SupportState) -> SupportState:
    fr = state["final_response"]
    ok = memory_manager.save(
        customer_id=state.get("customer_id", ""),
        user_message=state.get("message", ""),
        system_response=fr.get("message", ""),
        intent=fr.get("intent", ""),
        action=fr.get("action", ""),
    )
    fr["memory_updated"] = bool(ok)
    state["final_response"] = fr
    return state


# --- Routing ----------------------------------------------------------------
def route_request(state: SupportState) -> str:
    """Pick the next node based on the classified intent."""
    ir = state.get("intent_result", {})
    intent = ir.get("intent", "unknown")

    if ir.get("needs_clarification") or intent == "clarification":
        return "clarification"
    if intent in ("order_tracking", "product_info"):
        return "support_resolution"
    if intent == "complaint":
        return "complaint_handler"
    if intent == "escalation":
        return "escalation_agent"
    # unknown / unrecognized -> ask for clarification (do NOT escalate small talk)
    return "clarification"


# --- Build & compile --------------------------------------------------------
def build_graph():
    workflow = StateGraph(SupportState)

    workflow.add_node("load_memory", node_load_memory)
    workflow.add_node("query_handler", node_query_handler)
    workflow.add_node("support_resolution", node_support_resolution)
    workflow.add_node("complaint_handler", node_complaint_handler)
    workflow.add_node("escalation_agent", node_escalation_agent)
    workflow.add_node("clarification", node_clarification)
    workflow.add_node("final_decision", node_final_decision)
    workflow.add_node("update_memory", node_update_memory)

    workflow.add_edge(START, "load_memory")
    workflow.add_edge("load_memory", "query_handler")

    workflow.add_conditional_edges(
        "query_handler",
        route_request,
        {
            "support_resolution": "support_resolution",
            "complaint_handler": "complaint_handler",
            "escalation_agent": "escalation_agent",
            "clarification": "clarification",
        },
    )

    for agent_node in (
        "support_resolution",
        "complaint_handler",
        "escalation_agent",
        "clarification",
    ):
        workflow.add_edge(agent_node, "final_decision")

    workflow.add_edge("final_decision", "update_memory")
    workflow.add_edge("update_memory", END)

    return workflow.compile()


# Compile once at import time and reuse.
_COMPILED = build_graph()


def run_support_workflow(customer_id: str, message: str) -> dict:
    """Run the full workflow and return the structured response dict."""
    initial: SupportState = {"customer_id": customer_id, "message": message}
    final_state = _COMPILED.invoke(initial)
    return final_state["final_response"]
