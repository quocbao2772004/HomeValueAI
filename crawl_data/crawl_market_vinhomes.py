"""
Crawler cho market.vinhomes.vn
Parse dữ liệu từ trang chủ (có SSR đầy đủ) và từng trang chi tiết.

Cách dùng:
    python3 crawl_data/crawl_market_vinhomes.py
    python3 crawl_data/crawl_market_vinhomes.py --max-details 50 --output crawl_data/market_vinhomes.csv

Output: CSV với các cột chuẩn cho hệ thống valuation.
"""

from __future__ import annotations

import argparse
import csv
import re
import time
from datetime import UTC, datetime
from typing import Any

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://market.vinhomes.vn"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125 Safari/537.36"
DELAY_SECONDS = 0.8

PROPERTY_TYPE_MAP = {
    "căn hộ": "apartment",
    "chung cư": "apartment",
    "studio": "apartment",
    "pn": "apartment",
    "phòng ngủ": "apartment",
    "biệt thự": "villa",
    "song lập": "villa",
    "đơn lập": "villa",
    "liền kề": "townhouse",
    "nhà phố": "townhouse",
    "shophouse": "shophouse",
}

CSV_COLUMNS = [
    "source", "source_url", "title", "project_slug", "project_name",
    "property_type", "purpose", "price_total_vnd", "price_per_m2_vnd",
    "area_m2", "bedrooms", "total_floors", "subdivision", "view", "observed_at",
]


def fetch(url: str) -> str | None:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        if resp.status_code == 200:
            return resp.text
        print(f"  [WARN] {url} → HTTP {resp.status_code}")
    except Exception as e:
        print(f"  [ERROR] {url} → {e}")
    return None


def parse_price_vnd(text: str) -> float | None:
    text = text.strip().replace(",", ".")
    m = re.match(r"([\d.]+)\s*(tỷ|triệu|tr)", text, re.IGNORECASE)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).lower()
    if unit in ("tỷ", "ty"):
        return val * 1_000_000_000
    return val * 1_000_000


def infer_project(text: str) -> tuple[str, str]:
    lower = text.lower()
    if "grand park" in lower:
        return "vinhomes-grand-park", "Vinhomes Grand Park"
    if "ocean park 3" in lower or "ocp3" in lower:
        return "vinhomes-ocean-park-3", "Vinhomes Ocean Park 3"
    if "ocean park 2" in lower or "ocp2" in lower:
        return "vinhomes-ocean-park-2", "Vinhomes Ocean Park 2"
    if "ocean park" in lower:
        return "vinhomes-ocean-park", "Vinhomes Ocean Park"
    if "smart city" in lower:
        return "vinhomes-smart-city", "Vinhomes Smart City"
    return "", ""


def infer_property_type(text: str) -> str:
    lower = text.lower()
    for kw, pt in PROPERTY_TYPE_MAP.items():
        if kw in lower:
            return pt
    return "other"


def infer_purpose(url: str) -> str:
    if "/thu-cap/" in url:
        return "sale"  # chuyển nhượng = resale
    return "sale"  # sơ cấp = primary sale


def discover_listing_urls(html: str) -> list[str]:
    """Lấy tất cả URL chi tiết listing từ HTML homepage."""
    urls = re.findall(
        r'href="(https://market\.vinhomes\.vn/(?:so-cap|thu-cap)/[^"]+)"', html
    )
    return sorted(set(urls))


def parse_detail_page(url: str, html: str) -> dict[str, Any] | None:
    """Parse thông tin từ trang chi tiết listing."""
    soup = BeautifulSoup(html, "html.parser")
    now = datetime.now(UTC).isoformat()

    # Title: thường là h1 hoặc chuỗi đầu tiên có mã căn
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        # Thử tìm mã căn từ URL
        slug = url.rsplit("/", 1)[-1]
        title = slug.replace("-", " ").title()

    # Project
    project_slug, project_name = infer_project(url + " " + title + " " + html[:5000])

    # Giá: tìm số đầu tiên kèm "tỷ" hoặc "triệu"
    price_total = None
    price_per_m2 = None

    # Tìm giá tổng (ưu tiên giá ưu đãi nếu có)
    price_matches = re.findall(r'([\d,.]+)\s*tỷ', html)
    if price_matches:
        # Lấy giá nhỏ nhất (thường là giá ưu đãi)
        candidates = []
        for p in price_matches:
            try:
                val = float(p.replace(",", ".")) * 1_000_000_000
                if 500_000_000 < val < 200_000_000_000:  # sanity check
                    candidates.append(val)
            except ValueError:
                pass
        if candidates:
            price_total = min(candidates)

    # Giá/m2
    ppm_matches = re.findall(r'([\d,.]+)\s*triệu/m[²2]', html)
    if ppm_matches:
        try:
            price_per_m2 = float(ppm_matches[0].replace(",", ".")) * 1_000_000
        except ValueError:
            pass

    # Diện tích
    area = None
    # Tìm "Diện tích đất" hoặc "Diện tích" trong structured info
    area_section = re.search(
        r'(?:Diện tích(?:\s*đất)?|DT tim tường|Diện tích tim tường)[^<]*<[^>]*>[\s]*'
        r'([\d,.]+)\s*m[²2]',
        html, re.IGNORECASE
    )
    if area_section:
        try:
            area = float(area_section.group(1).replace(",", "."))
        except ValueError:
            pass
    if not area:
        # Fallback: tìm diện tích hợp lý từ text
        area_all = re.findall(r'([\d,.]+)\s*m[²2]', html)
        for a in area_all:
            try:
                val = float(a.replace(",", "."))
                if 20 < val < 2000:
                    area = val
                    break
            except ValueError:
                pass

    # Số tầng
    floors = None
    floor_match = re.search(r'Tổng số tầng[^<]*<[^>]*>\s*(\d+)', html, re.IGNORECASE)
    if floor_match:
        floors = int(floor_match.group(1))
    else:
        floor_match2 = re.search(r'(\d+)\s*tầng', html)
        if floor_match2:
            floors = int(floor_match2.group(1))

    # Phòng ngủ
    bedrooms = None
    bed_match = re.search(r'(\d+)\s*(?:phòng ngủ|PN|pn|bedroom)', html, re.IGNORECASE)
    if bed_match:
        bedrooms = int(bed_match.group(1))
    # Từ URL: "2-pn", "3-pn"
    bed_url = re.search(r'(\d+)-pn', url, re.IGNORECASE)
    if bed_url and not bedrooms:
        bedrooms = int(bed_url.group(1))

    # Hướng
    view = ""
    view_match = re.search(
        r'(?:Hướng ban công|Hướng cửa|Hướng)[^<]*<[^>]*>\s*'
        r'([^<]{2,20})',
        html, re.IGNORECASE
    )
    if view_match:
        view = view_match.group(1).strip()

    # Phân khu
    subdivision = ""
    sub_match = re.search(
        r'(?:Phân khu|Khu đô thị|Khu)[^<]*?</span>[^<]*<[^>]*>\s*([A-ZĐa-zÀ-ỹ][^<]{1,40})',
        html, re.IGNORECASE
    )
    if sub_match:
        text = sub_match.group(1).strip()
        if not re.search(r'[{}:;]', text):
            subdivision = text
    # Hoặc từ URL
    if not subdivision:
        sub_from_url = re.search(r'khu-([a-z-]+)-vinhomes', url)
        if sub_from_url:
            subdivision = sub_from_url.group(1).replace("-", " ").title()
    # Từ title nếu có "khu XXX"
    if not subdivision:
        sub_title = re.search(r'khu\s+([A-ZĐa-zÀ-ỹ][\w\s]{2,25})', title, re.IGNORECASE)
        if sub_title:
            subdivision = sub_title.group(1).strip()

    # Property type
    prop_type = infer_property_type(title + " " + url)

    # Purpose
    purpose = infer_purpose(url)

    if not price_total and not area:
        return None

    return {
        "source": "market_vinhomes",
        "source_url": url,
        "title": title,
        "project_slug": project_slug,
        "project_name": project_name,
        "property_type": prop_type,
        "purpose": purpose,
        "price_total_vnd": price_total,
        "price_per_m2_vnd": price_per_m2,
        "area_m2": area,
        "bedrooms": bedrooms,
        "total_floors": floors,
        "subdivision": subdivision,
        "view": view,
        "observed_at": now,
    }


def main():
    parser = argparse.ArgumentParser(description="Crawl market.vinhomes.vn")
    parser.add_argument("--max-details", type=int, default=100, help="Max detail pages to fetch")
    parser.add_argument("--output", default="crawl_data/market_vinhomes.csv", help="Output CSV")
    args = parser.parse_args()

    print("=" * 60)
    print("Crawler: market.vinhomes.vn")
    print("=" * 60)

    # Bước 1: lấy URLs từ homepage
    print("\n[1] Fetching homepage để discover listing URLs...")
    homepage = fetch(f"{BASE_URL}/")
    if not homepage:
        print("Không fetch được homepage!")
        return

    urls = discover_listing_urls(homepage)
    print(f"  Found {len(urls)} listing URLs")

    # Giới hạn
    urls = urls[: args.max_details]

    # Bước 2: fetch từng detail page
    print(f"\n[2] Fetching {len(urls)} detail pages...")
    listings: list[dict[str, Any]] = []
    for i, url in enumerate(urls, 1):
        print(f"  [{i}/{len(urls)}] {url}")
        html = fetch(url)
        if not html:
            continue
        item = parse_detail_page(url, html)
        if item:
            listings.append(item)
            print(f"    ✓ {item['title'][:50]} | {item['price_total_vnd']} | {item['area_m2']}m²")
        else:
            print(f"    ✗ Không parse được")
        time.sleep(DELAY_SECONDS)

    # Bước 3: ghi CSV
    print(f"\n[3] Ghi {len(listings)} listings vào {args.output}...")
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(listings)

    print(f"\nXong! {len(listings)} listings saved to {args.output}")


if __name__ == "__main__":
    main()
