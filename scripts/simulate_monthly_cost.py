import sys
import json
import argparse
from pathlib import Path

# Thêm thư mục gốc vào PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

def main():
    parser = argparse.ArgumentParser(description="Simulate Monthly Operational Cost (Unit Economics)")
    parser.add_argument("--mau", type=int, default=1000, help="Monthly Active Users (Default: 1000)")
    parser.add_argument("--premium-fee", type=float, default=5.0, help="Monthly subscription fee in USD for premium users (Default: 5.0)")
    parser.add_argument("--premium-conversion", type=float, default=0.05, help="Conversion rate to premium (Default: 5 percent)")
    args = parser.parse_args()

    mau = args.mau
    premium_fee = args.premium_fee
    conversion_rate = args.premium_conversion

    print("=" * 70)
    print("  SIMULATE MONTHLY COST & UNIT ECONOMICS (P&L)")
    print("=" * 70)

    # 1. Giả định (Assumptions)
    queries_per_session = 5
    sessions_per_month = 4
    queries_per_user_month = queries_per_session * sessions_per_month

    chat_ratio = 0.70
    amenity_ratio = 0.30

    # Thông số từ evaluate_cost.py
    input_tokens = 1417
    output_tokens = 200
    price_1m_input = 0.15
    price_1m_output = 0.60
    price_serpapi_1k = 1.00

    cost_chat = ((input_tokens / 1_000_000) * price_1m_input) + ((output_tokens / 1_000_000) * price_1m_output)
    cost_amenity = cost_chat + (price_serpapi_1k / 1000)

    # Tính Variable Cost / User / Month
    monthly_chat_queries = queries_per_user_month * chat_ratio
    monthly_amenity_queries = queries_per_user_month * amenity_ratio
    
    vc_user_month = (monthly_chat_queries * cost_chat) + (monthly_amenity_queries * cost_amenity)

    # 2. Chi phí hạ tầng (Fixed Infrastructure Cost)
    # Database: $25, Hosting: $20
    fixed_cost_month = 45.0

    # 3. Tính Tổng Chi Phí (Total Costs)
    total_variable_cost = mau * vc_user_month
    total_cost = total_variable_cost + fixed_cost_month
    cpupm = total_cost / mau if mau > 0 else 0

    # 4. Tính Doanh thu & Lợi nhuận (Revenue & Profit)
    paying_users = int(mau * conversion_rate)
    monthly_revenue = paying_users * premium_fee
    gross_profit = monthly_revenue - total_cost
    margin = (gross_profit / monthly_revenue * 100) if monthly_revenue > 0 else 0

    # Break-even point (Số paying users cần thiết để hòa vốn Fixed Cost, bù đắp VC)
    # Lợi nhuận trên mỗi paying user: Contribution Margin = premium_fee - vc_user_month
    contribution_margin = premium_fee - vc_user_month
    if contribution_margin > 0:
        break_even_paying_users = fixed_cost_month / contribution_margin
    else:
        break_even_paying_users = float('inf')

    print(f"[1] THÔNG SỐ GIẢ ĐỊNH (ASSUMPTIONS)")
    print(f"  - Monthly Active Users (MAU): {mau:,} users")
    print(f"  - Hành vi: {queries_per_user_month} queries / user / tháng (Tỉ trọng: 70% Chat, 30% Map)")
    print(f"  - Premium Fee: ${premium_fee:.2f} / tháng | Tỉ lệ chuyển đổi: {conversion_rate*100:.1f}%")
    print(f"  - Variable Cost / User / Month (CPUPM - Variable): ${vc_user_month:.4f}")

    print(f"\n[2] CHI PHÍ VÀ DOANH THU (MONTHLY P&L)")
    print(f"  - Chi phí hạ tầng cố định (Fixed Cost):  ${fixed_cost_month:,.2f}")
    print(f"  - Tổng chi phí biến đổi (Variable Cost): ${total_variable_cost:,.2f}")
    print(f"  => TỔNG CHI PHÍ VẬN HÀNH (TOTAL COST):   ${total_cost:,.2f}")
    print(f"  => Chi phí trung bình (Total CPUPM):     ${cpupm:.4f}")
    
    print(f"  --------------------------------------------------")
    print(f"  - Người dùng trả phí (Paying Users):     {paying_users:,}")
    print(f"  - TỔNG DOANH THU (REVENUE):              ${monthly_revenue:,.2f}")
    print(f"  => LỢI NHUẬN GỘP (GROSS PROFIT):         ${gross_profit:,.2f}")
    print(f"  => BIÊN LỢI NHUẬN (GROSS MARGIN):        {margin:.1f}%")
    
    print(f"\n[3] PHÂN TÍCH ĐIỂM HÒA VỐN (BREAK-EVEN)")
    print(f"  - Cần tối thiểu {int(break_even_paying_users) + 1} người dùng trả phí (${premium_fee}/tháng) để hệ thống tự nuôi sống (hòa vốn).")

    print("=" * 70)

    # 5. Lưu trữ số liệu
    results = {
        "assumptions": {
            "mau": mau,
            "queries_per_user_month": queries_per_user_month,
            "premium_fee_usd": premium_fee,
            "conversion_rate": conversion_rate,
            "variable_cost_user_month_usd": round(vc_user_month, 4),
            "fixed_cost_month_usd": fixed_cost_month
        },
        "financials": {
            "total_variable_cost_usd": round(total_variable_cost, 2),
            "total_cost_usd": round(total_cost, 2),
            "total_cpupm_usd": round(cpupm, 4),
            "paying_users": paying_users,
            "monthly_revenue_usd": round(monthly_revenue, 2),
            "gross_profit_usd": round(gross_profit, 2),
            "gross_margin_percent": round(margin, 1),
            "break_even_paying_users": int(break_even_paying_users) + 1 if break_even_paying_users != float('inf') else -1
        }
    }

    output_dir = Path(__file__).parent.parent / "eval" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / "monthly_cost_simulation.json"

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nĐã lưu kết quả chi tiết tại: {out_file}")


if __name__ == "__main__":
    main()
