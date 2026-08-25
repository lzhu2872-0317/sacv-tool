from __future__ import annotations

import ipaddress
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from ..config import Settings
from ..models import Citation, ProviderCandidate
from ..normalization import clean_text, extract_year
from .base import MetadataProvider, ProviderError
from .http import AsyncRateLimiter

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024


class WebProvider(MetadataProvider):
    """Validate cited web/policy sources without pretending they are journal records."""

    name = "web"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.rate_limiter = AsyncRateLimiter(settings.web_requests_per_second)
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36 "
                    "SACV-Tool/1.2.5"
                ),
                "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5",
                "Accept-Language": "en-US,en;q=0.8",
            },
        )

    async def search(self, citation: Citation) -> list[ProviderCandidate]:
        if not citation.url:
            return []
        _validate_public_http_url(citation.url)
        await self.rate_limiter.wait()
        try:
            async with self.client.stream("GET", citation.url) as response:
                if response.status_code == 404 or response.status_code == 410:
                    return []
                if response.status_code in {401, 403, 429}:
                    return [
                        _web_candidate(
                            citation.url,
                            provider="web_restricted",
                            status_code=response.status_code,
                            content_type=response.headers.get("content-type", ""),
                        )
                    ]
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").casefold()
                encoding = response.encoding or "utf-8"
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    remaining = MAX_DOCUMENT_BYTES - size
                    if remaining <= 0:
                        break
                    chunks.append(chunk[:remaining])
                    size += min(len(chunk), remaining)
                    if size >= MAX_DOCUMENT_BYTES:
                        break
                final_url = str(response.url)
                status_code = response.status_code
        except httpx.HTTPError as exc:
            raise ProviderError(f"Web source request failed: {exc}") from exc

        body = b"".join(chunks)
        title = ""
        authors: list[str] = []
        year = None
        if "html" in content_type or body.lstrip().startswith((b"<", b"<!")):
            decoded = body.decode(encoding, errors="replace")
            metadata = _parse_html_metadata(decoded)
            title = metadata["title"]
            authors = metadata["authors"]
            year = extract_year(metadata["date"])
            if _looks_like_soft_404(title, decoded):
                return []
        elif "pdf" in content_type or body.startswith(b"%PDF"):
            title, authors = _parse_pdf_metadata(body)

        host = clean_text(urlparse(final_url).hostname or "")
        return [
            ProviderCandidate(
                provider="web",
                identifier=final_url,
                title=title,
                authors=authors,
                year=year,
                venue=host,
                url=final_url,
                raw={"status_code": status_code, "content_type": content_type},
            )
        ]

    async def aclose(self) -> None:
        await self.client.aclose()


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.in_h1 = False
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.meta: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if tag.casefold() == "title":
            self.in_title = True
        if tag.casefold() == "h1" and not self.h1_parts:
            self.in_h1 = True
        if tag.casefold() != "meta":
            return
        key = (attributes.get("property") or attributes.get("name") or "").casefold()
        content = clean_text(attributes.get("content", ""))
        if key and content:
            self.meta.setdefault(key, []).append(content)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self.in_title = False
        if tag.casefold() == "h1":
            self.in_h1 = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self.in_h1:
            self.h1_parts.append(data)


def _parse_html_metadata(value: str) -> dict[str, object]:
    parser = _MetadataParser()
    parser.feed(value)
    title = _first_meta(parser, "citation_title", "og:title", "twitter:title")
    if not title:
        title = clean_text(" ".join(parser.title_parts))
    if not title:
        title = clean_text(" ".join(parser.h1_parts))
    authors = parser.meta.get("citation_author", []) or parser.meta.get("author", [])
    date = _first_meta(parser, "citation_publication_date", "article:published_time", "date", "dc.date")
    return {"title": title, "authors": authors[:12], "date": date}


def _first_meta(parser: _MetadataParser, *keys: str) -> str:
    for key in keys:
        values = parser.meta.get(key, [])
        if values:
            return values[0]
    return ""


def _looks_like_soft_404(title: str, body: str) -> bool:
    sample = clean_text(f"{title} {body[:4000]}").casefold()
    return bool(re.search(r"\b(?:404|page not found|content not found|page does not exist)\b", sample))


def _web_candidate(
    url: str,
    *,
    provider: str,
    status_code: int,
    content_type: str,
) -> ProviderCandidate:
    return ProviderCandidate(
        provider=provider,
        identifier=url,
        title="",
        venue=clean_text(urlparse(url).hostname or ""),
        url=url,
        raw={"status_code": status_code, "content_type": content_type.casefold()},
    )


def _parse_pdf_metadata(body: bytes) -> tuple[str, list[str]]:
    try:
        import pymupdf

        with pymupdf.open(stream=body, filetype="pdf") as document:
            metadata = document.metadata or {}
            title = clean_text(str(metadata.get("title", "")))
            author = clean_text(str(metadata.get("author", "")))
            if not title and len(document):
                lines = [clean_text(line) for line in document[0].get_text("text").splitlines()]
                title = next((line for line in lines if 12 <= len(line) <= 300), "")
            return title, [author] if author else []
    except Exception:
        return "", []


def _validate_public_http_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ProviderError("Only public HTTP(S) URLs can be validated")
    host = parsed.hostname.casefold()
    if host == "localhost" or host.endswith(".localhost"):
        raise ProviderError("Local URLs are not eligible for validation")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ProviderError("Private or reserved network URLs are not eligible for validation")
