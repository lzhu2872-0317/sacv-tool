from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from .benchmark import (
    calculate_metrics,
    citations_from_records,
    load_and_reclassify_saved_results,
    load_benchmark_csv,
    write_benchmark_predictions,
)
from .config import Settings
from .extractor import extract_citations
from .reports import summarize, write_reports
from .verifier import CitationVerifier

app = typer.Typer(help="SACV-Tool: verify academic citations against authoritative registries.", no_args_is_help=True)
console = Console()


@app.command()
def verify(
    input_path: Annotated[Path, typer.Argument(help="PDF, TXT, or Markdown manuscript/reference list")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Report output directory")] = Path("runs/latest"),
    email: Annotated[str, typer.Option(help="Contact email for Crossref polite pool")] = "",
    threshold: Annotated[float, typer.Option(min=0.01, max=1.0)] = 0.85,
    openalex: Annotated[bool, typer.Option("--openalex/--no-openalex", help="Use OpenAlex fallback")] = True,
    pubmed: Annotated[bool, typer.Option("--pubmed/--no-pubmed", help="Use PubMed as a fallback registry")] = False,
    web_validation: Annotated[
        bool, typer.Option("--web-validation/--no-web-validation", help="Validate policy and web citations")
    ] = True,
    concurrency: Annotated[int, typer.Option(min=1, max=10)] = 3,
) -> None:
    """Extract and verify citations, then write CSV, JSON, and HTML reports."""
    citations = extract_citations(input_path)
    if not citations:
        raise typer.BadParameter("No reference entries were found. Check that the document contains a References heading.")
    output.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_env(
        email=email or None,
        threshold=threshold,
        enable_openalex=openalex,
        enable_pubmed=pubmed,
        enable_web_validation=web_validation,
        concurrency=concurrency,
        cache_path=output / ".sacv-cache.json",
    )
    with Progress() as progress:
        task = progress.add_task("Verifying citations", total=len(citations))
        verifier = CitationVerifier(settings)
        results = asyncio.run(verifier.verify_many(citations, lambda done, _total: progress.update(task, completed=done)))
    paths = write_reports(results, output)
    _print_summary(summarize(results))
    for label, path in paths.items():
        console.print(f"[bold]{label.upper()}[/bold]: {path.resolve()}")


@app.command()
def benchmark(
    dataset: Annotated[
        Path,
        typer.Argument(help="CSV with citation or citation_text and label (valid|invalid) columns"),
    ],
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("runs/benchmark"),
    email: Annotated[str, typer.Option(help="Contact email for Crossref polite pool")] = "",
    threshold: Annotated[float, typer.Option(min=0.01, max=1.0)] = 0.85,
    openalex: Annotated[bool, typer.Option("--openalex/--no-openalex")] = True,
    pubmed: Annotated[bool, typer.Option("--pubmed/--no-pubmed")] = False,
    web_validation: Annotated[bool, typer.Option("--web-validation/--no-web-validation")] = True,
    reuse_results: Annotated[
        Path | None,
        typer.Option(
            "--reuse-results",
            help="Reclassify an existing sacv-results.json without making provider requests",
        ),
    ] = None,
) -> None:
    """Run a labeled gold-standard dataset and calculate both validity and ghost-detection metrics."""
    records = load_benchmark_csv(dataset)
    output.mkdir(parents=True, exist_ok=True)
    if reuse_results is not None:
        results = load_and_reclassify_saved_results(reuse_results, records)
        console.print(f"[bold]REPLAY[/bold]: reused provider evidence from {reuse_results.resolve()}")
    else:
        citations = citations_from_records(records)
        settings = Settings.from_env(
            email=email or None,
            threshold=threshold,
            enable_openalex=openalex,
            enable_pubmed=pubmed,
            enable_web_validation=web_validation,
            cache_path=output / ".sacv-cache.json",
        )
        with Progress() as progress:
            task = progress.add_task("Running benchmark", total=len(citations))
            results = asyncio.run(CitationVerifier(settings).verify_many(citations, lambda done, _total: progress.update(task, completed=done)))
    write_reports(results, output)
    predictions_path = write_benchmark_predictions(records, results, output)
    metrics = calculate_metrics(records, results)
    metrics_path = output / "benchmark-metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    console.print_json(json.dumps(metrics))
    console.print(f"[bold]METRICS[/bold]: {metrics_path.resolve()}")
    console.print(f"[bold]PREDICTIONS[/bold]: {predictions_path.resolve()}")


@app.command()
def serve(
    port: Annotated[int, typer.Option(min=1024, max=65535)] = 8501,
) -> None:
    """Start the local Streamlit web interface."""
    webapp = Path(__file__).with_name("webapp.py")
    command = [
        sys.executable, "-m", "streamlit", "run", str(webapp),
        "--server.port", str(port),
        "--server.address", "127.0.0.1",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    raise typer.Exit(subprocess.call(command))


def _print_summary(summary: dict) -> None:
    table = Table(title="SACV Audit Summary")
    columns = (
        "total",
        "auto_confirmed",
        "verified",
        "web_validated",
        "grey_literature_validated",
        "web_reachable",
        "web_access_restricted",
        "identifier_verified_parse_uncertain",
        "review",
        "not_found",
        "metadata_mismatch",
        "potential_hallucination",
        "parse_error",
        "error",
    )
    for column in columns:
        table.add_column(column.replace("_", " ").title(), justify="right")
    table.add_row(*(str(summary[column]) for column in columns))
    console.print(table)
