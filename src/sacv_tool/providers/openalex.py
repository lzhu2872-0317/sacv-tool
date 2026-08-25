from __future__ import annotations

from ..config import Settings
from ..models import Citation, ProviderCandidate
from ..normalization import clean_text, normalize_doi
from .base import MetadataProvider
from .http import ResilientJsonClient


class OpenAlexProvider(MetadataProvider):
    name = "openalex"
    base_url = "https://api.openalex.org/works"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.http = ResilientJsonClient(
            timeout=settings.request_timeout,
            retries=settings.retries,
            requests_per_second=settings.openalex_requests_per_second,
            user_agent="SACV-Tool/1.2.5",
        )

    async def search(self, citation: Citation) -> list[ProviderCandidate]:
        params: dict[str, str | int] = {"per-page": self.settings.max_candidates}
        if citation.doi:
            params["filter"] = f"doi:https://doi.org/{normalize_doi(citation.doi)}"
        else:
            params["search"] = citation.title or citation.raw
        if self.settings.email:
            params["mailto"] = self.settings.email
        if self.settings.openalex_api_key:
            params["api_key"] = self.settings.openalex_api_key
        payload = await self.http.get_json(self.base_url, params)
        return [_candidate_from_work(item) for item in payload.get("results", []) if isinstance(item, dict)]

    async def aclose(self) -> None:
        await self.http.aclose()


def _candidate_from_work(item: dict) -> ProviderCandidate:
    authors: list[str] = []
    for authorship in item.get("authorships", []) or []:
        author = authorship.get("author", {}) if isinstance(authorship, dict) else {}
        name = clean_text(str(author.get("display_name", "")))
        if name:
            authors.append(name)
    location = item.get("primary_location") or {}
    source = location.get("source") or {}
    doi = normalize_doi(str(item.get("doi", "")))
    identifier = clean_text(str(item.get("id", "")))
    return ProviderCandidate(
        provider="openalex",
        identifier=identifier or doi,
        title=clean_text(str(item.get("display_name") or item.get("title") or "")),
        authors=authors,
        year=_as_year(item.get("publication_year")),
        venue=clean_text(str(source.get("display_name", ""))),
        doi=doi,
        url=clean_text(str(location.get("landing_page_url", ""))) or identifier,
        raw=item,
    )


def _as_year(value: object) -> int | None:
    try:
        year = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return year if 1800 <= year <= 2100 else None
