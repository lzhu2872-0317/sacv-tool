from __future__ import annotations

from urllib.parse import quote

from ..config import Settings
from ..models import Citation, ProviderCandidate
from ..normalization import clean_text
from .base import MetadataProvider
from .http import ResilientJsonClient


class CrossrefProvider(MetadataProvider):
    name = "crossref"
    base_url = "https://api.crossref.org/works"

    def __init__(self, settings: Settings):
        contact = f" (mailto:{settings.email})" if settings.email else ""
        self.settings = settings
        self.http = ResilientJsonClient(
            timeout=settings.request_timeout,
            retries=settings.retries,
            requests_per_second=settings.crossref_requests_per_second,
            user_agent=f"SACV-Tool/1.2.5{contact}",
        )

    async def search(self, citation: Citation) -> list[ProviderCandidate]:
        candidates: list[ProviderCandidate] = []
        if citation.doi:
            payload = await self.http.get_json(f"{self.base_url}/{quote(citation.doi, safe='')}", self._contact_params())
            message = payload.get("message")
            if isinstance(message, dict) and message:
                candidates.append(_candidate_from_item(message))
                return candidates

        query = citation.title or citation.raw
        params: dict[str, str | int] = {
            "query.bibliographic": query,
            "rows": self.settings.max_candidates,
            "select": "DOI,title,author,published-print,published-online,issued,container-title,URL,type",
        }
        params.update(self._contact_params())
        payload = await self.http.get_json(self.base_url, params)
        items = payload.get("message", {}).get("items", []) if payload else []
        for item in items:
            if isinstance(item, dict):
                candidates.append(_candidate_from_item(item))
        return candidates

    def _contact_params(self) -> dict[str, str]:
        return {"mailto": self.settings.email} if self.settings.email else {}

    async def aclose(self) -> None:
        await self.http.aclose()


def _candidate_from_item(item: dict) -> ProviderCandidate:
    title = clean_text(_first(item.get("title")))
    venue = clean_text(_first(item.get("container-title")))
    authors: list[str] = []
    for author in item.get("author", []) or []:
        if not isinstance(author, dict):
            continue
        family = clean_text(str(author.get("family", "")))
        given = clean_text(str(author.get("given", "")))
        name = ", ".join(part for part in (family, given) if part)
        if name:
            authors.append(name)
    doi = clean_text(str(item.get("DOI", ""))).casefold()
    return ProviderCandidate(
        provider="crossref",
        identifier=doi or clean_text(str(item.get("URL", ""))),
        title=title,
        authors=authors,
        year=_year_from_item(item),
        venue=venue,
        doi=doi,
        url=clean_text(str(item.get("URL", ""))) or (f"https://doi.org/{doi}" if doi else ""),
        raw=item,
    )


def _first(value: object) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    return str(value or "")


def _year_from_item(item: dict) -> int | None:
    for key in ("published-print", "published-online", "issued"):
        date_parts = (item.get(key) or {}).get("date-parts", [])
        if date_parts and date_parts[0]:
            try:
                return int(date_parts[0][0])
            except (TypeError, ValueError):
                continue
    return None
