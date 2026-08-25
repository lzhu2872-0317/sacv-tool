from __future__ import annotations

from .models import Citation, MatchBreakdown, ProviderCandidate
from .normalization import best_similarity, normalize_doi, normalized_levenshtein, surname


def score_candidate(citation: Citation, candidate: ProviderCandidate) -> tuple[MatchBreakdown, list[str]]:
    title_score = normalized_levenshtein(citation.title, candidate.title) if citation.title and candidate.title else None
    author_score = _author_score(citation, candidate)
    year_score = _year_score(citation.year, candidate.year)
    venue_score = normalized_levenshtein(citation.venue, candidate.venue) if citation.venue and candidate.venue else None

    weighted = [
        (title_score, 0.65),
        (author_score, 0.20),
        (year_score, 0.10),
        (venue_score, 0.05),
    ]
    available = [(value, weight) for value, weight in weighted if value is not None]
    # Keep the original weights instead of re-normalizing the fields that happen
    # to be present. Otherwise a year-only candidate receives a misleading 1.0.
    overall = sum(float(value) * weight for value, weight in available) if available else 0.0

    citation_doi = normalize_doi(citation.doi)
    candidate_doi = normalize_doi(candidate.doi)
    doi_exact: bool | None = None
    reasons: list[str] = []
    if citation_doi:
        doi_exact = bool(candidate_doi and citation_doi == candidate_doi)
        if doi_exact:
            metadata_mismatch = (title_score is not None and title_score < 0.72) or (
                author_score is not None and author_score < 0.45
            )
            if metadata_mismatch:
                overall = min(overall, 0.70)
                reasons.append("DOI_METADATA_MISMATCH")
            else:
                overall = max(overall, 0.95)
                reasons.append("DOI_EXACT_MATCH")
        elif candidate_doi:
            overall = min(overall, 0.75)
            reasons.append("DOI_MISMATCH")

    return (
        MatchBreakdown(
            overall=round(overall, 6),
            title=title_score,
            author=author_score,
            year=year_score,
            venue=venue_score,
            doi_exact=doi_exact,
        ),
        reasons,
    )


def _author_score(citation: Citation, candidate: ProviderCandidate) -> float | None:
    if not citation.authors or not candidate.authors:
        return None
    expected = [surname(author) for author in citation.authors if surname(author)]
    actual = [surname(author) for author in candidate.authors if surname(author)]
    if not expected or not actual:
        return None
    per_author = [best_similarity(author, actual) for author in expected]
    # Primary author is the strongest signal; the mean rewards co-author agreement.
    return min(1.0, 0.6 * per_author[0] + 0.4 * (sum(per_author) / len(per_author)))


def _year_score(expected: int | None, actual: int | None) -> float | None:
    if expected is None or actual is None:
        return None
    difference = abs(expected - actual)
    if difference == 0:
        return 1.0
    if difference == 1:
        return 0.55
    return 0.0
