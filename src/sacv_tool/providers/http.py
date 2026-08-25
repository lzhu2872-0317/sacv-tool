from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .base import ProviderError


class AsyncRateLimiter:
    def __init__(self, requests_per_second: float):
        self.min_interval = 1.0 / max(requests_per_second, 0.01)
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_allowed - now)
            if delay:
                await asyncio.sleep(delay)
            self._next_allowed = max(now, self._next_allowed) + self.min_interval


class ResilientJsonClient:
    def __init__(self, *, timeout: float, retries: int, requests_per_second: float, user_agent: str):
        self.retries = retries
        self.rate_limiter = AsyncRateLimiter(requests_per_second)
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )

    async def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            await self.rate_limiter.wait()
            try:
                response = await self.client.get(url, params=params)
                if response.status_code == 404:
                    return {}
                if response.status_code == 429 or response.status_code >= 500:
                    retry_after = _retry_after_seconds(response, attempt)
                    await asyncio.sleep(retry_after)
                    continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ProviderError(f"Expected JSON object from {url}")
                return payload
            except (httpx.HTTPError, ValueError, ProviderError) as exc:
                last_error = exc
                if attempt < self.retries:
                    await asyncio.sleep(min(8.0, 0.5 * (2**attempt)))
        raise ProviderError(f"Request failed after {self.retries + 1} attempts: {last_error}")

    async def aclose(self) -> None:
        await self.client.aclose()


def _retry_after_seconds(response: httpx.Response, attempt: int) -> float:
    raw = response.headers.get("retry-after", "")
    try:
        return min(30.0, max(0.5, float(raw)))
    except ValueError:
        return min(8.0, 0.5 * (2**attempt))

