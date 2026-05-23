from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

from .config import AppConfig, SourceSettings
from .matching import score_job
from .models import JobOpportunity, ScanSummary
from .sources import JobSource, build_default_sources
from .storage import Storage


LOGGER = logging.getLogger(__name__)
SOURCE_PRIORITY = {
    "mostaql": 0,
}


class JobTracker:
    def __init__(self, config: AppConfig, storage: Storage, sources: list[JobSource] | None = None) -> None:
        self.config = config
        self.storage = storage
        self.sources = sources or build_default_sources()

    def _source_settings(self, name: str) -> SourceSettings:
        return self.config.profile.sources.get(name, SourceSettings())

    def _source_priority(self, name: str) -> int:
        return SOURCE_PRIORITY.get(name, 100)

    async def _fetch_source(self, client: httpx.AsyncClient, source: JobSource) -> list[JobOpportunity]:
        settings = self._source_settings(source.name)
        if not settings.enabled:
            return []
        try:
            return await source.fetch(client)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Source %s failed: %s", source.name, exc)
            return []

    async def fetch_matches(self) -> list[JobOpportunity]:
        timeout = httpx.Timeout(30.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "telegram-job-alert-bot/1.0"}) as client:
            results = await asyncio.gather(*(self._fetch_source(client, source) for source in self.sources))

        now = datetime.now(timezone.utc)
        lookback = now - timedelta(hours=self.config.profile.hours_lookback)

        scored: list[JobOpportunity] = []
        for jobs in results:
            for job in jobs:
                if job.published_at is not None and job.published_at.astimezone(timezone.utc) < lookback:
                    continue
                matched = score_job(job, self.config.profile, self._source_settings(job.source), now=now)
                if matched is not None and matched.url:
                    scored.append(matched)

        scored.sort(
            key=lambda job: (
                self._source_priority(job.source),
                -job.score,
                -(job.published_at.timestamp() if job.published_at else 0),
                job.source,
            )
        )
        return scored

    async def preview(self, limit: int | None = None) -> list[JobOpportunity]:
        jobs = await self.fetch_matches()
        return jobs[: limit or self.config.profile.max_alert_items]

    async def scan_for_alerts(self) -> ScanSummary:
        matches = await self.fetch_matches()
        seen = await self.storage.seen_job_keys([job.key for job in matches])
        new_jobs = [job for job in matches if job.key not in seen]

        warmup_mode = False
        if self.config.profile.warmup_without_alerts and not await self.storage.has_completed_scan():
            warmup_mode = True
            await self.storage.mark_jobs_seen(matches, sent=False)
            new_jobs = []
        else:
            await self.storage.mark_jobs_seen(new_jobs, sent=False)

        await self.storage.record_scan(
            total_jobs=len(matches),
            matched_jobs=len(matches),
            new_jobs=len(new_jobs),
            warmup_mode=warmup_mode,
        )
        return ScanSummary(
            total_jobs=len(matches),
            matched_jobs=matches,
            new_jobs=new_jobs,
            warmup_mode=warmup_mode,
        )
