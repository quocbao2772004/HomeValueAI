import json
import logging
from pathlib import Path
from datetime import datetime, UTC
import pandas as pd

from src.config import load_config
from src.evaluation import evaluate_market_data
from src.valuation import load_market_frame

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def evaluate_data_quality():
    config = load_config()
    db_path = "data/market.sqlite"
    
    logger.info("Evaluating market data deduplication rate...")
    eval_response = evaluate_market_data(config, db_path)
    dedupe_rate = eval_response.duplicate_rate
    
    logger.info("Checking data freshness on valuation frame...")
    frame = load_market_frame(db_path)
    
    stale_after_days = config.raw.get("quality", {}).get("stale_after_days", 45)
    now = datetime.now(UTC)
    
    if frame.empty:
        stale_rate = 0.0
        stale_count = 0
    else:
        frame["observed_dt"] = pd.to_datetime(frame["observed_at"], errors="coerce", utc=True)
        # Bỏ qua những dòng không có ngày tháng hợp lệ
        valid_dates = frame[pd.notna(frame["observed_dt"])]
        if valid_dates.empty:
            stale_rate = 0.0
            stale_count = 0
        else:
            stale_mask = valid_dates["observed_dt"] < (now - pd.Timedelta(days=stale_after_days))
            stale_count = int(stale_mask.sum())
            stale_rate = stale_count / len(valid_dates)
        
    logger.info("================ Evaluation Summary ================")
    logger.info(f"Deduplication Rate (Tỷ lệ lọc trùng): {dedupe_rate:.2%}")
    logger.info(f"Data Freshness (Tỷ lệ data quá hạn {stale_after_days} ngày): {stale_rate:.2%} ({stale_count} dòng quá hạn)")
    logger.info("====================================================")
    
    output_dir = Path("eval/results")
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"  => Deduplication Rate:      {dedupe_rate*100:.2f}%")
    print(f"  - Kỳ vọng (< 5%):           {'✅ ĐẠT' if dedupe_rate < 0.05 else '❌ KHÔNG ĐẠT'}")
    
    summary = {
        "deduplication_rate": float(dedupe_rate),
        "stale_data_rate": float(stale_rate),
        "stale_data_count": stale_count,
        "stale_threshold_days": stale_after_days,
        "total_valuation_records": len(frame)
    }
    
    with open(output_dir / "data_quality_metrics.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
        
    logger.info(f"Detailed results saved to {output_dir / 'data_quality_metrics.json'}")

if __name__ == "__main__":
    evaluate_data_quality()
