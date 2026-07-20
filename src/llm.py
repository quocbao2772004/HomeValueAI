from __future__ import annotations

import json
import os
import random
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.env import PROJECT_ROOT, load_app_env, resolve_project_path
from src.text import text_key

TRUE_VALUES = {"1", "true", "yes", "on"}
DEFAULT_PROMPT_DIR = PROJECT_ROOT / "prompts"
RESPONSE_STYLE_HINTS = (
    {
        "name": "direct",
        "instruction": "Lead with the main number or conclusion, then add 1-2 short supporting points.",
    },
    {
        "name": "consultative",
        "instruction": "Sound like a human advisor: softer, conversational, with one brief judgment before the next step.",
    },
    {
        "name": "compact",
        "instruction": "Use short sentences, minimal lead-in, and avoid repeating stock openings such as 'Minh thay' or 'Voi can nay'.",
    },
    {
        "name": "analytical",
        "instruction": "Emphasize reasons behind the number: comparable sample, confidence, and main price drivers.",
    },
    {
        "name": "next_step",
        "instruction": "After the main answer, suggest one useful next detail if context is incomplete, without asking too much.",
    },
)


def llm_enabled() -> bool:
    load_app_env()
    flag = os.getenv("VALUATION_LLM_ENABLED")
    if flag is not None:
        return flag.strip().lower() in TRUE_VALUES
    return bool(os.getenv("OPENAI_API_KEY") and os.getenv("MODEL"))


def generate_answer(intent: str, message: str, context: dict[str, Any], fallback_key: str | None = None) -> str:
    prompt_context = _context_with_response_style(_context_with_language(context, message))
    fallback = _format_answer_lines(_fallback_answer(fallback_key or intent, prompt_context))
    if not llm_enabled():
        return fallback
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("MODEL")
    if not api_key or not model:
        return fallback

    try:
        from openai import OpenAI
    except ImportError:
        return fallback

    try:
        base_url = os.getenv("OPENAI_BASE_URL")
        client = OpenAI(
            api_key=api_key,
            base_url=base_url if base_url else None,
            timeout=_float_env("OPENAI_TIMEOUT_SECONDS", 8.0)
        )
        system_prompt = _system_prompt_for_context(prompt_context)
        user_prompt = _load_prompt("VALUATION_USER_PROMPT_PATH", "chatbot_user.md").format(
            intent=intent,
            message=message,
            context_json=json.dumps(prompt_context, ensure_ascii=False, default=str, indent=2),
        )
        messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        response = client.chat.completions.create(**_chat_completion_kwargs(model, messages))
    except Exception:  # noqa: BLE001
        return fallback

    text = response.choices[0].message.content if response.choices else None
    if not text or not text.strip():
        return fallback
    formatted = _format_answer_lines(text)
    return fallback if _requires_structured_valuation_fallback(intent, context, formatted) else formatted


def _context_with_response_style(context: dict[str, Any]) -> dict[str, Any]:
    if "response_style" in context:
        return dict(context)
    return {**context, "response_style": random.choice(RESPONSE_STYLE_HINTS)}


def _context_with_language(context: dict[str, Any], message: str) -> dict[str, Any]:
    language = str(context.get("response_language") or detect_response_language(message))
    label = "English" if language == "en" else "Vietnamese"
    return {**context, "response_language": language, "response_language_label": label}


def _prompt_dir() -> Path:
    value = os.getenv("VALUATION_PROMPT_DIR")
    return resolve_project_path(value) if value else DEFAULT_PROMPT_DIR


def _load_prompt(env_name: str, default_name: str) -> str:
    load_app_env()
    raw_path = os.getenv(env_name)
    path = resolve_project_path(raw_path) if raw_path else _prompt_dir() / default_name
    return _read_text(str(path))


def _system_prompt_for_context(context: dict[str, Any]) -> str:
    load_app_env()
    if os.getenv("VALUATION_SYSTEM_PROMPT_PATH"):
        return _load_prompt("VALUATION_SYSTEM_PROMPT_PATH", "chatbot_system.md")
    plan = str(context.get("plan") or "").strip().lower()
    if plan == "agent_pro":
        return _load_prompt("VALUATION_SYSTEM_PROMPT_PATH", "chatbot_system_agent_pro.md")
    return _load_prompt("VALUATION_SYSTEM_PROMPT_PATH", "chatbot_system_basic.md")


@lru_cache(maxsize=16)
def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _fallback_answer(key: str, context: dict[str, Any]) -> str:
    templates = _fallback_templates()
    language = str(context.get("response_language") or "vi")
    safe_context = {name: _stringify(value) for name, value in context.items()}
    candidates = []
    if language != "vi":
        candidates.append(f"{key}_{language}")
    candidates.extend([key, f"default_{language}", "default"])
    for candidate in candidates:
        template = templates.get(candidate)
        if not template:
            continue
        try:
            return template.format(**safe_context)
        except KeyError:
            continue
    return ""


def detect_response_language(message: str | None) -> str:
    raw = str(message or "")
    if re.search(r"[ăâêôơưđĂÂÊÔƠƯĐáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", raw):
        return "vi"
    key = text_key(raw)
    if not key:
        return "vi"
    english_phrases = (
        "can you",
        "could you",
        "how much",
        "what is",
        "should i",
        "is it",
        "would it",
        "i want to",
        "for sale",
        "for rent",
    )
    english_terms = {
        "hello",
        "hi",
        "hey",
        "thanks",
        "thank",
        "help",
        "estimate",
        "valuation",
        "price",
        "sale",
        "sell",
        "buy",
        "rent",
        "rental",
        "lease",
        "market",
        "trend",
        "snapshot",
        "reference",
        "amenity",
        "amenities",
        "nearby",
        "around",
        "supermarket",
        "school",
        "hospital",
        "park",
        "apartment",
        "bedroom",
        "bedrooms",
        "furniture",
        "furnished",
        "unit",
        "units",
        "property",
        "properties",
        "room",
        "rooms",
        "sqm",
        "sq",
        "meter",
        "meters",
        "million",
        "billion",
        "vnd",
        "afford",
        "budget",
        "asking",
    }
    vietnamese_terms = {
        "chao",
        "cam",
        "on",
        "dinh",
        "gia",
        "ban",
        "mua",
        "thue",
        "can",
        "ho",
        "tien",
        "ich",
        "xung",
        "quanh",
        "truong",
        "hoc",
        "benh",
        "vien",
    }
    tokens = set(key.split())
    english_score = len(tokens.intersection(english_terms))
    if any(phrase in key for phrase in english_phrases):
        english_score += 2
    vietnamese_score = len(tokens.intersection(vietnamese_terms))
    if english_score >= 2 and english_score >= vietnamese_score:
        return "en"
    if key in {"hello", "hi", "hey", "thank you", "thanks", "help"}:
        return "en"
    return "vi"


def _format_answer_lines(text: str | None) -> str:
    if not text:
        return ""
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""
    if _has_markdown_table(normalized):
        return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in normalized.split("\n") if line.strip())
    if "\n" in normalized:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.split("\n")]
        return "\n\n".join(line for line in lines if line)

    decimal_safe = re.sub(r"(?<=\d)\.(?=\d)", "<decimal-dot>", re.sub(r"\s+", " ", normalized))
    parts = re.split(r"(?<=[.!?])\s+", decimal_safe)
    lines = [part.replace("<decimal-dot>", ".").strip() for part in parts if part.strip()]
    return " ".join(lines) if lines else normalized


def _bulletize_lines(lines: Any) -> str:
    formatted = []
    for line in lines:
        clean = str(line).strip()
        if not clean:
            continue
        clean = re.sub(r"^[-*•]\s+", "", clean)
        formatted.append(f"- {clean}")
    return "\n".join(formatted)


def _has_markdown_table(text: str | None) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    for index, line in enumerate(lines[:-1]):
        if _is_markdown_table_row(line) and _is_markdown_table_separator(lines[index + 1]):
            return True
    return False


def _requires_structured_valuation_fallback(intent: str, context: dict[str, Any], answer: str | None) -> bool:
    if intent != "valuation":
        return False
    example = str(context.get("example_answer") or "")
    if not _has_markdown_table(example):
        return False
    if not _has_markdown_table(answer):
        return True
    normalized = _strip_accents(str(answer or "").lower())
    return not any(marker in normalized for marker in ("gia tham chieu", "gia uoc tinh", "reasonable", "reference"))


def _is_markdown_table_row(line: str) -> bool:
    value = line.strip()
    return value.count("|") >= 2 and not _is_markdown_table_separator(value)


def _is_markdown_table_separator(line: str) -> bool:
    value = line.strip().strip("|").strip()
    if not value:
        return False
    cells = [cell.strip() for cell in value.split("|")]
    return len(cells) >= 2 and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn").replace("đ", "d")


@lru_cache(maxsize=1)
def _fallback_templates() -> dict[str, str]:
    load_app_env()
    raw_path = os.getenv("VALUATION_FALLBACK_PROMPT_PATH")
    path = resolve_project_path(raw_path) if raw_path else _prompt_dir() / "fallback_answers.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(key): str(value) for key, value in data.items()}


def _stringify(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_stringify(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, default=str)
    if value is None:
        return ""
    return str(value)


def _chat_completion_kwargs(model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if _uses_max_completion_tokens(model):
        kwargs["max_completion_tokens"] = _int_env("OPENAI_MAX_TOKENS", 220)
    else:
        kwargs["max_tokens"] = _int_env("OPENAI_MAX_TOKENS", 220)
        kwargs["temperature"] = _float_env("OPENAI_TEMPERATURE", 0.55)
    return kwargs


def _uses_max_completion_tokens(model: str) -> bool:
    normalized = model.lower()
    return normalized.startswith(("gpt-5", "o1", "o3", "o4")) or "gpt-5" in normalized


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default
