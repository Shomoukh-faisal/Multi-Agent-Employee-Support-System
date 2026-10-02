"""Pydantic schemas shared across the API, agents and workflow."""

from typing import Optional

from pydantic import BaseModel, Field


class SupportRequest(BaseModel):
    """Incoming customer message."""

    customer_id: str
    message: str


class IntentResult(BaseModel):
    """Output of the Query Handler agent."""

    intent: str
    confidence: float = 0.0
    entities: dict = Field(default_factory=dict)
    needs_clarification: bool = False
    clarification_question: Optional[str] = None


class SupportResponse(BaseModel):
    """Structured response returned by the backend for every request."""

    customer_id: str
    intent: str
    agent: str
    action: str
    message: str
    tool_used: Optional[str] = None
    data: dict = Field(default_factory=dict)
    escalated: bool = False
    escalation_reason: Optional[str] = None
    memory_updated: bool = False
    # --- diagnostics (surfaced in the GUI to show the pipeline working) ---
    confidence: float = 0.0
    entities: dict = Field(default_factory=dict)
    pipeline: list = Field(default_factory=list)
