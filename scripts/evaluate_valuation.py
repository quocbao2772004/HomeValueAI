import json
import logging
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import numpy as np

from src.config import load_config
from src.valuation import estimate_property, load_market_frame
from src.schemas import PropertyInput

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def evaluate_valuation(sample_size: int = 50):
    config = load_config()
    db_path = "data/market.sqlite"
    
    logger.info("Loading full market data...")
    full_frame = load_market_frame(db_path)
    
    # Filter for sale properties with valid price and area
    sale_frame = full_frame[(full_frame["purpose"] == "sale") & 
                            (pd.notna(full_frame["price_total_vnd"])) & 
                            (pd.notna(full_frame["area_m2"]))].copy()
    
    if len(sale_frame) < sample_size:
        sample_size = len(sale_frame)
        logger.warning(f"Requested sample size {sample_size} exceeds available sale records. Adjusting to {sample_size}.")
    
    # Randomly sample N listings to act as our ground truth
    logger.info(f"Sampling {sample_size} listings for hold-out evaluation...")
    ground_truth = sale_frame.sample(n=sample_size, random_state=42)
    
    results = []
    
    for idx, row in ground_truth.iterrows():
        # Create a mock frame that explicitly excludes this specific listing
        mock_frame = full_frame.drop(index=idx)
        
        project_val = str(row["project_name"]) if pd.notna(row.get("project_name")) else row["project_slug"]
        
        prop_input = PropertyInput(
            purpose="sale",
            project=project_val,
            property_type=str(row["property_type"]),
            area_m2=float(row["area_m2"]),
            bedrooms=int(row["bedrooms"]) if pd.notna(row.get("bedrooms")) else None,
            furniture=str(row["furniture"]) if pd.notna(row.get("furniture")) else None,
            view=str(row["view"]) if pd.notna(row.get("view")) else None,
            subdivision=str(row["subdivision"]) if pd.notna(row.get("subdivision")) else None,
        )
        
        actual_price = float(row["price_total_vnd"])
        
        # Patch load_market_frame directly to return our mock_frame
        with patch("src.valuation.load_market_frame", return_value=mock_frame):
            try:
                res = estimate_property(prop_input, config, db_path)
                p10 = res.p10_total_vnd
                p50 = res.p50_total_vnd
                p90 = res.p90_total_vnd
                
                ape = abs(p50 - actual_price) / actual_price
                hit = 1 if p10 <= actual_price <= p90 else 0
                
                results.append({
                    "id": row.get("id", str(idx)),
                    "project": prop_input.project,
                    "area_m2": prop_input.area_m2,
                    "actual_price": actual_price,
                    "predicted_p50": p50,
                    "p10": p10,
                    "p90": p90,
                    "ape": ape,
                    "hit": hit
                })
            except Exception as e:
                logger.debug(f"Could not estimate for index {idx}: {e}")
                
    if not results:
        logger.error("No results could be calculated.")
        return
        
    df_results = pd.DataFrame(results)
    mape = df_results["ape"].mean()
    hit_rate = df_results["hit"].mean()
    
    logger.info("================ Evaluation Summary ================")
    logger.info(f"Evaluated on: {len(results)} successful samples")
    logger.info(f"MAPE (Mean Absolute Percentage Error): {mape:.2%}")
    logger.info(f"Hit Rate (Actual price in P10-P90 range): {hit_rate:.2%}")
    logger.info("====================================================")
    
    output_dir = Path("eval/results")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    summary = {
        "sample_size": len(results),
        "mape": mape,
        "hit_rate": hit_rate,
        "results": results
    }
    
    with open(output_dir / "valuation_metrics.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
        
    logger.info(f"Detailed results saved to {output_dir / 'valuation_metrics.json'}")

if __name__ == "__main__":
    evaluate_valuation(sample_size=50)
