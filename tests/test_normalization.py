from src.normalization import parse_area, parse_bedrooms, parse_price


def test_parse_sale_price_billion():
    parsed = parse_price("4,45 tỷ", "sale")
    assert parsed.price_total_vnd == 4_450_000_000


def test_parse_price_per_m2():
    parsed = parse_price("72,09 tr/m²", "sale")
    assert parsed.price_per_m2_vnd == 72_090_000


def test_parse_rent_monthly():
    parsed = parse_price("18 triệu/tháng", "rent")
    assert parsed.rent_monthly_vnd == 18_000_000


def test_parse_area_and_bedrooms():
    assert parse_area("54,2 m²") == 54.2
    assert parse_bedrooms("Bán nhanh căn 2PN1VS") == 2
