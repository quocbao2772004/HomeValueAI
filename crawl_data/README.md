# crawl_data — crawlers dữ liệu Vinhomes

Nguồn dữ liệu thứ 5: giá chính thức từ sàn giao dịch BĐS Vinhomes.

## Cách dùng

```bash
python3 crawl_data/crawl_market_vinhomes.py
python3 crawl_data/crawl_market_vinhomes.py --max-details 50 --output crawl_data/market_vinhomes.csv
```

## Cơ chế

1. Fetch homepage `market.vinhomes.vn/` (render HTML đầy đủ qua SSR)
2. Discover tất cả URL chi tiết listing (sơ cấp `/so-cap/...` và thứ cấp `/thu-cap/...`)
3. Vào từng trang chi tiết → parse giá, diện tích, phòng ngủ, phân khu, hướng, loại hình

Lưu ý: các trang danh mục (`/so-cap`, `/thu-cap`) dùng React Server Components streaming nên chỉ fetch được listing từ homepage. Nếu cần nhiều hơn, cần headless browser (Playwright/Puppeteer).

## Output

CSV với cột: source, source_url, title, project_slug, project_name, property_type, purpose, price_total_vnd, price_per_m2_vnd, area_m2, bedrooms, total_floors, subdivision, view, observed_at.

## Giới hạn

- Homepage hiện chỉ hiển thị ~8-10 listings nổi bật; để có đầy đủ danh mục cần bổ sung headless browser cho trang phân trang.
- Crawler không bypass auth/CAPTCHA, chỉ đọc dữ liệu public SSR.

## Ba nguồn bổ sung tại Hà Nội

`crawl_vinhomes_hanoi_sources.py` thu thập dữ liệu công khai từ:

- Homedy: card tin đăng Vinhomes Hà Nội, bao gồm giá, diện tích, loại hình và URL gốc khi trang hiển thị chúng.
- `vinhomesreal.vn`: trang dự án Hà Nội được discover từ sitemap dự án.
- `bdsvinhomes.com.vn/du-an`: trang dự án Hà Nội được discover từ danh mục dự án.

```bash
python3 crawl_data/crawl_vinhomes_hanoi_sources.py
python3 crawl_data/crawl_vinhomes_hanoi_sources.py --source homedy --max-pages-per-source 4
```

Output mặc định:

- `crawl_data/vinhomes_hanoi_sources.csv`: mỗi dòng giữ nguồn và URL gốc; `listing` là tin đăng, `project_reference` là dữ liệu dự án/khoảng giá tham chiếu.
- `crawl_data/vinhomes_hanoi_sources_report.json`: số trang fetch và số record theo nguồn.

Crawler kiểm tra `robots.txt`, không dùng headless browser hay bypass CAPTCHA/login, và mặc định nghỉ 1 giây giữa các request. Dữ liệu chỉ được export vào `crawl_data/`; không tự động import vào database định giá.
