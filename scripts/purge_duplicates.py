"""Purge canonical-duplicate listing rows from the market database.

Valuation đã bỏ qua duplicate lúc đọc (src/dedupe.py), nhưng các dòng trùng
vẫn nằm vật lý trong bảng listing_observation. Script này áp đúng logic
canonical key để xác định dòng non-canonical và xóa chúng khỏi DB.

Mặc định chạy ở chế độ dry-run (chỉ in ra). Thêm --apply để xóa thật.

Cách dùng:
    python3 scripts/purge_duplicates.py                 # dry-run
    python3 scripts/purge_duplicates.py --apply         # xóa thật (tự backup)
    python3 scripts/purge_duplicates.py --db data/market.sqlite --apply
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dedupe import enrich_canonical_dedupe  # noqa: E402
from src.storage import load_market_frame  # noqa: E402


def _non_canonical_ids(db_path: str) -> list[int]:
    frame = load_market_frame(db_path)
    if frame.empty:
        return []
    enriched = enrich_canonical_dedupe(frame)
    listing_mask = enriched["basis"].fillna("listing").astype(str).eq("listing")
    removable = enriched[listing_mask & ~enriched["is_canonical_listing"]]
    if "id" not in removable:
        return []
    return [int(value) for value in removable["id"].dropna().tolist()]


def _backup(db_path: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.bak_{stamp}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge canonical-duplicate listing rows.")
    parser.add_argument("--db", default="data/market.sqlite", help="Đường dẫn SQLite DB")
    parser.add_argument("--apply", action="store_true", help="Xóa thật (mặc định dry-run)")
    args = parser.parse_args()

    db_path = args.db
    if not Path(db_path).exists():
        raise SystemExit(f"Không tìm thấy DB: {db_path}")

    ids = _non_canonical_ids(db_path)
    conn = sqlite3.connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM listing_observation").fetchone()[0]

    print(f"DB: {db_path}")
    print(f"listing_observation rows: {total}")
    print(f"Canonical-duplicate rows cần xóa: {len(ids)}")

    if not ids:
        print("Không có dòng trùng nào. DB đã sạch.")
        conn.close()
        return

    if not args.apply:
        print("\nDry-run. Thêm --apply để xóa thật.")
        conn.close()
        return

    backup_path = _backup(db_path)
    print(f"\nĐã backup: {backup_path}")
    conn.executemany("DELETE FROM listing_observation WHERE id = ?", [(i,) for i in ids])
    conn.commit()
    remaining = conn.execute("SELECT COUNT(*) FROM listing_observation").fetchone()[0]
    conn.close()
    print(f"Đã xóa {len(ids)} dòng. Còn lại: {remaining} rows.")


if __name__ == "__main__":
    main()
