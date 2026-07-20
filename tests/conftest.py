import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["VALUATION_LLM_ENABLED"] = "0"
os.environ["VALUATION_STORAGE_BACKEND"] = "sqlite"
os.environ["SERPAPI_API_KEY"] = ""
os.environ["GOOGLE_MAPS_API_KEY"] = ""
os.environ["GOOGLE_PLACES_API_KEY"] = ""
