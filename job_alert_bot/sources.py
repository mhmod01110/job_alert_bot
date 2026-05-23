from __future__ import annotations

import html
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .models import JobOpportunity


TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
MOSTAQL_ID_RE = re.compile(r"/project/(\d+)")


def strip_html(value: str) -> str:
    text = html.unescape(TAG_RE.sub(" ", value or ""))
    return SPACE_RE.sub(" ", text).strip()


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_datetime(value: str | int | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=timezone.utc)

    raw = str(value).strip()
    try:
        return ensure_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        pass

    try:
        return ensure_utc(parsedate_to_datetime(raw))
    except (TypeError, ValueError):
        return None


def external_id_from_url(url: str) -> str:
    match = MOSTAQL_ID_RE.search(url)
    if match:
        return match.group(1)
    return url.rstrip("/").rsplit("/", maxsplit=1)[-1]


class JobSource(ABC):
    name: str

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient) -> list[JobOpportunity]:
        raise NotImplementedError


class RemoteOkSource(JobSource):
    name = "remoteok"
    endpoint = "https://remoteok.com/api"

    async def fetch(self, client: httpx.AsyncClient) -> list[JobOpportunity]:
        response = await client.get(self.endpoint)
        response.raise_for_status()
        payload = response.json()
        jobs: list[JobOpportunity] = []
        for item in payload[1:]:
            if not item.get("id") or not item.get("position"):
                continue

            tags = [str(tag) for tag in item.get("tags", [])]
            job_type = ", ".join(
                tag for tag in tags if tag.lower() in {"part-time", "part time", "contract", "full-time", "freelance"}
            )
            jobs.append(
                JobOpportunity(
                    source=self.name,
                    external_id=str(item["id"]),
                    title=strip_html(str(item.get("position", ""))),
                    company=strip_html(str(item.get("company", ""))),
                    url=str(item.get("apply_url") or item.get("url") or "").strip(),
                    location=strip_html(str(item.get("location", ""))),
                    job_type=job_type,
                    description=strip_html(str(item.get("description", ""))),
                    tags=tags,
                    published_at=parse_datetime(item.get("epoch")),
                )
            )
        return jobs


class MostaqlSource(JobSource):
    name = "mostaql"
    endpoint = "https://mostaql.com/projects"

    async def fetch(self, client: httpx.AsyncClient) -> list[JobOpportunity]:
        response = await client.get(
            self.endpoint,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "ar,en;q=0.9",
            },
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        jobs: list[JobOpportunity] = []

        for row in soup.select("tbody[data-filter='collection'] tr.project-row"):
            title_link = row.select_one("h2 a[href]")
            if title_link is None:
                continue

            url = urljoin(self.endpoint, str(title_link.get("href") or "").strip())
            if not url:
                continue

            description_node = row.select_one("p.project__brief a, p.project__brief")
            owner_node = row.select_one("ul.project__meta li bdi")
            time_node = row.find("time")

            jobs.append(
                JobOpportunity(
                    source=self.name,
                    external_id=external_id_from_url(url),
                    title=strip_html(title_link.get_text(" ", strip=True)),
                    company=strip_html(owner_node.get_text(" ", strip=True) if owner_node else "Mostaql client"),
                    url=url,
                    location="remote",
                    job_type="freelance",
                    description=strip_html(description_node.get_text(" ", strip=True) if description_node else ""),
                    tags=["freelance", "arabic marketplace", "mostaql"],
                    published_at=parse_datetime(time_node.get("datetime")) if time_node is not None else None,
                )
            )
        return jobs


class RemotiveSource(JobSource):
    name = "remotive"
    endpoint = "https://remotive.com/api/remote-jobs"

    async def fetch(self, client: httpx.AsyncClient) -> list[JobOpportunity]:
        response = await client.get(self.endpoint)
        response.raise_for_status()
        payload = response.json()
        jobs: list[JobOpportunity] = []
        for item in payload.get("jobs", []):
            if not item.get("id") or not item.get("title"):
                continue

            jobs.append(
                JobOpportunity(
                    source=self.name,
                    external_id=str(item["id"]),
                    title=strip_html(str(item.get("title", ""))),
                    company=strip_html(str(item.get("company_name", ""))),
                    url=str(item.get("url") or "").strip(),
                    location=strip_html(str(item.get("candidate_required_location", ""))),
                    job_type=strip_html(str(item.get("job_type", ""))).replace("_", " "),
                    description=strip_html(str(item.get("description", ""))),
                    tags=[str(tag) for tag in item.get("tags", [])],
                    published_at=parse_datetime(item.get("publication_date")),
                )
            )
        return jobs


class JobicySource(JobSource):
    name = "jobicy"
    endpoint = "https://jobicy.com/api/v2/remote-jobs?count=100"

    async def fetch(self, client: httpx.AsyncClient) -> list[JobOpportunity]:
        response = await client.get(self.endpoint)
        response.raise_for_status()
        payload = response.json()
        jobs: list[JobOpportunity] = []
        for item in payload.get("jobs", []):
            if not item.get("id") or not item.get("jobTitle"):
                continue

            raw_job_type = item.get("jobType", [])
            job_type = ", ".join(str(entry) for entry in raw_job_type) if isinstance(raw_job_type, list) else str(raw_job_type)

            jobs.append(
                JobOpportunity(
                    source=self.name,
                    external_id=str(item["id"]),
                    title=strip_html(str(item.get("jobTitle", ""))),
                    company=strip_html(str(item.get("companyName", ""))),
                    url=str(item.get("url") or "").strip(),
                    location=strip_html(str(item.get("jobGeo", ""))),
                    job_type=strip_html(job_type),
                    description=strip_html(str(item.get("jobDescription", ""))),
                    tags=[strip_html(str(item.get("jobIndustry", ""))), strip_html(str(item.get("jobLevel", "")))],
                    published_at=parse_datetime(item.get("pubDate")),
                )
            )
        return jobs


def build_default_sources() -> list[JobSource]:
    return [MostaqlSource(), RemoteOkSource(), RemotiveSource(), JobicySource()]
