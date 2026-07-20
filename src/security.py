from __future__ import annotations

import hmac
import ipaddress
import os
import secrets
from pathlib import Path

from fastapi import HTTPException, Request

from src.env import load_app_env

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / ".runtime"
INTERNAL_PROXY_KEY_PATH = RUNTIME_DIR / "internal_proxy.key"


def internal_proxy_key() -> str:
    load_app_env()
    configured = os.getenv("INTERNAL_PROXY_KEY") or os.getenv("HOMEVALUE_INTERNAL_PROXY_KEY")
    if configured:
        return configured.strip()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if INTERNAL_PROXY_KEY_PATH.exists():
        return INTERNAL_PROXY_KEY_PATH.read_text(encoding="utf-8").strip()
    key = secrets.token_urlsafe(32)
    INTERNAL_PROXY_KEY_PATH.write_text(key, encoding="utf-8")
    try:
        INTERNAL_PROXY_KEY_PATH.chmod(0o600)
    except OSError:
        pass
    return key


def valid_internal_proxy_key(value: str | None) -> bool:
    supplied = str(value or "").strip()
    return bool(supplied) and hmac.compare_digest(supplied, internal_proxy_key())


def valid_admin_api_key(value: str | None) -> bool:
    load_app_env()
    configured = (
        os.getenv("ADMIN_API_KEY")
        or os.getenv("HOMEVALUE_ADMIN_API_KEY")
        or os.getenv("VERIFIED_TRANSACTION_API_KEY")
    )
    supplied = str(value or "").strip()
    return bool(configured and supplied) and hmac.compare_digest(supplied, configured.strip())


def bearer_or_key(authorization: str | None, x_admin_api_key: str | None) -> str | None:
    if x_admin_api_key:
        return x_admin_api_key
    value = str(authorization or "").strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return None


def require_admin_api_key(authorization: str | None, x_admin_api_key: str | None) -> None:
    if not valid_admin_api_key(bearer_or_key(authorization, x_admin_api_key)):
        raise HTTPException(status_code=401, detail="Thiếu hoặc sai Admin API Key.")


def should_allow_direct_request(request: Request) -> bool:
    host = request.headers.get("host", "").split(":", 1)[0].lower()
    client = request.client.host if request.client else ""
    if host == "testserver":
        return True
    if host in {"127.0.0.1", "localhost", "0.0.0.0"} and _is_loopback(client):
        return True
    if _bool_env("TRUST_PRIVATE_PROXY", True) and _is_private_non_loopback(client):
        return True
    return False


def _is_loopback(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _is_private_non_loopback(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.is_private and not ip.is_loopback


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
