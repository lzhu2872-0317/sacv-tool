import shutil
from pathlib import Path
from uuid import uuid4

from sacv_tool.benchmark import (
    BenchmarkRecord,
    calculate_metrics,
    load_and_reclassify_saved_results,
    load_benchmark_csv,
    write_benchmark_predictions,
)
from sacv_tool.models import Citation, VerificationResult, VerificationStatus


def result(status: VerificationStatus) -> VerificationResult:
    return VerificationResult(citation=Citation(raw="x"), status=status, score=1.0 if status is VerificationStatus.VERIFIED else 0.0)


def test_metrics_use_unambiguous_valid_and_ghost_classes():
    records = [
        BenchmarkRecord("a", "valid"), BenchmarkRecord("b", "valid"),
        BenchmarkRecord("c", "invalid"), BenchmarkRecord("d", "invalid"),
    ]
    results = [
        result(VerificationStatus.VERIFIED), result(VerificationStatus.FLAGGED),
        result(VerificationStatus.FLAGGED), result(VerificationStatus.VERIFIED),
    ]
    metrics = calculate_metrics(records, results)
    assert metrics["tp_valid"] == 1
    assert metrics["tn_invalid_flagged"] == 1
    assert metrics["precision_valid"] == 0.5
    assert metrics["recall_ghost_detection"] == 0.5


def test_loader_accepts_full_dataset_citation_text_column():
    path = Path.cwd() / f".sacv-benchmark-schema-{uuid4().hex}.csv"
    try:
        path.write_text(
            'record_id,label,citation_text,mutation_type\n'
            'V0001,valid,"Smith, J. (2024). A real article. Journal, 1(1), 1-2.",none\n'
            'I0001,invalid,"Smith, J. (2024). An invented article. Journal, 1(1), 3-4.",total_fabrication\n',
            encoding="utf-8-sig",
        )
        records = load_benchmark_csv(path)
    finally:
        path.unlink(missing_ok=True)

    assert [record.label for record in records] == ["valid", "invalid"]
    assert records[0].citation.startswith("Smith, J. (2024). A real article")
    assert records[1].record_id == "I0001"
    assert records[1].mutation_type == "total_fabrication"


def test_metrics_expose_attack_specific_acceptance_rates():
    records = [
        BenchmarkRecord("a", "invalid", mutation_type="identifier_hijacking_title"),
        BenchmarkRecord("b", "invalid", mutation_type="identifier_hijacking_title"),
        BenchmarkRecord("c", "invalid", mutation_type="total_fabrication"),
    ]
    results = [
        result(VerificationStatus.VERIFIED),
        result(VerificationStatus.METADATA_MISMATCH),
        result(VerificationStatus.POTENTIAL_HALLUCINATION),
    ]
    metrics = calculate_metrics(records, results)
    title_attack = metrics["by_mutation_type"]["identifier_hijacking_title"]
    assert title_attack["auto_accepted"] == 1
    assert title_attack["auto_accept_rate"] == 0.5
    assert metrics["status_by_ground_truth"]["invalid"]["metadata_mismatch"] == 1


def test_prediction_export_preserves_labels_and_decisions():
    records = [
        BenchmarkRecord(
            "a",
            "invalid",
            record_id="I0001",
            mutation_type="identifier_hijacking_title",
            human_validation_status="pending_double_review",
        )
    ]
    results = [result(VerificationStatus.METADATA_MISMATCH)]
    results[0].citation.ordinal = 1
    output_dir = Path.cwd() / f".sacv-predictions-{uuid4().hex}"
    try:
        path = write_benchmark_predictions(records, results, output_dir)
        exported = path.read_text(encoding="utf-8-sig")
        assert "I0001" in exported
        assert "identifier_hijacking_title" in exported
        assert "True" in exported
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def test_saved_exact_doi_title_hijack_is_reclassified_without_network():
    citation = "Smith, J. (2024). Quantum governance in orbital cities. doi:10.1234/real"
    saved = {
        "results": [
            {
                "ordinal": 1,
                "raw_citation": citation,
                "parsed_title": "Quantum governance in orbital cities",
                "parsed_authors": "Smith, J.",
                "parsed_year": 2024,
                "parsed_doi": "10.1234/real",
                "citation_type": "scholarly",
                "parse_confidence": 1.0,
                "status": "verified",
                "score": 0.95,
                "provider": "crossref",
                "matched_title": "Marine algae diversity in coastal wetlands",
                "matched_authors": "Smith, Jane",
                "matched_year": 2024,
                "matched_doi": "10.1234/real",
                "title_score": 0.2,
                "author_score": 1.0,
                "year_score": 1.0,
                "doi_exact": True,
                "reasons": "DOI_EXACT_MATCH | DOI_EXACT_AUTHOR_YEAR_CORROBORATED",
            }
        ]
    }
    path = Path.cwd() / f".sacv-saved-results-{uuid4().hex}.json"
    try:
        path.write_text(__import__("json").dumps(saved), encoding="utf-8")
        replayed = load_and_reclassify_saved_results(
            path,
            [BenchmarkRecord(citation, "invalid", mutation_type="identifier_hijacking_title")],
        )
        assert replayed[0].status is VerificationStatus.METADATA_MISMATCH
        assert "DOI_EXACT_TITLE_CONFLICT" in replayed[0].reasons
    finally:
        path.unlink(missing_ok=True)
