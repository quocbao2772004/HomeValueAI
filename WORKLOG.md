# Worklog — Team HomeValue AI

> Ghi lại tất cả công việc đã làm theo ngày. Ai làm gì, kết quả gì.

---

## 2026-05-29

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Template Sync | Khởi tạo repo từ starter-code-template (cohort 2) | ✅ Done | Cấu trúc project chuẩn, boilerplate code | 0.5h |

**Tổng kết ngày:** Khởi tạo repository từ template BTC cung cấp, sẵn sàng cho sprint đầu tiên.

---

## 2026-06-18

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Quốc Bảo | Lắp ráp HomeValue AI template app | ✅ Done | `src/main.py`, `src/valuation.py`, `src/chatbot.py` hoạt động | 3h |
| Quốc Bảo | Cập nhật README với live demo links (solanai.us) | ✅ Done | README.md có Live URL section | 0.5h |
| Quốc Bảo | Thêm tính năng data evaluation & map dashboard | ✅ Done | `/evaluation` endpoint, map tab trong frontend | 2h |
| Quốc Bảo | Thêm tư vấn tiện ích cho căn thuê (amenity map advice) | ✅ Done | `/amenities/advice` endpoint với Google Maps | 2h |
| Quốc Bảo | Giữ ngữ cảnh chat cho câu hỏi follow-up | ✅ Done | Chat context preservation trong `chatbot.py` | 1h |
| Quốc Bảo | Tích hợp agent tool amenity qua map | ✅ Done | `src/agent_tools.py`, route amenity qua map tool | 1.5h |
| Quốc Bảo | Fix lỗi Google Places API, amenity fallback, distances | ✅ Done | Error handling, fallback URL mode, khoảng cách ước tính | 1.5h |
| Quốc Bảo | Tích hợp SerpApi Google Maps cho amenity search | ✅ Done | SerpApi Maps lookup với place_results + local_results | 1h |
| Quốc Bảo | Fix retry cho frontend API fetches | ✅ Done | Retry logic transient errors trong `app.js` | 0.5h |
| Quốc Bảo | Thêm tính năng Login và Registration | ✅ Done | `src/auth.py`, login/register UI | 2h |
| Quốc Bảo | Fix hiển thị login trước app | ✅ Done | Auth flow: login → dashboard | 0.5h |
| Quốc Bảo | Deploy production lên solanai.us | ✅ Done | https://solanai.us live | 1h |

**Tổng kết ngày:** Sprint lớn nhất — hoàn thành toàn bộ core features: valuation engine, chatbot, amenity advice, authentication, evaluation endpoint. Deploy production thành công.

---

## 2026-06-24

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Quốc Bảo | Fix bug UI projects sliding windows | ✅ Done | Sửa hiển thị danh sách dự án trên frontend | 1h |
| Quốc Bảo | Cập nhật format chatbot response trên web và Zalo | ✅ Done | Response formatting cải thiện cho cả 2 kênh | 1.5h |

**Tổng kết ngày:** Sửa bugs UI và cải thiện format hiển thị chatbot response.

---

## 2026-06-25

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Ngọc Bách | Redesign toàn bộ UI theo phong cách Claude aesthetic | ✅ Done | `frontend/styles.css`, `frontend/index.html` được làm lại | 3h |

**Tổng kết ngày:** Làm lại giao diện frontend với design hiện đại, dark mode, glassmorphism.

---

## 2026-06-27

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Ngọc Bách | Viết evaluation scripts và metrics | ✅ Done | `scripts/evaluate_*.py`, metrics JSON files | 3h |
| Ngọc Bách | Bổ sung hạng mục In Progress và Checklist cho Eval Report | ✅ Done | `G3/G3.2 - results/report.md` cập nhật Action Plan | 1h |
| Ngọc Bách | Cập nhật Deduplication Rate expectation (< 5%) | ✅ Done | Docs cập nhật kỳ vọng phù hợp dữ liệu pre-cleaned | 0.5h |
| Ngọc Bách | Thêm local eval, cost reports, UI fixes, chart formatting | ✅ Done | `G3/G3.5 - Cost Report/`, chart labels, SSL bypass | 2h |

**Tổng kết ngày:** Hoàn thành evaluation pipeline: valuation accuracy, latency, cost analysis, data quality, intent accuracy. Tổng hợp báo cáo đánh giá.

---

## 2026-06-28

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Quốc Bảo | Thêm auth proxy guardrails | ✅ Done | `src/auth.py` rate limiting, proxy security | 1.5h |
| Ngọc Bách | Thêm Sample Guardrail Report | ✅ Done | `G3.3 - Guardrails/Guardrail_Report_HomeValue_AI.md` | 2h |
| Ngọc Bách | Fix broken tests và unused imports sau khi bỏ normalization | ✅ Done | Tests pass, clean imports | 1h |
| Ngọc Bách | Hoàn thiện WORKLOG, JOURNAL, Deliverables Checklist | ✅ Done | Các deliverables #8, #9 hoàn chỉnh | 1h |

**Tổng kết ngày:** Hoàn thiện guardrails (auth proxy + report), fix tests, hoàn thiện tài liệu deliverables cuối cùng.

---

## Tổng hợp đóng góp

| Member | Commits | Vai trò chính |
|--------|---------|---------------|
| Quốc Bảo (quocbao2772004) | 15 | Backend core, crawl/parse pipeline, amenity, auth, deploy |
| Ngọc Bách | 10 | UI redesign, evaluation, guardrails, documentation |
| Template Sync | 1 | Repo initialization |
