from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass(slots=True)
class SourceSettings:
    enabled: bool = True
    score_adjustment: float = 0.0


@dataclass(slots=True)
class Profile:
    profile_name: str
    headline: str
    title_keywords: list[str] = field(default_factory=list)
    skill_keywords: list[str] = field(default_factory=list)
    bonus_keywords: list[str] = field(default_factory=list)
    preferred_job_types: list[str] = field(default_factory=list)
    preferred_location_keywords: list[str] = field(default_factory=list)
    blocked_location_keywords: list[str] = field(default_factory=list)
    excluded_keywords: list[str] = field(default_factory=list)
    minimum_score: float = 10.0
    hours_lookback: int = 168
    max_alert_items: int = 8
    poll_interval_minutes: int = 60
    warmup_without_alerts: bool = True
    sources: dict[str, SourceSettings] = field(default_factory=dict)


@dataclass(slots=True)
class AppConfig:
    telegram_bot_token: str
    timezone: str
    profile_path: Path
    database_path: Path
    allowed_user_ids: set[int]
    log_level: str
    profile: Profile


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Profile file {path} must contain a YAML mapping.")
    return data


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Expected a YAML list of strings.")
    return [str(item).strip() for item in value if str(item).strip()]


def _load_profile(path: Path) -> Profile:
    raw = _load_yaml(path)
    sources_raw = raw.get("sources", {}) or {}
    sources: dict[str, SourceSettings] = {}
    for name, settings in sources_raw.items():
        settings = settings or {}
        sources[str(name).strip().lower()] = SourceSettings(
            enabled=bool(settings.get("enabled", True)),
            score_adjustment=float(settings.get("score_adjustment", 0.0)),
        )

    return Profile(
        profile_name=str(raw.get("profile_name", "Job Seeker")).strip(),
        headline=str(raw.get("headline", "")).strip(),
        title_keywords=_string_list(raw.get("title_keywords")),
        skill_keywords=_string_list(raw.get("skill_keywords")),
        bonus_keywords=_string_list(raw.get("bonus_keywords")),
        preferred_job_types=_string_list(raw.get("preferred_job_types")),
        preferred_location_keywords=_string_list(raw.get("preferred_location_keywords")),
        blocked_location_keywords=_string_list(raw.get("blocked_location_keywords")),
        excluded_keywords=_string_list(raw.get("excluded_keywords")),
        minimum_score=float(raw.get("minimum_score", 10.0)),
        hours_lookback=int(raw.get("hours_lookback", 168)),
        max_alert_items=int(raw.get("max_alert_items", 8)),
        poll_interval_minutes=int(raw.get("poll_interval_minutes", 60)),
        warmup_without_alerts=bool(raw.get("warmup_without_alerts", True)),
        sources=sources,
    )


def _allowed_user_ids(raw: str) -> set[int]:
    values: set[int] = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        values.add(int(chunk))
    return values


def load_config(base_dir: Path | None = None) -> AppConfig:
    base_dir = base_dir or Path.cwd()
    load_dotenv(base_dir / ".env")

    profile_path = Path(os.getenv("PROFILE_PATH", "profile.yaml"))
    if not profile_path.is_absolute():
        profile_path = base_dir / profile_path

    database_path = Path(os.getenv("DATABASE_PATH", "job_alerts.sqlite3"))
    if not database_path.is_absolute():
        database_path = base_dir / database_path

    profile = _load_profile(profile_path)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    return AppConfig(
        telegram_bot_token=token,
        timezone=os.getenv("BOT_TIMEZONE", "Africa/Cairo").strip(),
        profile_path=profile_path,
        database_path=database_path,
        allowed_user_ids=_allowed_user_ids(os.getenv("ALLOWED_USER_IDS", "")),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        profile=profile,
    )

