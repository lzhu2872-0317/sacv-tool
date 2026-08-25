import pytest

from sacv_tool.providers.base import ProviderError
from sacv_tool.providers.web import _parse_html_metadata, _validate_public_http_url, _web_candidate


def test_html_metadata_prefers_citation_fields():
    metadata = _parse_html_metadata(
        """
        <html><head>
        <title>Site title</title>
        <meta name="citation_title" content="Responsible AI Policy">
        <meta name="citation_author" content="Example University">
        <meta name="citation_publication_date" content="2024-06-01">
        </head></html>
        """
    )
    assert metadata["title"] == "Responsible AI Policy"
    assert metadata["authors"] == ["Example University"]
    assert metadata["date"] == "2024-06-01"


def test_html_metadata_falls_back_to_first_h1():
    metadata = _parse_html_metadata("<html><body><h1>Institutional AI Policy</h1></body></html>")
    assert metadata["title"] == "Institutional AI Policy"


def test_restricted_candidate_preserves_non_error_provider_state():
    candidate = _web_candidate(
        "https://example.edu/policy",
        provider="web_restricted",
        status_code=403,
        content_type="text/html",
    )
    assert candidate.provider == "web_restricted"
    assert candidate.raw["status_code"] == 403


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1/private", "http://localhost/private", "file:///etc/passwd"],
)
def test_web_validation_rejects_local_or_non_http_urls(url: str):
    with pytest.raises(ProviderError):
        _validate_public_http_url(url)
