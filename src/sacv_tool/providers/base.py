from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Citation, ProviderCandidate


class ProviderError(RuntimeError):
    pass


class MetadataProvider(ABC):
    name: str

    @abstractmethod
    async def search(self, citation: Citation) -> list[ProviderCandidate]:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None

