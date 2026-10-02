"""Conversation memory tool backed by a single JSON file.

Structure of memory.json:
    {
      "CUST-01": [
        {"user_message": "...", "system_response": "...",
         "intent": "...", "action": "...", "timestamp": "..."},
        ...
      ],
      ...
    }
"""

import json
import os
from datetime import datetime

from app import config


def _read_all() -> dict:
    """Load the whole memory store, returning {} on any problem."""
    try:
        with open(config.MEMORY_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    except Exception:
        return {}


def _write_all(data: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(config.MEMORY_JSON), exist_ok=True)
        with open(config.MEMORY_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def load_memory(customer_id: str) -> dict:
    """Return memory for one customer as {'customer_id', 'history'}."""
    if not customer_id:
        return {"customer_id": "", "history": []}
    store = _read_all()
    history = store.get(customer_id, [])
    if not isinstance(history, list):
        history = []
    return {"customer_id": customer_id, "history": history}


def save_interaction(
    customer_id: str,
    user_message: str,
    system_response: str,
    intent: str,
    action: str,
) -> bool:
    """Append one interaction to a customer's history."""
    if not customer_id:
        return False
    store = _read_all()
    history = store.get(customer_id, [])
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "user_message": user_message,
            "system_response": system_response,
            "intent": intent,
            "action": action,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
    )
    store[customer_id] = history
    return _write_all(store)


def clear_memory(customer_id: str) -> bool:
    """Remove all stored history for a customer."""
    if not customer_id:
        return False
    store = _read_all()
    if customer_id in store:
        del store[customer_id]
        return _write_all(store)
    return True
