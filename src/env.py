from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_app_env() -> Path | None:
    env_path_value = os.getenv("VALUATION_ENV_FILE")
    env_path = resolve_project_path(env_path_value) if env_path_value else DEFAULT_ENV_PATH
    if not env_path.exists():
        return None
    load_dotenv(env_path, override=False)
    return env_path
