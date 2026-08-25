from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    IDENTIFIER_VERIFIED_PARSE_UNCERTAIN = "identifier_verified_parse_uncertain"
    WEB_VALIDATED = "web_validated"
    GREY_LITERATURE_VALIDATED = "grey_literature_validated"
    WEB_REACHABLE = "web_reachable"
    WEB_ACCESS_RESTRICTED = "web_access_restricted"
    METADATA_MISMATCH = "metadata_mismatch"
    POTENTIAL_HALLUCINATION = "potential_hallucination"
    REVIEW = "review"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PARSE_ERROR = "parse_error"
    FLAGGED = "flagged"
    ERROR = "error"


class CitationType(StrEnum):
    SCHOLARLY = "scholarly"
    WEB_POLICY = "web_policy"
    BOOK_THESIS = "book_thesis"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class Citation:
    raw: str
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""
    url: str = ""
    citation_type: CitationType = CitationType.UNKNOWN
    parse_confidence: float = 1.0
    source_page: int | None = None
    source_end_page: int | None = None
    ordinal: int | None = None
    parse_flags: list[str] = field(default_factory=list)

    @property
    def primary_author(self) -> str:
        return self.authors[0] if self.authors else ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProviderCandidate:
    provider: str
    identifier: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""
    url: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self, include_raw: bool = False) -> dict[str, Any]:
        data = asdict(self)
        if not include_raw:
            data.pop("raw", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderCandidate":
        allowed = {name for name in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in data.items() if key in allowed})


@dataclass(slots=True)
class MatchBreakdown:
    overall: float
    title: float | None = None
    author: float | None = None
    year: float | None = None
    venue: float | None = None
    doi_exact: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class VerificationResult:
    citation: Citation
    status: VerificationStatus
    score: float
    candidate: ProviderCandidate | None = None
    breakdown: MatchBreakdown | None = None
    reasons: list[str] = field(default_factory=list)
    provider_errors: list[str] = field(default_factory=list)
    checked_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    reviewer_decision: str = "pending"
    reviewer_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        candidate = self.candidate.to_dict() if self.candidate else {}
        breakdown = self.breakdown.to_dict() if self.breakdown else {}
        return {
            "ordinal": self.citation.ordinal,
            "source_page": self.citation.source_page,
            "source_end_page": self.citation.source_end_page,
            "parse_flags": " | ".join(self.citation.parse_flags),
            "raw_citation": self.citation.raw,
            "parsed_title": self.citation.title,
            "parsed_authors": "; ".join(self.citation.authors),
            "parsed_year": self.citation.year,
            "parsed_venue": self.citation.venue,
            "parsed_doi": self.citation.doi,
            "parsed_url": self.citation.url,
            "citation_type": self.citation.citation_type.value,
            "parse_confidence": round(self.citation.parse_confidence, 4),
            "status": self.status.value,
            "score": round(self.score, 4),
            "provider": candidate.get("provider", ""),
            "matched_title": candidate.get("title", ""),
            "matched_authors": "; ".join(candidate.get("authors", [])),
            "matched_year": candidate.get("year"),
            "matched_venue": candidate.get("venue", ""),
            "matched_doi": candidate.get("doi", ""),
            "matched_url": candidate.get("url", ""),
            "title_score": _round_or_none(breakdown.get("title")),
            "author_score": _round_or_none(breakdown.get("author")),
            "year_score": _round_or_none(breakdown.get("year")),
            "venue_score": _round_or_none(breakdown.get("venue")),
            "doi_exact": breakdown.get("doi_exact"),
            "reasons": " | ".join(self.reasons),
            "provider_errors": " | ".join(self.provider_errors),
            "checked_at": self.checked_at,
            "reviewer_decision": self.reviewer_decision,
            "reviewer_note": self.reviewer_note,
        }


def _round_or_none(value: Any) -> float | None:
    return round(float(value), 4) if value is not None else None
