from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "projects.yaml"


@dataclass(frozen=True)
class PageConfig:
    purpose: str
    property_type: str
    url: str
    source: str = "auto"
    pagination: str = "auto"
    max_pages: int | None = None


@dataclass(frozen=True)
class ProjectConfig:
    slug: str
    name: str
    aliases: tuple[str, ...]
    district_hint: str | None
    pages: tuple[PageConfig, ...]


@dataclass(frozen=True)
class AppConfig:
    raw: dict[str, Any]
    projects: tuple[ProjectConfig, ...]

    @property
    def project_by_slug(self) -> dict[str, ProjectConfig]:
        return {project.slug: project for project in self.projects}


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path or DEFAULT_CONFIG_PATH)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    projects = []
    for item in raw.get("projects", []):
        projects.append(
            ProjectConfig(
                slug=item["slug"],
                name=item["name"],
                aliases=tuple(item.get("aliases", [])),
                district_hint=item.get("district_hint"),
                pages=tuple(PageConfig(**page) for page in item.get("pages", [])),
            )
        )
    return AppConfig(raw=raw, projects=tuple(projects))


def get_nested(config: AppConfig, *keys: str, default: Any = None) -> Any:
    current: Any = config.raw
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current
