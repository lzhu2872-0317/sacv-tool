from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Iterable

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s<>\[\]{}\"']+", re.IGNORECASE)
YEAR_RE = re.compile(r"(?<!\d)(18\d{2}|19\d{2}|20\d{2}|2100)(?:[a-z])?(?!\d)", re.IGNORECASE)


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\u00ad", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def repair_broken_identifiers(value: str) -> str:
    """Repair spaces inserted by PDF line wrapping inside DOI and URL tokens."""
    value = clean_text(value)
    value = re.sub(r"\bdoi\.\s+org\b", "doi.org", value, flags=re.IGNORECASE)
    for _ in range(4):
        updated = re.sub(
            r"(10\.\d{4,9}/)\s+(?=[A-Za-z0-9])",
            r"\1",
            value,
            flags=re.IGNORECASE,
        )
        updated = re.sub(
            r"(10\.\d{4,9}/\S*[-_/])\s+(?=[A-Za-z0-9])",
            r"\1",
            updated,
            flags=re.IGNORECASE,
        )
        updated = re.sub(
            r"(10\.\d{4,9}/\S*\.)\s+(?=[0-9a-z])",
            r"\1",
            updated,
            flags=re.IGNORECASE,
        )
        updated = re.sub(
            r"(https?://\S*[/_=&?#%\-])\s+(?=[A-Za-z0-9])",
            r"\1",
            updated,
            flags=re.IGNORECASE,
        )
        updated = re.sub(
            r"(https?://\S*\.)\s+(?=[0-9a-z])",
            r"\1",
            updated,
            flags=re.IGNORECASE,
        )
        if updated == value:
            break
        value = updated
    return value


def normalize_text(value: str) -> str:
    value = clean_text(value).casefold()
    decomposed = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in decomposed if not unicodedata.combining(char))
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def normalize_doi(value: str) -> str:
    value = clean_text(value)
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)", "", value, flags=re.IGNORECASE)
    match = DOI_RE.search(value)
    if not match:
        return ""
    return match.group(0).rstrip(".,;:)]}\"").casefold()


def extract_doi(value: str) -> str:
    match = DOI_RE.search(repair_broken_identifiers(value))
    return normalize_doi(match.group(0)) if match else ""


def extract_url(value: str) -> str:
    repaired = repair_broken_identifiers(value)
    match = URL_RE.search(repaired)
    if not match:
        return ""
    return match.group(0).rstrip(".,;:)]}\"")


def extract_year(value: str) -> int | None:
    match = YEAR_RE.search(value or "")
    return int(match.group(1)) if match else None


def normalized_levenshtein(left: str, right: str) -> float:
    """Return 0..1 similarity based on normalized Levenshtein distance."""
    left_n, right_n = normalize_text(left), normalize_text(right)
    if not left_n and not right_n:
        return 1.0
    if not left_n or not right_n:
        return 0.0
    if len(left_n) > len(right_n):
        left_n, right_n = right_n, left_n
    previous = list(range(len(left_n) + 1))
    for row, right_char in enumerate(right_n, 1):
        current = [row]
        for col, left_char in enumerate(left_n, 1):
            insert_cost = current[col - 1] + 1
            delete_cost = previous[col] + 1
            substitute_cost = previous[col - 1] + (left_char != right_char)
            current.append(min(insert_cost, delete_cost, substitute_cost))
        previous = current
    distance = previous[-1]
    return max(0.0, 1.0 - distance / max(len(left_n), len(right_n)))


def best_similarity(value: str, candidates: Iterable[str]) -> float:
    return max((normalized_levenshtein(value, candidate) for candidate in candidates if candidate), default=0.0)


def surname(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ""
    if "," in value:
        return normalize_text(value.split(",", 1)[0])
    tokens = normalize_text(value).split()
    return tokens[-1] if tokens else ""
