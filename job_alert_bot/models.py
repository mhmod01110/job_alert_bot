from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class JobOpportunity:
    source: str
    external_id: str
    title: str
    company: str
    url: str
    location: str = ""
    job_type: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    published_at: datetime | None = None
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.external_id}"


@dataclass(slots=True)
class ScanSummary:
    total_jobs: int
    matched_jobs: list[JobOpportunity]
    new_jobs: list[JobOpportunity]
    warmup_mode: bool = False

