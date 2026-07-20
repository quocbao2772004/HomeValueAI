import sys
import json
from pathlib import Path

# Thêm thư mục gốc vào PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

def main():
    print("=" * 60)
    print("  OPERATIONAL COST EVALUATION (UNIT ECONOMICS)")
    print("=" * 60)

    # Cấu hình đường dẫn
    project_root = Path(__file__).parent.parent
    prompts_dir = project_root / "prompts"
    system_prompt_path = prompts_dir / "chatbot_system.md"
    user_prompt_path = prompts_dir / "chatbot_user.md"

    # Đọc nội dung file
    def read_file_safe(filepath):
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    system_content = read_file_safe(system_prompt_path)
    user_content = read_file_safe(user_prompt_path)

    # Giả định Context mẫu (JSON từ database đưa vào prompt) có khoảng 1500 ký tự
    mock_context_chars = 1500
    
    total_input_chars = len(system_content) + len(user_content) + mock_context_chars

    # 1. Phân tích Token Chatbot (OpenAI)
    # Tỷ lệ ước lượng: 1 token ≈ 3 ký tự (tiếng Việt)
    estimated_input_tokens = total_input_chars / 3.0
    estimated_output_tokens = 200  # Cố định theo yêu cầu

    # Bảng giá GPT-4o-mini
    price_per_1m_input = 0.15
    price_per_1m_output = 0.60

    cost_input_per_query = (estimated_input_tokens / 1_000_000) * price_per_1m_input
    cost_output_per_query = (estimated_output_tokens / 1_000_000) * price_per_1m_output
    total_cost_per_chat_query = cost_input_per_query + cost_output_per_query

    total_cost_1000_chat = total_cost_per_chat_query * 1000

    # 2. Phân tích Amenity Search (SerpAPI)
    # Bảng giá tiêu chuẩn: $50 / 50,000 queries => $1.00 / 1000 queries
    cost_1000_amenity = 1.00
    total_cost_per_amenity_query = cost_1000_amenity / 1000

    # 3. Tổng hợp chi phí cho 1000 queries /chat + 1000 queries /amenities
    total_cost = total_cost_1000_chat + cost_1000_amenity

    # 4. Xuất báo cáo ra màn hình
    print(f"[1] LLM Chatbot (/chat) - Mô hình GPT-4o-mini")
    print(f"  - Chiều dài System Prompt: {len(system_content):,} chars")
    print(f"  - Chiều dài User Prompt:   {len(user_content):,} chars")
    print(f"  - Chiều dài Context mẫu:   {mock_context_chars:,} chars")
    print(f"  - Tổng Input Chars:        {total_input_chars:,} chars")
    print(f"  - Ước lượng Input Tokens:  {estimated_input_tokens:,.0f} tokens / query")
    print(f"  - Ước lượng Output Tokens: {estimated_output_tokens:,.0f} tokens / query")
    print(f"  => Chi phí /chat:          ${total_cost_1000_chat:.4f} / 1,000 queries\n")

    print(f"[2] Tiện ích quanh đây (/amenities) - SerpAPI")
    print(f"  - Đơn giá SerpAPI:         $50.00 / 50,000 credits")
    print(f"  => Chi phí /amenities:     ${cost_1000_amenity:.4f} / 1,000 queries\n")

    print("-" * 60)
    print(f"TỔNG CHI PHÍ ƯỚC TÍNH (1,000 /chat + 1,000 /amenities)")
    print(f"  Total Cost: ${total_cost:.4f}")
    print(f"  Kỳ vọng (< $1.5): {'✅ ĐẠT' if total_cost < 1.5 else '❌ KHÔNG ĐẠT'}")
    print("=" * 60)

    # Note quan trọng
    print("\n*Lưu ý: Cách tính token này là ước lượng (Estimation) dựa trên độ dài ký tự ")
    print("tiếng Việt chứ không đếm chính xác bằng thư viện tiktoken. Sai số dự kiến là ")
    print("nhỏ và chấp nhận được đối với mục đích dự toán chi phí.*")

    # 5. Lưu trữ số liệu
    results = {
        "assumptions": {
            "chars_per_token": 3.0,
            "mock_context_chars": mock_context_chars,
            "estimated_output_tokens": estimated_output_tokens,
            "pricing": {
                "gpt-4o-mini_input_1M": price_per_1m_input,
                "gpt-4o-mini_output_1M": price_per_1m_output,
                "serpapi_1k_credits": cost_1000_amenity
            }
        },
        "metrics": {
            "input_tokens_per_query": round(estimated_input_tokens),
            "cost_1000_chat_usd": round(total_cost_1000_chat, 4),
            "cost_1000_amenity_usd": round(cost_1000_amenity, 4),
            "total_cost_1000_mixed_queries_usd": round(total_cost, 4),
            "meets_expectation": total_cost < 1.5
        }
    }

    output_dir = project_root / "eval" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / "cost_metrics.json"

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nĐã lưu kết quả chi tiết tại: {out_file}")


if __name__ == "__main__":
    main()
