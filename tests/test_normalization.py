from sacv_tool.normalization import extract_doi, normalized_levenshtein, normalize_doi


def test_doi_normalization():
    raw = "https://doi.org/10.1007/s10489-021-02635-5."
    assert extract_doi(raw) == "10.1007/s10489-021-02635-5"
    assert normalize_doi(raw) == "10.1007/s10489-021-02635-5"


def test_normalized_levenshtein_ignores_case_and_punctuation():
    left = "Crossref: The sustainable source of community-owned scholarly metadata"
    right = "CROSSREF - the sustainable source of community owned scholarly metadata."
    assert normalized_levenshtein(left, right) > 0.96


def test_normalized_levenshtein_rejects_unrelated_titles():
    assert normalized_levenshtein("Academic libraries and AI", "Quantum chromodynamics in dense matter") < 0.40

