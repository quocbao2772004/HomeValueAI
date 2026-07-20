# Product Requirements Document (PRD)

**Dự án:** AI Định Giá Căn Hộ Đại Đô Thị (HomeValue AI)
**Tầm nhìn:** Trở thành nền tảng định giá và phân tích thị trường thứ cấp đáng tin cậy nhất dành riêng cho các Đại Đô Thị tại Việt Nam.

---

## 1. Mục Đích & Phạm Vi Dự Án (Project Scope)
Dự án hướng tới việc giải quyết bài toán định giá ảo trên thị trường mua bán/cho thuê lại căn hộ tại **tất cả các Đại đô thị lớn** (Ví dụ: Vinhomes Ocean Park, Smart City, Grand Park, Central Park, Ecopark...).

Dự án cung cấp một bộ công cụ sử dụng Trí tuệ nhân tạo (Machine Learning & LLM) để:
- Định giá trị thực của căn hộ dựa trên các đặc điểm vi mô (Tầng, View, Nội thất, Phân khu).
- Cung cấp lý do giải thích mức giá minh bạch (Explainable AI).
- Theo dõi biến động và xu hướng giá theo thời gian thực (Market Trends).

## 2. Các Tính Năng Cốt Lõi (Core Features)

### Epic 1: Giao Diện Người Dùng (User Experience)
- **F1. Form Định Giá Đa Năng:**
  - Chọn Đại đô thị (VOP, Smart City, Grand Park...).
  - Nhập liệu chi tiết: Diện tích, Số phòng ngủ/WC, Khoảng tầng, Tầm View, Tình trạng nội thất.
- **F2. Báo Cáo Định Giá Chi Tiết (Valuation Dashboard):**
  - Hiển thị mức giá ước tính (Bán / Cho Thuê).
  - Biểu đồ phân bố độ tin cậy (Confidence Interval).
- **F3. Khối Giải Thích AI (Explainable AI):**
  - Tích hợp LLM sinh ra đoạn văn 3-4 câu giải thích logic tại sao lại có mức giá đó dựa trên tiện ích nội khu và dữ liệu thị trường hiện tại.

### Epic 2: Lõi AI Định Giá (AI Engine)
- **F4. Multi-City ML Models:**
  - Huấn luyện mô hình ML (`RandomForest`, `XGBoost`) độc lập cho từng Đại đô thị để đảm bảo độ chính xác vi mô cao nhất (R2 Score >= 0.85).
- **F5. Automated Data Pipeline:**
  - Hệ thống crawl dữ liệu, làm sạch và dán nhãn tự động.

## 3. Kiến Trúc Kỹ Thuật (Tech Stack)
- **Frontend:** Next.js (React), TailwindCSS, TypeScript.
- **Backend:** FastAPI (Python).
- **Machine Learning:** Scikit-learn, Pandas.
- **LLM Integration:** OpenAI API.
