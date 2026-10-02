"""Memory and Context Manager.

Thin wrapper around memory_tool used by the LangGraph workflow to load
context before query handling and persist the interaction afterwards.
"""

from app.tools import memory_tool


def load(customer_id: str) -> dict:
    """Load prior conversation context for a customer."""
    return memory_tool.load_memory(customer_id)


def save(customer_id: str, user_message: str, system_response: str, intent: str, action: str) -> bool:
    """Persist the latest interaction."""
    return memory_tool.save_interaction(
        customer_id=customer_id,
        user_message=user_message,
        system_response=system_response,
        intent=intent,
        action=action,
    )


def clear(customer_id: str) -> bool:
    return memory_tool.clear_memory(customer_id)
