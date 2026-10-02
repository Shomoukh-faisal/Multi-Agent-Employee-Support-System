"""Complaint Handling agent.

Logs a complaint, checks complaint history and order status, and decides
whether the case must be escalated to a human.

Escalation rules:
  * repeated complaints (history count for this customer >= 2)
  * the related order status is 'Delayed'
  * urgency is high
  * the customer explicitly asked for human support
"""

from app import gemini_client
from app.tools import complaint_tool, order_tool


_ORDER_ONLY_WORDS = {
    "sorry",
    "correct",
    "correction",
    "actually",
    "maybe",
    "it",
    "is",
    "the",
    "order",
    "id",
    "ord",
}


def _complaint_sort_key(complaint: dict) -> tuple:
    complaint_id = complaint.get("complaint_id", "")
    try:
        number = int(str(complaint_id).split("-")[-1])
    except (TypeError, ValueError, IndexError):
        number = 0
    return (complaint.get("created_at", ""), number)


def _select_existing_complaint(history: list, order_id: str = "") -> dict | None:
    """Return the most relevant existing complaint for this customer/order."""
    if not history:
        return None

    matches = history
    if order_id:
        normalized = order_id.strip().upper()
        matches = [
            item
            for item in history
            if item.get("order_id", "").strip().upper() == normalized
        ]

    matches = [
        item
        for item in matches
        if not _is_only_order_reference(
            item.get("issue", ""),
            item.get("order_id", ""),
        )
    ]

    if not matches:
        return None
    return sorted(matches, key=_complaint_sort_key)[-1]


def _order_privacy_response(order_id: str) -> dict:
    return {
        "action": "order_not_owned",
        "message": (
            f"Order {order_id} is not linked to your customer account. "
            "Please check your order ID and try again."
        ),
        "tool_used": "order_tool",
        "data": {
            "order_id": order_id,
            "belongs_to_customer": False,
        },
        "escalated": False,
        "escalation_reason": None,
        "needs_clarification": True,
        "clarification_question": "Please share an order ID linked to your account.",
    }


def _order_belongs_to_customer(order_id: str, customer_id: str) -> bool:
    if not order_id:
        return True
    order = order_tool.get_order_by_id(order_id, customer_id)
    return bool(order.get("found") and order.get("belongs_to_customer", True))


def _authorized_complaint_history(history: list, customer_id: str) -> list:
    """Keep only complaints that do not point at another customer's order."""
    authorized = []
    for complaint in history:
        order_id = complaint.get("order_id", "")
        if _is_only_order_reference(complaint.get("issue", ""), order_id):
            continue
        if _order_belongs_to_customer(order_id, customer_id):
            authorized.append(complaint)
    return authorized


def _is_complaint_lookup(issue: str) -> bool:
    text = (issue or "").lower()
    return "complaint" in text and any(
        word in text
        for word in ("id", "number", "status", "update", "updates", "reference")
    )


def _is_only_order_reference(issue: str, order_id: str) -> bool:
    """True when the message is just a corrected/provided order id."""
    if not issue or not order_id:
        return False
    lowered = issue.lower().replace(order_id.lower(), " ")
    words = [word for word in lowered.replace("-", " ").split() if word.strip(",.?!")]
    return all(word.strip(",.?!") in _ORDER_ONLY_WORDS for word in words)


def _ask_for_order_id() -> dict:
    question = (
        "Sure, I can help you open a complaint. Please share the order ID first "
        "so I can verify it is linked to your account."
    )
    return {
        "action": "complaint_order_requested",
        "message": question,
        "tool_used": None,
        "data": {},
        "escalated": False,
        "escalation_reason": None,
        "needs_clarification": True,
        "clarification_question": question,
    }


def _ask_for_complaint_details(order_id: str, order_status: str | None = None) -> dict:
    status_part = (
        f"I found order {order_id} and its status is '{order_status}'."
        if order_status
        else f"I found order {order_id}."
    )
    question = (
        f"{status_part} Please tell me what happened so I can record the complaint."
    )
    return {
        "action": "complaint_issue_requested",
        "message": question,
        "tool_used": "order_tool",
        "data": {
            "order_id": order_id,
            "order_status": order_status,
        },
        "escalated": False,
        "escalation_reason": None,
        "needs_clarification": True,
        "clarification_question": question,
    }


def _existing_complaint_response(
    complaint: dict,
    prior_count: int,
    order_status: str | None = None,
) -> dict:
    complaint_id = complaint.get("complaint_id", "N/A")
    status = complaint.get("status", "Unknown")
    priority = complaint.get("priority", "Unknown")
    order_id = complaint.get("order_id") or "not linked to an order"
    issue = complaint.get("issue") or "No issue description recorded"
    created_at = complaint.get("created_at") or "unknown date"

    order_part = f" The related order is currently '{order_status}'." if order_status else ""
    return {
        "action": "complaint_existing_update",
        "message": (
            f"You already have an open complaint about this:\n"
            f"• Complaint ID: {complaint_id}\n"
            f"• Order: {order_id}\n"
            f"• Issue: {issue}\n"
            f"• Status: {status} (priority: {priority})\n"
            f"• Created: {created_at}.{order_part}\n\n"
            f"Would you like me to (1) escalate this to a human agent, "
            f"(2) add new details to it, or (3) file a separate new complaint? "
            f"You can also just say 'no thanks' if you're done."
        ),
        "tool_used": "complaint_tool",
        "data": {
            "complaint": complaint,
            "prior_complaint_count": prior_count,
            "order_status": order_status,
        },
        "escalated": False,
        "escalation_reason": None,
        "needs_clarification": True,
        "clarification_question": (
            "Would you like to escalate, add details, or open a new complaint?"
        ),
    }


def _polish(facts: str, fallback: str) -> str:
    if not gemini_client.is_available():
        return fallback
    prompt = (
        "You are an empathetic support employee. Using ONLY the facts below, "
        "write a short, reassuring reply confirming the complaint was logged "
        "and what happens next. Do not invent details.\n\n"
        f"Facts:\n{facts}\n\nReply:"
    )
    return gemini_client.generate_text(prompt) or fallback


def _escalate_existing_complaint(
    complaint_id: str,
    entities: dict,
    customer_id: str,
) -> dict:
    """Customer returned about an unresolved complaint — escalate it to a human.

    Does NOT create a new complaint row (we don't want duplicates). Produces an
    escalation outcome citing the existing complaint as the case to act on.
    """
    history = complaint_tool.get_complaint_history(customer_id)
    existing = next(
        (c for c in history if c.get("complaint_id") == complaint_id), None
    )
    if not existing:
        # Lost the reference somehow — fall back to a generic escalation.
        return {
            "action": "escalated_to_human",
            "message": (
                "I'm escalating this issue to a human support agent right now. "
                "They'll follow up with you shortly."
            ),
            "tool_used": "complaint_tool",
            "data": {"new_details": entities.get("complaint_issue", "")},
            "escalated": True,
            "escalation_reason": "Customer returned about an unresolved complaint.",
            "needs_clarification": False,
            "clarification_question": None,
        }

    new_details = (entities.get("complaint_issue") or "").strip()
    order_ref = existing.get("order_id") or "this issue"
    issue = existing.get("issue") or "the previous issue"
    reason = (
        f"Customer returned about unresolved complaint {complaint_id} "
        f"({issue}) for {order_ref}."
    )
    if new_details:
        reason += f" New details from customer: {new_details}"

    facts = (
        f"Customer is following up on complaint {complaint_id} about {issue} "
        f"(order {order_ref}). It is being escalated to a human agent."
    )
    fallback = (
        f"I understand — I'm escalating your complaint {complaint_id} about "
        f"{order_ref} to a human support agent right now. They'll review the "
        f"full case and follow up with you shortly. I'm sorry for the trouble."
    )
    return {
        "action": "complaint_existing_escalated",
        "message": _polish(facts, fallback),
        "tool_used": "complaint_tool",
        "data": {
            "complaint": existing,
            "new_details": new_details,
        },
        "escalated": True,
        "escalation_reason": reason,
        "needs_clarification": False,
        "clarification_question": None,
    }


def _initial_message_needs_escalation(
    issue: str, entities: dict, order_status: str | None = None
) -> bool:
    """Heuristic for first-time complaint messages that already warrant escalation."""
    if (order_status or "").strip() == "Delayed":
        return True
    if (entities.get("urgency") or "").lower() == "high":
        return True
    if entities.get("wants_human"):
        return True
    text = (issue or "").lower()
    return any(
        cue in text
        for cue in (
            "urgent", "asap", "immediately", "still not", "still no",
            "no one helped", "nobody helped", "no response", "no resolution",
            "unacceptable",
        )
    )


def _note_existing_complaint(
    complaint_id: str,
    entities: dict,
    customer_id: str,
) -> dict:
    """Acknowledge extra info from the customer and offer escalation."""
    history = complaint_tool.get_complaint_history(customer_id)
    existing = next(
        (c for c in history if c.get("complaint_id") == complaint_id), None
    )
    new_details = (entities.get("complaint_issue") or "").strip()
    return {
        "action": "complaint_existing_noted",
        "message": (
            f"Thanks for the extra information. I've noted it against complaint "
            f"{complaint_id}. Would you like me to escalate this to a human "
            f"agent so they can prioritise it?"
        ),
        "tool_used": "complaint_tool",
        "data": {
            "complaint": existing,
            "new_details": new_details,
        },
        "escalated": False,
        "escalation_reason": None,
        "needs_clarification": True,
        "clarification_question": (
            "Would you like to escalate this complaint to a human agent?"
        ),
    }


def handle(entities: dict, customer_id: str) -> dict:
    order_id = entities.get("order_id") or ""
    issue = (entities.get("complaint_issue") or "").strip()
    urgency = (entities.get("urgency") or "medium").lower()
    wants_human = bool(entities.get("wants_human"))

    # --- Follow-up after we showed the customer an existing complaint -------
    existing_id = entities.get("existing_complaint_id")
    follow_up = entities.get("follow_up_action")
    if existing_id and follow_up == "escalate":
        return _escalate_existing_complaint(existing_id, entities, customer_id)
    if existing_id and follow_up == "update":
        return _note_existing_complaint(existing_id, entities, customer_id)
    # follow_up == "new" falls through to the normal new-complaint flow below.

    raw_history = complaint_tool.get_complaint_history(customer_id)
    history = _authorized_complaint_history(raw_history, customer_id)
    prior_count = len(history)
    order_status = None

    if not order_id:
        return _ask_for_order_id()

    if order_id:
        order = order_tool.get_order_by_id(order_id, customer_id)
        if not order.get("found"):
            return {
                "action": "complaint_order_not_found",
                "message": (
                    f"I couldn't find an order with the ID {order_id}. "
                    "Please double-check the number so I can file the complaint correctly."
                ),
                "tool_used": "order_tool",
                "data": {"order": order},
                "escalated": False,
                "escalation_reason": None,
                "needs_clarification": True,
                "clarification_question": "What is the correct order ID?",
            }
        if customer_id and not order.get("belongs_to_customer", True):
            return _order_privacy_response(order_id)
        order_status = order.get("status")

    existing_complaint = _select_existing_complaint(history, order_id)
    if (
        existing_complaint
        and (order_id or _is_complaint_lookup(issue))
        and follow_up != "new"
    ):
        # If the customer's initial message is already urgent or asks for a
        # human, don't just re-show the existing complaint — escalate it now.
        if _initial_message_needs_escalation(issue, entities, order_status):
            return _escalate_existing_complaint(
                existing_complaint.get("complaint_id", ""), entities, customer_id
            )
        return _existing_complaint_response(
            existing_complaint,
            prior_count,
            order_status,
        )

    if _is_complaint_lookup(issue):
        latest_complaint = _select_existing_complaint(history)
        if latest_complaint:
            latest_order_id = latest_complaint.get("order_id", "")
            latest_order_status = None
            if latest_order_id:
                order = order_tool.get_order_by_id(latest_order_id, customer_id)
                if order.get("found") and order.get("belongs_to_customer", True):
                    latest_order_status = order.get("status")
            return _existing_complaint_response(
                latest_complaint,
                prior_count,
                latest_order_status,
            )

    if not issue or _is_only_order_reference(issue, order_id):
        return _ask_for_complaint_details(order_id, order_status)

    if order_id:
        order = order_tool.get_order_by_id(order_id, customer_id)
        if not order.get("found"):
            return {
                "action": "complaint_order_not_found",
                "message": (
                    f"I couldn't find an order with the ID {order_id}. "
                    "Please double-check the number so I can file the complaint correctly."
                ),
                "tool_used": "order_tool",
                "data": {"order": order},
                "escalated": False,
                "escalation_reason": None,
                "needs_clarification": True,
                "clarification_question": "What is the correct order ID?",
            }
        if customer_id and not order.get("belongs_to_customer", True):
            return _order_privacy_response(order_id)
        order_status = order.get("status")

    # Decide escalation + priority.
    escalation_reasons = []
    if prior_count >= 2:
        escalation_reasons.append("Customer has 2 or more prior complaints (repeated issue).")
    if order_status == "Delayed":
        escalation_reasons.append("The related order is marked as Delayed.")
    if urgency == "high":
        escalation_reasons.append("Customer marked the issue as high urgency.")
    if wants_human:
        escalation_reasons.append("Customer explicitly requested human support.")

    escalate = len(escalation_reasons) > 0
    priority = "High" if escalate else ("High" if urgency == "high" else "Medium")

    # Create the complaint record.
    complaint = complaint_tool.create_complaint(
        customer_id=customer_id,
        order_id=order_id,
        issue=issue,
        priority=priority,
        escalation_required=escalate,
    )

    if not complaint.get("created"):
        error = complaint.get("error", "Unknown error")
        return {
            "action": "complaint_create_failed",
            "message": (
                "I could not save the complaint because of a system error. "
                "Please try again in a moment or contact support directly."
            ),
            "tool_used": "complaint_tool",
            "data": {
                "complaint": complaint,
                "prior_complaint_count": prior_count,
                "order_status": order_status,
                "error": error,
            },
            "escalated": False,
            "escalation_reason": None,
            "needs_clarification": False,
            "clarification_question": None,
        }

    complaint_id = complaint.get("complaint_id", "N/A")

    if escalate:
        facts = (
            f"Complaint {complaint_id} was logged with priority {priority}. "
            f"It is being escalated to a human agent. "
            f"Reasons: {' '.join(escalation_reasons)}"
        )
        fallback = (
            f"I've logged your complaint as {complaint_id} (priority {priority}) and "
            f"escalated it to a human support agent who will follow up with you. "
            f"I'm sorry for the trouble."
        )
        action = "complaint_created_and_escalated"
    else:
        facts = (
            f"Complaint {complaint_id} was logged with priority {priority}. "
            f"Our team will review it."
        )
        fallback = (
            f"I've logged your complaint as {complaint_id} (priority {priority}). "
            f"Our support team will review it and get back to you."
        )
        action = "complaint_created"

    message = _polish(facts, fallback)

    return {
        "action": action,
        "message": message,
        "tool_used": "complaint_tool",
        "data": {
            "complaint": complaint,
            "prior_complaint_count": prior_count,
            "order_status": order_status,
        },
        "escalated": escalate,
        "escalation_reason": " ".join(escalation_reasons) if escalate else None,
        "needs_clarification": False,
        "clarification_question": None,
    }
