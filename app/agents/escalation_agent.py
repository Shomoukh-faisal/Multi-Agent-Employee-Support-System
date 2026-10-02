"""Escalation agent.

Produces an escalation decision and a concise human-support ticket summary.

Escalates when:
  * Gemini confidence < 0.6
  * intent is unknown
  * a repeated complaint exists for the customer
  * the user explicitly asks for human support
  * required data is unavailable
"""

from app import gemini_client
from app.tools import complaint_tool


def _summary(reason: str, customer_id: str, message: str) -> str:
    """Generate a short human-readable ticket summary."""
    fallback = (
        f"Escalation ticket for {customer_id}. Reason: {reason} "
        f"Suggested action: assign to a human support agent for review."
    )
    if not gemini_client.is_available():
        return fallback
    prompt = (
        "Write a 1-2 sentence internal ticket summary for a human support "
        "agent. Be factual and concise.\n\n"
        f"Customer: {customer_id}\nMessage: {message}\nReason: {reason}\n\nSummary:"
    )
    return gemini_client.generate_text(prompt) or fallback


def handle(intent: str, entities: dict, confidence: float, customer_id: str, message: str) -> dict:
    reasons = []

    if entities.get("wants_human"):
        reasons.append("Customer explicitly requested human support.")
    if intent == "unknown":
        reasons.append("The request could not be understood (unknown intent).")
    if confidence < 0.6:
        reasons.append(f"Low classification confidence ({confidence:.2f}).")

    history = complaint_tool.get_complaint_history(customer_id)
    if len(history) >= 2:
        reasons.append("Customer has repeated complaints on record.")

    if not reasons:
        reasons.append("Case requires human judgement or data was unavailable.")

    reason_text = " ".join(reasons)
    summary = _summary(reason_text, customer_id, message)

    return {
        "action": "escalated_to_human",
        "message": (
            "I'm connecting you with a human support agent who can help further. "
            "They'll have the full context of this conversation."
        ),
        "tool_used": "complaint_tool",
        "data": {
            "ticket_summary": summary,
            "suggested_human_action": "Assign to a support specialist and contact the customer.",
            "prior_complaint_count": len(history),
        },
        "escalated": True,
        "escalation_reason": reason_text,
        "needs_clarification": False,
        "clarification_question": None,
    }
