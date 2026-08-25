from __future__ import annotations

import csv
import html
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from .models import VerificationResult


def summarize(results: Sequence[VerificationResult]) -> dict[str, Any]:
    counts = Counter(result.status.value for result in results)
    total = len(results)
    auto_confirmed = (
        counts.get("verified", 0)
        + counts.get("web_validated", 0)
        + counts.get("grey_literature_validated", 0)
    )
    return {
        "total": total,
        "auto_confirmed": auto_confirmed,
        "verified": counts.get("verified", 0),
        "web_validated": counts.get("web_validated", 0),
        "grey_literature_validated": counts.get("grey_literature_validated", 0),
        "web_reachable": counts.get("web_reachable", 0),
        "web_access_restricted": counts.get("web_access_restricted", 0),
        "identifier_verified_parse_uncertain": counts.get("identifier_verified_parse_uncertain", 0),
        "review": counts.get("review", 0),
        "not_found": counts.get("not_found", 0),
        "metadata_mismatch": counts.get("metadata_mismatch", 0),
        "potential_hallucination": counts.get("potential_hallucination", 0),
        "conflict": counts.get("conflict", 0),
        "parse_error": counts.get("parse_error", 0),
        "flagged": counts.get("flagged", 0),
        "error": counts.get("error", 0),
        "needs_action": total - auto_confirmed,
        "verified_rate": round(auto_confirmed / total, 4)
        if total
        else 0.0,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def write_reports(results: Sequence[VerificationResult], output_dir: str | Path) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [result.to_dict() for result in results]
    summary = summarize(results)

    csv_path = output_dir / "sacv-results.csv"
    json_path = output_dir / "sacv-results.json"
    html_path = output_dir / "sacv-report.html"

    if rows:
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("", encoding="utf-8")
    json_path.write_text(json.dumps({"summary": summary, "results": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(build_html_report(results), encoding="utf-8")
    return {"csv": csv_path, "json": json_path, "html": html_path}


def build_html_report(results: Sequence[VerificationResult]) -> str:
    summary = summarize(results)
    table_rows = []
    for result in results:
        row = result.to_dict()
        status = html.escape(str(row["status"]))
        table_rows.append(
            "<tr>"
            f'<td>{row.get("ordinal") or ""}</td>'
            f'<td><span class="status {status}">{status.upper()}</span></td>'
            f'<td>{float(row["score"]):.3f}</td>'
            f'<td>{html.escape(str(row["raw_citation"]))}</td>'
            f'<td>{html.escape(str(row["matched_title"]))}</td>'
            f'<td>{html.escape(str(row["matched_doi"]))}</td>'
            f'<td>{html.escape(str(row["reasons"]))}</td>'
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SACV-Tool Audit Report</title>
<style>
:root{{--ink:#14213d;--muted:#667085;--line:#e4e7ec;--green:#067647;--amber:#b54708;--red:#b42318;--blue:#175cd3}}
body{{font-family:Inter,Segoe UI,Arial,sans-serif;margin:0;background:#f8fafc;color:var(--ink)}}
.wrap{{max-width:1280px;margin:36px auto;padding:0 24px}} h1{{margin-bottom:4px}} .subtitle{{color:var(--muted)}}
  .cards{{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:14px;margin:24px 0}}
.card{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px;box-shadow:0 1px 2px #1018280d}}
.card b{{display:block;font-size:30px;margin-top:5px}} table{{width:100%;border-collapse:collapse;background:white;font-size:13px}}
th,td{{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid var(--line)}} th{{background:#f2f4f7;position:sticky;top:0}}
  .status{{font-weight:700;font-size:11px;padding:4px 7px;border-radius:999px}} .verified,.web_validated,.grey_literature_validated{{color:var(--green);background:#ecfdf3}}
  .review,.not_found,.identifier_verified_parse_uncertain,.web_reachable,.web_access_restricted{{color:var(--amber);background:#fffaeb}} .conflict,.flagged,.metadata_mismatch,.potential_hallucination{{color:var(--red);background:#fef3f2}}
  .parse_error,.error{{color:var(--blue);background:#eff8ff}} .table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:12px}}
@media(max-width:700px){{.cards{{grid-template-columns:1fr 1fr}}}}
</style></head><body><main class="wrap"><h1>SACV-Tool Audit Report</h1><p class="subtitle">Semi-automated output: records outside Auto-confirmed require human review.</p>
  <section class="cards"><div class="card">Total<b>{summary['total']}</b></div><div class="card">Auto-confirmed<b>{summary['auto_confirmed']}</b></div><div class="card">Scholarly verified<b>{summary['verified']}</b></div>
  <div class="card">Web / grey validated<b>{summary['web_validated'] + summary['grey_literature_validated']}</b></div>
  <div class="card">Web reachable / restricted<b>{summary['web_reachable'] + summary['web_access_restricted']}</b></div><div class="card">Review / parse uncertain<b>{summary['review'] + summary['identifier_verified_parse_uncertain']}</b></div>
  <div class="card">Not found<b>{summary['not_found']}</b></div><div class="card">Metadata mismatch<b>{summary['metadata_mismatch']}</b></div>
  <div class="card">Potential hallucination<b>{summary['potential_hallucination']}</b></div>
  <div class="card">Parse / provider error<b>{summary['parse_error'] + summary['error']}</b></div></section>
<div class="table-wrap"><table><thead><tr><th>#</th><th>Status</th><th>Score</th><th>Submitted citation</th><th>Best registry title</th><th>DOI</th><th>Reason</th></tr></thead>
<tbody>{''.join(table_rows)}</tbody></table></div></main></body></html>"""
