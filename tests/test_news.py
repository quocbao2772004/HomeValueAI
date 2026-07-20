from __future__ import annotations

from datetime import UTC, datetime

import src.news as news_module
from src.config import load_config


class FakeResponse:
    ok = True

    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


def _rss(title: str, source: str = "Test News") -> str:
    pub_date = datetime(2026, 7, 10, 8, 0, tzinfo=UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
    return f"""
    <rss><channel>
      <item>
        <title>{title} - {source}</title>
        <link>https://example.com/{abs(hash(title))}</link>
        <source>{source}</source>
        <pubDate>{pub_date}</pubDate>
        <description>Tin kiểm thử</description>
      </item>
    </channel></rss>
    """


def test_project_news_marks_verified_nearby_event(monkeypatch):
    config = load_config()
    news_module.clear_news_cache()
    monkeypatch.setattr(news_module.requests, "get", lambda *args, **kwargs: FakeResponse(_rss("Khởi công đường Lê Quang Đạo kéo dài")))

    def fake_resolve(query: str):
        if "Smart City" in query:
            return {"name": "Vinhomes Smart City", "address": "Nam Từ Liêm", "lat": 21.007, "lng": 105.74}
        return {"name": "Đường Lê Quang Đạo", "address": "Nam Từ Liêm", "lat": 21.006, "lng": 105.742}

    monkeypatch.setattr(news_module, "resolve_location_coordinates", fake_resolve)

    payload = news_module.project_news(
        config,
        "Vinhomes Smart City",
        limit=1,
        location_label="S2.05, Vinhomes Smart City",
    )

    item = payload["items"][0]
    assert payload["nearby_verified_count"] == 1
    assert item["event_status"] == "under_construction"
    assert item["proximity_status"] == "verified_nearby"
    assert item["distance_m"] > 0
    assert item["main_insight"] if "main_insight" in item else True


def test_project_news_keeps_mismatched_geocode_unverified(monkeypatch):
    config = load_config()
    news_module.clear_news_cache()
    monkeypatch.setattr(news_module.requests, "get", lambda *args, **kwargs: FakeResponse(_rss("Đề xuất mở rộng công viên phía Tây")))

    def fake_resolve(query: str):
        if "Smart City" in query:
            return {"name": "Vinhomes Smart City", "address": "Nam Từ Liêm", "lat": 21.007, "lng": 105.74}
        return {"name": "Hồ Gươm", "address": "Hoàn Kiếm", "lat": 21.028, "lng": 105.852}

    monkeypatch.setattr(news_module, "resolve_location_coordinates", fake_resolve)

    payload = news_module.project_news(
        config,
        "Vinhomes Smart City",
        limit=1,
        location_label="S2.05, Vinhomes Smart City",
    )

    item = payload["items"][0]
    assert payload["nearby_verified_count"] == 0
    assert item["event_status"] == "proposed"
    assert item["proximity_status"] != "verified_nearby"
    assert "distance_m" not in item
