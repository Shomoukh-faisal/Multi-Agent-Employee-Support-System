"""Central configuration.

Loads environment variables and resolves absolute paths to the CSV / JSON
data files so the app works no matter which directory it is launched from.
"""

import os

from dotenv import load_dotenv

# Load variables from a .env file if one exists (no error if it is missing).
load_dotenv()

# --- Gemini / API settings --------------------------------------------------
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
# NOTE: set a model name your API key actually has access to. The proposal
# referenced "gemini-3.5-flash"; a safe, widely available default is used here.
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
API_BASE_URL: str = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").strip()

# --- Data file locations ----------------------------------------------------
# BASE_DIR points at the `app/` package directory.
BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
DATA_DIR: str = os.path.join(BASE_DIR, "data")

ORDERS_CSV: str = os.path.join(DATA_DIR, "orders.csv")
PRODUCTS_CSV: str = os.path.join(DATA_DIR, "products.csv")
COMPLAINTS_CSV: str = os.path.join(DATA_DIR, "complaints.csv")
MEMORY_JSON: str = os.path.join(DATA_DIR, "memory.json")


def gemini_enabled() -> bool:
    """True when a Gemini API key is configured."""
    return bool(GEMINI_API_KEY)
