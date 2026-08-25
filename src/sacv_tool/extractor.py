from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .models import Citation
from .normalization import DOI_RE, clean_text, normalize_doi
from .parser import LAYOUT_START_MARKER, is_reference_heading, parse_reference_pages, parse_references

PUBLISHER_NOISE_RE = re.compile(
    r"Downloaded\s+from|Wiley\s+Online\s+Library|Terms\s+and\s+Conditions|"
    r"articles?\s+are\s+governed\s+by|Page\s+\d+\s+of\s+\d+",
    re.IGNORECASE,
)


@dataclass(slots=True)
class LayoutLine:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str


def extract_citations(path: str | Path) -> list[Citation]:
    path = Path(path)
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return extract_from_pdf(path)
    if suffix in {".txt", ".md"}:
        return parse_references(path.read_text(encoding="utf-8-sig"))
    raise ValueError(f"Unsupported input format: {path.suffix}. Use PDF, TXT, or MD.")


def extract_from_pdf(path: str | Path) -> list[Citation]:
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF is required for PDF extraction. Run: pip install -e .") from exc

    with pymupdf.open(str(path)) as document:
        document_doi = _detect_document_doi(document)
        all_pages: list[tuple[int, str]] = []
        found_heading = False
        for page_number, page in enumerate(document, 1):
            lines = _extract_layout_lines(page)
            ordered = order_layout_lines(lines, page_width=float(page.rect.width), page_height=float(page.rect.height))
            page_text = render_layout_text(ordered, page_width=float(page.rect.width))
            all_pages.append((page_number, page_text))
            if not found_heading:
                found_heading = any(is_reference_heading(line) for line in page_text.splitlines())

        if not found_heading:
            fallback_index = max(0, int(len(all_pages) * 0.67))
            all_pages = all_pages[fallback_index:]

    return parse_reference_pages(all_pages, document_doi=document_doi)


def order_layout_lines(
    lines: Sequence[LayoutLine], *, page_width: float, page_height: float
) -> list[LayoutLine]:
    """Restore reading order for one- and two-column academic pages."""
    usable = [
        line
        for line in lines
        if line.text and not _is_noise_line(line, page_width=page_width, page_height=page_height)
    ]
    usable = _strip_marginal_line_numbers(usable, page_width=page_width)
    midpoint = page_width / 2.0
    initial_left = [line for line in usable if line.x1 <= midpoint + 8 and line.x0 < midpoint - 8]
    initial_right = [line for line in usable if line.x0 >= midpoint - 8]
    initial_spanning = [line for line in usable if line not in initial_left and line not in initial_right]
    # Justified single-column PDFs can expose each styled word as a separate
    # fragment on the same baseline.  Such fragments may fall in the right half
    # of the page, but the many full-width lines identify the page as one column.
    two_columns = (
        len(initial_left) >= 4
        and len(initial_right) >= 4
        and len(initial_spanning) < max(len(initial_left), len(initial_right))
    )
    usable = _merge_same_baseline_fragments(
        usable,
        page_width=page_width,
        enforce_columns=two_columns,
    )
    if not usable:
        return []

    left = [line for line in usable if line.x1 <= midpoint + 8 and line.x0 < midpoint - 8]
    right = [line for line in usable if line.x0 >= midpoint - 8]
    spanning = [line for line in usable if line not in left and line not in right]

    if not two_columns:
        return sorted(usable, key=lambda item: (round(item.y0, 1), item.x0))

    first_column_y = min(line.y0 for line in [*left, *right])
    last_column_y = max(line.y1 for line in [*left, *right])
    top_spanning = [line for line in spanning if line.y1 <= first_column_y + 4]
    bottom_spanning = [line for line in spanning if line.y0 >= last_column_y - 4]
    middle_spanning = [line for line in spanning if line not in top_spanning and line not in bottom_spanning]

    ordered: list[LayoutLine] = []
    ordered.extend(sorted(top_spanning, key=lambda item: (item.y0, item.x0)))
    ordered.extend(sorted(left, key=lambda item: (item.y0, item.x0)))
    ordered.extend(sorted(middle_spanning, key=lambda item: (item.y0, item.x0)))
    ordered.extend(sorted(right, key=lambda item: (item.y0, item.x0)))
    ordered.extend(sorted(bottom_spanning, key=lambda item: (item.y0, item.x0)))
    return ordered


def _strip_marginal_line_numbers(
    lines: Sequence[LayoutLine], *, page_width: float
) -> list[LayoutLine]:
    """Remove Word-style continuous line numbering before column detection.

    Line-numbered manuscripts expose a narrow numeric stream in the outer margin.
    Without this page-level check, that stream looks like the left column of a
    two-column paper and sends the bibliography through the wrong reading order.
    A normal numbered reference is usually part of the citation baseline (and is
    merged with its text); the dense, sequential, vertically regular margin stream
    checked here is specific to document line numbering.
    """
    side_candidates: dict[str, list[tuple[int, LayoutLine]]] = {"left": [], "right": []}
    for line in lines:
        if not re.fullmatch(r"\d{1,6}", line.text):
            continue
        if line.x1 <= page_width * 0.18:
            side_candidates["left"].append((int(line.text), line))
        elif line.x0 >= page_width * 0.82:
            side_candidates["right"].append((int(line.text), line))

    remove_ids: set[int] = set()
    for candidates in side_candidates.values():
        ordered = sorted(candidates, key=lambda item: item[1].y0)
        if len(ordered) < 4:
            continue
        values = [value for value, _line in ordered]
        value_steps = [later - earlier for earlier, later in zip(values, values[1:])]
        sequential_ratio = sum(1 <= step <= 10 for step in value_steps) / len(value_steps)
        y_steps = [
            later.y0 - earlier.y0
            for (_value_a, earlier), (_value_b, later) in zip(ordered, ordered[1:])
            if later.y0 > earlier.y0
        ]
        heights = [max(1.0, line.y1 - line.y0) for _value, line in ordered]
        x_positions = [line.x0 for _value, line in ordered]
        dense_stream = bool(
            y_steps
            and statistics.median(y_steps) <= statistics.median(heights) * 3.2
        )
        aligned_stream = max(x_positions) - min(x_positions) <= 12.0
        if sequential_ratio >= 0.80 and dense_stream and aligned_stream:
            remove_ids.update(id(line) for _value, line in ordered)

    return [line for line in lines if id(line) not in remove_ids]


def render_layout_text(lines: Sequence[LayoutLine], *, page_width: float) -> str:
    if not lines:
        return ""
    midpoint = page_width / 2.0
    left_margin = _column_margin([line for line in lines if line.x0 < midpoint])
    right_margin = _column_margin([line for line in lines if line.x0 >= midpoint])
    output: list[str] = []
    for line in lines:
        margin = left_margin if line.x0 < midpoint else right_margin
        is_start_hint = margin is not None and abs(line.x0 - margin) <= 2.8
        output.append((LAYOUT_START_MARKER if is_start_hint else "") + line.text)
    return "\n".join(output)


def _extract_layout_lines(page: Any) -> list[LayoutLine]:
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)
    output: list[LayoutLine] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        bx0, by0, bx1, by1 = block.get("bbox", (0, 0, 0, 0))
        if (bx1 - bx0) < page_width * 0.04 and (by1 - by0) > page_height * 0.45:
            continue
        block_text = " ".join(
            str(span.get("text", ""))
            for line in block.get("lines", [])
            for span in line.get("spans", [])
        )
        if PUBLISHER_NOISE_RE.search(block_text):
            continue
        for line in block.get("lines", []):
            spans = sorted(line.get("spans", []), key=lambda span: span.get("bbox", (0, 0, 0, 0))[0])
            if not spans:
                continue
            text_parts: list[str] = []
            previous_x1: float | None = None
            for span in spans:
                sx0, _sy0, sx1, _sy1 = span.get("bbox", (0, 0, 0, 0))
                text = str(span.get("text", ""))
                if previous_x1 is not None and sx0 - previous_x1 > 1.5 and text_parts and not text_parts[-1].endswith(" "):
                    text_parts.append(" ")
                text_parts.append(text)
                previous_x1 = float(sx1)
            text = clean_text("".join(text_parts))
            if not text:
                continue
            x0, y0, x1, y1 = line.get("bbox", (0, 0, 0, 0))
            output.append(LayoutLine(float(x0), float(y0), float(x1), float(y1), text))
    return output


def _merge_same_baseline_fragments(
    lines: Sequence[LayoutLine], *, page_width: float, enforce_columns: bool
) -> list[LayoutLine]:
    merged: list[LayoutLine] = []
    midpoint = page_width / 2.0
    for line in sorted(lines, key=lambda item: (round(item.y0, 1), item.x0)):
        if merged:
            previous = merged[-1]
            same_column = not enforce_columns or (previous.x0 < midpoint) == (line.x0 < midpoint)
            same_baseline = abs(previous.y0 - line.y0) <= 1.2
            close_enough = -2 <= line.x0 - previous.x1 <= 80
            if same_column and same_baseline and close_enough:
                separator = " " if line.x0 - previous.x1 > 1.5 else ""
                previous.text = clean_text(previous.text + separator + line.text)
                previous.x1 = max(previous.x1, line.x1)
                previous.y1 = max(previous.y1, line.y1)
                continue
        merged.append(LayoutLine(line.x0, line.y0, line.x1, line.y1, line.text))
    return merged


def _is_noise_line(line: LayoutLine, *, page_width: float, page_height: float) -> bool:
    if PUBLISHER_NOISE_RE.search(line.text):
        return True
    if line.y1 <= 42 and re.search(r"\b(?:page\s*)?\d+\s+of\s+\d+\b|\b[A-Z ]+MAGAZINE\b", line.text, re.IGNORECASE):
        return True
    if line.y0 >= page_height - 70 and re.fullmatch(r"\d{1,4}", line.text):
        return True
    if line.x0 >= page_width * 0.95 and (line.y1 - line.y0) > page_height * 0.25:
        return True
    return False


def _column_margin(lines: Sequence[LayoutLine]) -> float | None:
    candidates = [round(line.x0, 1) for line in lines if len(line.text) >= 3]
    if not candidates:
        return None
    # Academic reference lists normally use a hanging indent: continuation lines
    # are more numerous than citation starts.  The left-most body coordinate is
    # the start margin even on the last page where only one citation starts.
    return min(candidates)


def _detect_document_doi(document: Any) -> str:
    candidates: list[str] = []
    for page_index in range(min(2, len(document))):
        text = document[page_index].get_text("text")
        candidates.extend(normalize_doi(match.group(0)) for match in DOI_RE.finditer(text))
    candidates = [candidate for candidate in candidates if candidate]
    if not candidates:
        return ""
    return Counter(candidates).most_common(1)[0][0]
