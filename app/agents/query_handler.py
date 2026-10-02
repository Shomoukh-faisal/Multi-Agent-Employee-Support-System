"""Query Handler agent.

Classifies the customer message into one intent and extracts entities.
Uses Gemini when available, and a deterministic rule-based classifier as a
fallback so the system remains demonstrable without an API key.
"""

import re
from typing import Optional

from app import gemini_client

INTENTS = [
    "order_tracking",
    "product_info",
    "complaint",
    "escalation",
    "clarification",
    "unknown",
]

_CLASSIFY_PROMPT = """You are the intent-classification module of a customer support system.
Classify the customer message into exactly ONE intent from this list:
- order_tracking : the customer wants the status/location of an order
- product_info   : the customer asks about a product (price, warranty, details)
- complaint      : the customer reports a problem and wants it logged
- escalation     : the customer explicitly asks for a human / manager
- clarification  : the message is too vague to act on (missing key info), OR a greeting / thanks / small talk
- unknown        : none of the above

For greetings or small talk (e.g. "hi", "hello", "thanks"), use intent "clarification",
set needs_clarification true, and put a short friendly welcome in clarification_question.
Do NOT classify compliments, praise, or positive feedback as complaints.
If the customer only says they want to open/file/create a complaint but gives no actual
problem details, use intent "complaint" and leave complaint_issue null. The
complaint handler will ask for the order ID first, then the complaint details.
Only use "escalation" when the customer clearly asks for a human / manager.

Also extract these entities (use null when absent):
- order_id        (pattern like ORD-1234)
- product_id      (pattern like P-123)
- product_name    (free text product name)
- complaint_issue (short description of the problem)
- urgency         (one of: low, medium, high)
- wants_human     (true/false)

Conversation memory (recent turns, may be empty):
{memory}

Customer message:
"{message}"

Respond ONLY with JSON of this exact shape:
{{"intent": "...", "confidence": 0.0, "entities": {{"order_id": null, "product_id": null, "product_name": null, "complaint_issue": null, "urgency": null, "wants_human": false}}, "needs_clarification": false, "clarification_question": null}}
"""


# --- regex helpers used by both Gemini path and fallback --------------------
_ORDER_RE = re.compile(r"\bORD[-\s]?(\d{3,})\b", re.IGNORECASE)
_PRODUCT_RE = re.compile(r"\bP[-\s]?(\d{2,})\b", re.IGNORECASE)
_COMPLAINT_ID_RE = re.compile(r"\bCMP[-\s]?(\d{3,})\b", re.IGNORECASE)


def _load_product_names() -> list[str]:
    """Load product names from products.csv so the rule-based classifier
    can recognise messages like 'is the smart watch waterproof?' that name a
    product without giving its ID."""
    try:
        import csv as _csv  # local import keeps module load order safe
        from app import config as _cfg
        names = []
        with open(_cfg.PRODUCTS_CSV, encoding="utf-8") as f:
            for row in _csv.DictReader(f):
                name = (row.get("name") or "").strip().lower()
                if len(name) >= 4:
                    names.append(name)
        return names
    except Exception:
        return []


_PRODUCT_NAMES = _load_product_names()


def _mentions_product_name(text: str) -> Optional[str]:
    """Return the matched product name if the text mentions one, else None."""
    t = (text or "").lower()
    for n in _PRODUCT_NAMES:
        if n in t:
            return n
    return None


def _regex_order_id(text: str) -> Optional[str]:
    m = _ORDER_RE.search(text or "")
    return f"ORD-{m.group(1)}" if m else None


def _regex_product_id(text: str) -> Optional[str]:
    m = _PRODUCT_RE.search(text or "")
    return f"P-{m.group(1)}" if m else None


def _regex_complaint_id(text: str) -> Optional[str]:
    m = _COMPLAINT_ID_RE.search(text or "")
    return f"CMP-{m.group(1)}" if m else None


# Actions that terminate an in-progress complaint flow (a complaint is filed
# or filing definitively failed). NOTE: complaint_existing_update is NOT a
# terminator — after we show a customer their existing complaint, the very
# next message usually wants to act on it (escalate, add details, etc.), so
# the flow must continue.
_TERMINAL_COMPLAINT_ACTIONS = (
    "complaint_created",
    "complaint_created_and_escalated",
    "complaint_create_failed",
    "complaint_existing_escalated",
)


def _format_memory(memory: dict) -> str:
    history = (memory or {}).get("history", [])
    if not history:
        return "(no previous turns)"
    lines = []
    for turn in history[-4:]:
        lines.append(
            f"- user: {turn.get('user_message', '')} | intent: {turn.get('intent', '')}"
        )
    return "\n".join(lines)


def _fallback_classify(message: str, memory: dict) -> dict:
    """Deterministic classifier used when Gemini is unavailable."""
    text = (message or "").lower()
    order_id = _regex_order_id(message)
    product_id = _regex_product_id(message)

    wants_human = any(
        kw in text
        for kw in ["human", "agent", "representative", "real person", "manager", "speak to someone"]
    )
    high_urgency = any(kw in text for kw in ["urgent", "asap", "immediately", "now", "angry"])

    entities = {
        "order_id": order_id,
        "product_id": product_id,
        "product_name": None,
        "complaint_issue": None,
        "urgency": "high" if high_urgency else "medium",
        "wants_human": wants_human,
    }

    complaint_words = [
        "complain", "complaint", "broken", "late", "damaged",
        "wrong", "refund", "not working", "issue", "problem", "nobody helped",
        "didn't receive", "didnt receive", "not received", "not receive",
        "never received", "hasn't arrived", "hasnt arrived",
        "never showed up", "didn't show up", "didnt show up",
        "never arrived", "didn't arrive", "didnt arrive",
        "haven't arrived", "havent arrived", "package never", "order never",
    ]
    # Phrases that reference a previous turn -> resolve via conversation memory.
    follow_up_words = [
        "any update", "what about", "still", "any news", "that order",
        "same order", "last order", "previous", "i mean", "the delayed",
        "my last", "what's the status now",
    ]
    track_words = ["where", "track", "status", "delivered", "shipping", "arrive"]
    product_words = ["price", "cost", "warranty", "tell me about", "details", "specs", "product"]
    # Explicit help-request phrases. We keep these tight so we don't accidentally
    # catch things like "help me track my order" which should still ask for the
    # order ID. Matches the H1 case "I need help" by itself.
    help_words = [
        "i need help", "need help", "can you help",
        "help me", "i need assistance", "please help",
    ]

    is_follow_up = any(w in text for w in follow_up_words)
    is_help_request = any(w in text for w in help_words)
    matched_product_name = _mentions_product_name(text)

    # Greeting / small-talk detection (token-based to avoid substring matches).
    tokens = set(re.findall(r"[a-z']+", text))
    greeting_tokens = {"hi", "hello", "hey", "hiya", "howdy", "yo", "hola", "salam", "assalam"}
    thanks_tokens = {"thanks", "thank", "thankyou", "thx", "appreciate", "appreciated"}
    bye_tokens = {"bye", "goodbye", "cya"}
    starts_greeting = text.strip().startswith(("good morning", "good afternoon", "good evening"))
    is_greeting = bool(tokens & greeting_tokens) or starts_greeting
    is_thanks = bool(tokens & thanks_tokens)
    is_bye = bool(tokens & bye_tokens)

    intent = "unknown"
    confidence = 0.5
    needs_clarification = False
    clarification_question = None

    def _ask_for_order_id():
        return (
            "Sure — could you share your order ID (for example ORD-1002) "
            "so I can look it up?"
        )

    pending_complaint = _pending_complaint_context(memory)

    if wants_human:
        intent, confidence = "escalation", 0.9
    elif _is_positive_feedback(message):
        intent, confidence = "clarification", 0.85
        needs_clarification = True
        clarification_question = (
            "It sounds like you want to share a compliment or positive feedback. "
            "Please tell me what you would like to say, and I can help capture it."
        )
    elif pending_complaint and _continues_pending_complaint(message, pending_complaint):
        intent, confidence = "complaint", 0.82
        entities["order_id"] = order_id or _order_from_memory(memory)
        entities["complaint_issue"] = _complaint_issue_from_context(
            message, pending_complaint
        )
    elif _is_complaint_lookup(message):
        intent, confidence = "complaint", 0.8
        entities["order_id"] = order_id or _order_from_memory(memory)
        entities["complaint_issue"] = message
    elif order_id and any(w in text for w in complaint_words):
        # A complaint that names a specific order.
        intent, confidence = "complaint", 0.85
        entities["complaint_issue"] = message
    elif is_follow_up:
        # Try to continue the previous order thread from memory.
        recovered = order_id or _order_from_memory(memory)
        if recovered:
            intent, confidence = "order_tracking", 0.7
            entities["order_id"] = recovered
        else:
            intent, confidence = "clarification", 0.6
            needs_clarification = True
            clarification_question = "Which order are you asking about? Please share the order ID."
    elif any(w in text for w in complaint_words):
        intent, confidence = "complaint", 0.8
        entities["complaint_issue"] = message
    elif product_id or any(w in text for w in product_words) or matched_product_name:
        intent, confidence = "product_info", 0.8
        if matched_product_name and not entities.get("product_name"):
            entities["product_name"] = matched_product_name.title()
    elif order_id:
        intent, confidence = "order_tracking", 0.85
    elif any(w in text for w in track_words) or "order" in text:
        # A tracking question with no order id -> ask for it.
        intent, confidence = "clarification", 0.6
        needs_clarification = True
        clarification_question = _ask_for_order_id()
    elif is_greeting or is_thanks or is_bye:
        # Friendly small talk -> never escalate.
        intent, confidence = "clarification", 0.9
        needs_clarification = True
        if is_thanks:
            clarification_question = (
                "You're welcome! 😊 Is there anything else I can help with — "
                "tracking an order, product details, or a complaint?"
            )
        elif is_bye:
            clarification_question = "Thanks for chatting — have a great day! 👋"
        else:
            clarification_question = (
                "Hi! 👋 I'm your AI support assistant. I can help you track an order, "
                "get product details, or file a complaint. What can I help you with?"
            )
    elif is_help_request:
        # Generic help request with no other signal -> ask what they need help with.
        intent, confidence = "clarification", 0.85
        needs_clarification = True
        clarification_question = (
            "Sure, I'm here to help! Could you tell me what you need — "
            "tracking an order, product details, or filing a complaint?"
        )
    else:
        intent, confidence = "unknown", 0.3

    return {
        "intent": intent,
        "confidence": confidence,
        "entities": entities,
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question,
    }


_POSITIVE_FEEDBACK_RE = re.compile(
    r"\b(compliment|praise|positive feedback|appreciate|appreciation|commend|kudos)\b",
    re.IGNORECASE,
)

_COMPLAINT_DETAIL_RE = re.compile(
    r"\b(broken|late|delayed|damaged|wrong|refund|not working|issue|problem|"
    r"missing|defective|bad|poor|charged|overcharged|cancelled|canceled|"
    r"nobody helped|not delivered|lost)\b",
    re.IGNORECASE,
)

_GENERIC_COMPLAINT_RE = re.compile(
    r"\b(open|create|make|file|submit|raise|start|new|log)\b.*\b(complaint|complain)\b|"
    r"\b(complaint|complain)\b.*\b(open|create|make|file|submit|raise|start|new|log)\b",
    re.IGNORECASE,
)

_COMPLAINT_LOOKUP_RE = re.compile(
    r"\b(complaint|case|ticket)\b.*\b(id|number|status|update|updates|reference)\b|"
    r"\b(id|number|status|update|updates|reference)\b.*\b(complaint|case|ticket)\b",
    re.IGNORECASE,
)

_CORRECTION_RE = re.compile(
    r"\b(sorry|correct|correction|actually|i mean|the order is|order is)\b",
    re.IGNORECASE,
)


def _is_positive_feedback(message: str) -> bool:
    """Return true for compliments/positive feedback, not problem reports."""
    text = message or ""
    return bool(_POSITIVE_FEEDBACK_RE.search(text)) and not bool(
        _COMPLAINT_DETAIL_RE.search(text)
    )


def _is_complaint_lookup(message: str) -> bool:
    """Return true when the customer asks for an existing complaint id/status."""
    return bool(_COMPLAINT_LOOKUP_RE.search(message or ""))


def _is_generic_complaint_request(message: str, entities: dict) -> bool:
    """Detect a request to begin a complaint without the complaint details."""
    text = message or ""
    if not _GENERIC_COMPLAINT_RE.search(text):
        return False
    if _COMPLAINT_DETAIL_RE.search(text):
        return False
    issue = (entities or {}).get("complaint_issue")
    if issue and issue.strip() and issue.strip().lower() != text.strip().lower():
        return False
    return True


def _recent_complaint_flow_started(history: list) -> bool:
    """True when recent turns show the user is in the middle of filing a complaint."""
    for turn in reversed(history[-6:]):
        action = turn.get("action", "")
        intent = turn.get("intent", "")
        if action in _TERMINAL_COMPLAINT_ACTIONS:
            return False
        if intent == "complaint" and action in (
            "clarification_requested",
            "complaint_details_requested",
            "complaint_order_requested",
            "complaint_order_not_found",
            "complaint_issue_requested",
            "complaint_existing_update",
            "order_not_owned",
        ):
            return True
    return False


def _pending_complaint_context(memory: dict) -> Optional[dict]:
    """Recover the unresolved complaint context from saved conversation memory."""
    history = (memory or {}).get("history", [])
    if not history:
        return None

    # NEW: highest priority — the prior turn showed an existing complaint and
    # we're now waiting for the user to decide what to do with it.
    last = history[-1]
    if last.get("action") == "complaint_existing_update":
        order_id = (
            _regex_order_id(last.get("user_message", ""))
            or _regex_order_id(last.get("system_response", ""))
        )
        complaint_id = _regex_complaint_id(last.get("system_response", ""))
        return {
            "stage": "awaiting_existing_decision",
            "order_id": order_id,
            "complaint_id": complaint_id,
        }

    if not _recent_complaint_flow_started(history):
        return None

    order_id = None
    for turn in reversed(history[-6:]):
        user_message = turn.get("user_message", "")
        system_response = turn.get("system_response", "")
        action = turn.get("action", "")
        found_order = _regex_order_id(user_message) or _regex_order_id(system_response)
        if found_order and not order_id:
            order_id = found_order
        if action == "complaint_issue_requested":
            return {"stage": "issue", "order_id": order_id}
        if turn.get("intent") == "complaint" and action in (
            "clarification_requested",
            "complaint_details_requested",
            "complaint_order_requested",
            "complaint_order_not_found",
            "order_not_owned",
        ):
            return {"stage": "order", "order_id": order_id}

    return None


def _continues_pending_complaint(message: str, context: dict) -> bool:
    """Detect detail/correction messages that answer a complaint follow-up."""
    text = message or ""
    if (context or {}).get("stage") == "issue":
        return bool(text.strip())
    return bool(
        _regex_order_id(text)
        or _CORRECTION_RE.search(text)
        or _is_complaint_lookup(text)
    )


def _complaint_issue_from_context(message: str, context: dict) -> str:
    if (context or {}).get("stage") != "issue":
        return None
    return message


def _classify_existing_complaint_followup(message: str) -> str:
    """Decide what the customer wants after the bot showed them an existing complaint.

    Returns one of: "escalate", "update", "new", "done".
    """
    text = (message or "").lower()

    done_cues = (
        "never mind", "nevermind", "no thanks", "no thank", "that's all",
        "thats all", "all good", "i'm good", "im good", "im fine", "i'm fine",
        "no", "nope",
    )
    if any(c in text for c in done_cues) and len(text.strip().split()) <= 4:
        return "done"

    new_cues = (
        "new complaint", "different complaint", "another complaint",
        "separate complaint", "different order", "another order",
        "different issue", "different problem",
    )
    if any(c in text for c in new_cues):
        return "new"

    escalate_cues = (
        "escalat", "human", "agent", "manager", "real person", "still not",
        "still no", "didn't receive", "didnt receive", "didn't get", "didnt get",
        "never received", "not received", "no resolution", "no answer",
        "no response", "no one helped", "nobody helped", "no help",
        "urgent", "asap", "money", "refund", "unacceptable", "frustrated",
        "angry", "haven't received", "havent received", "untill now",
        "until now",
    )
    if any(c in text for c in escalate_cues):
        return "escalate"
    return "update"


def _apply_existing_complaint_followup(message, result, entities, pending):
    """Set up entities/intent for the follow-up turn after an existing complaint."""
    decision = _classify_existing_complaint_followup(message)

    if decision == "done":
        result["intent"] = "clarification"
        result["confidence"] = max(float(result.get("confidence", 0.0)), 0.9)
        result["needs_clarification"] = True
        result["clarification_question"] = (
            "No problem — is there anything else I can help you with?"
        )
        entities["complaint_issue"] = None
        result["entities"] = entities
        return result

    if decision == "new":
        # User wants a separate complaint. Try the current message first, then
        # fall back to the order we were just discussing so the customer
        # doesn't have to type the order ID again. They can still override by
        # supplying a different ORD-xxxx in their next message.
        recovered_order = (
            entities.get("order_id")
            or _regex_order_id(message)
            or pending.get("order_id")
        )
        result["intent"] = "complaint"
        result["confidence"] = max(float(result.get("confidence", 0.0)), 0.85)
        entities["order_id"] = recovered_order
        entities["complaint_issue"] = None
        entities["existing_complaint_id"] = None
        entities["follow_up_action"] = "new"
        result["entities"] = entities
        result["needs_clarification"] = False
        result["clarification_question"] = None
        return result

    # decision is "escalate" or "update" — both keep the existing complaint context.
    result["intent"] = "complaint"
    result["confidence"] = max(float(result.get("confidence", 0.0)), 0.85)
    entities["order_id"] = entities.get("order_id") or pending.get("order_id")
    entities["complaint_issue"] = message
    entities["existing_complaint_id"] = pending.get("complaint_id")
    entities["follow_up_action"] = decision  # "escalate" or "update"
    result["entities"] = entities
    result["needs_clarification"] = False
    result["clarification_question"] = None
    return result


def _postprocess(message: str, result: dict, memory: dict) -> dict:
    """Apply hard safety rules after LLM or fallback classification."""
    if _is_positive_feedback(message):
        result["intent"] = "clarification"
        result["confidence"] = max(float(result.get("confidence", 0.0)), 0.85)
        result["needs_clarification"] = True
        result["clarification_question"] = (
            "It sounds like you want to share a compliment or positive feedback. "
            "Please tell me what you would like to say, and I can help capture it."
        )
        result.setdefault("entities", {})["complaint_issue"] = None
        return result

    entities = result.get("entities") or {}
    pending_complaint = _pending_complaint_context(memory)

    # NEW: highest priority — handle the follow-up after we showed an existing
    # complaint. This fixes the bug where the next message got mis-routed back
    # to "please share your order id".
    if pending_complaint and pending_complaint.get("stage") == "awaiting_existing_decision":
        return _apply_existing_complaint_followup(
            message, result, entities, pending_complaint
        )

    if pending_complaint and _continues_pending_complaint(message, pending_complaint):
        entities["order_id"] = (
            entities.get("order_id")
            or _regex_order_id(message)
            or pending_complaint.get("order_id")
            or _order_from_memory(memory)
        )
        entities["complaint_issue"] = _complaint_issue_from_context(
            message, pending_complaint
        )
        result["intent"] = "complaint"
        result["confidence"] = max(float(result.get("confidence", 0.0)), 0.82)
        result["needs_clarification"] = False
        result["clarification_question"] = None

    if _is_complaint_lookup(message):
        entities["order_id"] = (
            entities.get("order_id") or _regex_order_id(message) or _order_from_memory(memory)
        )
        entities["complaint_issue"] = message
        result["intent"] = "complaint"
        result["confidence"] = max(float(result.get("confidence", 0.0)), 0.8)
        result["needs_clarification"] = False
        result["clarification_question"] = None

    if result.get("intent") == "complaint" and _is_generic_complaint_request(
        message, entities
    ):
        entities["complaint_issue"] = None
        result["entities"] = entities
        result["needs_clarification"] = False
        result["clarification_question"] = None

    # NEW: catch follow-up phrases like "any update?" or "what about it?" that
    # have no order id. The fallback classifier handles this directly, but the
    # Gemini path can return intent=clarification with no order id, which makes
    # the system look like it has no memory. Recover from memory here.
    text = (message or "").lower().strip()
    follow_up_cues = (
        "any update", "what about", "still", "any news", "that order",
        "same order", "last order", "previous order", "i mean", "the delayed",
        "my last order", "status now", "is it ready", "is it shipped",
    )
    if (
        not entities.get("order_id")
        and result.get("intent") in ("clarification", "unknown")
        and any(c in text for c in follow_up_cues)
    ):
        recovered = _order_from_memory(memory)
        if recovered:
            entities["order_id"] = recovered
            result["entities"] = entities
            result["intent"] = "order_tracking"
            result["confidence"] = max(float(result.get("confidence", 0.0)), 0.75)
            result["needs_clarification"] = False
            result["clarification_question"] = None
    return result


def _order_from_memory(memory: dict) -> Optional[str]:
    """Look back through memory for the most recent order id mentioned."""
    history = (memory or {}).get("history", [])
    for turn in reversed(history):
        for field in ("user_message", "system_response"):
            oid = _regex_order_id(turn.get(field, ""))
            if oid:
                return oid
    return None


def _normalise(result: dict) -> dict:
    """Guarantee all required keys exist and intent is valid."""
    entities = result.get("entities") or {}
    if not isinstance(entities, dict):
        entities = {}
    for key in ["order_id", "product_id", "product_name", "complaint_issue", "urgency"]:
        entities.setdefault(key, None)
    entities.setdefault("wants_human", False)

    intent = result.get("intent", "unknown")
    if intent not in INTENTS:
        intent = "unknown"

    try:
        confidence = float(result.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "intent": intent,
        "confidence": confidence,
        "entities": entities,
        "needs_clarification": bool(result.get("needs_clarification", False)),
        "clarification_question": result.get("clarification_question"),
    }


def classify(message: str, memory: dict) -> dict:
    """Return a normalised IntentResult-shaped dict for the message."""
    if gemini_client.is_available():
        prompt = _CLASSIFY_PROMPT.format(
            memory=_format_memory(memory), message=message.replace('"', "'")
        )
        raw = gemini_client.generate_json(prompt)
        if raw:
            result = _normalise(raw)
            # Backfill ids with regex if Gemini missed them.
            ents = result["entities"]
            ents["order_id"] = ents.get("order_id") or _regex_order_id(message)
            ents["product_id"] = ents.get("product_id") or _regex_product_id(message)
            # Recover order id from memory for vague follow-ups.
            if result["intent"] == "order_tracking" and not ents.get("order_id"):
                ents["order_id"] = _order_from_memory(memory)
            return _postprocess(message, result, memory)

    # No Gemini, or Gemini returned nothing usable.
    return _postprocess(message, _normalise(_fallback_classify(message, memory)), memory)
