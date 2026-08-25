from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Callable, Sequence

from .cache import JsonCache
from .config import Settings
from .matching import score_candidate
from .models import (
    Citation,
    CitationType,
    MatchBreakdown,
    ProviderCandidate,
    VerificationResult,
    VerificationStatus,
)
from .normalization import normalize_text
from .parser import has_fatal_parse_flag
from .providers import CrossrefProvider, MetadataProvider, OpenAlexProvider, PubMedProvider, WebProvider

ProgressCallback = Callable[[int, int], None]


class CitationVerifier:
    def __init__(self, settings: Settings, providers: Sequence[MetadataProvider] | None = None):
        self.settings = settings
        self.cache = JsonCache(settings.cache_path)
        self._owns_providers = providers is None
        if providers is None:
            built: list[MetadataProvider] = [CrossrefProvider(settings)]
            if settings.enable_openalex:
                built.append(OpenAlexProvider(settings))
            if settings.enable_pubmed:
                built.append(PubMedProvider(settings))
            if settings.enable_web_validation:
                built.append(WebProvider(settings))
            self.providers = built
        else:
            # Explicit providers are mainly used by deterministic tests and
            # integrations; keep their caller-selected order and do not reroute.
            self.providers = list(providers)

    async def verify_many(
        self, citations: Sequence[Citation], progress: ProgressCallback | None = None
    ) -> list[VerificationResult]:
        semaphore = asyncio.Semaphore(self.settings.concurrency)
        completed = 0
        completed_lock = asyncio.Lock()

        async def run_one(citation: Citation) -> VerificationResult:
            nonlocal completed
            async with semaphore:
                result = await self.verify_one(citation)
            async with completed_lock:
                completed += 1
                if progress:
                    progress(completed, len(citations))
                # Long benchmarks should remain resumable even if the terminal
                # closes or the network is interrupted before all rows finish.
                if completed % 25 == 0:
                    self.cache.save()
            return result

        try:
            results = await asyncio.gather(*(run_one(citation) for citation in citations))
            return list(results)
        finally:
            self.cache.save()
            if self._owns_providers:
                await asyncio.gather(*(provider.aclose() for provider in self.providers), return_exceptions=True)

    async def verify_one(self, citation: Citation) -> VerificationResult:
        if has_fatal_parse_flag(citation):
            return VerificationResult(
                citation=citation,
                status=VerificationStatus.PARSE_ERROR,
                score=0.0,
                reasons=[flag for flag in citation.parse_flags if not flag.endswith("_REPAIRED")],
            )

        all_candidates: list[ProviderCandidate] = []
        errors: list[str] = []
        queried = 0
        selected_providers = self._providers_for(citation)

        for index, provider in enumerate(selected_providers):
            cache_key = _cache_key(provider.name, citation)
            cached = self.cache.get(cache_key)
            if isinstance(cached, list):
                candidates = [ProviderCandidate.from_dict(item) for item in cached if isinstance(item, dict)]
                queried += 1
            else:
                try:
                    candidates = await provider.search(citation)
                    queried += 1
                    self.cache.set(cache_key, [candidate.to_dict(include_raw=False) for candidate in candidates])
                except Exception as exc:  # one source failure must not abort an audit
                    errors.append(f"{provider.name}: {type(exc).__name__}: {exc}")
                    candidates = []
            all_candidates.extend(candidates)

            # Crossref is the first scholarly source. Avoid unnecessary fallback
            # calls after it already produced strong evidence.
            if index == 0 and candidates:
                best_so_far = max(score_candidate(citation, candidate)[0].overall for candidate in candidates)
                if best_so_far >= self.settings.threshold:
                    break

        if not all_candidates:
            status = _classify_no_match(
                citation,
                queried=queried,
                provider_count=len(selected_providers),
                error_count=len(errors),
            )
            reason = "PROVIDER_ERROR" if status is VerificationStatus.ERROR else "NO_REGISTRY_MATCH"
            if citation.doi:
                reason += " | DOI_NOT_FOUND"
            elif citation.url:
                reason += " | URL_NOT_VALIDATED"
            elif _likely_coverage_gap(citation):
                reason += " | COVERAGE_GAP"
            if status is VerificationStatus.POTENTIAL_HALLUCINATION:
                reason += " | MULTI_REGISTRY_NO_MATCH"
            return VerificationResult(
                citation=citation,
                status=status,
                score=0.0,
                reasons=reason.split(" | "),
                provider_errors=errors,
            )

        ranked: list[tuple[float, ProviderCandidate, MatchBreakdown, list[str]]] = []
        for candidate in all_candidates:
            breakdown, match_reasons = score_candidate(citation, candidate)
            ranked.append((breakdown.overall, candidate, breakdown, match_reasons))
        score, candidate, breakdown, reasons = max(ranked, key=lambda item: item[0])

        hallucination_reason = _potential_hallucination_reason(
            citation,
            breakdown=breakdown,
            queried=queried,
            provider_count=len(selected_providers),
            error_count=len(errors),
        )
        if hallucination_reason:
            status, decision_reason = (
                VerificationStatus.POTENTIAL_HALLUCINATION,
                hallucination_reason,
            )
        else:
            status, decision_reason = _classify_match(
                score=score,
                breakdown=breakdown,
                reasons=reasons,
                threshold=self.settings.threshold,
                review_margin=self.settings.review_margin,
                citation=citation,
                candidate=candidate,
            )
        if status is VerificationStatus.VERIFIED and breakdown.doi_exact:
            # An exact identifier with independent descriptive corroboration is
            # strong evidence even when the field parser originally depressed
            # the weighted title score.
            score = max(score, 0.95)
            breakdown.overall = score
            if decision_reason != "DOI_EXACT_METADATA_CONFLICT":
                reasons = [reason for reason in reasons if reason != "DOI_METADATA_MISMATCH"]
        if decision_reason:
            reasons.append(decision_reason)

        return VerificationResult(
            citation=citation,
            status=status,
            score=score,
            candidate=candidate,
            breakdown=breakdown,
            reasons=reasons,
            provider_errors=errors,
        )

    def _providers_for(self, citation: Citation) -> list[MetadataProvider]:
        if not self._owns_providers:
            return list(self.providers)
        providers = {provider.name: provider for provider in self.providers}
        if citation.citation_type is CitationType.WEB_POLICY:
            names = ["web"]
        elif citation.citation_type is CitationType.BOOK_THESIS:
            names = ["crossref", "openalex"] + (["web"] if citation.url else [])
        elif citation.citation_type is CitationType.SCHOLARLY:
            names = ["crossref", "openalex", "pubmed"]
        else:
            names = ["crossref", "openalex"] + (["web"] if citation.url else [])
        return [providers[name] for name in names if name in providers]


def _cache_key(provider_name: str, citation: Citation) -> str:
    identity = citation.doi or citation.url or citation.title or citation.raw
    digest = hashlib.sha256(normalize_text(identity).encode("utf-8")).hexdigest()
    return f"{provider_name}:{digest}"


def _classify_match(
    *,
    score: float,
    breakdown: MatchBreakdown,
    reasons: list[str],
    threshold: float,
    review_margin: float,
    citation: Citation,
    candidate: ProviderCandidate,
) -> tuple[VerificationStatus, str]:
    if candidate.provider == "web_restricted":
        return VerificationStatus.WEB_ACCESS_RESTRICTED, "WEB_SERVER_ACCESS_RESTRICTED"

    if candidate.provider == "web":
        cited_title = normalize_text(citation.title)
        page_title = normalize_text(candidate.title)
        title_matches = bool(
            (breakdown.title is not None and breakdown.title >= 0.60)
            or (cited_title and page_title and cited_title in page_title)
        )
        if title_matches and citation.parse_confidence >= 0.70:
            if citation.citation_type is CitationType.BOOK_THESIS:
                return VerificationStatus.GREY_LITERATURE_VALIDATED, "OFFICIAL_URL_AND_TITLE_MATCH"
            return VerificationStatus.WEB_VALIDATED, "WEB_URL_AND_TITLE_MATCH"
        return VerificationStatus.WEB_REACHABLE, "URL_REACHABLE_METADATA_UNAVAILABLE"

    if "DOI_MISMATCH" in reasons and not breakdown.doi_exact:
        return VerificationStatus.METADATA_MISMATCH, "DOI_CONFLICT"

    metadata_evidence = sum(
        value is not None for value in (breakdown.title, breakdown.author, breakdown.year, breakdown.venue)
    )
    if breakdown.doi_exact:
        return _classify_exact_doi(citation, candidate, breakdown)

    if breakdown.title is None or metadata_evidence < 2:
        return VerificationStatus.REVIEW, "INSUFFICIENT_METADATA"

    corroborating = (breakdown.author is not None and breakdown.author >= 0.55) or (
        breakdown.year is not None and breakdown.year >= 0.55
    )
    if breakdown.title >= 0.85 and corroborating and score >= threshold:
        return VerificationStatus.VERIFIED, "VERIFIED_METADATA"
    if score >= threshold - review_margin:
        return VerificationStatus.REVIEW, "BORDERLINE_MATCH"
    if breakdown.title < 0.45 and breakdown.author is not None and breakdown.author < 0.45:
        # Without an identifier, a weak fuzzy search result is not proof that
        # the citation conflicts with that unrelated record.  Hallucination
        # escalation is handled above when registry coverage is sufficient;
        # otherwise retain it for review instead of inventing a conflict.
        return VerificationStatus.REVIEW, "WEAK_REGISTRY_CANDIDATE"
    return VerificationStatus.REVIEW, "SCORE_BELOW_THRESHOLD"


def _classify_exact_doi(
    citation: Citation,
    candidate: ProviderCandidate,
    breakdown: MatchBreakdown,
) -> tuple[VerificationStatus, str]:
    raw_text = normalize_text(citation.raw)
    registry_title = normalize_text(candidate.title)
    raw_title_match = bool(registry_title and registry_title in raw_text)
    author_year_match = bool(
        breakdown.author is not None
        and breakdown.author >= 0.75
        and breakdown.year is not None
        and breakdown.year >= 0.55
    )
    title_corroborated = bool(
        breakdown.title is not None
        and breakdown.title >= 0.72
        and (
            (breakdown.author is not None and breakdown.author >= 0.55)
            or (breakdown.year is not None and breakdown.year >= 0.55)
        )
    )
    if raw_title_match:
        return VerificationStatus.VERIFIED, "DOI_EXACT_RAW_TITLE_CORROBORATED"
    if title_corroborated:
        return VerificationStatus.VERIFIED, "VERIFIED_IDENTIFIER_AND_METADATA"

    contradictions = sum(
        (
            breakdown.title is not None and breakdown.title < 0.35,
            breakdown.author is not None and breakdown.author < 0.35,
            breakdown.year is not None and breakdown.year == 0.0,
        )
    )
    if citation.parse_confidence >= 0.85 and contradictions >= 2:
        return VerificationStatus.METADATA_MISMATCH, "DOI_EXACT_METADATA_CONFLICT"

    # Identifier hijacking can preserve a real DOI, author and year while
    # replacing only the article title.  A high-quality parsed title that is
    # strongly inconsistent with the DOI registry record must therefore take
    # precedence over author/year agreement.
    if (
        breakdown.title is not None
        and breakdown.title < 0.45
        and citation.parse_confidence >= 0.85
    ):
        return VerificationStatus.METADATA_MISMATCH, "DOI_EXACT_TITLE_CONFLICT"
    # Author + year can rescue a DOI record only when no usable title was
    # parsed.  If a title exists but is merely borderline, retain human review.
    if breakdown.title is None and author_year_match:
        return VerificationStatus.VERIFIED, "DOI_EXACT_AUTHOR_YEAR_CORROBORATED"

    return VerificationStatus.IDENTIFIER_VERIFIED_PARSE_UNCERTAIN, "DOI_EXACT_PARSE_UNCERTAIN"


def _classify_no_match(
    citation: Citation, *, queried: int, provider_count: int, error_count: int
) -> VerificationStatus:
    if provider_count > 0 and error_count == provider_count:
        return VerificationStatus.ERROR
    if (
        queried >= 2
        and not citation.doi
        and not citation.url
        and citation.parse_confidence >= 0.85
        and citation.citation_type in {CitationType.SCHOLARLY, CitationType.UNKNOWN}
    ):
        return VerificationStatus.POTENTIAL_HALLUCINATION
    return VerificationStatus.NOT_FOUND


def _potential_hallucination_reason(
    citation: Citation,
    *,
    breakdown: MatchBreakdown,
    queried: int,
    provider_count: int,
    error_count: int,
) -> str:
    if (
        citation.doi
        or citation.url
        or citation.parse_confidence < 0.85
        or citation.citation_type not in {CitationType.SCHOLARLY, CitationType.UNKNOWN}
    ):
        return ""
    # Search APIs almost always return *something*.  A low-ranked record with
    # only the same publication year is still no meaningful bibliographic hit.
    title_absent = breakdown.title is None or breakdown.title < 0.45
    author_absent = breakdown.author is None or breakdown.author < 0.45
    if not (title_absent and author_absent):
        return ""
    if queried >= 2:
        return "MULTI_REGISTRY_NO_MEANINGFUL_MATCH"
    # Recall is the safety-critical objective.  If one registry produced only
    # an unrelated hit while another configured registry was temporarily down,
    # surface a *potential* hallucination with the outage explicitly recorded.
    # The stricter parse threshold protects low-quality and grey-literature data.
    if queried >= 1 and provider_count >= 2 and error_count >= 1 and citation.parse_confidence >= 0.90:
        return "NO_MEANINGFUL_MATCH_PARTIAL_REGISTRY_OUTAGE"
    return ""


def _likely_coverage_gap(citation: Citation) -> bool:
    raw = citation.raw
    return bool(
        re.search(r"[\u3400-\u9fff]", raw)
        or re.search(
            r"\b(?:thesis|dissertation|report|white\s+paper|working\s+paper|cnki|cctv)\b",
            raw,
            re.IGNORECASE,
        )
        or (re.search(r"https?://", raw, re.IGNORECASE) and not citation.doi)
    )
