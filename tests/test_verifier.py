from pathlib import Path
from uuid import uuid4

import pytest

from sacv_tool.config import Settings
from sacv_tool.models import Citation, CitationType, ProviderCandidate, VerificationStatus
from sacv_tool.providers.base import MetadataProvider
from sacv_tool.verifier import CitationVerifier


class FakeProvider(MetadataProvider):
    name = "fake"

    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = 0

    async def search(self, citation):
        self.calls += 1
        return list(self.candidates)


class FailingProvider(MetadataProvider):
    name = "failing_registry"

    async def search(self, citation):
        raise RuntimeError("temporary registry outage")


@pytest.fixture
def cache_path():
    """Use one disposable file, avoiding pytest's Windows temp-directory ACL issue."""
    path = Path.cwd() / f".sacv-test-cache-{uuid4().hex}.json"
    yield path
    path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_verifier_returns_verified(cache_path: Path):
    citation = Citation(raw="x", title="Correct title", authors=["Smith, J."], year=2024, ordinal=1)
    candidate = ProviderCandidate(
        provider="fake", identifier="id", title="Correct title", authors=["Smith, Jane"], year=2024
    )
    settings = Settings(cache_path=cache_path)
    result = (await CitationVerifier(settings, [FakeProvider([candidate])]).verify_many([citation]))[0]
    assert result.status is VerificationStatus.VERIFIED


@pytest.mark.asyncio
async def test_verifier_flags_null_registry_response(cache_path: Path):
    settings = Settings(cache_path=cache_path)
    citation = Citation(raw="Fabricated (2025). Nothing.", title="Nothing", year=2025)
    result = (await CitationVerifier(settings, [FakeProvider([])]).verify_many([citation]))[0]
    assert result.status is VerificationStatus.NOT_FOUND
    assert "NO_REGISTRY_MATCH" in result.reasons


@pytest.mark.asyncio
async def test_verifier_never_verifies_year_only_evidence(cache_path: Path):
    citation = Citation(raw="Li (2025). A detailed title.", title="A detailed title", authors=["Li, W."], year=2025)
    candidate = ProviderCandidate(provider="fake", identifier="project", title="", authors=[], year=2025)
    settings = Settings(cache_path=cache_path)
    result = (await CitationVerifier(settings, [FakeProvider([candidate])]).verify_many([citation]))[0]
    assert result.status is VerificationStatus.REVIEW
    assert result.score == 0.10
    assert "INSUFFICIENT_METADATA" in result.reasons


@pytest.mark.asyncio
async def test_parse_error_is_returned_before_registry_query(cache_path: Path):
    citation = Citation(
        raw="Management, 97, Article 102997. https://doi.org/10.1016/j.ijhm.2021.102997",
        doi="10.1016/j.ijhm.2021.102997",
        parse_flags=["SPLIT_CITATION"],
    )
    provider = FakeProvider([])
    settings = Settings(cache_path=cache_path)
    result = (await CitationVerifier(settings, [provider]).verify_many([citation]))[0]
    assert result.status is VerificationStatus.PARSE_ERROR
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_doi_mismatch_is_reported_as_metadata_mismatch(cache_path: Path):
    citation = Citation(
        raw="Smith (2024). Correct title.", title="Correct title", authors=["Smith, J."], year=2024,
        doi="10.1234/submitted",
    )
    candidate = ProviderCandidate(
        provider="fake", identifier="10.1234/other", title="Correct title", authors=["Smith, Jane"],
        year=2024, doi="10.1234/other",
    )
    settings = Settings(cache_path=cache_path)
    result = (await CitationVerifier(settings, [FakeProvider([candidate])]).verify_many([citation]))[0]
    assert result.status is VerificationStatus.METADATA_MISMATCH
    assert "DOI_CONFLICT" in result.reasons


@pytest.mark.asyncio
async def test_reachable_web_source_with_matching_page_title_is_web_validated(cache_path: Path):
    citation = Citation(
        raw="Example University. (2024). Responsible AI policy. https://example.edu/policy",
        title="Responsible AI policy",
        year=2024,
        url="https://example.edu/policy",
        citation_type=CitationType.WEB_POLICY,
    )
    candidate = ProviderCandidate(
        provider="web",
        identifier="https://example.edu/policy",
        title="Responsible AI policy | Example University",
        year=2024,
        url="https://example.edu/policy",
    )
    result = (
        await CitationVerifier(
            Settings(cache_path=cache_path), [FakeProvider([candidate])]
        ).verify_many([citation])
    )[0]
    assert result.status is VerificationStatus.WEB_VALIDATED


@pytest.mark.asyncio
async def test_reachable_web_source_without_title_has_non_error_evidence_status(cache_path: Path):
    citation = Citation(
        raw="Example University. 2024. Policy. https://example.edu/policy.pdf",
        title="Policy",
        url="https://example.edu/policy.pdf",
        citation_type=CitationType.WEB_POLICY,
    )
    candidate = ProviderCandidate(
        provider="web",
        identifier=citation.url,
        title="",
        url=citation.url,
    )
    result = (
        await CitationVerifier(
            Settings(cache_path=cache_path), [FakeProvider([candidate])]
        ).verify_many([citation])
    )[0]
    assert result.status is VerificationStatus.WEB_REACHABLE


@pytest.mark.asyncio
async def test_web_403_is_access_restricted_not_provider_error(cache_path: Path):
    citation = Citation(
        raw="Example University. 2024. Policy. https://example.edu/policy",
        title="Policy",
        url="https://example.edu/policy",
        citation_type=CitationType.WEB_POLICY,
    )
    candidate = ProviderCandidate(
        provider="web_restricted",
        identifier=citation.url,
        title="",
        url=citation.url,
    )
    result = (
        await CitationVerifier(
            Settings(cache_path=cache_path), [FakeProvider([candidate])]
        ).verify_many([citation])
    )[0]
    assert result.status is VerificationStatus.WEB_ACCESS_RESTRICTED
    assert result.provider_errors == []


@pytest.mark.asyncio
async def test_two_empty_registries_can_mark_high_quality_unlinked_record_as_potential_hallucination(cache_path: Path):
    citation = Citation(
        raw="Smith, J. (2024). A detailed but unindexed article. Journal Name, 1(1), 1-9.",
        title="A detailed but unindexed article",
        authors=["Smith, J."],
        year=2024,
        citation_type=CitationType.SCHOLARLY,
        parse_confidence=0.95,
    )
    first = FakeProvider([])
    first.name = "registry_one"
    second = FakeProvider([])
    second.name = "registry_two"
    result = (
        await CitationVerifier(
            Settings(cache_path=cache_path), [first, second]
        ).verify_many([citation])
    )[0]
    assert result.status is VerificationStatus.POTENTIAL_HALLUCINATION
    assert "MULTI_REGISTRY_NO_MATCH" in result.reasons


@pytest.mark.asyncio
async def test_unrelated_search_results_from_two_registries_are_not_treated_as_real_matches(cache_path: Path):
    citation = Citation(
        raw="Smith, J. (2024). A detailed fabricated article. Journal Name, 1(1), 1-9.",
        title="A detailed fabricated article",
        authors=["Smith, J."],
        year=2024,
        citation_type=CitationType.SCHOLARLY,
        parse_confidence=0.95,
    )
    first = FakeProvider(
        [ProviderCandidate(provider="registry_one", identifier="1", title="Unrelated botany paper", authors=["Jones"])]
    )
    first.name = "registry_one"
    second = FakeProvider(
        [ProviderCandidate(provider="registry_two", identifier="2", title="Different physics study", authors=["Lee"])]
    )
    second.name = "registry_two"
    result = (
        await CitationVerifier(Settings(cache_path=cache_path), [first, second]).verify_many([citation])
    )[0]
    assert result.status is VerificationStatus.POTENTIAL_HALLUCINATION
    assert "MULTI_REGISTRY_NO_MEANINGFUL_MATCH" in result.reasons


@pytest.mark.asyncio
async def test_strongly_parsed_ghost_is_surfaced_when_second_registry_is_temporarily_down(cache_path: Path):
    citation = Citation(
        raw=(
            "Goldman, A. (2026). Bibliographic integrity in the age of LLMs: "
            "An analysis of NeurIPS 2025 proceedings. Journal of Artificial "
            "Intelligence Research, 74, 112-128."
        ),
        title="Bibliographic integrity in the age of LLMs: An analysis of NeurIPS 2025 proceedings",
        authors=["Goldman, A."],
        year=2026,
        citation_type=CitationType.SCHOLARLY,
        parse_confidence=1.0,
    )
    weak = FakeProvider(
        [
            ProviderCandidate(
                provider="registry_one",
                identifier="unrelated",
                title="Error analysis of agentic reasoning on a benchmark challenge",
                authors=["Demirhan, H."],
                year=2026,
            )
        ]
    )
    weak.name = "registry_one"
    result = (
        await CitationVerifier(Settings(cache_path=cache_path), [weak, FailingProvider()]).verify_many([citation])
    )[0]
    assert result.status is VerificationStatus.POTENTIAL_HALLUCINATION
    assert "NO_MEANINGFUL_MATCH_PARTIAL_REGISTRY_OUTAGE" in result.reasons
    assert result.provider_errors


@pytest.mark.asyncio
async def test_exact_doi_with_low_parse_confidence_is_not_blindly_verified(cache_path: Path):
    citation = Citation(
        raw="Unparsed fragment with DOI 10.1234/exact",
        title="",
        doi="10.1234/exact",
        parse_confidence=0.50,
    )
    candidate = ProviderCandidate(
        provider="fake",
        identifier="10.1234/exact",
        title="Completely different complete title",
        doi="10.1234/exact",
    )
    result = (
        await CitationVerifier(
            Settings(cache_path=cache_path), [FakeProvider([candidate])]
        ).verify_many([citation])
    )[0]
    assert result.status is VerificationStatus.IDENTIFIER_VERIFIED_PARSE_UNCERTAIN


@pytest.mark.asyncio
async def test_exact_doi_with_conflicting_parsed_title_is_not_rescued_by_author_and_year(cache_path: Path):
    citation = Citation(
        raw="Smith, J. 2024. Translated article title. Journal Name. https://doi.org/10.1234/exact",
        title="Translated article title",
        authors=["Smith, J."],
        year=2024,
        doi="10.1234/exact",
        parse_confidence=0.95,
    )
    candidate = ProviderCandidate(
        provider="fake",
        identifier="10.1234/exact",
        title="Correct complete title",
        authors=["Smith, Jane"],
        year=2024,
        doi="10.1234/exact",
    )
    result = (
        await CitationVerifier(
            Settings(cache_path=cache_path), [FakeProvider([candidate])]
        ).verify_many([citation])
    )[0]
    assert result.status is VerificationStatus.METADATA_MISMATCH
    assert "DOI_EXACT_TITLE_CONFLICT" in result.reasons


@pytest.mark.asyncio
async def test_exact_doi_with_no_parsed_title_can_use_author_and_year_corroboration(cache_path: Path):
    citation = Citation(
        raw="Smith, J. (2024). https://doi.org/10.1234/exact",
        title="",
        authors=["Smith, J."],
        year=2024,
        doi="10.1234/exact",
        parse_confidence=0.80,
    )
    candidate = ProviderCandidate(
        provider="fake",
        identifier="10.1234/exact",
        title="Correct complete title",
        authors=["Smith, Jane"],
        year=2024,
        doi="10.1234/exact",
    )
    result = (
        await CitationVerifier(
            Settings(cache_path=cache_path), [FakeProvider([candidate])]
        ).verify_many([citation])
    )[0]
    assert result.status is VerificationStatus.VERIFIED
    assert "DOI_EXACT_AUTHOR_YEAR_CORROBORATED" in result.reasons


@pytest.mark.asyncio
async def test_exact_doi_with_multiple_true_metadata_contradictions_is_mismatch(cache_path: Path):
    citation = Citation(
        raw="Smith, J. 2020. Completely different title. https://doi.org/10.1234/exact",
        title="Completely different title",
        authors=["Smith, J."],
        year=2020,
        doi="10.1234/exact",
        parse_confidence=0.95,
    )
    candidate = ProviderCandidate(
        provider="fake",
        identifier="10.1234/exact",
        title="Registry title",
        authors=["Jones, Alex"],
        year=2024,
        doi="10.1234/exact",
    )
    result = (
        await CitationVerifier(
            Settings(cache_path=cache_path), [FakeProvider([candidate])]
        ).verify_many([citation])
    )[0]
    assert result.status is VerificationStatus.METADATA_MISMATCH
    assert "DOI_EXACT_METADATA_CONFLICT" in result.reasons
