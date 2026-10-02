"""Complaint log tool. Reads complaint history and appends new complaints.

New complaint ids auto-increment in the form CMP-001, CMP-002, ...
"""

import csv
import os
from datetime import date
from typing import List

import pandas as pd

from app import config

_FIELDS = [
    "complaint_id",
    "customer_id",
    "order_id",
    "issue",
    "status",
    "priority",
    "created_at",
    "escalation_required",
]


def _read_complaints() -> pd.DataFrame:
    try:
        return pd.read_csv(config.COMPLAINTS_CSV, dtype=str).fillna("")
    except FileNotFoundError:
        return pd.DataFrame(columns=_FIELDS)
    except Exception:
        return pd.DataFrame(columns=_FIELDS)


def get_complaint_history(customer_id: str) -> List[dict]:
    """Return all complaints filed by a customer (possibly empty)."""
    if not customer_id:
        return []
    df = _read_complaints()
    if df.empty or "customer_id" not in df.columns:
        return []
    matches = df[df["customer_id"].str.upper() == customer_id.strip().upper()]
    return matches.to_dict(orient="records")


def _next_complaint_id(df: pd.DataFrame) -> str:
    """Compute the next CMP-### id based on existing rows."""
    max_num = 0
    if not df.empty and "complaint_id" in df.columns:
        for cid in df["complaint_id"].tolist():
            try:
                num = int(str(cid).split("-")[-1])
                max_num = max(max_num, num)
            except (ValueError, IndexError):
                continue
    return f"CMP-{max_num + 1:03d}"


def create_complaint(
    customer_id: str,
    order_id: str,
    issue: str,
    priority: str = "Medium",
    escalation_required: bool = False,
) -> dict:
    """Append a new complaint row to complaints.csv and return it."""
    df = _read_complaints()
    complaint_id = _next_complaint_id(df)

    row = {
        "complaint_id": complaint_id,
        "customer_id": customer_id,
        "order_id": order_id or "",
        "issue": issue or "Unspecified issue",
        "status": "Open",
        "priority": priority or "Medium",
        "created_at": date.today().isoformat(),
        "escalation_required": str(bool(escalation_required)),
    }

    # Ensure the data directory and a header exist, then append.
    os.makedirs(os.path.dirname(config.COMPLAINTS_CSV), exist_ok=True)
    file_exists = os.path.exists(config.COMPLAINTS_CSV) and os.path.getsize(
        config.COMPLAINTS_CSV
    ) > 0

    try:
        with open(config.COMPLAINTS_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_FIELDS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception as exc:  # pragma: no cover
        return {"created": False, "error": str(exc)}

    row["created"] = True
    return row
