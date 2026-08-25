from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    threshold: float = 0.85
    review_margin: float = 0.08
    max_candidates: int = 5
    concurrency: int = 3
    request_timeout: float = 20.0
    retries: int = 3
    email: str = ""
    enable_pubmed: bool = False
    enable_openalex: bool = True
    enable_web_validation: bool = True
    ncbi_api_key: str = ""
    openalex_api_key: str = ""
    cache_path: Path = Path(".sacv-cache.json")

    @classmethod
    def from_env(cls, **overrides: object) -> "Settings":
        values: dict[str, object] = {
            "email": os.getenv("SACV_EMAIL", ""),
            "ncbi_api_key": os.getenv("NCBI_API_KEY", ""),
            "openalex_api_key": os.getenv("OPENALEX_API_KEY", ""),
        }
        values.update({key: value for key, value in overrides.items() if value is not None})
        settings = cls(**values)
        settings.validate()
        return settings

    def validate(self) -> None:
        if not 0.0 < self.threshold <= 1.0:
            raise ValueError("threshold must be in (0, 1]")
        if not 0.0 <= self.review_margin < self.threshold:
            raise ValueError("review_margin must be in [0, threshold)")
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be at least 1")
        if self.concurrency < 1:
            raise ValueError("concurrency must be at least 1")

    @property
    def crossref_requests_per_second(self) -> float:
        # Current Crossref list-query limits: public 1/s; polite 3/s.
        return 3.0 if self.email else 1.0

    @property
    def pubmed_requests_per_second(self) -> float:
        return 10.0 if self.ncbi_api_key else 3.0

    @property
    def openalex_requests_per_second(self) -> float:
        return 8.0 if self.openalex_api_key else 3.0

    @property
    def web_requests_per_second(self) -> float:
        return 2.0
