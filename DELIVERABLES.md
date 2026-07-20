# Deliverables Report — HomeValue AI (C2-App-134)

> Tài liệu tổng hợp toàn bộ kết quả công việc (deliverables) của dự án **HomeValue AI** — Trợ lý định giá bất động sản Vinhomes Hà Nội.

**Team:** Quốc Bảo, Ngọc Bách  
**Ngày cập nhật:** 28/06/2026  
**Repository:** [C2-App-134](https://github.com/AI20K-Build-Cohort-2/C2-App-134)

---

## 1. Deployed Production URL

| Service | URL | Trạng thái |
|---------|-----|------------|
| 🌐 Web App (Frontend + Proxy) | **https://solanai.us** | ✅ Live |
| 🔌 API Service | https://apivinhomes.solanai.us | ✅ Live |
| 💓 Health Check | https://apivinhomes.solanai.us/health | ✅ Live |

**Hạ tầng:** VPS Linux, Docker Compose, systemd service  
**Domain:** solanai.us (Cloudflare DNS + SSL)  
**Kiến trúc:** Frontend proxy (port 2707) → Backend FastAPI (port 1108), internal header auth

---

## 2. Evaluation Metrics

> Chi tiết đầy đủ: [`G3/G3.2 - eval/report.md`](G3/G3.2%20-%20eval/report.md)

### 2.1 Valuation Accuracy (Hold-out Validation, N = 50)

| Metric | Baseline / Target | Actual | Status |
|--------|-------------------|--------|--------|
| MAPE (Mean Absolute Percentage Error) | < 15% | **9.44%** | ✅ Đạt |
| Hit Rate (Giá thực ∈ [P10, P90]) | > 70% | **78.00%** | ✅ Đạt |
| Sai số < 5% | — | 36.0% | — |
| Sai số 5% – 10% | — | 30.0% | — |
| Sai số 10% – 20% | — | 20.0% | — |
| Sai số > 20% | — | 14.0% | — |

### 2.2 System Latency (p95)

| Endpoint | Baseline / Target | Actual | Status |
|----------|-------------------|--------|--------|
| `/valuation` (tính toán Pandas cục bộ) | < 200 ms | **77.86 ms** | ✅ Đạt |
| `/chat` (OpenAI LLM + DB lookup) | < 3,000 ms | **2,882.51 ms** | ✅ Đạt |

### 2.3 Data Quality

| Metric | Baseline / Target | Actual | Status |
|--------|-------------------|--------|--------|
| Deduplication Rate | < 5% | **3.16%** (27/854 rows) | ✅ Đạt |
| Freshness Violation (tin > 45 ngày) | 0% | **0.00%** | ✅ Đạt |
| Unique Listings Available | > 500 | **827 rows** | ✅ Đạt |
| Crawl Source Coverage | 4 sources | **4/4** (Batdongsan, OneHousing, VinhomesLand, VinhomesOnline) | ✅ Đạt |

### 2.4 Chatbot Intent Accuracy (N = 20 câu gán nhãn thủ công)

| Intent | Baseline / Target | Actual | Status |
|--------|-------------------|--------|--------|
| `greeting` | > 95% | **100%** (4/4) | ✅ |
| `valuation` | > 95% | **100%** (4/4) | ✅ |
| `trend` | > 95% | **75%** (3/4) | ⚠️ |
| `snapshot` | > 95% | **50%** (2/4) | ⚠️ |
| `out-of-scope` | > 95% | **0%** (0/4) | ❌ |
| **Overall** | > 95% | **65%** | ❌ Chưa đạt |

> **Ghi chú:** Điểm nghẽn là hệ thống fallback mặc định về `valuation` khi không nhận diện được intent. Action plan cải thiện đã có trong [report.md](G3/G3.2%20-%20eval/report.md#6-action-plan--checklist-in-progress).

### 2.5 Operational Cost (Unit Economics)

| Metric | Baseline / Target | Actual | Status |
|--------|-------------------|--------|--------|
| LLM cost per 1,000 queries (GPT-4o-mini) | < $1.00 | **$0.3326** | ✅ Đạt |
| SerpAPI cost per 1,000 queries | < $2.00 | **$1.00** | ✅ Đạt |
| Tổng cost per 1,000 mixed queries | < $1.50 | **$1.3326** | ✅ Đạt |

---

## 3. Guardrails

> Chi tiết đầy đủ: [`G3/G3.3 - Guardrails/Guardrail_Report_HomeValue_AI.md`](G3/G3.3%20-%20Guardrails/Guardrail_Report_HomeValue_AI.md)

**Khung tham chiếu:** OWASP Top 10 for LLM Applications (2025) & NIST AI RMF

### 3.1 Tổng quan rủi ro & trạng thái

| Rủi ro | Guardrail | Kết quả Red-team | Trạng thái |
|--------|-----------|-------------------|------------|
| R1 — Prompt Injection (LLM01) | Prompt sanitizer + Intent parser | RT-001 ✅ Pass | ✅ |
| R2 — Thao túng định giá / Data Poisoning (LLM03) | AuthN/AuthZ cho `/verified-transactions` | RT-002 🔴 Fail | ❌ P0 |
| R3 — Bịa đặt thông tin / Hallucination (LLM09) | Tách biệt Logic Toán học vs LLM | RT-003 ✅ Pass | ✅ |
| R4 — Lạm dụng API & Chi phí / DoS (LLM10) | Rate Limiting | RT-004 🔴 Fail | ❌ P0 |
| R7 — SQL/NoSQL Injection | Pydantic validation | RT-005 ✅ Pass | ✅ |

### 3.2 Guardrail theo 3 lớp

| Lớp | Controls đạt | Controls chưa đạt |
|-----|-------------|-------------------|
| **A — AI/LLM** | GR-A1 Sanitizer ✅, GR-A2 Math-only pricing ✅, GR-A3 Fallback ✅ | — |
| **B — Bảo mật ứng dụng** | GR-B2 Secret management ✅, GR-B3 Pydantic ✅, GR-B5 CORS ✅ | GR-B1 AuthZ ❌ P0 |
| **C — Hạ tầng / Chống lạm dụng** | GR-C3 Deduplication ✅ | GR-C1 Rate limit ❌ P0, GR-C2 Cost budget ⏳ |

### 3.3 Quyết định phát hành

- ✅ **GO** cho Demo / Pilot nội bộ
- ⛔ **NO-GO** cho Public Production (chờ fix RR-1 AuthZ + RR-2 Rate Limiting)

---

## 4. Demo Video

| Mục | Thông tin |
|-----|----------|
| 🎬 Video Demo | [Google Drive](https://drive.google.com/file/d/16whLZxUet4OdyMEbuzO2eBvgZa9tAXtf/view?usp=drive_link) |
| 📊 Pitch Deck | [Google Drive](https://drive.google.com/file/d/1gFVPDGpt0QEFGJWS1eySx8K3J6FE5JGs/view?usp=sharing) |
| ⏱️ Thời lượng | 3 – 5 phút |

**Nội dung video:**
1. **Slides Pitch** — Vấn đề, giải pháp, tech stack, kiến trúc, kết quả evaluation
2. **Live Demo** — Trình diễn trực tiếp trên https://solanai.us:
   - Chat hỏi định giá bán/thuê căn hộ
   - Xem kết quả P10/P50/P90 với comparable listings
   - Dashboard market trends & charts
   - Tìm tiện ích xung quanh căn thuê (Google Maps)
   - Login/Register flow

---

## 5. Cost Report (Optional)

> Chi tiết đầy đủ: [`G3/G3.5 - Cost Report/cost_report.md`](G3/G3.5%20-%20Cost%20Report/cost_report.md)

### 5.1 Chi phí trên mỗi user/tháng (CPUPM)

**Giả định hành vi người dùng:**
- 5 queries/session × 4 sessions/tháng = **20 queries/user/tháng**
- 70% chat (LLM only) + 30% amenity search (LLM + SerpAPI)

| Hạng mục | Đơn giá | Phân bổ/user/tháng |
|----------|---------|-------------------|
| LLM GPT-4o-mini (14 queries) | $0.0003326/query | $0.0047 |
| SerpAPI Maps (6 queries) | $0.001/query | $0.0060 |
| LLM cho amenity (6 queries) | $0.0003326/query | $0.0020 |
| **Tổng biến đổi (CPUPM)** | | **$0.0126** (~320 VNĐ) |

### 5.2 Chi phí cố định

| Hạng mục | Chi phí/tháng |
|----------|---------------|
| Database (Supabase/MongoDB) | $25.00 |
| Hosting (Vercel/Render/VPS) | $20.00 |
| **Tổng cố định** | **$45.00** |

### 5.3 Mô phỏng P&L (10,000 MAU, 5% conversion, $5/tháng Premium)

| Hạng mục | Số tiền |
|----------|---------|
| Chi phí cố định | $45.00 |
| Chi phí biến đổi (10K users) | $126.51 |
| **Tổng chi phí vận hành** | **$171.51** |
| **Doanh thu** (500 users × $5) | **$2,500.00** |
| **Lợi nhuận gộp** | **$2,328.49** |
| **Biên lợi nhuận** | **93.1%** |

> **Break-even:** Chỉ cần **10 khách hàng Premium** là hòa vốn toàn bộ chi phí hạ tầng + API.

---

## Tổng hợp Links Deliverables

| # | Deliverable | Link |
|---|-------------|------|
| 1 | Source Code | [src/](https://github.com/AI20K-Build-Cohort-2/C2-App-134/tree/main/src) |
| 2 | README.md | [README.md](https://github.com/AI20K-Build-Cohort-2/C2-App-134/blob/main/README.md) |
| 3 | Architecture Diagram | [ARCHITECTURE.md](https://github.com/AI20K-Build-Cohort-2/C2-App-134/blob/main/ARCHITECTURE.md) |
| 4 | AI Logs | [.ai-log/](https://github.com/AI20K-Build-Cohort-2/C2-App-134/tree/main/.ai-log) |
| 5 | Live URL | https://solanai.us |
| 6 | Video Demo | [Google Drive](https://drive.google.com/file/d/16whLZxUet4OdyMEbuzO2eBvgZa9tAXtf/view?usp=drive_link) |
| 7 | Pitch Deck | [Google Drive](https://drive.google.com/file/d/1gFVPDGpt0QEFGJWS1eySx8K3J6FE5JGs/view?usp=sharing) |
| 8 | Development Journal | [JOURNAL.md](https://github.com/AI20K-Build-Cohort-2/C2-App-134/blob/main/JOURNAL.md) |
| 9 | Worklog | [WORKLOG.md](https://github.com/AI20K-Build-Cohort-2/C2-App-134/blob/main/WORKLOG.md) |
| 10 | Evaluation Evidence | [G3/G3.2 - eval/](https://github.com/AI20K-Build-Cohort-2/C2-App-134/tree/main/G3/G3.2%20-%20eval) |
| 11 | Guardrail Report | [G3/G3.3 - Guardrails/](https://github.com/AI20K-Build-Cohort-2/C2-App-134/tree/main/G3/G3.3%20-%20Guardrails) |
| 12 | Cost Report | [G3/G3.5 - Cost Report/](https://github.com/AI20K-Build-Cohort-2/C2-App-134/tree/main/G3/G3.5%20-%20Cost%20Report) |
| 13 | Tests | [tests/](https://github.com/AI20K-Build-Cohort-2/C2-App-134/tree/main/tests) |
| 14 | CI/CD | [ci.yml](https://github.com/AI20K-Build-Cohort-2/C2-App-134/blob/main/.github/workflows/ci.yml) |
