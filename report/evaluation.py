"""Accuracy evaluation for the AI Support Employee.

Runs a labeled test set through the LangGraph workflow and reports:
  * intent-classification accuracy
  * escalation-decision accuracy
  * data-integrity check (no fabricated data for unknown IDs)
  * a few tool-data correctness spot checks

It is deterministic: complaint cases are evaluated against the seed complaint
log (reset before each complaint query) and customer memory is cleared per
query, so results are reproducible. The data files are restored at the end.

Run from the project root:  python report/evaluation.py
(Results reflect the rule-based fallback unless a GEMINI_API_KEY is set.)
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app import config, gemini_client  # noqa: E402
from app.graph import run_support_workflow  # noqa: E402
from app.tools import complaint_tool, memory_tool, order_tool  # noqa: E402

COMPLAINTS_SEED = (
    "complaint_id,customer_id,order_id,issue,status,priority,created_at,escalation_required\n"
    "CMP-001,CUST-01,ORD-1003,Late delivery,Open,High,2026-02-20,True\n"
    "CMP-002,CUST-02,ORD-1006,Wrong item delivered,Resolved,Medium,2026-02-14,False\n"
    "CMP-003,CUST-05,ORD-1008,Product arrived damaged,In Progress,High,2026-02-16,True\n"
    "CMP-004,CUST-07,ORD-1011,Refund delay,Open,Medium,2026-02-18,False\n"
)
MEMORY_SEED = {
    "CUST-06": [
        {
            "user_message": "Where is my order ORD-1009?",
            "system_response": "Your order ORD-1009 is currently 'Processing'. It is heading to "
            "Tabuk with a delivery date of 2026-03-05. Latest update: Order is being prepared.",
            "intent": "order_tracking",
            "action": "order_status_provided",
            "timestamp": "2026-03-01T10:15:00",
        }
    ]
}

# id, customer, message, expected_intent, expected_escalated, is_complaint
DATASET = [
    # --- order tracking (with id) ---
    ("T1", "CUST-02", "Where is my order ORD-1002?", "order_tracking", False, False),
    ("T2", "CUST-04", "Track ORD-1005 please", "order_tracking", False, False),
    ("T3", "CUST-05", "What is the status of ORD-1007?", "order_tracking", False, False),
    ("T4", "CUST-03", "ORD-1010 delivery status", "order_tracking", False, False),
    ("T5", "CUST-08", "Has ORD-1012 shipped yet?", "order_tracking", False, False),
    # --- product info ---
    ("P1", "CUST-01", "Tell me about product P-101.", "product_info", False, False),
    ("P2", "CUST-06", "What's the warranty on P-108?", "product_info", False, False),
    ("P3", "CUST-02", "price of P-110", "product_info", False, False),
    ("P4", "CUST-05", "How much does the Bukhoor Incense Burner cost?", "product_info", False, False),
    ("P5", "CUST-04", "details about P-109", "product_info", False, False),
    # --- explicit escalation ---
    ("E1", "CUST-02", "I want to speak to a human.", "escalation", True, False),
    ("E2", "CUST-04", "Can I talk to a real person?", "escalation", True, False),
    ("E3", "CUST-06", "connect me to an agent", "escalation", True, False),
    ("E4", "CUST-01", "I need to speak to your manager", "escalation", True, False),
    # --- clarification / greetings ---
    ("C1", "CUST-02", "Where is my order?", "clarification", False, False),
    ("C2", "CUST-05", "hi", "clarification", False, False),
    ("C3", "CUST-03", "hello there", "clarification", False, False),
    ("C4", "CUST-04", "thanks a lot!", "clarification", False, False),
    ("C5", "CUST-08", "good morning", "clarification", False, False),
    # --- complaints (reset to seed before each) ---
    ("M1", "CUST-01", "I want to complain about order ORD-1003. It is late.", "complaint", True, True),
    ("M2", "CUST-05", "I want to complain about ORD-1008, it arrived damaged.", "complaint", False, True),
    ("M3", "CUST-08", "My order ORD-1012 is wrong, I want a refund.", "complaint", False, True),
    ("M4", "CUST-07", "Complaint about ORD-1011: refund not received, this is urgent.", "complaint", True, True),
    ("M5", "CUST-03", "ORD-1010 is broken after one day, very disappointed.", "complaint", False, True),
    # --- hard paraphrases (stress the classifier) ---
    ("H1", "CUST-01", "I need help", "clarification", False, False),
    ("H2", "CUST-04", "is the smart watch waterproof?", "product_info", False, False),
    ("H3", "CUST-02", "my package never showed up", "complaint", False, False),
]


def reset_complaints():
    with open(config.COMPLAINTS_CSV, "w", encoding="utf-8") as f:
        f.write(COMPLAINTS_SEED)


def restore_state():
    reset_complaints()
    with open(config.MEMORY_JSON, "w", encoding="utf-8") as f:
        json.dump(MEMORY_SEED, f, indent=2, ensure_ascii=False)


def main():
    print("=" * 70)
    print("AI Support Employee — Accuracy Evaluation")
    print("Mode:", "Gemini" if gemini_client.is_available() else "Rule-based fallback")
    print("=" * 70)

    intent_correct = esc_correct = 0
    per_intent = {}
    rows = []

    for qid, cust, msg, exp_intent, exp_esc, is_cmp in DATASET:
        memory_tool.clear_memory(cust)
        if is_cmp:
            reset_complaints()
        r = run_support_workflow(cust, msg)
        got_intent = r["intent"]
        got_esc = r["escalated"]

        i_ok = got_intent == exp_intent
        e_ok = got_esc == exp_esc
        intent_correct += i_ok
        esc_correct += e_ok

        d = per_intent.setdefault(exp_intent, {"n": 0, "ok": 0})
        d["n"] += 1
        d["ok"] += i_ok

        rows.append((qid, exp_intent, got_intent, i_ok, exp_esc, got_esc, e_ok, msg))

    total = len(DATASET)
    print(f"\n{'ID':<4}{'expected':<15}{'predicted':<15}{'int':<5}{'esc':<5} message")
    print("-" * 70)
    for qid, exp_i, got_i, i_ok, exp_e, got_e, e_ok, msg in rows:
        print(f"{qid:<4}{exp_i:<15}{got_i:<15}{'✓' if i_ok else '✗':<5}"
              f"{'✓' if e_ok else '✗':<5} {msg[:34]}")

    print("\n" + "-" * 70)
    print(f"Intent accuracy     : {intent_correct}/{total} = {intent_correct / total * 100:.1f}%")
    print(f"Escalation accuracy : {esc_correct}/{total} = {esc_correct / total * 100:.1f}%")
    print("\nPer-intent (correct / total):")
    for intent, d in sorted(per_intent.items()):
        print(f"  {intent:<16}{d['ok']}/{d['n']}")

    # Data-integrity check: unknown order id must not be fabricated.
    reset_complaints()
    memory_tool.clear_memory("CUST-02")
    r = run_support_workflow("CUST-02", "Where is my order ORD-9999?")
    integrity = (not r["data"].get("found", False)) and ("find" in r["message"].lower())
    print(f"\nData-integrity (ORD-9999 not fabricated): {'PASS' if integrity else 'FAIL'}")

    # Tool-data correctness spot checks against the CSVs.
    memory_tool.clear_memory("CUST-02")
    r1 = run_support_workflow("CUST-02", "Where is my order ORD-1002?")
    chk1 = r1["data"].get("status") == "In Transit" and r1["data"].get("shipping_city") == "Jeddah"
    r2 = run_support_workflow("CUST-01", "Tell me about product P-101.")
    chk2 = r2["data"].get("name") == "Smart Watch" and str(r2["data"].get("price")) == "299"
    print(f"Tool-data correctness (order status / product details): "
          f"{'PASS' if (chk1 and chk2) else 'FAIL'}")

    restore_state()
    print("\nData files restored to seed state.")
    print("=" * 70)


if __name__ == "__main__":
    main()
