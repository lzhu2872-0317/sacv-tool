from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .matching import score_candidate
from .models import (
    Citation,
    CitationType,
    MatchBreakdown,
    ProviderCandidate,
    VerificationResult,
    VerificationStatus,
)
from .parser import parse_citation


@dataclass(slots=True)
class BenchmarkRecord:
    citation: str
    label: str
    record_id: str = ""
    target_class: str = ""
    mutation_type: str = ""
    human_validation_status: str = ""
    benchmark_split: str = ""


def load_benchmark_csv(path: str | Path) -> list[BenchmarkRecord]:
    records: list[BenchmarkRecord] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, 2):
            citation = (
                row.get("citation")
                or row.get("citation_text")
                or row.get("reference")
                or row.get("raw_citation")
                or ""
            ).strip()
            label = (row.get("label") or row.get("ground_truth") or "").strip().casefold()
            if label in {"true", "1", "genuine", "verified"}:
                label = "valid"
            elif label in {"false", "0", "fake", "ghost", "hallucinated"}:
                label = "invalid"
            if not citation or label not in {"valid", "invalid"}:
                raise ValueError(
                    f"Invalid benchmark row {row_number}: expected "
                    "citation/citation_text and label=valid|invalid"
                )
            records.append(
                BenchmarkRecord(
                    citation=citation,
                    label=label,
                    record_id=(row.get("record_id") or "").strip(),
                    target_class=(row.get("target_class") or "").strip(),
                    mutation_type=(row.get("mutation_type") or "").strip(),
                    human_validation_status=(row.get("human_validation_status") or "").strip(),
                    benchmark_split=(row.get("benchmark_split") or "").strip(),
                )
            )
    return records


def citations_from_records(records: Sequence[BenchmarkRecord]):
    return [parse_citation(record.citation, ordinal=index) for index, record in enumerate(records, 1)]


def load_and_reclassify_saved_results(
    path: str | Path, records: Sequence[BenchmarkRecord]
) -> list[VerificationResult]:
    """Replay decision rules from saved provider evidence without network calls.

    This is intended for evaluating classification-rule changes against a
    previously completed benchmark.  It refuses differently ordered input so
    labels cannot silently drift away from their predictions.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    rows = payload.get("results") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or len(rows) != len(records):
        raise ValueError("Saved results must contain one result for every benchmark row")

    results: list[VerificationResult] = []
    for ordinal, (record, row) in enumerate(zip(records, rows, strict=True), 1):
        if not isinstance(row, dict):
            raise ValueError("Saved result rows must be JSON objects")
        citation = _citation_from_saved_row(row)
        expected = parse_citation(record.citation, ordinal=ordinal)
        if citation.raw.strip() != expected.raw.strip() or citation.ordinal != ordinal:
            raise ValueError(
                f"Saved result ordinal {citation.ordinal} does not match the benchmark citation"
            )
        result = _result_from_saved_row(row, citation)
        if result.breakdown and result.breakdown.doi_exact and result.candidate:
            # Recompute component scores from the preserved provider metadata so
            # replay is governed by current matching and decision rules.
            breakdown, reasons = score_candidate(citation, result.candidate)
            from .verifier import _classify_exact_doi

            status, decision_reason = _classify_exact_doi(citation, result.candidate, breakdown)
            if status is VerificationStatus.VERIFIED:
                breakdown.overall = max(breakdown.overall, 0.95)
                reasons = [reason for reason in reasons if reason != "DOI_METADATA_MISMATCH"]
            reasons.append(decision_reason)
            result.status = status
            result.score = breakdown.overall
            result.breakdown = breakdown
            result.reasons = reasons
        results.append(result)
    return results


def calculate_metrics(
    records: Sequence[BenchmarkRecord], results: Sequence[VerificationResult]
) -> dict[str, Any]:
    if len(records) != len(results):
        raise ValueError("Benchmark records and results must have equal length")
    tp = fp = tn = fn = excluded = 0
    status_by_truth: dict[str, Counter[str]] = defaultdict(Counter)
    mutation_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "auto_accepted": 0, "needs_review": 0, "errors": 0}
    )
    for record, result in zip(records, results, strict=True):
        status_by_truth[record.label][result.status.value] += 1
        mutation = record.mutation_type or ("none" if record.label == "valid" else "unspecified")
        group = mutation_counts[mutation]
        group["total"] += 1
        if result.status is VerificationStatus.ERROR:
            excluded += 1
            group["errors"] += 1
            continue
        predicted_valid = _is_auto_accepted(result.status)
        if predicted_valid:
            group["auto_accepted"] += 1
        else:
            group["needs_review"] += 1
        actual_valid = record.label == "valid"
        if actual_valid and predicted_valid:
            tp += 1
        elif not actual_valid and predicted_valid:
            fp += 1
        elif not actual_valid and not predicted_valid:
            tn += 1
        else:
            fn += 1
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    ghost_precision = _safe_div(tn, tn + fn)
    ghost_recall = _safe_div(tn, tn + fp)
    ghost_f1 = _safe_div(2 * ghost_precision * ghost_recall, ghost_precision + ghost_recall)
    by_mutation_type: dict[str, dict[str, int | float]] = {}
    for mutation, counts in sorted(mutation_counts.items()):
        denominator = counts["total"] - counts["errors"]
        by_mutation_type[mutation] = {
            **counts,
            "auto_accept_rate": round(_safe_div(counts["auto_accepted"], denominator), 6),
            "review_rate": round(_safe_div(counts["needs_review"], denominator), 6),
        }

    valid_total = sum(record.label == "valid" for record in records)
    invalid_total = len(records) - valid_total
    return {
        "dataset_total": len(records),
        "dataset_valid": valid_total,
        "dataset_invalid": invalid_total,
        "invalid_prevalence": round(_safe_div(invalid_total, len(records)), 6),
        "tp_valid": tp,
        "fp_invalid_accepted": fp,
        "tn_invalid_flagged": tn,
        "fn_valid_flagged": fn,
        "excluded_errors": excluded,
        "precision_valid": round(precision, 6),
        "recall_valid": round(recall, 6),
        "f1_valid": round(f1, 6),
        "precision_ghost_detection": round(ghost_precision, 6),
        "recall_ghost_detection": round(ghost_recall, 6),
        "f1_ghost_detection": round(ghost_f1, 6),
        # Kept for backward compatibility.  This is the share of all evaluated
        # rows correctly flagged as invalid, not the benchmark's base rate.
        "hallucination_rate": round(_safe_div(tn, len(records) - excluded), 6),
        "correctly_flagged_invalid_share": round(_safe_div(tn, len(records) - excluded), 6),
        "status_by_ground_truth": {
            label: dict(sorted(counts.items()))
            for label, counts in sorted(status_by_truth.items())
        },
        "by_mutation_type": by_mutation_type,
    }


def write_benchmark_predictions(
    records: Sequence[BenchmarkRecord],
    results: Sequence[VerificationResult],
    output_dir: str | Path,
) -> Path:
    """Write label-aware row predictions for reproducible error analysis."""
    if len(records) != len(results):
        raise ValueError("Benchmark records and results must have equal length")
    path = Path(output_dir) / "benchmark-predictions.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "record_id",
        "label",
        "target_class",
        "mutation_type",
        "human_validation_status",
        "benchmark_split",
        "ordinal",
        "status",
        "auto_accepted",
        "correct_binary_decision",
        "score",
        "parsed_title",
        "parsed_doi",
        "matched_title",
        "matched_doi",
        "title_score",
        "author_score",
        "year_score",
        "doi_exact",
        "reasons",
        "provider_errors",
        "raw_citation",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record, result in zip(records, results, strict=True):
            result_data = result.to_dict()
            auto_accepted = _is_auto_accepted(result.status)
            expected_accepted = record.label == "valid"
            writer.writerow(
                {
                    "record_id": record.record_id,
                    "label": record.label,
                    "target_class": record.target_class,
                    "mutation_type": record.mutation_type,
                    "human_validation_status": record.human_validation_status,
                    "benchmark_split": record.benchmark_split,
                    "ordinal": result_data["ordinal"],
                    "status": result_data["status"],
                    "auto_accepted": auto_accepted,
                    "correct_binary_decision": auto_accepted == expected_accepted,
                    "score": result_data["score"],
                    "parsed_title": result_data["parsed_title"],
                    "parsed_doi": result_data["parsed_doi"],
                    "matched_title": result_data["matched_title"],
                    "matched_doi": result_data["matched_doi"],
                    "title_score": result_data["title_score"],
                    "author_score": result_data["author_score"],
                    "year_score": result_data["year_score"],
                    "doi_exact": result_data["doi_exact"],
                    "reasons": result_data["reasons"],
                    "provider_errors": result_data["provider_errors"],
                    "raw_citation": result_data["raw_citation"],
                }
            )
    return path


def _is_auto_accepted(status: VerificationStatus) -> bool:
    return status in {
        VerificationStatus.VERIFIED,
        VerificationStatus.WEB_VALIDATED,
        VerificationStatus.GREY_LITERATURE_VALIDATED,
    }


def _citation_from_saved_row(row: dict[str, Any]) -> Citation:
    citation_type_value = row.get("citation_type") or CitationType.UNKNOWN.value
    try:
        citation_type = CitationType(citation_type_value)
    except ValueError:
        citation_type = CitationType.UNKNOWN
    return Citation(
        raw=str(row.get("raw_citation") or ""),
        title=str(row.get("parsed_title") or ""),
        authors=_split_joined(row.get("parsed_authors")),
        year=_optional_int(row.get("parsed_year")),
        venue=str(row.get("parsed_venue") or ""),
        doi=str(row.get("parsed_doi") or ""),
        url=str(row.get("parsed_url") or ""),
        citation_type=citation_type,
        parse_confidence=float(row.get("parse_confidence") or 0.0),
        source_page=_optional_int(row.get("source_page")),
        source_end_page=_optional_int(row.get("source_end_page")),
        ordinal=_optional_int(row.get("ordinal")),
        parse_flags=_split_pipe(row.get("parse_flags")),
    )


def _result_from_saved_row(row: dict[str, Any], citation: Citation) -> VerificationResult:
    provider = str(row.get("provider") or "")
    candidate = None
    if provider:
        candidate = ProviderCandidate(
            provider=provider,
            identifier=str(row.get("matched_doi") or row.get("matched_url") or ""),
            title=str(row.get("matched_title") or ""),
            authors=_split_joined(row.get("matched_authors")),
            year=_optional_int(row.get("matched_year")),
            venue=str(row.get("matched_venue") or ""),
            doi=str(row.get("matched_doi") or ""),
            url=str(row.get("matched_url") or ""),
        )
    has_breakdown = any(
        row.get(name) not in {None, ""}
        for name in ("title_score", "author_score", "year_score", "venue_score", "doi_exact")
    )
    breakdown = None
    if has_breakdown:
        breakdown = MatchBreakdown(
            overall=float(row.get("score") or 0.0),
            title=_optional_float(row.get("title_score")),
            author=_optional_float(row.get("author_score")),
            year=_optional_float(row.get("year_score")),
            venue=_optional_float(row.get("venue_score")),
            doi_exact=_optional_bool(row.get("doi_exact")),
        )
    return VerificationResult(
        citation=citation,
        status=VerificationStatus(str(row.get("status") or VerificationStatus.ERROR.value)),
        score=float(row.get("score") or 0.0),
        candidate=candidate,
        breakdown=breakdown,
        reasons=_split_pipe(row.get("reasons")),
        provider_errors=_split_pipe(row.get("provider_errors")),
        checked_at=str(row.get("checked_at") or ""),
        reviewer_decision=str(row.get("reviewer_decision") or "pending"),
        reviewer_note=str(row.get("reviewer_note") or ""),
    )


def _split_joined(value: object) -> list[str]:
    return [item.strip() for item in str(value or "").split(";") if item.strip()]


def _split_pipe(value: object) -> list[str]:
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


def _optional_int(value: object) -> int | None:
    if value in {None, ""}:
        return None
    return int(value)


def _optional_float(value: object) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)


def _optional_bool(value: object) -> bool | None:
    if value in {None, ""}:
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "1", "yes"}


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0
