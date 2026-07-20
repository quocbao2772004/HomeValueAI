import sys
import time
import json
from pathlib import Path
import numpy as np
from fastapi.testclient import TestClient

# Thêm thư mục gốc vào PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.main import app

def main():
    print("=" * 60)
    print("  SYSTEM PERFORMANCE & LATENCY EVALUATION")
    print("=" * 60)

    client = TestClient(app)
    N_CALLS = 20

    # 1. Chuẩn bị Payload
    valuation_payload = {
        "project": "Vinhomes Smart City",
        "purpose": "sale",
        "property_type": "apartment",
        "area_m2": 54.0,
        "bedrooms": 2
    }

    chat_payload = {
        "message": "Định giá bán căn hộ Vinhomes Smart City 54.2m2 2PN full nội thất"
    }

    results = {}

    # 2. Benchmark /valuation
    print(f"Đang benchmark API /valuation ({N_CALLS} requests)...")
    val_latencies = []
    
    # Warm-up request (không tính vào thời gian benchmark)
    client.post("/valuation", json=valuation_payload)
    
    for _ in range(N_CALLS):
        start_time = time.perf_counter()
        response = client.post("/valuation", json=valuation_payload)
        end_time = time.perf_counter()
        
        # Có thể kiểm tra response.status_code == 200 nếu cần
        latency_ms = (end_time - start_time) * 1000
        val_latencies.append(latency_ms)

    val_p95 = np.percentile(val_latencies, 95)
    val_mean = np.mean(val_latencies)
    results["valuation"] = {
        "mean_ms": val_mean,
        "p95_ms": val_p95,
        "raw_latencies_ms": val_latencies
    }

    # 3. Benchmark /chat
    print(f"Đang benchmark API /chat ({N_CALLS} requests)...")
    chat_latencies = []
    
    # Warm-up request
    client.post("/chat", json=chat_payload)
    
    for _ in range(N_CALLS):
        start_time = time.perf_counter()
        response = client.post("/chat", json=chat_payload)
        end_time = time.perf_counter()
        
        latency_ms = (end_time - start_time) * 1000
        chat_latencies.append(latency_ms)

    chat_p95 = np.percentile(chat_latencies, 95)
    chat_mean = np.mean(chat_latencies)
    results["chat"] = {
        "mean_ms": chat_mean,
        "p95_ms": chat_p95,
        "raw_latencies_ms": chat_latencies
    }

    # 4. Xuất báo cáo ra màn hình
    print("\n" + "=" * 60)
    print("BÁO CÁO ĐỘ TRỄ (LATENCY REPORT)")
    print("=" * 60)
    
    print(f"[API /valuation]")
    print(f"  - Mean Latency: {val_mean:.2f} ms")
    print(f"  - p95 Latency:  {val_p95:.2f} ms")
    print(f"  - Đạt kỳ vọng (< 200ms)? {'✅ CÓ' if val_p95 < 200 else '❌ KHÔNG'}")
    
    print(f"\n[API /chat]")
    print(f"  - Mean Latency: {chat_mean:.2f} ms")
    print(f"  - p95 Latency:  {chat_p95:.2f} ms")
    print(f"  - Đạt kỳ vọng (< 3000ms)? {'✅ CÓ' if chat_p95 < 3000 else '❌ KHÔNG'}")
    print("=" * 60)

    # 5. Lưu kết quả
    output_dir = Path(__file__).parent.parent / "eval" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    out_file = output_dir / "latency_metrics.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"Đã lưu kết quả chi tiết tại: {out_file}")

if __name__ == "__main__":
    main()
