# HomeValue AI

> Trợ lý định giá bán/thuê cho căn hộ và nhà thấp tầng Vinhomes Hà Nội, kết hợp dữ liệu listing công khai, snapshot bảng giá, comparable valuation và chatbot tiếng Việt.

## Live Demo

| Service | URL |
|---------|-----|
| Web demo | https://solanai.us |
| API service | https://apivinhomes.solanai.us |
| Health check | https://apivinhomes.solanai.us/health |

## Vấn Đề

Người mua, chủ nhà và môi giới thường phải tự tổng hợp giá rao từ nhiều nguồn, lọc tin nhiễu, rồi ước lượng khoảng giá hợp lý theo dự án, diện tích, số phòng ngủ, nội thất và mục đích bán/thuê. Quy trình này tốn thời gian, thiếu minh bạch về mẫu so sánh và dễ bị lệch bởi một vài tin rao bất thường.

## Giải Pháp

HomeValue AI cung cấp:

- API định giá trả về P10/P50/P90, độ tin cậy, mẫu so sánh và yếu tố ảnh hưởng.
- Chatbot tiếng Việt nhận câu hỏi tự nhiên như "Định giá bán căn hộ Vinhomes Smart City 54m2 2PN full nội thất".
- Dashboard tĩnh để chat, nhập thông tin căn, xem trend thị trường, chart dữ liệu tổng hợp, comparable listings, Google Maps cho từng căn và tiện ích quanh căn thuê.
- Pipeline crawl/parse dữ liệu từ Batdongsan, OneHousing, VinhomesLand và VinhomesOnline theo cấu hình trong `config/projects.yaml`.
- Evaluation endpoint kiểm tra coverage 4 nguồn, duplicate chéo nguồn, quality flags và readiness theo từng dự án.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI, Python 3.11 |
| Valuation | Comparable listings, weighted quantiles, optional sklearn baseline |
| Chatbot | Rule-based intent/entity extraction, optional OpenAI answer rewriting |
| Amenities | Agent tool `maps_amenity_search`, SerpApi Google Maps lookup, optional Google Places fallback |
| Storage | SQLite local fallback, MongoDB production option |
| Frontend | Static HTML/CSS/JavaScript dashboard |
| DevOps | Docker, Docker Compose, GitHub Actions, AI logging hooks |

## Quick Start

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
python3 scripts/serve.py
```

API chạy tại `http://127.0.0.1:8000`.

Chạy frontend local qua proxy:

```bash
python3 scripts/frontend_proxy.py
```

Mở `http://127.0.0.1:2707`. Frontend gọi API qua same-origin `/api`, proxy sẽ forward nội bộ sang backend.

Chạy 2 service theo domain bằng Docker Compose:

```bash
docker compose up -d --build
```

- Web `solanai.us`: `http://127.0.0.1:2707` (frontend proxy + static UI)
- API `apivinhomes.solanai.us`: `http://127.0.0.1:1108/health`

Khi chạy production trên `solanai.us`, frontend dùng API base `/api`. Proxy frontend gắn internal header trước khi gọi backend, còn API public trực tiếp bị chặn ở các endpoint ứng dụng. Backend cần giữ `VALUATION_CORS_ORIGINS` có `https://solanai.us` và `https://www.solanai.us`.

Service production có file mẫu tại `deploy/solanai/homevalue-ai.service`; `WorkingDirectory` trỏ thẳng về `/home/anonymous/VINUNI/buildphase/C2-App-134` để API đọc đúng `.env`, `config/`, `data/` và `prompts/`.

## API Chính

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/projects` | Danh sách dự án đang hỗ trợ |
| POST | `/valuation` | Định giá căn bán/thuê |
| POST | `/chat` | Chatbot định giá/trend/bảng giá |
| GET | `/market-trends` | Median và sample size theo cửa sổ thời gian |
| GET | `/price-snapshots` | Bảng giá tham khảo từ nguồn public |
| GET | `/evaluation` | Đánh giá nguồn crawl, duplicate và độ sẵn sàng dữ liệu |
| POST | `/amenities/advice` | Tạo truy vấn Google Maps/Places và tư vấn tiện ích quanh căn thuê |
| POST | `/verified-transactions` | Nhập giao dịch xác thực thủ công |

Ví dụ:

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Định giá bán căn hộ Vinhomes Smart City 54.2m2 2PN full nội thất"}'
```

Ví dụ gọi API deploy:

```bash
curl -X POST https://apivinhomes.solanai.us/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Định giá bán căn hộ Vinhomes Smart City 54.2m2 2PN full nội thất"}'
```

Ví dụ tìm tiện ích quanh căn thuê:

```bash
curl -X POST https://apivinhomes.solanai.us/amenities/advice \
  -H "Content-Type: application/json" \
  -d '{"project":"vinhomes-smart-city","purpose":"rent","address":"S1.01 Vinhomes Smart City"}'
```

## Project Structure

```text
├── src/                    # FastAPI app, chatbot, crawler, parser, valuation logic
├── frontend/               # Static dashboard copied from BuildPhase UI
├── config/projects.yaml    # Project/source/crawl/quality configuration
├── prompts/                # Chatbot system/user/fallback/intent prompts
├── data/                   # Seed SQLite DB and processed CSVs for demo/test
├── models/                 # Optional sklearn quantile baseline artefacts
├── scripts/                # Crawl, serve, scheduler, train, migration, AI logging hooks
├── tests/                  # pytest suite
├── docs/product/           # PRD, brief, survey and UI docs from product folder
├── docs/technical/         # Backend architecture notes
├── G3/                     # Evaluation evidence (G3.2, G3.3, G3.5)
└── presentation/           # Demo materials placeholder
```

## Data And Operations

Seed data is included in `data/market.sqlite` and `data/processed/*.csv` so the API works immediately. Large raw crawler snapshots are ignored by git; regenerate them when needed:

```bash
python3 scripts/crawl.py --limit 8
python3 scripts/scheduler.py --once
python3 scripts/train.py --purpose sale
```

Storage mode is controlled by `VALUATION_STORAGE_BACKEND`:

- `auto`: use MongoDB when `MONGODB_URI` exists, otherwise SQLite.
- `sqlite`: force local `data/market.sqlite`.
- `mongo`: require `MONGODB_URI`.

Amenity advice hoạt động theo ba chế độ:

- Có `SERPAPI_API_KEY`: backend gọi SerpApi Google Maps, đọc cả `place_results` và `local_results`, rồi trả tên tiện ích, địa chỉ, rating và khoảng cách ước tính.
- Có `GOOGLE_MAPS_API_KEY`: backend gọi Google Places Text Search để lấy tên địa điểm, địa chỉ, rating mẫu.
- Không có key hợp lệ: backend tạo sẵn Google Maps search/embed URL cho từng nhóm tiện ích như giao thông, siêu thị, trường học, y tế, ăn uống mua sắm và công viên.

Agent Pro tự động gắn tiện ích vào định giá khi có vị trí đủ tối thiểu; kết quả Maps được cache theo `MAPS_ENRICHMENT_CACHE_TTL_SECONDS` để các lượt follow-up cùng dự án/tòa/phân khu không gọi lại provider liên tục.

News Search cho Agent Pro lấy Google News RSS theo dự án/quận và các chủ đề hạ tầng, quy hoạch, tiện ích. Nếu có `SERPAPI_API_KEY` hoặc `GOOGLE_MAPS_API_KEY`, backend geocode vị trí định giá và địa danh trong tin để chỉ gắn nhãn "gần vị trí" khi khoảng cách được xác minh trong `NEWS_NEARBY_RADIUS_KM`. Kết quả được cache theo `NEWS_CACHE_TTL_SECONDS`; lỗi provider hoặc tin chưa xác minh không làm hỏng kết quả định giá.

Valuation không dùng trực tiếp mọi dòng crawl thô. Backend tạo canonical key theo dự án, loại hình, mục đích, diện tích, số phòng ngủ, mức giá và dấu hiệu vị trí để gộp duplicate chéo nguồn trước khi tính P10/P50/P90. Trong seed DB hiện tại `/evaluation` ghi nhận 854 listing rows thô, 827 listing rows unique và 27 duplicate rows đã được gộp.

Các mốc giá trong UI:

- `P10`: vùng giá thấp trong nhóm so sánh, khoảng 10% mẫu rẻ hơn mức này.
- `P50`: trung vị thị trường, dùng làm giá neo chính.
- `P90`: vùng giá cao trong nhóm so sánh, khoảng 10% mẫu đắt hơn mức này.

## Deliverables Checklist

| # | Deliverable | Status | Location |
|---|-------------|--------|----------|
| 1 | Source Code | ✅ Done | [`src/`](src/) |
| 2 | README.md | ✅ Done | [`README.md`](README.md) |
| 3 | Architecture Diagram | ✅ Done | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| 4 | AI Logs | ✅ Done | [`.ai-log/`](.ai-log/) |
| 5 | Live URL | ✅ Done | https://solanai.us |
| 6 | Video Demo | ✅ Done | [Google Drive](https://drive.google.com/file/d/16whLZxUet4OdyMEbuzO2eBvgZa9tAXtf/view?usp=drive_link) |
| 7 | Pitch Deck | ✅ Done | [Google Drive](https://drive.google.com/file/d/1gFVPDGpt0QEFGJWS1eySx8K3J6FE5JGs/view?usp=sharing) |
| 8 | Development Journal | ✅ Done | [`JOURNAL.md`](JOURNAL.md) |
| 9 | Worklog | ✅ Done | [`WORKLOG.md`](WORKLOG.md) |
| 10 | Evaluation Evidence | ✅ Done | [`G3/G3.2 - results/report.md`](G3/G3.2%20-%20results/report.md) |

**Bonus:**
- [x] Dockerfile and Docker Compose
- [x] GitHub Actions CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml))
- [x] Guardrail Report ([`G3/G3.3 - Guardrails/`](G3/G3.3%20-%20Guardrails/))
- [x] Cost Report ([`G3/G3.5 - Cost Report/`](G3/G3.5%20-%20Cost%20Report/))
- [x] Product docs ([`docs/product/`](docs/product/))
- [x] Tests in [`tests/`](tests/) (8 test files)

## License

MIT
