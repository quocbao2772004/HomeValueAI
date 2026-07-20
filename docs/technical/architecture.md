# Architecture Notes

## Flow

`config/projects.yaml -> crawler -> storage(raw_fetch)/raw_html -> source parser -> storage(listing_observation, price_snapshot, property_candidate) -> valuation API`

Storage production là MongoDB khi có `MONGODB_URI`; local/dev fallback SQLite qua cùng storage abstraction. Các collection/table chính giữ cùng tên: `raw_fetch`, `listing_observation`, `price_snapshot`, `property_candidate`, `verified_transaction`.

Verified transactions đi vào `verified_transaction` và được weighted cao hơn trong valuation.

## No Hard-Coded Market Data

Code không chứa listing giả, khung giá giả, hay danh sách URL cố định trong logic. Các phần thay đổi theo thị trường nằm ở `config/projects.yaml`:

- project slug/name/aliases
- crawl URLs
- source adapter selection (`batdongsan`, `onehousing`)
- fetch mode/rate limit
- quality thresholds
- valuation sample-size thresholds

## Caveats

- Direct fetch tới Batdongsan hiện bị Cloudflare 403 trong môi trường này.
- Reader fallback có thể trả snapshot bị block hoặc snapshot lẫn listing ngoài scope; parser chỉ giữ listing tự nhận diện được project qua title hoặc detail URL.
- OneHousing parser đọc structured data trong `__NEXT_DATA__` public HTML và không gọi các endpoint disallow trong robots.
- Khi chưa có giao dịch chốt, API luôn ghi caveat: ước tính dựa trên giá rao công khai đã lọc nhiễu.
