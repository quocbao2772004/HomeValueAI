from __future__ import annotations

import os
from pathlib import Path
import sys

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src.env import load_app_env  # noqa: E402


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

if __name__ == "__main__":
    load_app_env()
    uvicorn.run(
        "src.main:app",
        host=os.getenv("VALUATION_HOST", "127.0.0.1"),
        port=_int_env("VALUATION_PORT", 8000),
        reload=_bool_env("VALUATION_RELOAD"),
        app_dir=str(ROOT),
    )
