from src.zalo_format import format_zalo_answer


def test_zalo_formatter_splits_amenity_sections_into_grouped_bullets():
    answer = (
        "Tiện ích quanh căn cũng là một điểm cộng:\n\n"
        "| Nhóm tiện ích | Thông tin |\n"
        "| --- | --- |\n"
        "| Giao thông | có Metro số 5 cách khoảng 700m, Bus nội khu cách khoảng 300m. |\n"
        "| Y tế | có Vinmec cách khoảng 850m, Phòng khám Tây Mỗ cách khoảng 1.3km. |\n"
        "| Lưu ý | Khoảng cách là ước tính theo tọa độ map. |"
    )

    formatted = format_zalo_answer(answer)

    assert "Giao thông:\n• Metro số 5 cách khoảng 700m.\n• Bus nội khu cách khoảng 300m." in formatted
    assert "Y tế:\n• Vinmec cách khoảng 850m.\n• Phòng khám Tây Mỗ cách khoảng 1.3km." in formatted
    assert "\n\n• Lưu ý: Khoảng cách là ước tính theo tọa độ map." in formatted
