from sacv_tool.matching import score_candidate
from sacv_tool.models import Citation, ProviderCandidate


def test_exact_doi_and_metadata_is_strong_match():
    citation = Citation(
        raw="x", title="A reliable title", authors=["Smith, J."], year=2024, doi="10.1234/example"
    )
    candidate = ProviderCandidate(
        provider="crossref", identifier="10.1234/example", title="A reliable title", authors=["Smith, Jane"],
        year=2024, doi="10.1234/example"
    )
    score, reasons = score_candidate(citation, candidate)
    assert score.overall >= 0.95
    assert "DOI_EXACT_MATCH" in reasons


def test_identifier_hijacking_is_capped_and_flagged():
    citation = Citation(
        raw="x", title="AI auditing in academic libraries", authors=["Thelwall, M."], year=2024,
        doi="10.6087/kcse.75"
    )
    candidate = ProviderCandidate(
        provider="crossref", identifier="10.6087/kcse.75", title="Using the Crossref Metadata API to explore publisher content",
        authors=["Lammey, Richard"], year=2016, doi="10.6087/kcse.75"
    )
    score, reasons = score_candidate(citation, candidate)
    assert score.overall <= 0.70
    assert "DOI_METADATA_MISMATCH" in reasons


def test_year_only_match_cannot_receive_a_perfect_score():
    citation = Citation(raw="x", title="A title absent from the registry record", authors=["Li, W."], year=2025)
    candidate = ProviderCandidate(provider="crossref", identifier="project", title="", authors=[], year=2025)
    score, _reasons = score_candidate(citation, candidate)
    assert score.overall == 0.10
    assert score.title is None
    assert score.author is None
