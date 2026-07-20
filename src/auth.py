from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.database import DEFAULT_DB_PATH, connect, init_db
from src.env import load_app_env
from src.schemas import AuthLoginRequest, AuthRegisterRequest, AuthTokenResponse, AuthUser

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 210_000
RUNTIME_DIR = Path(__file__).resolve().parents[1] / ".runtime"
AUTH_SECRET_PATH = RUNTIME_DIR / "auth_secret.key"


def register_user(payload: AuthRegisterRequest, db_path: str | Path = DEFAULT_DB_PATH) -> AuthTokenResponse:
    name = _normalize_name(payload.name)
    email = _normalize_email(payload.email)
    password_hash = _hash_password(payload.password)
    now = datetime.now(UTC).isoformat()
    conn = connect(db_path)
    init_db(conn)
    try:
        cursor = conn.execute(
            """
            INSERT INTO app_user (created_at, updated_at, name, email, password_hash)
            VALUES (?, ?, ?, ?, ?)
            """,
            (now, now, name, email, password_hash),
        )
        conn.commit()
        user = AuthUser(id=int(cursor.lastrowid), name=name, email=email, created_at=now, credit_balance=5)
    except sqlite3.IntegrityError as exc:
        raise ValueError("Email này đã được đăng ký.") from exc
    finally:
        conn.close()
    return _token_response(user)


def login_user(payload: AuthLoginRequest, db_path: str | Path = DEFAULT_DB_PATH) -> AuthTokenResponse:
    email = _normalize_email(payload.email)
    conn = connect(db_path)
    init_db(conn)
    try:
        row = conn.execute(
            "SELECT id, created_at, name, email, password_hash, credit_balance, pro_expires_at FROM app_user WHERE email = ?",
            (email,),
        ).fetchone()
    finally:
        conn.close()
    if not row or not _verify_password(payload.password, row["password_hash"]):
        raise ValueError("Email hoặc mật khẩu không đúng.")
    user = _auth_user_from_row(row)
    return _token_response(user)


def current_user_from_token(token: str, db_path: str | Path = DEFAULT_DB_PATH) -> AuthUser:
    payload = _decode_token(token)
    user_id = int(payload["sub"])
    conn = connect(db_path)
    init_db(conn)
    try:
        row = conn.execute(
            "SELECT id, created_at, name, email, credit_balance, pro_expires_at FROM app_user WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise ValueError("Phiên đăng nhập không còn hợp lệ.")
    return _auth_user_from_row(row)


def bearer_token(authorization: str | None) -> str:
    value = str(authorization or "").strip()
    if not value.lower().startswith("bearer "):
        raise ValueError("Thiếu token đăng nhập.")
    token = value[7:].strip()
    if not token:
        raise ValueError("Thiếu token đăng nhập.")
    return token


def _token_response(user: AuthUser) -> AuthTokenResponse:
    return AuthTokenResponse(access_token=_encode_token(user), user=user)


def _auth_user_from_row(row: sqlite3.Row) -> AuthUser:
    pro_expires_at = row["pro_expires_at"] if "pro_expires_at" in row.keys() else None
    credit_balance = row["credit_balance"] if "credit_balance" in row.keys() else 5
    return AuthUser(
        id=int(row["id"]),
        name=row["name"],
        email=row["email"],
        created_at=row["created_at"],
        credit_balance=int(credit_balance or 0),
        pro_expires_at=pro_expires_at,
        is_pro=_is_active_pro(pro_expires_at),
    )


def _is_active_pro(value: str | None) -> bool:
    if not value:
        return False
    try:
        expires_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at > datetime.now(UTC)
    except ValueError:
        return False


def _normalize_name(value: str) -> str:
    name = re.sub(r"\s+", " ", value or "").strip()
    if len(name) < 2:
        raise ValueError("Tên cần có ít nhất 2 ký tự.")
    return name


def _normalize_email(value: str) -> str:
    email = str(value or "").strip().lower()
    if not EMAIL_PATTERN.match(email):
        raise ValueError("Email không hợp lệ.")
    return email


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "$".join(
        [
            PASSWORD_ALGORITHM,
            str(PASSWORD_ITERATIONS),
            _b64encode(salt),
            _b64encode(digest),
        ]
    )


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = stored_hash.split("$", 3)
        iterations = int(iterations_text)
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
    except (ValueError, TypeError):
        return False
    if algorithm != PASSWORD_ALGORITHM or iterations <= 0:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _encode_token(user: AuthUser) -> str:
    expires_at = datetime.now(UTC) + timedelta(hours=_token_ttl_hours())
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "name": user.name,
        "exp": int(expires_at.timestamp()),
    }
    body = _b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    signature = _sign(body.encode("utf-8"))
    return f"{body}.{signature}"


def _decode_token(token: str) -> dict[str, Any]:
    try:
        body, signature = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("Token đăng nhập không hợp lệ.") from exc
    expected = _sign(body.encode("utf-8"))
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Token đăng nhập không hợp lệ.")
    try:
        payload = json.loads(_b64decode(body).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Token đăng nhập không hợp lệ.") from exc
    if int(payload.get("exp") or 0) < int(datetime.now(UTC).timestamp()):
        raise ValueError("Phiên đăng nhập đã hết hạn.")
    if not payload.get("sub"):
        raise ValueError("Token đăng nhập không hợp lệ.")
    return payload


def _sign(data: bytes) -> str:
    return _b64encode(hmac.new(_auth_secret(), data, hashlib.sha256).digest())


def _auth_secret() -> bytes:
    load_app_env()
    value = os.getenv("AUTH_SECRET_KEY") or os.getenv("HOMEVALUE_AUTH_SECRET")
    if value:
        return value.strip().encode("utf-8")
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if AUTH_SECRET_PATH.exists():
        return AUTH_SECRET_PATH.read_text(encoding="utf-8").strip().encode("utf-8")
    secret = secrets.token_urlsafe(48)
    AUTH_SECRET_PATH.write_text(secret, encoding="utf-8")
    try:
        AUTH_SECRET_PATH.chmod(0o600)
    except OSError:
        pass
    return secret.encode("utf-8")


def _token_ttl_hours() -> int:
    load_app_env()
    try:
        return max(1, int(os.getenv("AUTH_TOKEN_TTL_HOURS", "168")))
    except ValueError:
        return 168


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))
