"""Order data access tool (read-only).

All factual order data comes from orders.csv. Gemini is never allowed to
invent this data.
"""

from typing import List

import pandas as pd

from app import config


def _read_orders() -> pd.DataFrame:
    """Load orders.csv, returning an empty frame if the file is missing/bad."""
    try:
        df = pd.read_csv(config.ORDERS_CSV, dtype=str).fillna("")
        return df
    except FileNotFoundError:
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def get_order_by_id(order_id: str, customer_id: str = "") -> dict:
    """Return a single order by its id.

    Returns a dict with ``found`` set to False when the order does not exist.
    If ``customer_id`` is provided, ownership is reported via ``belongs_to_customer``.
    """
    if not order_id:
        return {"found": False, "reason": "missing_order_id"}

    df = _read_orders()
    if df.empty:
        return {"found": False, "reason": "no_data"}

    match = df[df["order_id"].str.upper() == order_id.strip().upper()]
    if match.empty:
        return {"found": False, "reason": "not_found", "order_id": order_id}

    order = match.iloc[0].to_dict()
    order["found"] = True
    if customer_id:
        order["belongs_to_customer"] = (
            order.get("customer_id", "").upper() == customer_id.strip().upper()
        )
    return order


def get_customer_orders(customer_id: str) -> List[dict]:
    """Return every order belonging to a customer (possibly empty list)."""
    if not customer_id:
        return []

    df = _read_orders()
    if df.empty:
        return []

    matches = df[df["customer_id"].str.upper() == customer_id.strip().upper()]
    return matches.to_dict(orient="records")
