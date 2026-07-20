from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.database import DEFAULT_DB_PATH, connect, init_db
from src.schemas import AuthUser


class InsufficientCreditsError(ValueError):
    def __init__(self, required: int, balance: int):
        self.required = required
        self.balance = balance
        super().__init__("Số điểm hiện tại không đủ để thực hiện thao tác này.")


@dataclass(frozen=True)
class CreditCharge:
    status: str
    action: str
    required: int
    charged: int
    balance_before: int | None
    balance_after: int | None
    idempotency_key: str | None

    def model(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "action": self.action,
            "required": self.required,
            "charged": self.charged,
            "balance_before": self.balance_before,
            "balance_after": self.balance_after,
            "idempotency_key": self.idempotency_key,
        }


def current_credit_balance(user_id: int, db_path: str | Path = DEFAULT_DB_PATH) -> int:
    conn = connect(db_path)
    init_db(conn)
    try:
        row = conn.execute("SELECT credit_balance FROM app_user WHERE id = ?", (user_id,)).fetchone()
    finally:
        conn.close()
    return int(row["credit_balance"] or 0) if row else 0


def has_credits(user: AuthUser | None, required: int, db_path: str | Path = DEFAULT_DB_PATH) -> bool:
    if required <= 0:
        return True
    if user is None:
        return True
    return current_credit_balance(user.id, db_path) >= required


def charge_credits(
    user: AuthUser | None,
    action: str,
    amount: int,
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> CreditCharge:
    amount = int(amount or 0)
    if amount <= 0:
        return CreditCharge("not_required", action, 0, 0, user.credit_balance if user else None, user.credit_balance if user else None, idempotency_key)
    if user is None:
        return CreditCharge("anonymous_not_charged", action, amount, 0, None, None, idempotency_key)

    key = _clean_idempotency_key(idempotency_key) or f"auto-{uuid.uuid4().hex}"
    conn = connect(db_path)
    init_db(conn)
    try:
        existing = conn.execute(
            """
            SELECT delta, balance_after, status
            FROM credit_ledger
            WHERE user_id = ? AND action = ? AND idempotency_key = ?
            """,
            (user.id, action, key),
        ).fetchone()
        if existing:
            charged = abs(int(existing["delta"] or 0)) if int(existing["delta"] or 0) < 0 else 0
            return CreditCharge(
                "already_charged",
                action,
                amount,
                charged,
                None,
                int(existing["balance_after"]),
                key,
            )

        before_row = conn.execute("SELECT credit_balance FROM app_user WHERE id = ?", (user.id,)).fetchone()
        balance_before = int(before_row["credit_balance"] or 0) if before_row else 0
        if balance_before < amount:
            raise InsufficientCreditsError(amount, balance_before)

        now = datetime.now(UTC).isoformat()
        cursor = conn.execute(
            """
            UPDATE app_user
            SET credit_balance = credit_balance - ?, updated_at = ?
            WHERE id = ? AND credit_balance >= ?
            """,
            (amount, now, user.id, amount),
        )
        if cursor.rowcount != 1:
            latest = current_credit_balance(user.id, db_path)
            raise InsufficientCreditsError(amount, latest)

        after_row = conn.execute("SELECT credit_balance FROM app_user WHERE id = ?", (user.id,)).fetchone()
        balance_after = int(after_row["credit_balance"] or 0)
        conn.execute(
            """
            INSERT INTO credit_ledger (
              created_at, user_id, action, delta, balance_after,
              idempotency_key, status, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                user.id,
                action,
                -amount,
                balance_after,
                key,
                "charged",
                json.dumps(metadata or {}, ensure_ascii=False, default=str),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        row = conn.execute(
            """
            SELECT delta, balance_after
            FROM credit_ledger
            WHERE user_id = ? AND action = ? AND idempotency_key = ?
            """,
            (user.id, action, key),
        ).fetchone()
        if not row:
            raise
        return CreditCharge("already_charged", action, amount, abs(int(row["delta"] or 0)), None, int(row["balance_after"]), key)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return CreditCharge("charged", action, amount, amount, balance_before, balance_after, key)


def credit_summary(action: str, required: int, user: AuthUser | None) -> dict[str, Any]:
    balance = user.credit_balance if user else None
    return CreditCharge("not_charged", action, required, 0, balance, balance, None).model()


def _clean_idempotency_key(value: str | None) -> str | None:
    key = str(value or "").strip()
    if not key:
        return None
    return key[:160]
