from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

import streamlit as st

from sacv_tool.config import Settings
from sacv_tool.extractor import extract_citations
from sacv_tool.reports import build_html_report, summarize
from sacv_tool.verifier import CitationVerifier


st.set_page_config(
    page_title="SACV-Tool | Citation Veracity Audit",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)


STATUS_LABELS = {
    "verified": "Scholarly verified",
    "web_validated": "Web validated",
    "grey_literature_validated": "Grey literature validated",
    "web_reachable": "Web reachable",
    "web_access_restricted": "Web access restricted",
    "identifier_verified_parse_uncertain": "Identifier verified · parse uncertain",
    "review": "Human review",
    "not_found": "Not found",
    "metadata_mismatch": "Metadata mismatch",
    "potential_hallucination": "Potential hallucination",
    "parse_error": "Parse error",
    "error": "Provider error",
    "conflict": "Conflict (legacy)",
    "flagged": "Flagged (legacy)",
}

STATUS_GROUPS = {
    "Confirmed": {"verified", "web_validated", "grey_literature_validated"},
    "Review": {
        "web_reachable",
        "web_access_restricted",
        "identifier_verified_parse_uncertain",
        "review",
        "not_found",
    },
    "Conflict": {"metadata_mismatch", "potential_hallucination", "conflict", "flagged"},
    "Technical": {"parse_error", "error"},
}


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --sacv-navy: #12213f;
            --sacv-blue: #356ae6;
            --sacv-ink: #172033;
            --sacv-muted: #65708a;
            --sacv-line: #e3e8f2;
        }
        .stApp { background: #f6f8fc; color: var(--sacv-ink); }
        [data-testid="stHeader"] { background: rgba(246, 248, 252, .82); }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #101d37 0%, #17294b 100%);
            border-right: 0;
        }
        [data-testid="stSidebar"] * { color: #f8faff; }
        [data-testid="stSidebar"] [data-baseweb="slider"] div { color: #8fb0ff; }
        [data-testid="stSidebar"] .stTextInput input { color: #172033; background: #ffffff; }
        [data-testid="stSidebar"] [data-testid="stExpander"] {
            background: rgba(255,255,255,.065); border: 1px solid rgba(255,255,255,.14);
        }
        [data-testid="stSidebar"] [data-testid="stExpander"] summary { color: #f8faff; }
        [data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.15); }
        .block-container { max-width: 1440px; padding-top: 1.4rem; padding-bottom: 3rem; }
        .sacv-brand { display:flex; gap:.75rem; align-items:center; padding:.25rem 0 1rem; }
        .sacv-brand-mark {
            display:grid; place-items:center; width:42px; height:42px; border-radius:13px;
            background:linear-gradient(135deg,#5f8cff,#35d0c7); color:#071329;
            font-weight:900; box-shadow:0 10px 24px rgba(45,107,230,.28);
        }
        .sacv-brand-name { font-size:1.1rem; font-weight:800; letter-spacing:.01em; }
        .sacv-brand-sub { font-size:.72rem; opacity:.68; margin-top:.08rem; }
        .sacv-hero {
            position:relative; overflow:hidden; padding:2.2rem 2.35rem; border-radius:24px;
            background:linear-gradient(123deg,#11203e 0%,#1b3a70 62%,#176b75 120%);
            color:#fff; box-shadow:0 18px 45px rgba(24,45,86,.16); margin-bottom:1.35rem;
        }
        .sacv-hero:after {
            content:""; position:absolute; width:280px; height:280px; right:-70px; top:-135px;
            border-radius:50%; border:52px solid rgba(126,231,221,.11);
        }
        .sacv-eyebrow { font-size:.78rem; font-weight:750; letter-spacing:.13em; color:#8fe4dd; }
        .sacv-hero h1 { color:#fff; font-size:2.55rem; line-height:1.08; margin:.55rem 0 .65rem; }
        .sacv-hero p { max-width:760px; color:#d9e4f8; font-size:1.02rem; margin:0; }
        .sacv-chip-row { display:flex; flex-wrap:wrap; gap:.55rem; margin-top:1.3rem; }
        .sacv-chip {
            padding:.38rem .72rem; border:1px solid rgba(255,255,255,.16); border-radius:999px;
            background:rgba(255,255,255,.08); color:#edf5ff; font-size:.76rem; font-weight:650;
        }
        .sacv-section-title { font-size:1.22rem; font-weight:780; color:var(--sacv-navy); margin:.2rem 0 .25rem; }
        .sacv-section-note { color:var(--sacv-muted); font-size:.88rem; margin-bottom:.85rem; }
        [data-testid="stFileUploaderDropzone"] {
            border:1.5px dashed #a9b9dc; border-radius:17px; background:#fff;
            padding:1.15rem; box-shadow:0 4px 14px rgba(32,54,98,.04);
        }
        [data-testid="stMetric"] {
            background:#fff; border:1px solid var(--sacv-line); border-radius:16px;
            padding:1.05rem 1.1rem; box-shadow:0 7px 20px rgba(24,45,86,.055);
        }
        [data-testid="stMetricLabel"] { color:#68758e; }
        [data-testid="stMetricValue"] { color:var(--sacv-navy); font-weight:780; }
        .sacv-callout {
            border:1px solid #dce4f2; background:#fff; border-radius:15px; padding:1rem 1.1rem;
            color:#4e5c76; font-size:.88rem; box-shadow:0 4px 16px rgba(24,45,86,.04);
        }
        .sacv-callout strong { color:var(--sacv-navy); }
        .sacv-legend { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.7rem; margin:.4rem 0 1.2rem; }
        .sacv-legend-item { background:#fff; border:1px solid var(--sacv-line); border-radius:13px; padding:.85rem; }
        .sacv-dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:.4rem; }
        .sacv-legend-item b { color:var(--sacv-navy); font-size:.88rem; }
        .sacv-legend-item small { display:block; color:#758097; margin:.3rem 0 0 1.18rem; line-height:1.35; }
        .sacv-footer { text-align:center; color:#7b8598; font-size:.78rem; padding:2rem 0 .4rem; }
        .stTabs [data-baseweb="tab-list"] { gap:.35rem; border-bottom:1px solid var(--sacv-line); }
        .stTabs [data-baseweb="tab"] { border-radius:10px 10px 0 0; padding:.7rem 1rem; font-weight:650; }
        .stButton > button[kind="primary"] {
            border:0; border-radius:11px; font-weight:720;
            background:linear-gradient(100deg,#356ae6,#248ca7); box-shadow:0 7px 18px rgba(53,106,230,.22);
        }
        .stDownloadButton > button { border-radius:11px; border-color:#ccd6e9; background:#fff; }
        @media (max-width: 900px) {
            .sacv-hero { padding:1.55rem; border-radius:18px; }
            .sacv-hero h1 { font-size:2rem; }
            .sacv-legend { grid-template-columns:1fr 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar() -> dict[str, object]:
    with st.sidebar:
        st.markdown(
            """
            <div class="sacv-brand">
              <div class="sacv-brand-mark">S</div>
              <div><div class="sacv-brand-name">SACV-Tool</div>
              <div class="sacv-brand-sub">EVIDENCE-LED CITATION AUDIT</div></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("### Audit configuration")
        email = st.text_input(
            "Contact email",
            placeholder="Configured securely on cloud" if os.getenv("SACV_EMAIL") else "name@example.com",
            help="Used only in registry request headers. A cloud secret is used when this field is empty.",
        )
        if os.getenv("SACV_EMAIL") and not email:
            st.caption("✓ Registry contact is configured securely")
        threshold = st.slider("Verification threshold", 0.50, 1.00, 0.85, 0.01)
        review_margin = st.slider("Human-review margin", 0.01, 0.25, 0.08, 0.01)
        concurrency = st.slider("Concurrent citations", 1, 3, 3)
        with st.expander("Data sources", expanded=True):
            use_openalex = st.checkbox("OpenAlex fallback", value=True)
            use_pubmed = st.checkbox("PubMed fallback", value=False)
            use_web_validation = st.checkbox("Policy & web validation", value=True)
        st.divider()
        st.markdown("**How decisions are made**")
        st.caption(
            "DOI evidence is checked first. Records without a DOI use title, author, year and venue evidence. "
            "A database miss never becomes an automatic misconduct decision."
        )
        st.caption("Version 1.2.5 · Research prototype")
    return {
        "email": email,
        "threshold": threshold,
        "review_margin": review_margin,
        "concurrency": concurrency,
        "enable_openalex": use_openalex,
        "enable_pubmed": use_pubmed,
        "enable_web_validation": use_web_validation,
    }


def _render_hero() -> None:
    st.markdown(
        """
        <section class="sacv-hero">
          <div class="sacv-eyebrow">SEMI-AUTOMATED CITATION VERACITY</div>
          <h1>Audit references with<br>traceable evidence.</h1>
          <p>Extract citations, cross-check scholarly registries and web sources, then review every uncertain decision before export.</p>
          <div class="sacv-chip-row">
            <span class="sacv-chip">Crossref</span><span class="sacv-chip">OpenAlex</span>
            <span class="sacv-chip">PubMed optional</span><span class="sacv-chip">Human-in-the-loop</span>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_uploader(options: dict[str, object]) -> None:
    heading, action = st.columns([3, 1], vertical_alignment="bottom")
    with heading:
        st.markdown('<div class="sacv-section-title">Start a new audit</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="sacv-section-note">Upload a searchable PDF or a plain-text reference list. Maximum one file per audit.</div>',
            unsafe_allow_html=True,
        )
    with action:
        if st.session_state.get("sacv_results") and st.button("Clear current audit", width="stretch"):
            st.session_state.pop("sacv_results", None)
            st.session_state.pop("sacv_filename", None)
            st.rerun()

    uploaded = st.file_uploader(
        "Source document",
        type=["pdf", "txt", "md"],
        label_visibility="collapsed",
        help="Scanned PDFs must be OCR-processed before upload.",
    )
    run_clicked = st.button(
        "Run citation audit",
        type="primary",
        icon="▶",
        disabled=uploaded is None,
        width="stretch",
    )
    st.caption(
        "Privacy note: the uploaded file is processed in a temporary session directory. Parsed citation metadata is sent to the selected external registries."
    )
    if not (run_clicked and uploaded is not None):
        return

    with tempfile.TemporaryDirectory(prefix="sacv-") as temp_dir:
        input_path = Path(temp_dir) / uploaded.name
        input_path.write_bytes(uploaded.getvalue())
        with st.status("Preparing citation audit…", expanded=True) as audit_status:
            try:
                st.write("Extracting and reconstructing the reference list")
                citations = extract_citations(input_path)
            except Exception as exc:
                audit_status.update(label="Input could not be read", state="error")
                st.error(f"Unable to read input: {exc}")
                st.stop()
            if not citations:
                audit_status.update(label="No citations found", state="error")
                st.error("Add a References/Bibliography heading or upload a plain reference list.")
                st.stop()

            st.write(f"Found **{len(citations)}** reconstructed citations")
            progress = st.progress(0.0, text="Connecting to evidence sources")
            settings = Settings.from_env(
                email=options["email"] or None,
                threshold=options["threshold"],
                review_margin=options["review_margin"],
                enable_openalex=options["enable_openalex"],
                enable_pubmed=options["enable_pubmed"],
                enable_web_validation=options["enable_web_validation"],
                concurrency=options["concurrency"],
                cache_path=Path(temp_dir) / ".sacv-cache.json",
            )

            def update(done: int, total: int) -> None:
                progress.progress(done / total, text=f"Cross-checking evidence · {done}/{total}")

            try:
                results = asyncio.run(CitationVerifier(settings).verify_many(citations, update))
            except Exception as exc:
                audit_status.update(label="Audit interrupted", state="error")
                st.error(f"Audit failed: {type(exc).__name__}: {exc}")
                st.stop()
            progress.empty()
            st.session_state["sacv_results"] = results
            st.session_state["sacv_filename"] = uploaded.name
            audit_status.update(label=f"Audit complete · {len(results)} citations", state="complete", expanded=False)


def _render_overview(results: list, summary: dict[str, object]) -> None:
    rate = float(summary["verified_rate"])
    total = int(summary["total"])
    review_count = int(summary["needs_action"])
    conflict_count = int(summary["metadata_mismatch"]) + int(summary["potential_hallucination"])
    technical_count = int(summary["parse_error"]) + int(summary["error"])

    cols = st.columns(5)
    cols[0].metric("Total citations", total)
    cols[1].metric("Auto-confirmed", int(summary["auto_confirmed"]), f"{rate:.1%} of total")
    cols[2].metric("Needs review", review_count)
    cols[3].metric("Evidence conflicts", conflict_count)
    cols[4].metric("Technical issues", technical_count)

    st.markdown("#### Audit completion profile")
    st.progress(rate, text=f"{rate:.1%} supported strongly enough for automatic confirmation")
    st.caption("Auto-confirmed combines scholarly, web and grey-literature records with sufficient matching evidence.")

    st.markdown(
        """
        <div class="sacv-legend">
          <div class="sacv-legend-item"><b><span class="sacv-dot" style="background:#1b9a67"></span>Confirmed</b><small>Evidence supports the citation.</small></div>
          <div class="sacv-legend-item"><b><span class="sacv-dot" style="background:#e8a020"></span>Review</b><small>Coverage or evidence is incomplete.</small></div>
          <div class="sacv-legend-item"><b><span class="sacv-dot" style="background:#df5b61"></span>Conflict</b><small>Metadata requires close inspection.</small></div>
          <div class="sacv-legend-item"><b><span class="sacv-dot" style="background:#6684c2"></span>Technical</b><small>Parsing or provider interruption.</small></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    statuses = Counter(result.status.value for result in results)
    group_counts = {
        group: sum(statuses.get(status, 0) for status in members)
        for group, members in STATUS_GROUPS.items()
    }
    st.bar_chart(group_counts, horizontal=True, color="#356ae6")

    if int(summary["potential_hallucination"]):
        st.warning(
            f"{summary['potential_hallucination']} citation(s) meet the evidence rule for potential hallucination. "
            "This is a review priority, not an automatic misconduct finding."
        )
    elif conflict_count == 0:
        st.success("No high-priority citation conflicts were identified in this audit.")


def _render_results(results: list) -> None:
    all_statuses = sorted({result.status.value for result in results})
    filter_cols = st.columns([1.35, 1, 1])
    query = filter_cols[0].text_input("Search citations", placeholder="Title, DOI, author or reason")
    selected_statuses = filter_cols[1].multiselect(
        "Status",
        options=all_statuses,
        format_func=lambda value: STATUS_LABELS.get(value, value.replace("_", " ").title()),
    )
    selected_type = filter_cols[2].selectbox(
        "Citation type", ["All"] + sorted({result.citation.citation_type.value for result in results})
    )

    filtered = []
    query_folded = query.casefold().strip()
    for index, result in enumerate(results):
        row = result.to_dict()
        haystack = " ".join(
            str(row.get(key, ""))
            for key in ("raw_citation", "parsed_title", "matched_title", "matched_doi", "reasons")
        ).casefold()
        if query_folded and query_folded not in haystack:
            continue
        if selected_statuses and result.status.value not in selected_statuses:
            continue
        if selected_type != "All" and result.citation.citation_type.value != selected_type:
            continue
        filtered.append((index, result))

    st.caption(f"Showing {len(filtered)} of {len(results)} citations. Reviewer fields remain editable.")
    visible = [
        "ordinal", "source_page", "citation_type", "status", "score", "raw_citation",
        "matched_title", "matched_doi", "reasons", "reviewer_decision", "reviewer_note",
    ]
    display_rows = []
    for _, result in filtered:
        row = result.to_dict()
        display_rows.append({key: row.get(key) for key in visible})

    if not display_rows:
        st.info("No citations match the current filters.")
        return

    editor_key = f"review_editor_{','.join(selected_statuses)}_{selected_type}_{query_folded}"
    edited = st.data_editor(
        display_rows,
        width="stretch",
        height=min(720, 96 + len(display_rows) * 35),
        hide_index=True,
        column_config={
            "ordinal": st.column_config.NumberColumn("#", width="small"),
            "source_page": st.column_config.NumberColumn("Page", width="small"),
            "citation_type": st.column_config.TextColumn("Type", width="small"),
            "status": st.column_config.TextColumn("System status", width="medium"),
            "score": st.column_config.ProgressColumn("Score", min_value=0.0, max_value=1.0, format="%.3f"),
            "raw_citation": st.column_config.TextColumn("Submitted citation", width="large"),
            "matched_title": st.column_config.TextColumn("Best evidence title", width="large"),
            "matched_doi": st.column_config.TextColumn("Matched DOI", width="medium"),
            "reasons": st.column_config.TextColumn("Evidence notes", width="large"),
            "reviewer_decision": st.column_config.SelectboxColumn(
                "Reviewer decision",
                options=["pending", "accept_valid", "confirm_flag", "override_valid"],
                required=True,
                width="medium",
            ),
            "reviewer_note": st.column_config.TextColumn("Reviewer note", width="large"),
        },
        disabled=[key for key in visible if key not in {"reviewer_decision", "reviewer_note"}],
        key=editor_key,
    )
    for (result_index, _), row in zip(filtered, edited, strict=True):
        results[result_index].reviewer_decision = row["reviewer_decision"]
        results[result_index].reviewer_note = row["reviewer_note"] or ""


def _render_evidence_guide() -> None:
    st.markdown("#### Decision guide")
    st.markdown(
        """
        | Output | What the system found | Recommended action |
        |---|---|---|
        | **Scholarly / web verified** | Strong identifier or multi-field metadata agreement | Normally accept; spot-check samples |
        | **Human review / not found** | Evidence is incomplete or registry coverage may be missing | Search the cited source manually |
        | **Metadata mismatch** | DOI or descriptive metadata conflicts | Compare DOI landing page with the citation |
        | **Potential hallucination** | No DOI/URL and no meaningful match across enabled scholarly sources | Treat as high-priority manual review |
        | **Parse / provider error** | Extraction uncertainty or external service interruption | Inspect source page or rerun later |
        """
    )
    st.markdown(
        """
        <div class="sacv-callout"><strong>Interpretation boundary.</strong> SACV-Tool is a decision-support system.
        A missing registry record is not evidence of fabrication, and a potential-hallucination status is not an automatic academic-misconduct conclusion.</div>
        """,
        unsafe_allow_html=True,
    )


def _render_exports(results: list) -> None:
    final_rows = [result.to_dict() for result in results]
    csv_buffer = io.StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=list(final_rows[0]))
    writer.writeheader()
    writer.writerows(final_rows)
    payload = {"summary": summarize(results), "results": final_rows}

    st.markdown("#### Export the complete evidence record")
    st.caption("Exports include every citation, provider match, reason code and reviewer decision—not only the filtered table view.")
    download_columns = st.columns(3)
    download_columns[0].download_button(
        "Download CSV", csv_buffer.getvalue().encode("utf-8-sig"), "sacv-results.csv", "text/csv",
        icon="⬇", width="stretch",
    )
    download_columns[1].download_button(
        "Download HTML report", build_html_report(results).encode("utf-8"), "sacv-report.html", "text/html",
        icon="⬇", width="stretch",
    )
    download_columns[2].download_button(
        "Download JSON", json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        "sacv-results.json", "application/json", icon="⬇", width="stretch",
    )


_inject_styles()
options = _render_sidebar()
_render_hero()
_render_uploader(options)

results = st.session_state.get("sacv_results")
if results:
    filename = st.session_state.get("sacv_filename", "uploaded document")
    st.divider()
    st.markdown('<div class="sacv-section-title">Audit workspace</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sacv-section-note">Current source: {filename}</div>', unsafe_allow_html=True)
    summary = summarize(results)
    overview_tab, results_tab, guide_tab, export_tab = st.tabs(
        ["Overview", "Citation results", "Evidence guide", "Export"]
    )
    with overview_tab:
        _render_overview(results, summary)
    with results_tab:
        _render_results(results)
    with guide_tab:
        _render_evidence_guide()
    with export_tab:
        _render_exports(results)
else:
    st.markdown(
        """
        <div class="sacv-callout"><strong>Ready when you are.</strong> Results will appear in a structured audit workspace with summary metrics, searchable citations, evidence notes and downloadable reports.</div>
        """,
        unsafe_allow_html=True,
    )

st.markdown(
    '<div class="sacv-footer">SACV-Tool · Evidence-led reference screening with mandatory human oversight</div>',
    unsafe_allow_html=True,
)
