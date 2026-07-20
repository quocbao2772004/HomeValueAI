# Báo Cáo Dự Toán Chi Phí & Lợi Nhuận (Cost Report & Unit Economics)

Báo cáo này phân tích chi tiết chi phí trung bình trên mỗi người dùng hàng tháng (Cost per User per Month - **CPUPM**) cho hệ thống HomeValue AI. Dựa trên phương pháp **Bottom-up Unit Economics**, báo cáo giúp đánh giá điểm hòa vốn và tiềm năng sinh lời của dự án.

---

## 1. Các Giả Định Về Hành Vi Người Dùng (Assumptions & Benchmarks)

Căn cứ vào hành vi sử dụng phổ biến của người dùng đối với AI Chatbot (như Intercom) và ứng dụng PropTech (như Zillow, Batdongsan):

- **Số lượt hỏi mỗi phiên (Queries/Session):** `5 queries` 
  *(Người dùng thường hỏi qua lại 3-5 câu để thỏa mãn một nhu cầu tìm kiếm)*
- **Tần suất truy cập (Sessions/Month):** `4 sessions` 
  *(Trung bình quay lại ứng dụng 1 lần mỗi tuần)*
- **Tổng số queries mỗi tháng:** `20 queries / user / tháng`
- **Tỉ trọng tính năng:**
  - `70%`: Nhóm câu hỏi định giá, xu hướng (Chỉ dùng LLM API).
  - `30%`: Nhóm câu hỏi tiện ích xung quanh (Dùng LLM API + SerpAPI Map).

## 2. Chi Phí Biến Đổi (Variable Cost)

Dựa trên kết quả đo lường thực tế từ hệ thống (`evaluate_cost.py`):
- **Đơn giá gọi LLM GPT-4o-mini:** `$0.0003326 / query`
- **Đơn giá gọi SerpAPI:** `$0.001 / query`
- **Tổng đơn giá nhóm chức năng tiện ích:** `$0.0013326 / query`

**Phân bổ chi phí cho 20 queries/người dùng/tháng:**
- Nhóm Chat (14 queries): `14 × $0.0003326 ≈ $0.0046`
- Nhóm Map (6 queries): `6 × $0.0013326 ≈ $0.0080`
- **Tổng Chi phí biến đổi (CPUPM - Variable): `$0.0126 / user / tháng`** *(Khoảng 320 VNĐ)*.

## 3. Chi Phí Cố Định (Fixed Infrastructure Cost)

Chi phí ước tính tối thiểu để duy trì máy chủ với kiến trúc Serverless:
- **Database (Supabase / MongoDB):** `$25 / tháng`
- **Hosting Backend/Frontend (Vercel / Render):** `$20 / tháng`
- **Tổng Fixed Cost:** `$45.00 / tháng`

## 4. Kịch Bản Mô Phỏng Tài Chính (Monthly P&L Simulation)

Kịch bản được chạy từ công cụ `simulate_monthly_cost.py` với các tham số:
- **Quy mô người dùng (MAU):** `10,000 users`
- **Mức phí Premium (Premium Fee):** `$5.00 / tháng`
- **Tỉ lệ chuyển đổi mua Premium:** `5.0%` (Tương đương 500 khách hàng trả phí)

### Bảng Kết Quả Tính Toán (P&L):
| Hạng mục | Số tiền (USD) | Ghi chú |
| :--- | :--- | :--- |
| **Fixed Cost** (Hạ tầng máy chủ) | `$45.00` | Cố định hàng tháng |
| **Total Variable Cost** (API LLM & Map) | `$126.51` | Tính theo số queries thực tế |
| **TỔNG CHI PHÍ VẬN HÀNH (TOTAL COST)** | **`$171.51`** | |
| | | |
| **DOANH THU (REVENUE)** (500 users × $5) | **`$2,500.00`** | |
| **LỢI NHUẬN GỘP (GROSS PROFIT)** | **`$2,328.49`** | |
| **BIÊN LỢI NHUẬN (GROSS MARGIN)** | **`93.1%`** | Cực kỳ lý tưởng cho một SaaS AI |

## 5. Điểm Hòa Vốn (Break-even Point)
Dựa trên giá bán $5.00/tháng và chi phí biến đổi cho mỗi user quá nhỏ:
- Chỉ cần bán thành công gói Premium cho **10 khách hàng**, dự án sẽ lập tức trang trải được toàn bộ chi phí máy chủ và API (Hòa vốn).
- Mọi khách hàng thứ 11 trở đi gần như mang lại lợi nhuận ròng nguyên vẹn.

---
*Báo cáo được trích xuất tự động từ module tài chính của hệ thống.*
