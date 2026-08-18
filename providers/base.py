from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


class ProviderError(RuntimeError):
    """Raised when an AI provider cannot be configured or called."""


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    display_name: str
    requires_api_key: bool
    default_api_key_env: Optional[str]
    default_base_url: Optional[str]
    default_model: str


class TranslationProvider(ABC):
    """Provider-neutral interface used by the EPUB translation engine."""

    info: ProviderInfo

    @property
    @abstractmethod
    def model(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def translate(
        self,
        *,
        system_prompt: str,
        content: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Translate content and return only the assistant text."""
        raise NotImplementedError

    def list_models(self) -> list[str]:
        """Return available model IDs when the provider supports model listing."""
        return []
