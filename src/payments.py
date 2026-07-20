from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from src.database import DEFAULT_DB_PATH, connect, init_db
from src.env import load_app_env
from src.schemas import AuthUser, PaymentOrderRequest, PaymentOrderResponse

PLAN_AGENT_PRO_MONTHLY = "agent_pro_monthly"
PLAN_CREDITS_100 = "credits_100"
PAYMENT_STATUS_PENDING = "pending"
PAYMENT_STATUS_PAID = "paid"
PAYMENT_STATUS_EXPIRED = "expired"
PAYMENT_CODE_PREFIXES = ("HVPRO", "HVCRD")


def create_pro_order(
    user: AuthUser,
    payload: PaymentOrderRequest,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> PaymentOrderResponse:
    if payload.plan not in {PLAN_AGENT_PRO_MONTHLY, PLAN_CREDITS_100}:
        raise ValueError("Gói thanh toán không hợp lệ.")
    settings = payment_settings()
    plan = _payment_plan_config(payload.plan, settings)
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings["expires_minutes"])
    order_code = _new_order_code(db_path, plan["code_prefix"])
    transfer_content = order_code
    qr_image_url = vietqr_image_url(
        bank_bin=settings["bank_bin"],
        account_no=settings["account_no"],
        account_name=settings["account_name"],
        amount_vnd=plan["amount_vnd"],
        transfer_content=transfer_content,
        template=settings["vietqr_template"],
    )
    record = {
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "user_id": user.id,
        "order_code": order_code,
        "plan": payload.plan,
        "amount_vnd": plan["amount_vnd"],
        "status": PAYMENT_STATUS_PENDING,
        "expires_at": expires_at.isoformat(),
        "bank_bin": settings["bank_bin"],
        "bank_account_no": settings["account_no"],
        "bank_account_name": settings["account_name"],
        "transfer_content": transfer_content,
        "qr_image_url": qr_image_url,
    }
    conn = connect(db_path)
    init_db(conn)
    try:
        conn.execute(
            """
            INSERT INTO payment_order (
                created_at, updated_at, user_id, order_code, plan, amount_vnd, status,
                expires_at, bank_bin, bank_account_no, bank_account_name, transfer_content,
                qr_image_url
            ) VALUES (
                :created_at, :updated_at, :user_id, :order_code, :plan, :amount_vnd, :status,
                :expires_at, :bank_bin, :bank_account_no, :bank_account_name, :transfer_content,
                :qr_image_url
            )
            """,
            record,
        )
        conn.commit()
        row = _payment_order_row(conn, order_code, user.id)
    finally:
        conn.close()
    return _payment_response(row)


def get_payment_order(
    user: AuthUser,
    order_code: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> PaymentOrderResponse:
    conn = connect(db_path)
    init_db(conn)
    try:
        row = _payment_order_row(conn, _normalize_order_code(order_code), user.id)
        if not row:
            raise ValueError("Không tìm thấy đơn thanh toán.")
        row = _expire_if_needed(conn, row)
    finally:
        conn.close()
    return _payment_response(row)


def check_payment_order(
    user: AuthUser,
    order_code: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> PaymentOrderResponse:
    conn = connect(db_path)
    init_db(conn)
    try:
        row = _payment_order_row(conn, _normalize_order_code(order_code), user.id)
        if not row:
            raise ValueError("Không tìm thấy đơn thanh toán.")
        row = _expire_if_needed(conn, row)
        if row["status"] != PAYMENT_STATUS_PENDING:
            return _payment_response(row)

        transaction = _find_matching_mbbank_transaction(row)
        if transaction:
            row = _mark_paid(conn, row, transaction)
    finally:
        conn.close()
    return _payment_response(row)


def vietqr_image_url(
    *,
    bank_bin: str,
    account_no: str,
    account_name: str,
    amount_vnd: int,
    transfer_content: str,
    template: str = "compact2",
) -> str:
    bank = quote(str(bank_bin).strip(), safe="")
    account = quote(str(account_no).strip(), safe="")
    tmpl = quote(str(template or "compact2").strip(), safe="")
    return (
        f"https://img.vietqr.io/image/{bank}-{account}-{tmpl}.png"
        f"?amount={int(amount_vnd)}"
        f"&addInfo={quote(transfer_content, safe='')}"
        f"&accountName={quote(account_name, safe='')}"
    )


def payment_settings() -> dict[str, Any]:
    load_app_env()
    account_no = _env_first("MBBANK_ACCOUNT_NO", "PAYMENT_ACCOUNT_NO")
    account_name = _env_first("MBBANK_ACCOUNT_NAME", "PAYMENT_ACCOUNT_NAME") or "HOMEVALUE AI"
    if not account_no:
        raise ValueError("Thiếu MBBANK_ACCOUNT_NO hoặc PAYMENT_ACCOUNT_NO để tạo VietQR.")
    return {
        "bank_bin": _env_first("MBBANK_BANK_BIN", "PAYMENT_BANK_BIN") or "970422",
        "account_no": account_no,
        "account_name": account_name,
        "agent_pro_amount_vnd": _int_env("PAYMENT_AGENT_PRO_AMOUNT_VND", 299_000),
        "credit_pack_amount_vnd": _int_env("PAYMENT_CREDIT_PACK_AMOUNT_VND", 50_000),
        "credit_pack_credits": _int_env("PAYMENT_CREDIT_PACK_CREDITS", 100),
        "expires_minutes": _int_env("PAYMENT_ORDER_EXPIRES_MINUTES", 30),
        "vietqr_template": os.getenv("VIETQR_TEMPLATE", "compact2").strip() or "compact2",
    }


def _payment_plan_config(plan: str, settings: dict[str, Any]) -> dict[str, Any]:
    if plan == PLAN_AGENT_PRO_MONTHLY:
        return {
            "amount_vnd": settings["agent_pro_amount_vnd"],
            "code_prefix": "HVPRO",
            "credits_added": 0,
        }
    if plan == PLAN_CREDITS_100:
        return {
            "amount_vnd": settings["credit_pack_amount_vnd"],
            "code_prefix": "HVCRD",
            "credits_added": settings["credit_pack_credits"],
        }
    raise ValueError("Gói thanh toán không hợp lệ.")


def _new_order_code(db_path: str | Path, prefix: str) -> str:
    conn = connect(db_path)
    init_db(conn)
    try:
        for _ in range(20):
            code = prefix + secrets.token_hex(3).upper()
            exists = conn.execute("SELECT 1 FROM payment_order WHERE order_code = ?", (code,)).fetchone()
            if not exists:
                return code
    finally:
        conn.close()
    raise RuntimeError("Không tạo được mã thanh toán duy nhất.")


def _payment_order_row(conn: sqlite3.Connection, order_code: str, user_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT po.*, au.pro_expires_at AS user_pro_expires_at,
               au.credit_balance AS user_credit_balance
        FROM payment_order po
        JOIN app_user au ON au.id = po.user_id
        WHERE po.order_code = ? AND po.user_id = ?
        """,
        (order_code, user_id),
    ).fetchone()


def _expire_if_needed(conn: sqlite3.Connection, row: sqlite3.Row) -> sqlite3.Row:
    if row["status"] != PAYMENT_STATUS_PENDING:
        return row
    try:
        expires_at = datetime.fromisoformat(row["expires_at"])
    except ValueError:
        return row
    if expires_at > datetime.now(UTC):
        return row
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE payment_order SET status = ?, updated_at = ? WHERE id = ?",
        (PAYMENT_STATUS_EXPIRED, now, row["id"]),
    )
    conn.commit()
    return _payment_order_row(conn, row["order_code"], row["user_id"]) or row


def _mark_paid(conn: sqlite3.Connection, row: sqlite3.Row, transaction: dict[str, Any]) -> sqlite3.Row:
    now = datetime.now(UTC)
    matched_ref_no = str(transaction.get("refNo") or "").strip() or None
    matched_amount = _transaction_credit_amount(transaction)
    conn.execute(
        """
        UPDATE payment_order
        SET status = ?, updated_at = ?, paid_at = ?, matched_ref_no = ?,
            matched_amount_vnd = ?, raw_transaction_json = ?
        WHERE id = ?
        """,
        (
            PAYMENT_STATUS_PAID,
            now.isoformat(),
            now.isoformat(),
            matched_ref_no,
            matched_amount,
            json.dumps(transaction, ensure_ascii=False, default=str),
            row["id"],
        ),
    )
    if row["plan"] == PLAN_AGENT_PRO_MONTHLY:
        pro_expires_at = now + timedelta(days=_int_env("AGENT_PRO_DAYS", 30))
        conn.execute(
            "UPDATE app_user SET updated_at = ?, pro_expires_at = ? WHERE id = ?",
            (now.isoformat(), pro_expires_at.isoformat(), row["user_id"]),
        )
    elif row["plan"] == PLAN_CREDITS_100:
        credits_added = _credits_added_for_plan(row["plan"])
        conn.execute(
            """
            UPDATE app_user
            SET updated_at = ?, credit_balance = COALESCE(credit_balance, 0) + ?
            WHERE id = ?
            """,
            (now.isoformat(), credits_added, row["user_id"]),
        )
    conn.commit()
    return _payment_order_row(conn, row["order_code"], row["user_id"]) or row


def _find_matching_mbbank_transaction(row: sqlite3.Row) -> dict[str, Any] | None:
    transactions = fetch_mbbank_transactions(
        account_no=row["bank_account_no"],
        from_date=datetime.fromisoformat(row["created_at"]) - timedelta(days=1),
        to_date=datetime.now(UTC) + timedelta(days=1),
    )
    expected_amount = int(row["amount_vnd"])
    expected_code = _compact(row["transfer_content"])
    for transaction in transactions:
        tx = _transaction_to_dict(transaction)
        amount = _transaction_credit_amount(tx)
        if amount < expected_amount:
            continue
        haystack = _compact(" ".join(str(tx.get(key) or "") for key in ("description", "addDescription", "refNo")))
        if expected_code and expected_code in haystack:
            return tx
    return None


def fetch_mbbank_transactions(*, account_no: str, from_date: datetime, to_date: datetime) -> list[Any]:
    load_app_env()
    username = _env_first("MBBANK_USERNAME", "MB_USERNAME")
    password = _env_first("MBBANK_PASSWORD", "MB_PASSWORD")
    if not username or not password:
        raise RuntimeError("Thiếu MBBANK_USERNAME/MBBANK_PASSWORD để kiểm tra giao dịch.")
    try:
        import mbbank  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Thiếu package mbbank-lib. Cài bằng: pip install mbbank-lib") from exc
    client = mbbank.MBBank(
        username=username,
        password=password,
        timeout=float(os.getenv("MBBANK_TIMEOUT_SECONDS", "20")),
    )
    try:
        history = client.getTransactionAccountHistory(accountNo=account_no, from_date=from_date, to_date=to_date)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Không kết nối được MBBank để kiểm tra giao dịch. Thử lại sau vài giây.") from exc
    return list(getattr(history, "transactionHistoryList", []) or [])


def _payment_response(row: sqlite3.Row | None) -> PaymentOrderResponse:
    if not row:
        raise ValueError("Không tìm thấy đơn thanh toán.")
    return PaymentOrderResponse(
        order_code=row["order_code"],
        plan=row["plan"],
        amount_vnd=int(row["amount_vnd"]),
        status=row["status"],
        transfer_content=row["transfer_content"],
        qr_image_url=row["qr_image_url"],
        bank_bin=row["bank_bin"],
        bank_account_no=row["bank_account_no"],
        bank_account_name=row["bank_account_name"],
        expires_at=row["expires_at"],
        paid_at=row["paid_at"],
        matched_ref_no=row["matched_ref_no"],
        pro_expires_at=row["user_pro_expires_at"],
        credits_added=_credits_added_for_plan(row["plan"]),
        credit_balance=int(row["user_credit_balance"]) if row["user_credit_balance"] is not None else None,
    )


def _transaction_to_dict(transaction: Any) -> dict[str, Any]:
    if isinstance(transaction, dict):
        return transaction
    if hasattr(transaction, "model_dump"):
        return transaction.model_dump()
    if hasattr(transaction, "dict"):
        return transaction.dict()
    return {
        key: getattr(transaction, key)
        for key in ("creditAmount", "debitAmount", "description", "addDescription", "refNo", "transactionDate")
        if hasattr(transaction, key)
    }


def _transaction_credit_amount(transaction: dict[str, Any]) -> int:
    value = transaction.get("creditAmount")
    if value is None:
        return 0
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits or 0)


def _normalize_order_code(value: str) -> str:
    code = _compact(value)
    if not any(code.startswith(prefix) for prefix in PAYMENT_CODE_PREFIXES):
        raise ValueError("Mã thanh toán không hợp lệ.")
    return code


def _credits_added_for_plan(plan: str) -> int:
    if plan == PLAN_CREDITS_100:
        return _int_env("PAYMENT_CREDIT_PACK_CREDITS", 100)
    return 0


def _compact(value: str) -> str:
    normalized = unicodedata.normalize("NFD", str(value or ""))
    ascii_text = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^A-Za-z0-9]", "", ascii_text).upper()


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default
