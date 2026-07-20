# Weekly Journal — Team HomeValue AI

> Ghi lại mỗi tuần: học được gì, khó khăn gì, quyết định gì, kế hoạch tiếp.

---

## Week 1: 2026-05-29 - 2026-06-04

### Mục tiêu tuần này
- [x] Khởi tạo repository từ template BTC
- [x] Phân tích yêu cầu dự án và lựa chọn bài toán
- [x] Lên kế hoạch Product Brief và PRD

### Đã hoàn thành
- Repo được tạo từ starter-code-template cohort 2, cấu trúc chuẩn
- Xác định bài toán: Trợ lý định giá bán/thuê bất động sản Vinhomes Hà Nội
- Viết Product Brief, PRD, phân tích đối thủ (AIPrice.vn, Batdongsan)

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Chọn giữa giá thuê hay giá bán | Hỗ trợ cả hai, dùng flag `purpose: sale/rent` | Phạm vi rõ ràng hơn |
| Nguồn dữ liệu nào đáng tin cậy | Crawl từ 4 nguồn: Batdongsan, OneHousing, VinhomesLand, VinhomesOnline | Coverage tốt hơn |

### Bài học
- Bài toán BĐS phải có dữ liệu đủ lớn và đa nguồn mới cho kết quả chính xác
- PRD cần focus vào MVP — không cố làm nhiều feature cùng lúc

### Kế hoạch tuần sau
- [x] Xây dựng pipeline crawl/parse dữ liệu
- [x] Setup backend FastAPI cơ bản

---

## Week 2: 2026-06-05 - 2026-06-11

### Mục tiêu tuần này
- [x] Xây dựng data pipeline: crawl → parse → normalize → store
- [x] Implement valuation engine (P10/P50/P90)
- [x] Setup storage layer (SQLite local + MongoDB option)

### Đã hoàn thành
- Pipeline crawl hoàn chỉnh: `scripts/crawl.py` → `src/crawler.py` → `src/parser.py`
- Valuation engine dùng weighted quantiles, trả P10/P50/P90 + confidence + caveats
- Config-driven architecture qua `config/projects.yaml`
- Storage abstraction layer: SQLite fallback + MongoDB production

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| HTML structure khác nhau giữa các nguồn | Parser đa năng: regex, `__NEXT_DATA__`, JSON-LD | Hỗ trợ 4 nguồn |
| Duplicate listings giữa các nguồn | Canonical key deduplication (`src/dedupe.py`) | 3.16% duplicate rate |
| Giá rao bất thường làm lệch thống kê | Weighted quantiles thay vì simple average | P10/P50/P90 ổn định |

### Bài học
- Config-driven design giúp thêm nguồn mới không cần sửa code
- Deduplication chéo nguồn quan trọng hơn expected — 27 rows duplicate trong 854 rows

### Kế hoạch tuần sau
- [x] Xây chatbot tiếng Việt
- [x] Tích hợp OpenAI rewrite

---

## Week 3: 2026-06-12 - 2026-06-18

### Mục tiêu tuần này
- [x] Xây chatbot tiếng Việt với intent detection
- [x] Tích hợp OpenAI cho answer rewriting
- [x] Deploy production lên solanai.us
- [x] Thêm amenity advice cho căn thuê

### Đã hoàn thành
- Chatbot hoàn chỉnh: intent detection (greeting/valuation/trend/snapshot) + entity extraction (project/area/bedrooms/purpose/furniture)
- OpenAI GPT-4o-mini rewrite cho câu trả lời tự nhiên hơn
- Amenity advice: SerpApi Maps → Google Places fallback → URL-only mode
- Login/Registration system
- **Deploy production**: https://solanai.us (frontend), https://apivinhomes.solanai.us (API)
- Frontend static dashboard hoạt động với chat, valuation, market trends, comparable listings

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| CORS issues khi frontend gọi API | Proxy frontend (`scripts/frontend_proxy.py`) + CORS config | Same-origin `/api` hoạt động |
| Google Places API key chi phí cao | Ưu tiên SerpApi, fallback Google Places, cuối cùng tạo URL | Chi phí gần $0 |
| Chat context mất khi follow-up | Preserve context trong session | Chat liền mạch |

### Bài học
- Deploy sớm, test trên production thực tế — nhiều bug chỉ xuất hiện khi live
- Amenity advice 3 tầng (SerpApi → Places → URL) đảm bảo luôn có output dù thiếu API key
- Login flow cần hiển thị trước app để bảo vệ API

### Kế hoạch tuần sau
- [x] Fix bugs UI
- [x] Redesign giao diện

---

## Week 4: 2026-06-19 - 2026-06-25

### Mục tiêu tuần này
- [x] Fix bugs UI và cải thiện UX
- [x] Redesign giao diện theo phong cách hiện đại
- [x] Cải thiện format chatbot response

### Đã hoàn thành
- Fix bug projects sliding windows trên frontend
- Cập nhật format chatbot response cho cả web và Zalo
- **Redesign toàn bộ UI** theo phong cách Claude aesthetic: dark mode, glassmorphism, modern typography
- Giao diện mới responsive, premium look & feel

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| UI cũ trông basic, thiếu ấn tượng | Redesign toàn bộ với dark mode + glassmorphism | Giao diện premium |
| Chatbot response hiển thị khác nhau web vs Zalo | Format riêng cho mỗi kênh (`src/zalo_format.py`) | Consistent UX |

### Bài học
- UI/UX là tiêu chí chấm điểm quan trọng — đầu tư redesign đáng giá
- Dark mode + glassmorphism tạo ấn tượng tốt với giám khảo

### Kế hoạch tuần sau
- [x] Viết evaluation scripts
- [x] Hoàn thiện guardrails và documentation

---

## Week 5: 2026-06-26 - 2026-06-28

### Mục tiêu tuần này
- [x] Chạy evaluation pipeline đầy đủ
- [x] Viết Guardrail Report
- [x] Hoàn thiện Cost Report
- [x] Fix tests, clean code
- [x] Hoàn thiện tất cả deliverables

### Đã hoàn thành
- **Evaluation pipeline hoàn chỉnh:**
  - Valuation Accuracy: MAPE 9.44%, Hit Rate 78%
  - System Latency: valuation p95 = 77.86ms, chat p95 = 2.88s
  - Cost Analysis: $1.33/1000 queries
  - Data Quality: Dedup rate 3.16%, Freshness 100%
  - Intent Accuracy: 65% (điểm nghẽn: out-of-scope fallback)
- **Guardrail Report:** Auth proxy guardrails, input validation, rate limiting
- **Cost Report:** Unit economics, monthly simulation
- Fix broken tests sau khi refactor normalization
- Hoàn thiện WORKLOG, JOURNAL, Deliverables Checklist
- **Video demo** và **Pitch deck** đã sẵn sàng

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Intent accuracy chỉ đạt 65% | Xác định root cause: thiếu out-of-scope rule | Action plan đã lên |
| Tests broken sau refactor | Sửa imports và assertions | 100% tests pass |

### Bài học
- Evaluation Evidence là deliverable ít đội có — đây là lợi thế cạnh tranh lớn
- Guardrails (rate limiting, auth proxy) cần thiết cho production
- Cost report minh bạch giúp chứng minh feasibility thương mại

### Kế hoạch tiếp theo
- [ ] Fix intent accuracy lên > 95% (thêm out-of-scope rules)
- [ ] Chuẩn bị thuyết trình Demo Day

---
