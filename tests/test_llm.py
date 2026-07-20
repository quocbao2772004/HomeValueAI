from src.llm import _format_answer_lines


def test_answer_formatter_preserves_prose_bullets_and_markdown_tables():
    answer = _format_answer_lines(
        "Kết luận ngắn gọn.\n\n| Hạng mục | Giá trị |\n| --- | --- |\n| Giá tham chiếu | 5 tỷ |\n\n- Kiểm tra thêm tầng và view."
    )

    assert answer.startswith("Kết luận ngắn gọn.")
    assert "| Hạng mục | Giá trị |" in answer
    assert "| Giá tham chiếu | 5 tỷ |" in answer
    assert answer.endswith("- Kiểm tra thêm tầng và view.")
