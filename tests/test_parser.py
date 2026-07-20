from src.config import load_config
from src.parser import parse_listing_markdown, parse_price_snapshots, parse_property_candidates


def test_parse_markdown_listing_block():
    cfg = load_config("config/projects.yaml")
    text = """
    [![Image 1] ### Bán nhanh: Căn 2PN1VS tại S303 giá 4,45 tỷ full nội thất đẹp (dự án Smart City)
    4,45 tỷ·54,2 m²·82,10 tr/m²·2·1 ·P. Tây Mỗ Đăng 4 ngày trước]
    (https://batdongsan.com.vn/ban-can-ho-chung-cu-phuong-tay-mo-the-sapphire-vinhomes-smart-city/ban-nhanh-2pn1vs-tai-s303-gia-4-45-ty-full-noi-that-pr45662905
    "Bán nhanh: Căn 2PN1VS tại S303 giá 4,45 tỷ full nội thất đẹp (dự án Smart City)")
    """
    rows = parse_listing_markdown(
        text,
        cfg,
        {"project_slug": "vinhomes-smart-city", "purpose": "sale", "property_type": "apartment"},
    )
    assert len(rows) == 1
    assert rows[0]["price_total_vnd"] == 4_450_000_000
    assert rows[0]["area_m2"] == 54.2
    assert rows[0]["bedrooms"] == 2


def test_parse_onehousing_next_data():
    cfg = load_config("config/projects.yaml")
    html = """
    <html><body>
    <script id="__NEXT_DATA__" type="application/json">
    {
      "props": {
        "pageProps": {
          "inventory": {
            "data": [{
              "id": "abc",
              "project_name": "Vinhomes Ocean Park",
              "sector_name": "The Pavilion",
              "block_name": "P3",
              "inventory_code": "P6JKPC",
              "property_type": ["Chung cư"],
              "property_group": "HIGH_RISE",
              "property_code": "P3.21.05A",
              "number_of_bedrooms": 1,
              "number_of_bedrooms_displays": "1PN",
              "min_selling_price": 3790000000,
              "min_unit_price": 81000000,
              "min_area": 47,
              "views": ["Công viên"],
              "furniture_status": "Nội thất cao cấp",
              "available_for_sale_status": "AVAILABLE",
              "last_modified_date": "1767842095000",
              "number_of_bathrooms": [1],
              "tags": [{"code": "TCA_DOCQUYEN"}]
            }]
          }
        }
      }
    }
    </script>
    </body></html>
    """
    rows = parse_listing_markdown(
        html,
        cfg,
        {
            "source": "onehousing",
            "url": "https://onehousing.vn/ban-can-ho-chung-cu-Vinhomes-Ocean-Park",
            "purpose": "sale",
            "property_type": "apartment",
        },
    )
    assert len(rows) == 1
    assert rows[0]["source"] == "onehousing"
    assert rows[0]["project_slug"] == "vinhomes-ocean-park"
    assert rows[0]["price_total_vnd"] == 3_790_000_000
    assert rows[0]["area_m2"] == 47
    assert rows[0]["bedrooms"] == 1


def test_parse_vinhomesonline_jsonld_detail_when_project_matches():
    cfg = load_config("config/projects.yaml")
    html = """
    <html><head>
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "Bán Căn hộ S301 — Vinhomes Smart City",
      "description": "Căn hộ tại Vinhomes Smart City, phân khu The Sapphire. 2 phòng ngủ, diện tích 54.2m². Sổ hồng lâu dài.",
      "offers": {
        "@type": "Offer",
        "price": "4450000000",
        "priceCurrency": "VND",
        "url": "https://vinhomesonline.vn/tin/vsmart-s301-secondary"
      }
    }
    </script>
    </head><body>
      <dl>
        <dt>Mã căn</dt><dd>S301</dd>
        <dt>Loại hình</dt><dd>Căn hộ</dd>
        <dt>Phòng ngủ</dt><dd>2 PN</dd>
        <dt>Phòng vệ sinh</dt><dd>1 WC</dd>
        <dt>Diện tích thông thủy</dt><dd>54.2 m²</dd>
        <dt>Tình trạng</dt><dd>Còn hàng</dd>
        <dt>Dự án</dt><dd>Vinhomes Smart City</dd>
      </dl>
    </body></html>
    """
    rows = parse_listing_markdown(
        html,
        cfg,
        {
            "source": "vinhomesonline",
            "url": "https://vinhomesonline.vn/tin/vsmart-s301-secondary",
            "purpose": "sale",
            "property_type": "apartment",
        },
    )
    assert len(rows) == 1
    assert rows[0]["source"] == "vinhomesonline"
    assert rows[0]["project_slug"] == "vinhomes-smart-city"
    assert rows[0]["price_total_vnd"] == 4_450_000_000
    assert round(rows[0]["price_per_m2_vnd"]) == round(4_450_000_000 / 54.2)
    assert rows[0]["bedrooms"] == 2
    candidates = parse_property_candidates(
        html,
        cfg,
        {
            "source": "vinhomesonline",
            "url": "https://vinhomesonline.vn/tin/vsmart-s301-secondary",
            "purpose": "sale",
            "property_type": "apartment",
        },
    )
    assert len(candidates) == 1
    assert candidates[0]["mapped_project_slug"] == "vinhomes-smart-city"
    assert candidates[0]["raw_project_name"] == "Vinhomes Smart City"


def test_parse_vinhomesland_price_snapshot_table():
    cfg = load_config("config/projects.yaml")
    html = """
    <html><body>
      <table>
        <tr><th>Loại hình</th><th>Diện tích</th><th>Giá bán</th></tr>
        <tr><td>Căn hộ 2PN</td><td>53 – 71 m2</td><td>3.1 – 7.1 tỷ</td></tr>
      </table>
    </body></html>
    """
    rows = parse_price_snapshots(
        html,
        cfg,
        {
            "source": "vinhomesland",
            "url": "https://vinhomesland.vn/vinhomes-smart-city/",
            "project_slug": "vinhomes-smart-city",
            "purpose": "sale",
            "property_type": "other",
        },
    )
    assert len(rows) == 1
    assert rows[0]["source"] == "vinhomesland"
    assert rows[0]["property_type"] == "apartment"
    assert rows[0]["area_min_m2"] == 53
    assert rows[0]["area_max_m2"] == 71
    assert rows[0]["price_min_vnd"] == 3_100_000_000
    assert rows[0]["price_max_vnd"] == 7_100_000_000
