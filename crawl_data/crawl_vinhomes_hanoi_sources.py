"""Collect public Vinhomes Hà Nội market references from approved source sites.

Sources:
* Homedy: public listing cards for Vinhomes Hà Nội projects.
* vinhomesreal.vn: public project pages discovered through its project sitemap.
* bdsvinhomes.com.vn: public project pages linked from /du-an.

The crawler deliberately stays small and polite: it checks robots.txt, does not
use a browser/CAPTCHA workaround, limits pages per source, and sleeps between
requests. It writes a provenance-preserving CSV; it does not import anything
into the application database automatically.

Examples:
    python3 crawl_data/crawl_vinhomes_hanoi_sources.py
    python3 crawl_data/crawl_vinhomes_hanoi_sources.py --source homedy --max-pages-per-source 4
    python3 crawl_data/crawl_vinhomes_hanoi_sources.py --output crawl_data/vinhomes_hanoi_sources.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.robotparser
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "vinhomes_hanoi_sources.csv"
DEFAULT_REPORT = ROOT / "vinhomes_hanoi_sources_report.json"
USER_AGENT = "HomeValueAIDataCollector/1.0 (+https://solanai.us; contact: data@solanai.us)"
TIMEOUT_SECONDS = 20

CSV_COLUMNS = [
    "record_type",
    "source",
    "source_url",
    "title",
    "project_slug",
    "project_name",
    "purpose",
    "property_type",
    "price_min_vnd",
    "price_max_vnd",
    "price_per_m2_vnd",
    "area_min_m2",
    "area_max_m2",
    "bedrooms",
    "address",
    "raw_price_text",
    "observed_at",
]


@dataclass(frozen=True)
class Source:
    name: str
    root_url: str
    discovery_url: str


@dataclass
class CrawlRecord:
    record_type: str
    source: str
    source_url: str
    title: str
    project_slug: str
    project_name: str
    purpose: str
    property_type: str
    price_min_vnd: int | None
    price_max_vnd: int | None
    price_per_m2_vnd: int | None
    area_min_m2: float | None
    area_max_m2: float | None
    bedrooms: int | None
    address: str
    raw_price_text: str
    observed_at: str


SOURCES = {
    "homedy": Source(
        name="homedy",
        root_url="https://homedy.com",
        discovery_url="https://homedy.com/vinhomes-smart-city-pj56634141",
    ),
    "vinhomesreal": Source(
        name="vinhomesreal",
        root_url="https://vinhomesreal.vn",
        discovery_url="https://vinhomesreal.vn/sitemap/du-an/sitemap.xml",
    ),
    "bdsvinhomes": Source(
        name="bdsvinhomes",
        root_url="https://bdsvinhomes.com.vn",
        discovery_url="https://bdsvinhomes.com.vn/du-an",
    ),
}

# Only projects located in Hà Nội. Ocean Park 2/3 are deliberately absent because
# they are in Hưng Yên, even though they share the wider Vinhomes ecosystem.
HANOI_PROJECTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("vinhomes-global-gate", "Vinhomes Global Gate", ("global gate", "co loa")),
    ("vinhomes-smart-city", "Vinhomes Smart City", ("smart city", "tay mo", "tây mỗ", "dai mo", "đại mỗ")),
    ("vinhomes-ocean-park", "Vinhomes Ocean Park", ("ocean park", "gia lam", "gia lâm")),
    ("vinhomes-times-city", "Vinhomes Times City", ("times city", "times hub")),
    ("vinhomes-royal-city", "Vinhomes Royal City", ("royal city",)),
    ("vinhomes-riverside", "Vinhomes Riverside", ("riverside", "the harmony", "symphony")),
    ("vinhomes-metropolis", "Vinhomes Metropolis", ("metropolis", "lieu giai", "liễu giai")),
    ("vinhomes-skylake", "Vinhomes Skylake", ("skylake", "pham hung", "phạm hùng")),
    ("vinhomes-green-bay", "Vinhomes Green Bay", ("green bay", "me tri", "mễ trì")),
    ("vinhomes-gardenia", "Vinhomes Gardenia", ("gardenia", "ham nghi", "hàm nghi")),
    ("vinhomes-green-villas", "Vinhomes Green Villas", ("green villas",)),
)

PROPERTY_KEYWORDS = (
    ("shophouse", "shophouse"),
    ("nhà phố", "townhouse"),
    ("liền kề", "townhouse"),
    ("biệt thự", "villa"),
    ("căn hộ", "apartment"),
    ("chung cư", "apartment"),
    ("studio", "apartment"),
)


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def normalized_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/") or "/", "", "", ""))


def infer_project(text: str) -> tuple[str, str] | None:
    lowered = compact(text.replace("-", " ").replace("_", " ")).casefold()
    for slug, name, aliases in HANOI_PROJECTS:
        if any(alias in lowered for alias in aliases):
            return slug, name
    return None


def infer_property_type(text: str) -> str:
    lowered = text.casefold()
    for keyword, property_type in PROPERTY_KEYWORDS:
        if keyword in lowered:
            return property_type
    return "other"


def infer_purpose(text: str) -> str:
    lowered = text.casefold()
    return "rent" if any(term in lowered for term in ("cho thuê", "thuê căn", "thuê nhà")) else "sale"


def parse_vnd_range(text: str) -> tuple[int | None, int | None, int | None]:
    """Return (minimum, maximum, price_per_m2) from a Vietnamese price string."""
    cleaned = compact(text).casefold().replace(",", ".")
    if not cleaned or any(token in cleaned for token in ("thỏa thuận", "liên hệ", "đang cập nhật")):
        return None, None, None

    match = re.search(
        r"(?P<low>\d+(?:\.\d+)?)\s*(?:[-–—]|đến|to)?\s*"
        r"(?P<high>\d+(?:\.\d+)?)?\s*(?P<unit>tỷ|ty|triệu|tr)"
        r"(?P<per_m2>\s*/\s*m(?:2|²))?",
        cleaned,
    )
    if not match:
        return None, None, None

    multiplier = 1_000_000_000 if match.group("unit") in {"tỷ", "ty"} else 1_000_000
    low = int(float(match.group("low")) * multiplier)
    high = int(float(match.group("high")) * multiplier) if match.group("high") else low
    if match.group("per_m2"):
        return None, None, low
    return low, high, None


def parse_area_range(text: str) -> tuple[float | None, float | None]:
    cleaned = compact(text).casefold().replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:[-–—]|đến)?\s*(\d+(?:\.\d+)?)?\s*m(?:2|²)", cleaned)
    if not match:
        return None, None
    low = float(match.group(1))
    high = float(match.group(2)) if match.group(2) else low
    if not 15 <= low <= 5_000 or not 15 <= high <= 5_000:
        return None, None
    return low, high


def parse_bedrooms(text: str) -> int | None:
    match = re.search(r"\b([1-5])\s*(?:pn|phòng ngủ)\b", text.casefold())
    return int(match.group(1)) if match else None


def title_from_page(soup: BeautifulSoup) -> str:
    og = soup.select_one('meta[property="og:title"]')
    if og and og.get("content"):
        return compact(str(og["content"]))
    h1 = soup.find("h1")
    if h1:
        return compact(h1.get_text(" ", strip=True))
    return compact(soup.title.get_text(" ", strip=True)) if soup.title else ""


def page_text(soup: BeautifulSoup) -> str:
    return compact(soup.get_text(" ", strip=True))


def address_from_text(text: str) -> str:
    sentences = [compact(item) for item in re.split(r"(?<=[.!?])\s+", text)]
    for sentence in sentences:
        lowered = sentence.casefold()
        if "hà nội" in lowered or any(
            term in lowered
            for term in (
                "nam từ liêm",
                "gia lâm",
                "hai bà trưng",
                "thanh xuân",
                "ba đình",
                "cầu giấy",
                "đông anh",
                "long biên",
            )
        ):
            return sentence[:300]
    return "Hà Nội"


def extract_project_price(text: str) -> tuple[int | None, int | None, int | None, str]:
    """Find the first clearly labelled sale-price phrase on a project page."""
    for phrase in re.split(r"(?<=[.!?:;])\s+", compact(text)):
        lowered = phrase.casefold()
        if "giá" not in lowered or not any(unit in lowered for unit in ("tỷ", "triệu", "tr")):
            continue
        low, high, price_per_m2 = parse_vnd_range(phrase)
        if low or price_per_m2:
            return low, high, price_per_m2, phrase[:300]
    return None, None, None, ""


class PublicFetcher:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = max(delay_seconds, 0.0)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8"})
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last_request_at = 0.0

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._robots.get(root)
        if parser is None:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(f"{root}/robots.txt")
            try:
                response = self.session.get(parser.url, timeout=TIMEOUT_SECONDS)
                if response.ok:
                    parser.parse(response.text.splitlines())
                else:
                    parser.allow_all = True
            except requests.RequestException:
                # Do not guess that a protected page is allowed when robots cannot be read.
                parser.disallow_all = True
            self._robots[root] = parser
        return parser.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> str | None:
        if not self.allowed(url):
            print(f"  [SKIP robots] {url}")
            return None
        wait_for = self.delay_seconds - (time.monotonic() - self._last_request_at)
        if wait_for > 0:
            time.sleep(wait_for)
        try:
            response = self.session.get(url, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as error:
            print(f"  [WARN request] {url}: {error}")
            return None
        finally:
            self._last_request_at = time.monotonic()
        if response.status_code != 200:
            print(f"  [WARN HTTP {response.status_code}] {url}")
            return None
        return response.text


def homedy_records(source: Source, html: str, observed_at: str) -> list[CrawlRecord]:
    soup = BeautifulSoup(html, "html.parser")
    records: list[CrawlRecord] = []
    seen_urls: set[str] = set()
    for card in soup.select(".p-item"):
        price_node = card.select_one(".info-price")
        link = card.select_one("a.image-thumb[href]")
        if not price_node or not link:
            continue
        detail_url = normalized_url(urljoin(source.root_url, str(link["href"])))
        if detail_url in seen_urls:
            continue
        card_text = compact(card.get_text(" ", strip=True))
        project = infer_project(card_text)
        if not project:
            continue
        seen_urls.add(detail_url)
        title_node = card.select_one(".hoz-box-title, .info-title, h3, h2")
        title = (
            compact(title_node.get_text(" ", strip=True))
            if title_node
            else compact(str(link.get("title") or card_text))
        )
        price_text = compact(price_node.get_text(" ", strip=True))
        price_min, price_max, price_per_m2 = parse_vnd_range(price_text)
        area_node = card.select_one(".info-acreage")
        area_min, area_max = parse_area_range(area_node.get_text(" ", strip=True) if area_node else card_text)
        address_node = card.select_one(".hoz-box-address, .p-info-address")
        address = compact(address_node.get_text(" ", strip=True)) if address_node else address_from_text(card_text)
        records.append(
            CrawlRecord(
                record_type="listing",
                source=source.name,
                source_url=detail_url,
                title=title[:500],
                project_slug=project[0],
                project_name=project[1],
                purpose=infer_purpose(card_text),
                property_type=infer_property_type(card_text),
                price_min_vnd=price_min,
                price_max_vnd=price_max,
                price_per_m2_vnd=price_per_m2,
                area_min_m2=area_min,
                area_max_m2=area_max,
                bedrooms=parse_bedrooms(card_text),
                address=address[:300],
                raw_price_text=price_text,
                observed_at=observed_at,
            )
        )
    return records


def project_record(source: Source, url: str, html: str, observed_at: str) -> CrawlRecord | None:
    soup = BeautifulSoup(html, "html.parser")
    title = title_from_page(soup)
    text = page_text(soup)
    project = infer_project(f"{url} {title}") or infer_project(text[:10_000])
    if not project:
        return None
    price_min, price_max, price_per_m2, raw_price = extract_project_price(text)
    area_min, area_max = parse_area_range(text)
    return CrawlRecord(
        record_type="project_reference",
        source=source.name,
        source_url=normalized_url(url),
        title=title[:500],
        project_slug=project[0],
        project_name=project[1],
        purpose="sale",
        property_type=infer_property_type(f"{title} {text[:2_000]}"),
        price_min_vnd=price_min,
        price_max_vnd=price_max,
        price_per_m2_vnd=price_per_m2,
        area_min_m2=area_min,
        area_max_m2=area_max,
        bedrooms=None,
        address=address_from_text(text),
        raw_price_text=raw_price,
        observed_at=observed_at,
    )


def hanoi_project_urls(source: Source, fetcher: PublicFetcher) -> list[str]:
    html = fetcher.get(source.discovery_url)
    if not html:
        return []
    soup = BeautifulSoup(html, "xml" if source.name == "vinhomesreal" else "html.parser")
    candidates: list[str] = []
    if source.name == "vinhomesreal":
        links = [node.get_text(strip=True) for node in soup.find_all("loc")]
    elif source.name == "bdsvinhomes":
        links = [urljoin(source.root_url, str(anchor["href"])) for anchor in soup.select("a[href]")]
    else:
        return [source.discovery_url]

    for url in links:
        parsed = urlparse(url)
        if parsed.netloc.lower() != urlparse(source.root_url).netloc.lower():
            continue
        path = parsed.path.casefold()
        if "ocean-park-2" in path or "ocean-park-3" in path:
            continue
        if infer_project(url):
            candidates.append(normalized_url(url))
    return list(dict.fromkeys(candidates))


def crawl_source(source: Source, fetcher: PublicFetcher, max_pages: int) -> tuple[list[CrawlRecord], dict[str, int]]:
    observed_at = datetime.now(UTC).isoformat()
    records: list[CrawlRecord] = []
    stats = {"requested_pages": 0, "fetched_pages": 0, "records": 0}
    if source.name == "homedy":
        html = fetcher.get(source.discovery_url)
        stats["requested_pages"] = 1
        if html:
            stats["fetched_pages"] = 1
            records.extend(homedy_records(source, html, observed_at))
            reference = project_record(source, source.discovery_url, html, observed_at)
            if reference:
                records.append(reference)
    else:
        urls = hanoi_project_urls(source, fetcher)[:max_pages]
        stats["requested_pages"] = len(urls)
        for url in urls:
            html = fetcher.get(url)
            if not html:
                continue
            stats["fetched_pages"] += 1
            record = project_record(source, url, html, observed_at)
            if record:
                records.append(record)
    stats["records"] = len(records)
    return records, stats


def deduplicate(records: Iterable[CrawlRecord]) -> list[CrawlRecord]:
    unique: dict[tuple[str, str, str], CrawlRecord] = {}
    for record in records:
        key = (record.source, record.source_url, record.record_type)
        unique[key] = record
    return sorted(unique.values(), key=lambda item: (item.source, item.project_name, item.title))


def write_csv(records: list[CrawlRecord], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(asdict(record) for record in records)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect public Vinhomes Hà Nội data from Homedy, vinhomesreal.vn and bdsvinhomes.com.vn."
    )
    parser.add_argument("--source", choices=[*SOURCES, "all"], default="all", help="Run one source or all three.")
    parser.add_argument(
        "--max-pages-per-source",
        type=int,
        default=20,
        help="Maximum project pages fetched for each project-reference source.",
    )
    parser.add_argument("--delay-seconds", type=float, default=1.0, help="Minimum delay between HTTP requests.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    selected = list(SOURCES.values()) if args.source == "all" else [SOURCES[args.source]]
    fetcher = PublicFetcher(args.delay_seconds)
    all_records: list[CrawlRecord] = []
    report = {"started_at": datetime.now(UTC).isoformat(), "sources": {}}
    for source in selected:
        print(f"\n[{source.name}] collecting public Vinhomes Hà Nội pages")
        records, stats = crawl_source(source, fetcher, max(args.max_pages_per_source, 1))
        all_records.extend(records)
        report["sources"][source.name] = stats
        print(f"  fetched={stats['fetched_pages']} records={stats['records']}")

    records = deduplicate(all_records)
    write_csv(records, args.output)
    report.update(
        {"finished_at": datetime.now(UTC).isoformat(), "records_written": len(records), "output": str(args.output)}
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {len(records)} rows to {args.output}")


if __name__ == "__main__":
    main()
