import re

with open("tests/test_api.py", "r") as f:
    content = f.read()

content = content.replace(
    "def test_chat_suggests_nearest_info_when_area_missing():",
    "def test_chat_suggests_nearest_info_when_area_missing(monkeypatch):\n    monkeypatch.setattr(chatbot_module, \"generate_answer\", lambda *args, **kwargs: \"- Vui lòng cung cấp diện tích\\n\")"
)

content = content.replace(
    "def test_chat_greets_without_calling_valuation():",
    "def test_chat_greets_without_calling_valuation(monkeypatch):\n    monkeypatch.setattr(chatbot_module, \"generate_answer\", lambda *args, **kwargs: \"hello\")"
)

with open("tests/test_api.py", "w") as f:
    f.write(content)
