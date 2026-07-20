# Manual Test Evidence — HomeValue AI

> Bằng chứng kiểm thử thủ công với output thực tế chạy trên seed DB `data/market.sqlite`.
> Môi trường: `VALUATION_LLM_ENABLED=0`, `VALUATION_STORAGE_BACKEND=sqlite`, FastAPI TestClient.
> Ngày chạy: 2026-06-20. Test suite kèm theo: `33 passed`.

Cách tái lập:

```bash
cp .env.example .env
pip install -r requirements.txt
python3 -m pytest -q          # 33 passed
python3 scripts/serve.py      # API tại http://127.0.0.1:8000
```

Các case dưới đây gọi trực tiếp API và dán nguyên văn response thực tế (rút gọn các mảng dài, giữ nguyên số liệu).

---

## Tổng hợp kết quả

| # | Test case | Endpoint | Kỳ vọng | Thực tế | Status |
|---|-----------|----------|---------|---------|--------|
| TC1 | Health check | `GET /health` | 200, status ok | `{"status":"ok"}` | ✅ |
| TC2 | Danh sách dự án | `GET /projects` | 4 dự án có alias | 4 dự án trả về đúng | ✅ |
| TC3 | Định giá bán qua API | `POST /valuation` | P10/P50/P90 + comparables | 4.18 / 4.93 / 5.58 tỷ, 263 mẫu | ✅ |
| TC4 | Chatbot định giá bán (tiếng Việt) | `POST /chat` | answer có giá + tiện ích | đúng định dạng, có tiện ích | ✅ |
| TC5 | Chatbot định giá thuê + tiện ích | `POST /chat` | giá thuê/tháng + tiện ích | 5 - 12.3 triệu/tháng | ✅ |
| TC6 | Chatbot thiếu thông tin | `POST /chat` | hỏi lại slot còn thiếu | missing `project`, `area_m2` | ✅ |
| TC7 | Market trends | `GET /market-trends` | median theo cửa sổ | median 91 triệu/m2, 263 mẫu | ✅ |
| TC8 | Data quality evaluation | `GET /evaluation` | coverage + dedupe | 827 raw / 827 unique / 0 dup | ✅ |

Latency thực đo (TestClient, trung bình 5 lần sau warmup):

| Endpoint | avg | min | max |
|----------|-----|-----|-----|
| `GET /health` | 2.4 ms | 2.0 ms | 2.8 ms |
| `GET /projects` | 15.3 ms | 14.2 ms | 17.9 ms |
| `POST /valuation` | 114.4 ms | 102.7 ms | 147.9 ms |
| `POST /chat` | 1563.6 ms | 1532.6 ms | 1632.8 ms |
| `GET /market-trends` | 108.8 ms | 94.2 ms | 143.0 ms |
| `GET /evaluation` | 132.5 ms | 126.9 ms | 138.0 ms |

Lưu ý: `/chat` cao hơn vì khi định giá nó gọi thêm tool tìm tiện ích xung quanh (Google Maps/SerpApi) để giải thích giá. Tắt tiện ích hoặc cache lại sẽ giảm về mức ~150 ms như `/valuation`.

---

## TC1 — Health check

Request:

```http
GET /health
```

Response (200):

```json
{ "status": "ok" }
```

---

## TC2 — Danh sách dự án hỗ trợ

Request:

```http
GET /projects
```

Response (200, rút gọn alias):

```json
[
  { "slug": "vinhomes-ocean-park",   "name": "Vinhomes Ocean Park",   "district_hint": "Gia Lâm" },
  { "slug": "vinhomes-smart-city",   "name": "Vinhomes Smart City",   "district_hint": "Nam Từ Liêm" },
  { "slug": "vinhomes-ocean-park-2", "name": "Vinhomes Ocean Park 2", "district_hint": "Hưng Yên" },
  { "slug": "vinhomes-ocean-park-3", "name": "Vinhomes Ocean Park 3", "district_hint": "Hưng Yên" }
]
```

---

## TC3 — Định giá bán căn hộ qua `/valuation`

Request:

```http
POST /valuation
Content-Type: application/json

{
  "purpose": "sale",
  "project": "vinhomes-smart-city",
  "property_type": "apartment",
  "area_m2": 54.2,
  "bedrooms": 2,
  "furniture": "full"
}
```

Response (200, rút gọn `comparable_listings`):

```json
{
  "purpose": "sale",
  "project": "Vinhomes Smart City",
  "property_type": "apartment",
  "currency": "VND",
  "estimate_basis": "listing_comparables_plus_verified_transactions_with_snapshot_reference",
  "p10_total_vnd": 4184938340.0,
  "p50_total_vnd": 4932200000.0,
  "p90_total_vnd": 5582600000.0,
  "p10_price_per_m2_vnd": 77212884.0,
  "p50_price_per_m2_vnd": 91000000.0,
  "p90_price_per_m2_vnd": 103000000.0,
  "sample_size": 263,
  "confidence": "high",
  "data_freshness": "2026-06-14T04:45:56.098261+00:00",
  "comparable_listings": [
    {
      "title": "Bán nhanh: Căn 2PN1VS tại S303 giá 4,45 tỷ full nội thất đẹp (dự án Smart City)",
      "price_total_vnd": 4450000000.0,
      "price_per_m2_vnd": 82103321.03,
      "area_m2": 54.2, "bedrooms": 2, "subdivision": "Sapphire", "furniture": "full",
      "similarity_score": 1.11
    },
    {
      "title": "Cắt lỗ 300tr! 2PN +(1VS) 54,5m2 tòa GS1 - The Miami, giá 4,65 tỷ",
      "price_total_vnd": 4650000000.0, "area_m2": 54.5, "bedrooms": 2,
      "subdivision": "Masteri", "furniture": "full", "similarity_score": 1.108
    }
  ]
}
```

Nhận xét: ước tính P50 ≈ 4.93 tỷ (≈ 91 triệu/m2), confidence `high` với 263 mẫu so sánh — nằm trong khoảng các tin chào bán thực tế 4.45–5.3 tỷ.

---

## TC4 — Chatbot định giá bán (input tiếng Việt tự nhiên)

Request:

```http
POST /chat
Content-Type: application/json

{ "message": "Định giá bán căn hộ Vinhomes Smart City 54.2m2 2PN full nội thất" }
```

Response (200) — trường `answer` (xuống dòng được hiển thị nguyên văn):

```text
- Ước tính giá bán hợp lý: 4.18 - 5.58 tỷ.
- Giá trung vị thị trường hiện tại: 4.93 tỷ.
- Độ tin cậy: 84%.
- Phân tích:
- Diện tích 54.2m² thuộc nhóm 2PN căn hộ tại Vinhomes Smart City.
- Các căn tương tự trong top mẫu so sánh đang được chào bán từ 4.45 - 5.3 tỷ.
- Dataset hiện chưa có giao dịch chốt verified phù hợp; kết quả đang dựa trên giá rao công khai đã lọc nhiễu.
- Mẫu tính toán gồm 263 listing/giao dịch sau lọc nhiễu.
- Các yếu tố có thể làm thay đổi giá:
- + Full nội thất: đã được đưa vào so khớp khi dữ liệu listing có thông tin nội thất.
- + View hồ/công viên/nội khu và tầng đẹp: thường giúp thanh khoản và mức chào bán tốt hơn.
- + Tòa/phân khu có tiện ích, pháp lý và vận hành tốt: có thể kéo giá lên so với mặt bằng chung.
- Tiện ích xung quanh ảnh hưởng tới giá:
- Giao thông: có Gần Ngã Tư Đường 72 Cũ - Lê Trọng Tấn - Hà Đông... gần đây, là yếu tố thường nâng đỡ giá bán của căn.
- Siêu thị: có WinMart, Siêu Thị Tạp Hóa - Minh Lan Mart... gần đây, là yếu tố thường nâng đỡ giá bán của căn.
- Trường học: có Trường THCS Tây Mỗ, Trường Tiểu Học Dương Nội A gần đây...
- Y tế: có Bệnh viện Đa khoa Vinmec Smart City gần đây...
- Càng nhiều tiện ích thiết yếu (giao thông, siêu thị, y tế) trong bán kính đi bộ thì giá bán càng dễ nằm ở nhóm cao của khoảng ước tính.
- Để định giá chính xác hơn, vui lòng cung cấp:
- Tòa/phân khu
- Tầng
- Hướng ban công/view
```

Các trường khác: `intent="valuation"`, `missing_fields=[]`, `valuation.sample_size=263`, `valuation.confidence="high"`.

Nhận xét: chatbot tách đúng slot (project, area, bedrooms, furniture, purpose=sale), gọi tool tìm tiện ích xung quanh và dùng nó để giải thích giá ngay trong luồng định giá bán (trước đây chỉ chạy cho thuê).

---

## TC5 — Chatbot định giá thuê kèm tiện ích xung quanh

Request:

```http
POST /chat
Content-Type: application/json

{ "message": "Tôi có căn Vinhomes Smart City 54m², 2 phòng ngủ. Cho thuê được bao nhiêu?" }
```

Response (200) — trường `answer`:

```text
- Ước tính giá thuê hợp lý: 5 - 12.3 triệu/tháng.
- Giá trung vị thị trường hiện tại: 8 triệu/tháng.
- Độ tin cậy: 64%.
- Phân tích:
- Diện tích 54m² thuộc nhóm 2PN căn hộ tại Vinhomes Smart City.
- Mẫu cùng dự án hiện chưa đủ mạnh; hệ thống đang dùng thêm nhóm căn hộ tương tự trong rổ Vinhomes Hà Nội làm proxy.
- Các căn tương tự trong top mẫu so sánh đang được chào thuê từ 5 - 13 triệu/tháng.
- Mẫu tính toán gồm 25 listing/giao dịch sau lọc nhiễu.
- Các yếu tố có thể làm thay đổi giá: (full nội thất / view / tòa - phân khu ...)
- Tiện ích xung quanh ảnh hưởng tới giá:
- Giao thông: có Gần Ngã Tư Đường 72 Cũ - Lê Trọng Tấn - Hà Đông... là yếu tố thường nâng đỡ giá thuê của căn.
- Siêu thị: có Minh Lan Mart, WinMart gần đây...
- Trường học: có Trường THCS Tây Mỗ, Trường Liên cấp H.A.S Dương Nội...
- Y tế: có Bệnh viện Đa khoa Quốc tế Vinmec Smart City...
- Càng nhiều tiện ích thiết yếu (giao thông, siêu thị, y tế) trong bán kính đi bộ thì giá thuê càng dễ nằm ở nhóm cao của khoảng ước tính.
- Để định giá chính xác hơn, vui lòng cung cấp: Tòa/phân khu, Tầng, Tình trạng nội thất, Hướng ban công/view
```

Các trường khác: `intent="valuation"`, `valuation.purpose="rent"`, `p10/p50/p90 = 5 / 8 / 12.3 triệu`, `data.amenity_advice.categories` có dữ liệu.

Nhận xét: nhận diện đúng `purpose=rent`, đơn vị tiền là triệu/tháng, confidence thấp hơn (64%) do mẫu thuê mỏng (25 mẫu) nên phải dùng proxy — đúng kỳ vọng minh bạch dữ liệu.

---

## TC6 — Chatbot thiếu thông tin (missing slot handling)

Request:

```http
POST /chat
Content-Type: application/json

{ "message": "Định giá giúp tôi một căn hộ" }
```

Response (200) — trường `answer`:

```text
- Mình cần thêm dự án/khu đô thị, diện tích m2 để định giá sát hơn.
- Dữ liệu gần nhất đang có: Vinhomes Ocean Park (432 mẫu, diện tích hay gặp 43.4-64.9 m2, median 72.0 triệu/m2);
  Vinhomes Smart City (263 mẫu, ..., median 91.0 triệu/m2); Vinhomes Ocean Park 3 (2 mẫu, ..., median 111.5 triệu/m2).
- Với bộ lọc hiện tại, diện tích thường nằm quanh 43-64 m2, median 54.9 m2.
- Một vài mẫu gần nhất: Vinhomes Smart City 30.1 m2 1PN 3.03 tỷ (101.0 triệu/m2); ...
- Bạn xác nhận giúp mình dự án và diện tích cụ thể để mình chốt định giá sát hơn.
```

Các trường khác: `intent="valuation"`, `missing_fields=["project","area_m2"]`, `valuation=null`, `data.retrieval_suggestions` chứa `nearest_projects`, `nearby_listings`, `area_hint`, `snapshot_hints`.

Nhận xét: thay vì báo lỗi, bot phát hiện thiếu `project` + `area_m2`, gọi `missing_info_retrieval` để gợi ý dữ liệu gần nhất và hỏi lại — đúng UX kỳ vọng.

---

## TC7 — Market trends

Request:

```http
GET /market-trends?project=vinhomes-smart-city&purpose=sale&property_type=apartment
```

Response (200, rút gọn):

```json
{
  "project": "Vinhomes Smart City",
  "property_type": "apartment",
  "purpose": "sale",
  "windows": {
    "1m":  { "sample_size": 263, "median": 91000000.0, "p10": 78906250.0, "p90": 103963723.0 },
    "3m":  { "sample_size": 263, "median": 91000000.0, "p10": 78906250.0, "p90": 103963723.0 },
    "6m":  { "sample_size": 263, "median": 91000000.0, "p10": 78906250.0, "p90": 103963723.0 },
    "12m": { "sample_size": 263, "median": 91000000.0, "p10": 78906250.0, "p90": 103963723.0 }
  },
  "reference_price_snapshots": [
    {
      "source": "vinhomesland",
      "label": "Căn hộ 1PN",
      "area_min_m2": 33.0, "area_max_m2": 45.0,
      "price_min_vnd": 1900000000.0, "price_max_vnd": 4500000000.0,
      "basis": "published_price_range"
    }
  ]
}
```

Nhận xét: trả median theo 4 cửa sổ thời gian kèm sample size và snapshot bảng giá để đối chiếu. Seed DB là một lần crawl nên các cửa sổ trùng nhau — đúng với dữ liệu hiện có.

---

## TC8 — Data quality evaluation

Request:

```http
GET /evaluation
```

Response (200, rút gọn):

```json
{
  "raw_listing_rows": 827,
  "deduped_listing_rows": 827,
  "duplicate_listing_rows": 0,
  "duplicate_rate": 0.0,
  "expected_sources": ["batdongsan", "onehousing", "vinhomesland", "vinhomesonline"],
  "observed_sources": ["batdongsan", "onehousing", "vinhomesland", "vinhomesonline"],
  "missing_sources": [],
  "source_counts": [
    { "source": "batdongsan",     "raw_rows": 286, "deduped_rows": 286, "duplicate_rows": 0, "price_snapshot_rows": 0,   "candidate_rows": 0 },
    { "source": "onehousing",     "raw_rows": 541, "deduped_rows": 541, "duplicate_rows": 0, "price_snapshot_rows": 0,   "candidate_rows": 0 },
    { "source": "vinhomesland",   "raw_rows": 75,  "deduped_rows": 0,   "duplicate_rows": 0,  "price_snapshot_rows": 75,  "candidate_rows": 0 },
    { "source": "vinhomesonline", "raw_rows": 192, "deduped_rows": 0,   "duplicate_rows": 0,  "price_snapshot_rows": 0,   "candidate_rows": 192 }
  ]
}
```

Nhận xét: đủ 4 nguồn (`missing_sources` rỗng). Seed DB đã được làm sạch bằng `scripts/purge_duplicates.py --apply` — trước đó có 854 rows với 27 dòng canonical-duplicate (3.16%), nay còn 827 rows và 0 duplicate. VinhomesLand vào dạng `price_snapshot`, VinhomesOnline vào dạng `candidate` chờ xác minh mapping — không bị tính vào valuation.

---

## Kết luận

- 8/8 test case pass với output thực tế khớp kỳ vọng.
- Test suite tự động: `33 passed`.
- Định giá minh bạch (P10/P50/P90 + comparables + confidence theo sample size).
- Tool tìm tiện ích xung quanh hiện chạy cho cả định giá **bán và thuê** để giải thích giá (TC4 và TC5).
- Pipeline dữ liệu có đo coverage 4 nguồn và dedupe chéo nguồn (TC8).

Hạn chế đã ghi nhận:

- Chưa có giao dịch chốt verified nên accuracy mới đối chiếu được với giá rao, chưa đối chiếu closing price.
- `/chat` latency ~1.5s do gọi tiện ích trực tiếp; nên cache theo vị trí hoặc cho phép tắt khi cần phản hồi nhanh.
