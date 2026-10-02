"""FastAPI backend for the AI Support Employee."""

from fastapi import FastAPI, HTTPException

from app import config, gemini_client
from app.graph import run_support_workflow
from app.schemas import SupportRequest, SupportResponse
from app.tools import complaint_tool, memory_tool, order_tool

app = FastAPI(
    title="AI Support Employee",
    description="Agentic AI customer support system (FastAPI + LangGraph + Gemini).",
    version="1.0.0",
)


@app.get("/")
def root() -> dict:
    """Health check + basic info."""
    return {
        "service": "AI Support Employee",
        "status": "online",
        "gemini_enabled": gemini_client.is_available(),
        "model": config.GEMINI_MODEL,
        "endpoints": [
            "POST /support/chat",
            "GET /orders/{customer_id}",
            "GET /complaints/{customer_id}",
            "DELETE /memory/{customer_id}",
        ],
    }


@app.post("/support/chat", response_model=SupportResponse)
def support_chat(request: SupportRequest) -> SupportResponse:
    """Main entry point: run the agentic workflow for a customer message."""
    if not request.customer_id.strip():
        raise HTTPException(status_code=400, detail="customer_id is required")
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message is required")

    result = run_support_workflow(request.customer_id.strip(), request.message.strip())
    return SupportResponse(**result)


@app.get("/orders/{customer_id}")
def get_orders(customer_id: str) -> dict:
    """List all orders for a customer."""
    orders = order_tool.get_customer_orders(customer_id)
    return {"customer_id": customer_id, "count": len(orders), "orders": orders}


@app.get("/complaints/{customer_id}")
def get_complaints(customer_id: str) -> dict:
    """List all complaints for a customer."""
    complaints = []
    for complaint in complaint_tool.get_complaint_history(customer_id):
        order_id = complaint.get("order_id", "")
        if order_id:
            order = order_tool.get_order_by_id(order_id, customer_id)
            if order.get("found") and not order.get("belongs_to_customer", True):
                continue
        complaints.append(complaint)
    return {"customer_id": customer_id, "count": len(complaints), "complaints": complaints}


@app.delete("/memory/{customer_id}")
def delete_memory(customer_id: str) -> dict:
    """Clear stored conversation memory for a customer."""
    ok = memory_tool.clear_memory(customer_id)
    return {"customer_id": customer_id, "cleared": ok}
