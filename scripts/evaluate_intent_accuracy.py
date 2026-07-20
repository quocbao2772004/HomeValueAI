import sys
import json
from pathlib import Path

# Thêm thư mục gốc vào PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.chatbot import _detect_intent

def main():
    print("=" * 60)
    print("  CHATBOT INTENT ACCURACY EVALUATION")
    print("=" * 60)

    # 1. Chuẩn bị Dataset Đánh Giá
    dataset = [
        # Greeting
        {"message": "Xin chào", "expected": "greeting"},
        {"message": "Hello", "expected": "greeting"},
        {"message": "Chào bạn", "expected": "greeting"},
        {"message": "Hi shop", "expected": "greeting"},
        
        # Valuation
        {"message": "Định giá căn hộ 54m2 Vinhomes Smart City", "expected": "valuation"},
        {"message": "Nhà tôi bán được bao nhiêu tiền", "expected": "valuation"},
        {"message": "Cần bán gấp shophouse 120m2", "expected": "valuation"},
        {"message": "Thuê căn 2PN Ocean Park giá bao nhiêu", "expected": "valuation"},
        
        # Trend
        {"message": "Giá chung cư Hà Nội năm nay tăng hay giảm?", "expected": "trend"},
        {"message": "Xu hướng giá bất động sản hiện nay", "expected": "trend"},
        {"message": "Thị trường dạo này thế nào", "expected": "trend"},
        {"message": "Trend giá thuê", "expected": "trend"},
        
        # Snapshot
        {"message": "Cho tôi thống kê thị trường Vinhomes Smart City", "expected": "snapshot"},
        {"message": "Tình hình giao dịch khu vực này thế nào", "expected": "snapshot"},
        {"message": "Bảng giá chủ đầu tư mới nhất", "expected": "snapshot"},
        {"message": "Tham khảo giá bán tham chiếu", "expected": "snapshot"},
        
        # Out-of-scope
        {"message": "Thời tiết hôm nay thế nào?", "expected": "out-of-scope"},
        {"message": "Ai là tổng thống Mỹ?", "expected": "out-of-scope"},
        {"message": "Tôi muốn đặt vé máy bay", "expected": "out-of-scope"},
        {"message": "Ăn trưa món gì ngon?", "expected": "out-of-scope"}
    ]

    # 2. Tiến hành Đánh Giá
    results = []
    correct_count = 0
    total_cases = len(dataset)
    
    # Dictionary để tính per-intent metrics
    intent_metrics = {
        "greeting": {"total": 0, "correct": 0},
        "valuation": {"total": 0, "correct": 0},
        "trend": {"total": 0, "correct": 0},
        "snapshot": {"total": 0, "correct": 0},
        "out-of-scope": {"total": 0, "correct": 0}
    }
    
    # Confusion matrix: confusion[expected][predicted]
    confusion_matrix = {}

    for item in dataset:
        msg = item["message"]
        expected = item["expected"]
        
        # Gọi hàm phân loại intent của hệ thống
        predicted = _detect_intent(msg)
        
        # Note: Hiện tại _detect_intent() không có luật cho "out-of-scope", 
        # nó sẽ default về "valuation". Để làm nổi bật điều này, chúng ta 
        # vẫn so sánh với "out-of-scope"
        is_correct = (predicted == expected)
        
        if is_correct:
            correct_count += 1
            intent_metrics[expected]["correct"] += 1
            
        intent_metrics[expected]["total"] += 1
        
        if expected not in confusion_matrix:
            confusion_matrix[expected] = {}
        confusion_matrix[expected][predicted] = confusion_matrix[expected].get(predicted, 0) + 1
        
        results.append({
            "message": msg,
            "expected": expected,
            "predicted": predicted,
            "is_correct": is_correct
        })

    # 3. Tính Toán Metrics
    overall_accuracy = correct_count / total_cases

    print(f"\n[1] TỔNG QUAN")
    print(f"  - Tổng số mẫu (Test cases): {total_cases}")
    print(f"  - Số mẫu đoán đúng:        {correct_count}")
    print(f"  - Accuracy:                 {overall_accuracy*100:.2f}%")
    print(f"  - Kỳ vọng (> 95%):          {'✅ ĐẠT' if overall_accuracy > 0.95 else '❌ KHÔNG ĐẠT'}")

    print(f"\n[2] CHI TIẾT THEO INTENT (Per-Intent Accuracy)")
    for intent, data in intent_metrics.items():
        total = data["total"]
        if total > 0:
            acc = data["correct"] / total
            print(f"  - {intent:<15}: {acc*100:6.2f}% ({data['correct']}/{total})")

    print(f"\n[3] CONFUSION MATRIX (Expected -> Predicted)")
    for exp, preds in confusion_matrix.items():
        preds_str = ", ".join([f"'{k}': {v}" for k, v in preds.items()])
        print(f"  - {exp:<15} => {preds_str}")

    print("\n*Nhận xét: Nếu 'out-of-scope' bị nhầm thành 'valuation', đó là do thiết kế hiện tại đang dùng 'valuation' làm fallback mặc định (default return).*")

    # 4. Xuất Báo Cáo json
    output_dir = Path(__file__).parent.parent / "eval" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / "intent_accuracy_metrics.json"

    report_data = {
        "overall_accuracy": overall_accuracy,
        "total_cases": total_cases,
        "correct_count": correct_count,
        "per_intent_metrics": intent_metrics,
        "confusion_matrix": confusion_matrix,
        "detailed_results": results
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    print(f"\nĐã lưu kết quả chi tiết tại: {out_file}")
    print("=" * 60)


if __name__ == "__main__":
    main()
