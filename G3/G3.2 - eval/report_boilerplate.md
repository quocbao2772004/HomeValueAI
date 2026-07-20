# Evaluation Report

> Báo cáo đánh giá chất lượng sản phẩm theo tiêu chí BTC.

---

## 1. Metrics

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Response accuracy | >80% | — | ⏳ |
| Response latency | <3s | — | ⏳ |
| User satisfaction | >4/5 | — | ⏳ |
| Test suite | All tests pass | 25 passed | ✅ |
| Crawl source coverage | 4 public sources | 4/4 observed | ✅ |
| Cross-source dedupe | Duplicate rows removed before valuation | 27 listing rows merged | ✅ |
| Unique valuation samples | Seed DB ready for demo | 827 unique listing rows | ✅ |

## 1.1 Data Quality Evaluation

Endpoint: `GET /evaluation`

Latest seed DB snapshot:

| Source | Listing rows | Unique rows used for valuation | Price snapshots | Candidates |
|--------|--------------|----------------------------------|-----------------|------------|
| Batdongsan | 295 | 286 | 0 | 0 |
| OneHousing | 559 | 541 | 0 | 0 |
| VinhomesLand | 0 | 0 | 75 | 0 |
| VinhomesOnline | 0 | 0 | 0 | 192 |

Notes:

- Valuation uses canonical dedupe keys before computing P10/P50/P90, so duplicate listings from different sources are not double-counted.
- VinhomesLand is treated as `price_snapshot` because it mostly publishes aggregate price tables/ranges.
- VinhomesOnline currently contributes `property_candidate` rows when project mapping is uncertain; these are kept out of valuation until mapping is verified.

## 2. Test Results

### Unit Tests
```
python3 -m pytest -q
# 25 passed
```

### Integration Tests
```
python3 - <<'PY'
from fastapi.testclient import TestClient
from src.main import app
client = TestClient(app)
assert client.get("/health").status_code == 200
assert client.get("/evaluation").status_code == 200
PY
```

## 3. User Feedback

| User | Feedback | Rating |
|------|----------|--------|
| [User 1] | [feedback] | [1-5] |
| [User 2] | [feedback] | [1-5] |

## 4. Demo Results

- Ngày demo: [YYYY-MM-DD]
- Người tham gia: [số người]
- Feedback chung: [tóm tắt]
- Issues phát hiện: [danh sách]

## 5. Action Items

- [ ] Bổ sung giao dịch thật đã xác minh để đo accuracy so với closing price.
- [ ] Geocode chính xác tòa/căn khi có dữ liệu tọa độ thay vì dùng Google Maps search query.
