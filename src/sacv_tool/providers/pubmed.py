from __future__ import annotations

import re

from ..config import Settings
from ..models import Citation, ProviderCandidate
from ..normalization import clean_text, extract_doi, extract_year, surname
from .base import MetadataProvider
from .http import ResilientJsonClient


class PubMedProvider(MetadataProvider):
    name = "pubmed"
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.http = ResilientJsonClient(
            timeout=settings.request_timeout,
            retries=settings.retries,
            requests_per_second=settings.pubmed_requests_per_second,
            user_agent="SACV-Tool/1.2.5",
        )

    async def search(self, citation: Citation) -> list[ProviderCandidate]:
        title_query = citation.title or citation.raw
        term = f'"{title_query}"[Title]'
        author = surname(citation.primary_author)
        if author:
            term += f" AND {author}[Author]"
        common = self._common_params()
        search_payload = await self.http.get_json(
            f"{self.base_url}/esearch.fcgi",
            {"db": "pubmed", "retmode": "json", "retmax": self.settings.max_candidates, "term": term, **common},
        )
        ids = search_payload.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        summary_payload = await self.http.get_json(
            f"{self.base_url}/esummary.fcgi",
            {"db": "pubmed", "retmode": "json", "id": ",".join(ids), **common},
        )
        result = summary_payload.get("result", {})
        candidates: list[ProviderCandidate] = []
        for pmid in ids:
            item = result.get(str(pmid), {})
            if not item:
                continue
            article_ids = item.get("articleids", []) or []
            doi = ""
            for identifier in article_ids:
                if identifier.get("idtype") == "doi":
                    doi = clean_text(str(identifier.get("value", ""))).casefold()
                    break
            if not doi:
                doi = extract_doi(str(item.get("elocationid", "")))
            candidates.append(
                ProviderCandidate(
                    provider="pubmed",
                    identifier=str(pmid),
                    title=clean_text(str(item.get("title", ""))).rstrip("."),
                    authors=[clean_text(str(author.get("name", ""))) for author in item.get("authors", []) if author.get("name")],
                    year=extract_year(str(item.get("pubdate", ""))),
                    venue=clean_text(str(item.get("fulljournalname", ""))),
                    doi=doi,
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    raw=item,
                )
            )
        return candidates

    def _common_params(self) -> dict[str, str]:
        params = {"tool": "sacv_tool"}
        if self.settings.email:
            params["email"] = self.settings.email
        if self.settings.ncbi_api_key:
            params["api_key"] = self.settings.ncbi_api_key
        return params

    async def aclose(self) -> None:
        await self.http.aclose()
