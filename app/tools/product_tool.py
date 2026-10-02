"""Product knowledge-base tool (read-only) backed by products.csv."""

from typing import List, Union

import pandas as pd

from app import config


def _read_products() -> pd.DataFrame:
    try:
        return pd.read_csv(config.PRODUCTS_CSV, dtype=str).fillna("")
    except FileNotFoundError:
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def get_product_by_id(product_id: str) -> dict:
    """Return a single product by id, or {'found': False} when not present."""
    if not product_id:
        return {"found": False, "reason": "missing_product_id"}

    df = _read_products()
    if df.empty:
        return {"found": False, "reason": "no_data"}

    match = df[df["product_id"].str.upper() == product_id.strip().upper()]
    if match.empty:
        return {"found": False, "reason": "not_found", "product_id": product_id}

    product = match.iloc[0].to_dict()
    product["found"] = True
    return product


def search_product(query: str) -> Union[dict, List[dict]]:
    """Search products by id or name (case-insensitive, partial match).

    Returns the single matching product dict when exactly one matches,
    otherwise a list of matching product dicts (empty if none match).
    """
    if not query:
        return []

    df = _read_products()
    if df.empty:
        return []

    q = query.strip().lower()

    # Exact id match first.
    by_id = df[df["product_id"].str.lower() == q]
    if not by_id.empty:
        product = by_id.iloc[0].to_dict()
        product["found"] = True
        return product

    # Partial match against name or description.
    mask = (
        df["name"].str.lower().str.contains(q, na=False)
        | df["description"].str.lower().str.contains(q, na=False)
        | df["category"].str.lower().str.contains(q, na=False)
    )
    results = df[mask].to_dict(orient="records")
    if len(results) == 1:
        results[0]["found"] = True
        return results[0]
    return results
