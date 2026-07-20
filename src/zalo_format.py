from __future__ import annotations

import re

from src.schemas import ChatResponse
from src.text import text_key

MISSING_LABELS = {
    "purpose": "Mục đích bán hay thuê",
    "project": "Dự án/khu đô thị",
    "property_type": "Loại hình bất động sản",
    "area_m2": "Diện tích m2",
    "bedrooms": "Số phòng ngủ",
}

MISSING_INTRO = {
    "valuation": "Mình cần thêm vài thông tin này để dự đoán giá sát hơn:",
    "trend": "Mình cần thêm thông tin này để xem đúng xu hướng thị trường:",
    "snapshot": "Mình cần thêm thông tin này để tra đúng bảng giá tham khảo:",
    "amenity": "Mình cần thêm thông tin này để tìm tiện ích quanh căn:",
}

MISSING_EXAMPLE = {
    "valuation": "Bạn gửi theo mẫu này là được: bán căn hộ Vinhomes Smart City 54m2, 2PN, full nội thất.",
    "trend": "Bạn cho mình tên dự án hoặc khu đô thị nhé.",
    "snapshot": "Bạn cho mình tên dự án hoặc khu đô thị nhé.",
    "amenity": "Bạn cho mình tên dự án, tòa hoặc phân khu nếu có nhé.",
}

AMENITY_SECTION_LABELS = {
    "giao thông",
    "giao thong",
    "siêu thị",
    "sieu thi",
    "trường học",
    "truong hoc",
    "y tế",
    "y te",
    "ăn uống mua sắm",
    "an uong mua sam",
    "công viên",
    "cong vien",
    "mua sắm",
    "mua sam",
    "giải trí",
    "giai tri",
    "tiện ích",
    "tien ich",
}


def format_zalo_chat_response(response: ChatResponse) -> ChatResponse:
    if response.missing_fields:
        answer = _format_missing_response(response)
    else:
        answer = format_zalo_answer(response.answer)
    return response.model_copy(update={"answer": answer})


def format_zalo_answer(answer: str) -> str:
    normalized = answer.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    formatted: list[str] = []
    index = 0
    while index < len(lines):
        raw_line = lines[index].strip()
        if not raw_line:
            _append_blank(formatted)
            index += 1
            continue

        if _is_markdown_table_row(raw_line):
            table_rows, index = _consume_table(lines, index)
            _append_bullet_block(formatted, _table_rows_to_points(table_rows))
            continue

        if _is_markdown_list_item(raw_line):
            list_items, index = _consume_markdown_list(lines, index)
            points = [cleaned for item in list_items if (cleaned := _clean_idea(item))]
            if len(points) > 1:
                _append_bullet_block(formatted, points)
            elif points:
                _append_text(formatted, points[0])
            continue

        for part in _split_prose_ideas(raw_line):
            _append_text(formatted, _clean_prose(part))
        index += 1
    return _compact_output(formatted)


def _format_missing_response(response: ChatResponse) -> str:
    intent = response.intent or "valuation"
    missing_points = _missing_field_points(response)
    lines: list[str] = []

    if len(missing_points) == 1:
        intro = MISSING_INTRO.get(intent, "Mình cần thêm thông tin này để trả lời chính xác hơn:")
        lines.append(f"{intro.rstrip(':')}:")
        lines.append("")
        lines.append(f"• {missing_points[0]}")
    else:
        lines.append(MISSING_INTRO.get(intent, "Mình cần thêm vài thông tin này để trả lời chính xác hơn:"))
        lines.append("")
        lines.extend(f"• {point}" for point in missing_points)

    suggestion_points = _missing_suggestion_points(response)
    if suggestion_points:
        _append_point_section(lines, "Gợi ý nhanh từ dữ liệu hiện có", suggestion_points)

    example = MISSING_EXAMPLE.get(intent)
    if example:
        lines.extend(["", example])
    return _compact_output(lines)


def _missing_field_points(response: ChatResponse) -> list[str]:
    guidance = ((response.data or {}).get("missing_field_guidance") or []) if response.data else []
    points: list[str] = []
    for item in guidance:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or MISSING_LABELS.get(str(item.get("field")), str(item.get("field")))).strip()
        options = [
            str(option.get("label") or option.get("value")).strip()
            for option in item.get("options") or []
            if isinstance(option, dict) and (option.get("label") or option.get("value"))
        ]
        examples = [str(example).strip() for example in item.get("examples") or [] if str(example).strip()]
        hint = str(item.get("hint") or "").strip()

        if options:
            points.append(f"{label}: {', '.join(options)}")
        elif examples:
            points.append(f"{label}: nhập dạng {', '.join(examples)}")
        elif hint:
            points.append(f"{label}: {hint}")
        elif label:
            points.append(label)

    if points:
        return points
    return [MISSING_LABELS.get(field, field) for field in response.missing_fields]


def _missing_suggestion_points(response: ChatResponse) -> list[str]:
    suggestions = ((response.data or {}).get("retrieval_suggestions") or {}) if response.data else {}
    points: list[str] = []

    if "project" in response.missing_fields:
        for project in (suggestions.get("nearest_projects") or [])[:2]:
            name = project.get("name")
            if not name:
                continue
            detail = _join_details(
                [
                    f"diện tích hay gặp {project.get('area_range_text')}" if project.get("area_range_text") else "",
                    f"mặt bằng khoảng {project.get('median_metric_text')}" if project.get("median_metric_text") else "",
                ]
            )
            points.append(f"{name}: {detail}" if detail else str(name))

    area_hint = suggestions.get("area_hint")
    if "area_m2" in response.missing_fields and area_hint:
        detail = _join_details(
            [
                f"diện tích hay gặp {area_hint.get('range_text')}" if area_hint.get("range_text") else "",
                f"trung vị {area_hint.get('median_text')}" if area_hint.get("median_text") else "",
            ]
        )
        if detail:
            points.append(f"Nhóm căn tương tự: {detail}")

    location_hints = suggestions.get("location_hints") or {}
    subdivisions = [
        item.get("name")
        for item in location_hints.get("subdivisions") or []
        if isinstance(item, dict) and item.get("name")
    ]
    towers = [
        item.get("code")
        for item in location_hints.get("towers") or []
        if isinstance(item, dict) and item.get("code")
    ]
    if subdivisions:
        points.append(f"Phân khu đang có dữ liệu: {', '.join(str(item) for item in subdivisions[:4])}")
    if towers:
        points.append(f"Mã tòa hay gặp: {', '.join(str(item) for item in towers[:6])}")

    return points[:5]


def _join_details(parts: list[str]) -> str:
    return ", ".join(part for part in parts if part)


def _split_prose_ideas(line: str) -> list[str]:
    if len(line) <= 220:
        return [line]
    parts = re.split(r"(?<=[.!?])\s+(?=[0-9A-ZÀ-Ỵà-ỵ])", line)
    return [part for part in parts if part.strip()]


def _consume_table(lines: list[str], start: int) -> tuple[list[str], int]:
    table_rows: list[str] = []
    index = start
    while index < len(lines):
        raw_line = lines[index].strip()
        if not _is_markdown_table_row(raw_line):
            break
        table_rows.append(raw_line)
        index += 1
    return table_rows, index


def _table_rows_to_points(rows: list[str]) -> list[str]:
    if len(rows) >= 2 and _is_markdown_table_separator(rows[1]):
        rows = rows[2:]
    points = [_table_row_to_idea(row) for row in rows if not _is_markdown_table_separator(row)]
    return [point for point in points if point]


def _table_row_to_idea(line: str) -> str:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    cells = [cell for cell in cells if cell]
    if len(cells) < 2:
        return ""
    label = cells[0].rstrip(":")
    value = " - ".join(cells[1:])
    return f"{label}: {value}"


def _is_markdown_table_row(line: str) -> bool:
    return line.startswith("|") and line.endswith("|") and line.count("|") >= 2


def _is_markdown_table_separator(line: str) -> bool:
    if not _is_markdown_table_row(line):
        return False
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(cell and set(cell) <= {"-", ":"} for cell in cells)


def _is_markdown_list_item(line: str) -> bool:
    return bool(re.match(r"^(?:[-*•]|\d+[.)])\s+", line))


def _consume_markdown_list(lines: list[str], start: int) -> tuple[list[str], int]:
    items: list[str] = []
    index = start
    while index < len(lines):
        raw_line = lines[index].strip()
        if not _is_markdown_list_item(raw_line):
            break
        items.append(re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", raw_line).strip())
        index += 1
    return items, index


def _append_bullet_block(lines: list[str], points: list[str]) -> None:
    clean_points = [cleaned for point in points if (cleaned := _clean_idea(point))]
    if not clean_points:
        return
    if lines and lines[-1] != "":
        lines.append("")
    previous_was_amenity = False
    for point in clean_points:
        if _is_amenity_section_point(point):
            _append_amenity_section(lines, point)
            previous_was_amenity = True
        else:
            if previous_was_amenity and lines and lines[-1] != "":
                lines.append("")
            lines.append(f"• {point}")
            previous_was_amenity = False


def _is_amenity_section_point(point: str) -> bool:
    label, separator, value = point.partition(":")
    return bool(separator and value.strip() and _section_key(label) in AMENITY_SECTION_LABELS)


def _append_amenity_section(lines: list[str], point: str) -> None:
    label, _, raw_value = point.partition(":")
    items = _amenity_section_items(raw_value)
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(f"{label.strip()}:")
    if not items:
        lines.append(f"• {_clean_idea(raw_value)}")
        return
    lines.extend(f"• {item}" for item in items)


def _amenity_section_items(value: str) -> list[str]:
    cleaned = _clean_idea(value)
    cleaned = re.sub(r"^(?:có|co)\s+", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.rstrip(".")
    if not cleaned:
        return []

    parts = re.split(r",\s+(?=[^,;]+(?:cách khoảng|cach khoang|cách|cach)\b)", cleaned, flags=re.IGNORECASE)
    if len(parts) == 1:
        parts = re.split(r";\s+", cleaned)
    return [_ensure_period(part.strip()) for part in parts if part.strip()]


def _section_key(label: str) -> str:
    return text_key(label)


def _append_point_section(lines: list[str], title: str, points: list[str]) -> None:
    clean_points = [cleaned for point in points if (cleaned := _clean_idea(point))]
    if not clean_points:
        return
    if len(clean_points) == 1:
        lines.extend(["", f"{title}: {_ensure_period(clean_points[0])}"])
        return
    lines.extend(["", f"{title}:"])
    lines.extend(f"• {point}" for point in clean_points)


def _append_blank(lines: list[str]) -> None:
    if lines and lines[-1] != "":
        lines.append("")


def _append_text(lines: list[str], text: str) -> None:
    cleaned = _clean_prose(text)
    if cleaned:
        lines.append(cleaned)


def _compact_output(lines: list[str]) -> str:
    compacted: list[str] = []
    previous_blank = True
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if compacted and not previous_blank:
                compacted.append("")
            previous_blank = True
            continue
        compacted.append(line)
        previous_blank = False
    return "\n".join(compacted).strip()


def _clean_prose(text: str) -> str:
    return " ".join(text.replace("**", "").strip().split())


def _clean_idea(text: str) -> str:
    cleaned = _clean_prose(text)
    cleaned = cleaned.strip(" -•")
    return cleaned


def _ensure_period(text: str) -> str:
    return text if text.endswith((".", "!", "?")) else f"{text}."
