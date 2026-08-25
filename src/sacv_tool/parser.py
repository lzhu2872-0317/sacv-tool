from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Sequence

from .models import Citation, CitationType
from .normalization import DOI_RE, clean_text, extract_doi, extract_url, extract_year, repair_broken_identifiers

LAYOUT_START_MARKER = "\u241e"
REFERENCE_HEADING_KEYS = frozenset({"references", "bibliography", "workscited", "referencelist"})
REFERENCE_END_HEADING_KEYS = frozenset(
    {
        "appendix",
        "appendices",
        "annex",
        "annexes",
        "acknowledgments",
        "acknowledgements",
        "declarations",
        "funding",
        "fundinginformation",
        "conflictofinterest",
        "conflictsofinterest",
        "authorbiographies",
        "authorbiography",
        "biographicalnotes",
        "abouttheauthors",
        "authordetails",
        "howtocitethisarticle",
    }
)

REFERENCE_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)?\s*)?(references|bibliography|works\s+cited|reference\s+list)\s*$",
    re.IGNORECASE,
)
REFERENCE_END_HEADING_RE = re.compile(
    r"^\s*(?:\d{1,4}\s+)?(?:appendix|appendices|annex|annexes|附录)(?:\s+[A-Z0-9IVX]+)?(?:\s*[:.\-–—].*)?\s*$",
    re.IGNORECASE,
)
INLINE_END_HEADING_RE = re.compile(
    r"(?<!\w)(?:\d{1,4}\s+)?(?:appendix|appendices|annex|annexes|附录)\s+"
    r"[A-Z0-9IVX一二三四五六七八九十]+(?:\s*[:：.\-–—])",
    re.IGNORECASE,
)
# Four-digit naked years are common in Chicago references ("Author. 2023.")
# and must never be mistaken for a numbered bibliography item.
NUMBERED_START_RE = re.compile(r"^\s*(?:\[\d+\]|\d{1,3}[.)])\s+")
AUTHOR_YEAR_START_RE = re.compile(
    r"^[A-ZÀ-ÖØ-Þ][\w'’\-À-öø-ÿ]+(?:\s+[A-ZÀ-ÖØ-Þ][\w'’\-À-öø-ÿ]+)*,\s*"
    r"(?:[A-ZÀ-ÖØ-Þ]\.(?:\s*-\s*[A-ZÀ-ÖØ-Þ]\.)?\s*){1,4}"
    r"(?=.{0,220}?(?:\(|\b)(?:18|19|20)\d{2}[a-z]?)",
    re.UNICODE,
)
CORPORATE_DATE_START_RE = re.compile(
    r"^[A-ZÀ-ÖØ-Þ][\w&'’\-À-öø-ÿ]*"
    r"(?:\s+(?:[A-ZÀ-ÖØ-Þ][\w&'’\-À-öø-ÿ]+|of|and|the)){0,11}\.\s*"
    r"(?:(?:\((?:(?:18|19|20)\d{2}[a-z]?(?:,\s*[^)]{1,40})?|n\.?\s*d\.?)\)\.?)"
    r"|(?:(?:18|19|20)\d{2}[a-z]?\.))",
)
NO_DATE_RE = re.compile(
    r"\(\s*n\.?\s*d\.?\s*\)",
    re.UNICODE,
)
CHINESE_YEAR_START_RE = re.compile(r"^[\u3400-\u9fff].{0,100}?[（(](?:18|19|20)\d{2}[a-z]?[）)]")
PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,4}\s*$")
FATAL_PARSE_FLAGS = frozenset(
    {
        "SPLIT_CITATION",
        "MERGED_CITATION",
        "APPENDIX_CONTAMINATION",
        "REFERENCE_BOUNDARY_CONTAMINATION",
        "WATERMARK_CONTAMINATION",
        "SELF_DOI_CONTAMINATION",
        "BIOGRAPHY_CONTAMINATION",
    }
)


@dataclass(slots=True)
class ReferenceEntry:
    raw: str
    source_page: int | None = None
    source_end_page: int | None = None
    parse_flags: list[str] = field(default_factory=list)


def locate_reference_section(text: str) -> tuple[str, bool]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for index, line in enumerate(lines):
        if _is_reference_heading(line):
            selected: list[str] = []
            for candidate in lines[index + 1 :]:
                prefix, stopped = _truncate_at_end_heading(candidate)
                if prefix:
                    selected.append(prefix)
                if stopped:
                    break
            return "\n".join(selected), True
    return text, False


def split_reference_entries(text: str) -> list[str]:
    section, _ = locate_reference_section(text)
    records = _split_reference_records([(None, section)])
    return [record.raw for record in records]


def parse_reference_pages(pages: Sequence[tuple[int, str]], document_doi: str = "") -> list[Citation]:
    """Parse references while preserving the real PDF start/end page for each entry."""
    lines = _collect_reference_lines(pages)
    records = _split_records_from_lines(lines)
    return [
        parse_citation(
            record.raw,
            ordinal=index,
            source_page=record.source_page,
            source_end_page=record.source_end_page,
            parse_flags=record.parse_flags,
            document_doi=document_doi,
        )
        for index, record in enumerate(records, 1)
    ]


def parse_citation(
    raw: str,
    ordinal: int | None = None,
    source_page: int | None = None,
    source_end_page: int | None = None,
    parse_flags: Sequence[str] | None = None,
    document_doi: str = "",
) -> Citation:
    raw = repair_broken_identifiers(clean_text(NUMBERED_START_RE.sub("", raw)))
    # A hyphen followed by extracted whitespace is a PDF line-wrap artifact;
    # real hyphenated words have no intervening space in the source string.
    raw = re.sub(r"(?<=\w)-\s+(?=\w)", "", raw)
    doi = extract_doi(raw)
    url = extract_url(raw)
    year_match = _find_citation_year_match(raw)
    year = int(year_match.group(1)) if year_match and year_match.group(1) else None
    authors_text, remainder = _split_at_year(raw)
    title_led = bool(
        year_match
        and authors_text
        and not re.search(r",\s*[A-ZÀ-ÖØ-Þ](?:\.|$)", authors_text)
        and not CORPORATE_DATE_START_RE.match(raw)
    )
    if title_led:
        authors = []
        title = authors_text.strip(" .")
        remainder_title, remainder_venue = _parse_title_venue(remainder, doi)
        venue = remainder_title or remainder_venue
    else:
        authors = _parse_authors(authors_text)
        title, venue = _parse_title_venue(remainder, doi)
    flags = list(dict.fromkeys([*(parse_flags or []), *_diagnose_entry(raw)]))
    if document_doi and doi and doi.casefold() == document_doi.casefold():
        flags.append("SELF_DOI_CONTAMINATION")
    flags = list(dict.fromkeys(flags))
    citation_type = _classify_citation_type(raw, doi=doi, url=url)
    parse_confidence = _parse_confidence(
        raw,
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        url=url,
        citation_type=citation_type,
        flags=flags,
    )
    return Citation(
        raw=raw,
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        url=url,
        citation_type=citation_type,
        parse_confidence=parse_confidence,
        source_page=source_page,
        source_end_page=source_end_page if source_end_page is not None else source_page,
        ordinal=ordinal,
        parse_flags=flags,
    )


def parse_references(text: str) -> list[Citation]:
    section, _ = locate_reference_section(text)
    records = _split_reference_records([(None, section)])
    return [
        parse_citation(record.raw, ordinal=index, parse_flags=record.parse_flags)
        for index, record in enumerate(records, 1)
    ]


def has_fatal_parse_flag(citation: Citation) -> bool:
    return any(flag in FATAL_PARSE_FLAGS for flag in citation.parse_flags)


def _collect_reference_lines(pages: Sequence[tuple[int, str]]) -> list[tuple[int | None, str]]:
    prepared = _prepare_page_lines(pages)
    heading_location: tuple[int, int] | None = None
    for page_index, (_page_number, lines) in enumerate(prepared):
        for line_index, line in enumerate(lines):
            if _is_reference_heading(line):
                heading_location = (page_index, line_index)
                break
        if heading_location is not None:
            break

    collected: list[tuple[int | None, str]] = []
    stopped = False
    for page_index, (page_number, lines) in enumerate(prepared):
        if heading_location is not None:
            if page_index < heading_location[0]:
                continue
            start = heading_location[1] + 1 if page_index == heading_location[0] else 0
        else:
            start = 0
        for line in lines[start:]:
            has_start_hint = line.startswith(LAYOUT_START_MARKER)
            value = line.removeprefix(LAYOUT_START_MARKER)
            prefix, is_end = _truncate_at_end_heading(value)
            if prefix and not _is_reference_heading(prefix) and not PAGE_NUMBER_RE.match(prefix):
                collected.append((page_number, (LAYOUT_START_MARKER if has_start_hint else "") + prefix))
            if is_end:
                stopped = True
                break
        if stopped:
            break
    return collected


def _prepare_page_lines(pages: Sequence[tuple[int, str]]) -> list[tuple[int, list[str]]]:
    prepared: list[tuple[int, list[str]]] = []
    boundary_counts: Counter[str] = Counter()
    boundary_members: list[set[str]] = []
    for page_number, text in pages:
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        normalized = []
        for line in lines:
            has_start_hint = line.startswith(LAYOUT_START_MARKER)
            value = clean_text(line.removeprefix(LAYOUT_START_MARKER))
            normalized.append((LAYOUT_START_MARKER if has_start_hint and value else "") + value)
        prepared.append((page_number, normalized))
        members = {
            line.removeprefix(LAYOUT_START_MARKER).casefold()
            for index, line in enumerate(normalized)
            if line
            and (index < 2 or index >= max(0, len(normalized) - 2))
            and len(line) <= 100
            and extract_year(line) is None
            and not extract_doi(line)
            and not _is_reference_heading(line)
            and not _is_end_heading(line)
        }
        boundary_members.append(members)
        boundary_counts.update(members)

    repeated = {line for line, count in boundary_counts.items() if count >= 2}
    cleaned: list[tuple[int, list[str]]] = []
    for (page_number, lines), members in zip(prepared, boundary_members, strict=True):
        output: list[str] = []
        for index, line in enumerate(lines):
            at_boundary = index < 2 or index >= max(0, len(lines) - 2)
            comparable = line.removeprefix(LAYOUT_START_MARKER).casefold()
            if at_boundary and comparable in repeated and comparable in members:
                continue
            if PAGE_NUMBER_RE.match(line.removeprefix(LAYOUT_START_MARKER)):
                continue
            output.append(line)
        cleaned.append((page_number, output))
    return cleaned


def _split_reference_records(pages: Sequence[tuple[int | None, str]]) -> list[ReferenceEntry]:
    lines: list[tuple[int | None, str]] = []
    for page_number, text in pages:
        lines.extend(
            (page_number, line)
            for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        )
    return _split_records_from_lines(lines)


def _split_records_from_lines(lines: Sequence[tuple[int | None, str]]) -> list[ReferenceEntry]:
    entries: list[ReferenceEntry] = []
    current: list[tuple[int | None, str]] = []
    flags: list[str] = []
    layout_aware = any(raw_line.startswith(LAYOUT_START_MARKER) for _page, raw_line in lines)

    def flush() -> None:
        if not current:
            return
        raw = clean_text(" ".join(line for _page, line in current))
        start_page = next((page for page, _line in current if page is not None), None)
        end_page = next((page for page, _line in reversed(current) if page is not None), start_page)
        pieces = _split_inline_entries(raw)
        repaired = len(pieces) > 1
        for piece in pieces:
            if not _looks_like_reference(piece):
                continue
            piece_flags = list(flags)
            if repaired:
                piece_flags.append("MERGED_CITATION_REPAIRED")
            piece_flags.extend(_diagnose_entry(piece))
            entries.append(
                ReferenceEntry(
                    raw=piece,
                    source_page=start_page,
                    source_end_page=end_page,
                    parse_flags=list(dict.fromkeys(piece_flags)),
                )
            )
        current.clear()
        flags.clear()

    for page_number, raw_line in lines:
        has_start_hint = raw_line.startswith(LAYOUT_START_MARKER)
        line = clean_text(raw_line.removeprefix(LAYOUT_START_MARKER))
        if not line:
            continue
        page_changed = bool(current and page_number != current[-1][0])
        hinted_start = has_start_hint
        if current and page_changed and has_start_hint and not _looks_like_reference_start(line):
            previous = clean_text(" ".join(value for _page, value in current))
            hinted_start = _looks_like_title_led_start(line, previous)
            if not hinted_start:
                flags.append("SPLIT_CITATION_REPAIRED")
        inferred_start = not layout_aware and _looks_like_reference_start(line)
        if current and (hinted_start or inferred_start):
            flush()
        elif current and _looks_like_continuation_fragment(line):
            flags.append("SPLIT_CITATION_REPAIRED")
        elif not current and _looks_like_continuation_fragment(line):
            flags.append("SPLIT_CITATION")
        current.append((page_number, line))
    flush()
    return entries


def _split_inline_entries(entry: str) -> list[str]:
    boundaries: set[int] = set()
    for match in DOI_RE.finditer(entry):
        tail_start = match.end()
        while tail_start < len(entry) and entry[tail_start] in " .;,)]}\t\r\n":
            tail_start += 1
        if tail_start < len(entry) and _looks_like_reference_start(entry[tail_start:]):
            boundaries.add(tail_start)

    for whitespace in re.finditer(r"\s+", entry):
        tail_start = whitespace.end()
        if tail_start < 25 or tail_start >= len(entry):
            continue
        previous = entry[: whitespace.start()].rstrip()
        if (
            previous
            and previous[-1] in ".;)]"
            and _has_bibliographic_year(previous)
            and _looks_like_reference_start(entry[tail_start:])
        ):
            boundaries.add(tail_start)

    if not boundaries:
        return [entry]
    pieces: list[str] = []
    start = 0
    for boundary in sorted(boundaries):
        piece = clean_text(entry[start:boundary])
        if piece:
            pieces.append(piece)
        start = boundary
    final = clean_text(entry[start:])
    if final:
        pieces.append(final)
    return pieces


def _looks_like_reference_start(value: str) -> bool:
    value = clean_text(value)
    return bool(
        NUMBERED_START_RE.match(value)
        or AUTHOR_YEAR_START_RE.match(value)
        or CORPORATE_DATE_START_RE.match(value)
        or CHINESE_YEAR_START_RE.match(value)
    )


def _looks_like_title_led_start(value: str, previous: str) -> bool:
    """Disambiguate a real title-led entry from a continuation at a page break."""
    value = clean_text(value)
    previous = clean_text(previous)
    has_date = bool(_find_citation_year_match(value) or NO_DATE_RE.search(value))
    previous_complete = bool(
        previous.endswith(".")
        or re.search(r"https?://\S+$", previous, re.IGNORECASE)
        or DOI_RE.search(previous[-180:])
    )
    return has_date and previous_complete


def _looks_like_continuation_fragment(value: str) -> bool:
    value = clean_text(value)
    if not value or _looks_like_reference_start(value):
        return False
    if re.match(r"^(?:https?://|doi\s*:)", value, re.IGNORECASE):
        return True
    if re.match(
        r"^[A-ZÀ-ÖØ-Þ][\w&'’\-À-öø-ÿ ]{2,60},\s*(?:\d{1,4}|vol\.?\b|no\.?\b|article\b)",
        value,
        re.IGNORECASE,
    ):
        return True
    return bool(DOI_RE.search(value) and len(value.split()) < 18 and not _has_bibliographic_year(value))


def _diagnose_entry(value: str) -> list[str]:
    flags: list[str] = []
    if len(DOI_RE.findall(value)) >= 2:
        flags.append("MERGED_CITATION")
    if len(re.findall(r"https?://", value, re.IGNORECASE)) >= 2:
        flags.append("MULTIPLE_URLS")
    if _looks_like_continuation_fragment(value):
        flags.append("SPLIT_CITATION")
    if re.search(r"\b(?:appendix|appendices|annex|annexes)\b|附录", value, re.IGNORECASE):
        flags.append("APPENDIX_CONTAMINATION")
    if re.search(r"Downloaded\s+from|Wiley\s+Online\s+Library|Terms\s+and\s+Conditions", value, re.IGNORECASE):
        flags.append("WATERMARK_CONTAMINATION")
    if re.search(r"\bAUTHOR\s+BIOGRAPH(?:Y|IES)\b|\bis\s+(?:a|an|the)\s+(?:Professor|Dean|Research Associate)", value, re.IGNORECASE):
        flags.append("BIOGRAPHY_CONTAMINATION")
    if re.search(r"\bHow\s+to\s+cite\s+this\s+article\s*:", value, re.IGNORECASE):
        flags.append("REFERENCE_BOUNDARY_CONTAMINATION")
    return flags


def _is_end_heading(value: str) -> bool:
    value = clean_text(value.removeprefix(LAYOUT_START_MARKER))
    if not value or len(value) > 180:
        return False
    key = _heading_key(value)
    return any(key == candidate or key.startswith(candidate) for candidate in REFERENCE_END_HEADING_KEYS)


def _truncate_at_end_heading(value: str) -> tuple[str, bool]:
    """Return text before an appendix heading, including headings embedded in PDF blocks."""
    value = clean_text(value)
    if _is_end_heading(value):
        return "", True
    match = INLINE_END_HEADING_RE.search(value)
    if match:
        return clean_text(value[: match.start()]), True
    inline = re.search(
        r"(?<!\w)(?:how\s+to\s+cite\s+this\s+article|author\s+biograph(?:y|ies)|"
        r"biographical\s+notes|about\s+the\s+authors)\s*[:.]?",
        value,
        re.IGNORECASE,
    )
    if inline:
        return clean_text(value[: inline.start()]), True
    return value, False


def _is_reference_heading(value: str) -> bool:
    value = clean_text(value.removeprefix(LAYOUT_START_MARKER))
    if not value or len(value) > 100:
        return False
    return _heading_key(value) in REFERENCE_HEADING_KEYS


def is_reference_heading(value: str) -> bool:
    return _is_reference_heading(value)


def _heading_key(value: str) -> str:
    value = re.sub(r"^\s*\d+(?:\.\d+)*\s*", "", clean_text(value))
    return re.sub(r"[^a-z]", "", value.casefold())


def _has_bibliographic_year(value: str) -> bool:
    without_doi = re.sub(
        r"(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)?" + DOI_RE.pattern,
        "",
        value,
        flags=re.IGNORECASE,
    )
    return extract_year(without_doi) is not None


def _looks_like_reference(value: str) -> bool:
    value = clean_text(value)
    return len(value) >= 25 and (
        extract_year(value) is not None or bool(extract_doi(value)) or bool(NO_DATE_RE.search(value))
    )


def _split_at_year(raw: str) -> tuple[str, str]:
    match = _find_citation_year_match(raw)
    if not match:
        no_date = NO_DATE_RE.search(raw)
        if no_date:
            return raw[: no_date.start()].strip(" ,.;()"), raw[no_date.end() :].strip(" .,:;")
    if not match:
        return raw.split(".", 1)[0], raw
    return raw[: match.start()].strip(" ,.;()"), raw[match.end() :].strip()


def _find_citation_year_match(raw: str) -> re.Match[str] | None:
    # Prefer the explicit publication date. This avoids treating a year in a
    # report title (for example "2021 China ... (2022)") as the publication year.
    parenthesized = re.search(
        r"\(\s*((?:18|19|20)\d{2})[a-z]?(?:,\s*[^)]{1,40})?\)\s*[.,;:]?\s*",
        raw,
        re.IGNORECASE,
    )
    if parenthesized:
        return parenthesized
    return re.search(
        r"\b((?:18|19|20)\d{2})[a-z]?\b\s*[.,;:]?\s*",
        raw,
        re.IGNORECASE,
    )


def _parse_authors(value: str) -> list[str]:
    value = re.sub(r"\bet\s+al\.?", "", value, flags=re.IGNORECASE)
    apa_pattern = re.compile(
        r"(?:^|,\s+|&\s+)([A-ZÀ-ÖØ-Þ][\w'’\-À-öø-ÿ]*(?:\s+[A-ZÀ-ÖØ-Þ][\w'’\-À-öø-ÿ]*)?),\s*((?:[A-Z]\.?(?:\s*|-)?)+)",
        re.UNICODE,
    )
    apa_authors = [clean_text(f"{family}, {initials}") for family, initials in apa_pattern.findall(value)]
    if apa_authors:
        return apa_authors[:12]
    parts = re.split(r"\s*(?:;|\s&\s|\sand\s)\s*", value)
    authors = [clean_text(part.strip(" ,.;")) for part in parts]
    return [author for author in authors if author][:12]


def _parse_title_venue(remainder: str, doi: str) -> tuple[str, str]:
    if doi:
        remainder = re.sub(
            r"(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)?" + re.escape(doi),
            "",
            remainder,
            flags=re.IGNORECASE,
        )
    # URLs are terminal citation fields and PDF extraction often inserts spaces
    # inside a wrapped URL. Remove the complete tail, not only the first token.
    remainder = re.sub(r"https?://.*$", "", remainder, flags=re.IGNORECASE)
    remainder = clean_text(remainder).strip(" .;,")
    if not remainder:
        return "", ""

    # Chicago-style records commonly wrap the complete article title in curly
    # or straight quotation marks. Parse that boundary before looking at commas,
    # because title-internal commas must not be mistaken for venue separators.
    quoted = re.match(r"^[“\"](?P<title>.+?)[”\"]\s*(?P<tail>.*)$", remainder)
    if quoted:
        title = quoted.group("title").strip(" .;,\"“”")
        return title, _venue_from_tail(quoted.group("tail"))

    arxiv = re.match(r"^(?P<title>.+?)\.\s+(?P<tail>arXiv\s+preprint\b.*)$", remainder, re.IGNORECASE)
    if arxiv:
        return arxiv.group("title").strip(" .;,"), _venue_from_tail(arxiv.group("tail"))

    parts = [
        part.strip(" .;,")
        for part in re.split(r"\.\s+(?=[A-ZÀ-ÖØ-Þ])", remainder)
        if part.strip(" .;,")
    ]
    if len(parts) == 1:
        comma_parts = [part.strip() for part in remainder.split(",") if part.strip()]
        title = comma_parts[0] if comma_parts else remainder
        venue = ", ".join(comma_parts[1:3]) if len(comma_parts) > 1 else ""
        return title, venue
    return parts[0], parts[1]


def _venue_from_tail(value: str) -> str:
    value = clean_text(value).strip(" .;,")
    if not value:
        return ""
    # Remove volume/issue/pages while retaining the publication/container name.
    venue = re.split(
        r"(?:,?\s+)(?=\d+(?:\s*\(\d+\))?\s*(?::|,)|(?:vol\.?|volume)\s+\d+)",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return venue.strip(" .;,")


def _classify_citation_type(raw: str, *, doi: str, url: str) -> CitationType:
    if re.search(
        r"\b(?:master'?s\s+thesis|doctoral\s+thesis|ph\.?d\.?\s+thesis|dissertation|"
        r"handbook|monograph|isbn|book\s+chapter|university\s+press)\b",
        raw,
        re.IGNORECASE,
    ):
        return CitationType.BOOK_THESIS
    if doi or re.search(
        r"\b(?:journal|proceedings|conference|volume|vol\.?|issue)\b|\b\d+\s*\(\d+\)\s*[:,]",
        raw,
        re.IGNORECASE,
    ):
        return CitationType.SCHOLARLY
    if url or re.search(
        r"\b(?:policy|guidelines?|report|university|institute|association|commission|government|publisher)\b",
        raw,
        re.IGNORECASE,
    ):
        return CitationType.WEB_POLICY
    return CitationType.UNKNOWN


def _parse_confidence(
    raw: str,
    *,
    title: str,
    authors: Sequence[str],
    year: int | None,
    doi: str,
    url: str,
    citation_type: CitationType,
    flags: Sequence[str],
) -> float:
    if any(flag in FATAL_PARSE_FLAGS for flag in flags):
        return 0.0
    confidence = 1.0
    if not title or len(title) < 8:
        confidence -= 0.35
    if citation_type is CitationType.SCHOLARLY and not authors:
        confidence -= 0.18
    if citation_type is CitationType.SCHOLARLY and year is None:
        confidence -= 0.12
    if citation_type is CitationType.UNKNOWN and not (doi or url):
        confidence -= 0.18
    if "MULTIPLE_URLS" in flags:
        confidence -= 0.30
    if "MERGED_CITATION_REPAIRED" in flags:
        confidence -= 0.08
    if "SPLIT_CITATION_REPAIRED" in flags:
        confidence -= 0.03
    if len(raw) > 1200:
        confidence -= 0.35
    elif len(raw) > 700:
        confidence -= 0.18
    return round(max(0.0, min(1.0, confidence)), 4)
