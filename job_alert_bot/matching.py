from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from .config import Profile, SourceSettings
from .models import JobOpportunity


REMOTE_HINTS = (
    "remote",
    "worldwide",
    "global",
    "distributed",
    "anywhere",
    "work from home",
)

FRESH_WINDOWS = (
    (timedelta(days=2), 1.5),
    (timedelta(days=7), 0.5),
)

SPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = text.lower()
    text = text.replace("&", " and ")
    text = text.replace("-", " ")
    text = text.replace("/", " ")
    text = text.replace("_", " ")
    text = text.replace("|", " ")
    return SPACE_RE.sub(" ", text).strip()


@lru_cache(maxsize=512)
def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    escaped = re.escape(normalize(phrase)).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<!\w){escaped}(?!\w)")


def _matching_terms(haystack: str, phrases: list[str]) -> list[str]:
    matches: list[str] = []
    for phrase in phrases:
        candidate = normalize(phrase)
        if candidate and _phrase_pattern(candidate).search(haystack):
            matches.append(phrase)
    return matches


def _reasons_from_hits(prefix: str, hits: list[str], limit: int = 3) -> list[str]:
    return [f"{prefix}: {hit}" for hit in hits[:limit]]


def score_job(
    job: JobOpportunity,
    profile: Profile,
    source_settings: SourceSettings,
    now: datetime | None = None,
) -> JobOpportunity | None:
    now = now or datetime.now(timezone.utc)

    title_text = normalize(job.title)
    location_text = normalize(job.location)
    job_type_text = normalize(job.job_type)
    body_text = normalize(" ".join([job.description, " ".join(job.tags), job.location, job.job_type]))
    full_text = normalize(" ".join([job.title, job.company, job.location, job.job_type, " ".join(job.tags), job.description]))

    title_hits = _matching_terms(title_text, profile.title_keywords)
    skill_hits_in_title = _matching_terms(title_text, profile.skill_keywords)
    excluded_hits_in_title = _matching_terms(title_text, profile.excluded_keywords)
    skill_hits = _matching_terms(full_text, profile.skill_keywords)
    bonus_hits = _matching_terms(full_text, profile.bonus_keywords)
    job_type_hits = _matching_terms(" ".join([job_type_text, body_text]), profile.preferred_job_types)
    location_hits = _matching_terms(" ".join([location_text, body_text]), profile.preferred_location_keywords)
    blocked_hits = _matching_terms(" ".join([location_text, body_text]), profile.blocked_location_keywords)
    excluded_hits = _matching_terms(full_text, profile.excluded_keywords)
    remote_hits = _matching_terms(full_text, list(REMOTE_HINTS))

    if excluded_hits_in_title:
        return None

    if not title_hits and not skill_hits_in_title and len(skill_hits) < 2:
        return None

    if excluded_hits and not title_hits and not skill_hits_in_title:
        return None

    score = 0.0
    score += len(title_hits) * 9.0
    score += len(skill_hits_in_title) * 4.0
    score += max(len(skill_hits) - len(skill_hits_in_title), 0) * 1.5
    score += len(bonus_hits) * 2.5
    score += len(job_type_hits) * 4.0
    score += len(location_hits) * 2.0
    score += len(remote_hits) * 1.5
    score -= len(blocked_hits) * 6.0
    score -= len(excluded_hits) * 5.0
    score += source_settings.score_adjustment

    if job.published_at is not None:
        age = now - job.published_at.astimezone(timezone.utc)
        for max_age, bonus in FRESH_WINDOWS:
            if age <= max_age:
                score += bonus
                break

    if blocked_hits and score < profile.minimum_score + 3:
        return None

    if score < profile.minimum_score:
        return None

    reasons: list[str] = []
    reasons.extend(_reasons_from_hits("Role", title_hits))
    reasons.extend(_reasons_from_hits("Stack", skill_hits_in_title or skill_hits))
    reasons.extend(_reasons_from_hits("Fit", job_type_hits or bonus_hits or location_hits))
    if not reasons:
        reasons.append("Matched your profile")

    job.score = round(score, 1)
    job.reasons = reasons[:4]
    return job
