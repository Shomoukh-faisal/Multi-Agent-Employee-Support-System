"""Reusable Gemini client built on the official google-genai SDK.

The client degrades gracefully:
  * If no API key is configured, generate_text returns "" and generate_json
    returns {} so callers can fall back to deterministic rule-based logic.
  * generate_json always returns a dict, even when the model produces invalid
    or fenced JSON.
"""

import json
import re
from typing import Optional

from app import config

# Import the SDK lazily so the rest of the project still imports/runs even if
# google-genai is not installed (useful for offline grading of the tools).
try:
    from google import genai  # type: ignore

    _SDK_AVAILABLE = True
except Exception:  # pragma: no cover - only when SDK missing
    genai = None  # type: ignore
    _SDK_AVAILABLE = False


_client = None  # cached singleton


def _get_client():
    """Return a cached genai.Client, or None if it cannot be created."""
    global _client
    if _client is not None:
        return _client
    if not _SDK_AVAILABLE or not config.GEMINI_API_KEY:
        return None
    try:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    except Exception:
        _client = None
    return _client


def is_available() -> bool:
    """True when the SDK is installed and an API key is configured."""
    return _SDK_AVAILABLE and bool(config.GEMINI_API_KEY)


def generate_text(prompt: str) -> str:
    """Generate plain text. Returns "" on any failure (caller handles fallback)."""
    client = _get_client()
    if client is None:
        return ""
    try:
        response = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
        )
        return (getattr(response, "text", "") or "").strip()
    except Exception:
        return ""


def _extract_json(text: str) -> Optional[dict]:
    """Best-effort extraction of a JSON object from a model response."""
    if not text:
        return None

    # Strip Markdown code fences such as ```json ... ```
    cleaned = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()

    # First try the whole thing.
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    # Fall back to the first {...} block found in the text.
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def generate_json(prompt: str) -> dict:
    """Generate a JSON object. Always returns a dict ({} on failure)."""
    raw = generate_text(prompt + "\n\nReturn ONLY valid minified JSON, no prose, no code fences.")
    parsed = _extract_json(raw)
    return parsed if isinstance(parsed, dict) else {}
