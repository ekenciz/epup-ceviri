from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


DEFAULT_TARGET_LANGUAGE = "Turkish"
DEFAULT_WORKERS = 8
DEFAULT_CHUNK_TOKENS = 4000
DEFAULT_MAX_TOKENS = 12000
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 180.0
DEFAULT_PROVIDER = "openrouter"
DEFAULT_ANALYSIS_CHUNK_TOKENS = 6000
DEFAULT_ANALYSIS_MAX_TOKENS = 4000
DEFAULT_ANALYSIS_MAX_TERMS = 250
DEFAULT_ANALYSIS_MIN_CONFIDENCE = 0.65
DEFAULT_ANALYSIS_TEMPERATURE = 0.1


class ConfigError(ValueError):
    """Raised when translation configuration is invalid."""


@dataclass(frozen=True)
class ProviderConfig:
    """Provider-specific settings independent from CLI or GUI code."""

    name: str = DEFAULT_PROVIDER
    model: Optional[str] = None
    api_key: Optional[str] = field(default=None, repr=False)
    api_key_env: Optional[str] = None
    base_url: Optional[str] = None
    timeout: float = DEFAULT_TIMEOUT

    def validate(self, supported_providers: Optional[list[str]] = None) -> None:
        if not self.name or not self.name.strip():
            raise ConfigError("Provider name cannot be empty.")
        if supported_providers is not None and self.name not in supported_providers:
            supported = ", ".join(supported_providers)
            raise ConfigError(
                f"Unknown provider '{self.name}'. Supported providers: {supported}"
            )
        if self.timeout <= 0:
            raise ConfigError("Provider timeout must be greater than 0 seconds.")
        if self.model is not None and not self.model.strip():
            raise ConfigError("Model cannot be an empty string.")
        if self.base_url is not None and not self.base_url.strip():
            raise ConfigError("Base URL cannot be an empty string.")
        if self.api_key is not None and not self.api_key.strip():
            raise ConfigError("API key cannot be an empty string.")
        if self.api_key_env is not None and not self.api_key_env.strip():
            raise ConfigError("API key environment variable cannot be an empty string.")


@dataclass(frozen=True)
class BookAnalysisConfig:
    """Automatic glossary-generation settings shared by CLI and future GUI."""

    enabled: bool = False
    analysis_only: bool = False
    output_path: Optional[Path] = None
    chunk_tokens: int = DEFAULT_ANALYSIS_CHUNK_TOKENS
    max_tokens: int = DEFAULT_ANALYSIS_MAX_TOKENS
    max_terms: int = DEFAULT_ANALYSIS_MAX_TERMS
    min_confidence: float = DEFAULT_ANALYSIS_MIN_CONFIDENCE
    temperature: float = DEFAULT_ANALYSIS_TEMPERATURE

    def validate(self) -> None:
        if self.chunk_tokens < 1:
            raise ConfigError("Analysis chunk token budget must be at least 1.")
        if self.max_tokens < 1:
            raise ConfigError("Analysis max output tokens must be at least 1.")
        if self.max_terms < 1:
            raise ConfigError("Analysis max terms must be at least 1.")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ConfigError("Analysis minimum confidence must be between 0 and 1.")
        if self.temperature < 0:
            raise ConfigError("Analysis temperature cannot be negative.")
        if self.output_path is not None and self.output_path.suffix.lower() != ".json":
            raise ConfigError("Analysis output must have a .json extension.")


@dataclass(frozen=True)
class TranslationConfig:
    """Complete translation-job settings shared by CLI, GUI and the engine."""

    input_epub: Optional[Path] = None
    target_language: str = DEFAULT_TARGET_LANGUAGE
    workers: int = DEFAULT_WORKERS
    chunk_tokens: int = DEFAULT_CHUNK_TOKENS
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    retries: int = DEFAULT_MAX_RETRIES
    glossary_path: Optional[Path] = None
    enforce_glossary: bool = True
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    analysis: BookAnalysisConfig = field(default_factory=BookAnalysisConfig)

    def validate(
        self,
        *,
        supported_providers: Optional[list[str]] = None,
        require_input: bool = True,
        check_input_exists: bool = True,
    ) -> None:
        self.provider.validate(supported_providers)
        self.analysis.validate()

        if not self.target_language.strip():
            raise ConfigError("Target language cannot be empty.")
        if self.workers < 1:
            raise ConfigError("Workers must be at least 1.")
        if self.chunk_tokens < 1:
            raise ConfigError("Chunk token budget must be at least 1.")
        if self.max_tokens < 1:
            raise ConfigError("Maximum output tokens must be at least 1.")
        if self.retries < 1:
            raise ConfigError("Retries must be at least 1.")
        if self.temperature < 0:
            raise ConfigError("Temperature cannot be negative.")

        if self.glossary_path is not None:
            if self.glossary_path.suffix.lower() != ".json":
                raise ConfigError("Glossary file must have a .json extension.")
            if check_input_exists and not self.glossary_path.exists():
                raise ConfigError(f"Glossary file does not exist: {self.glossary_path}")
            if check_input_exists and not self.glossary_path.is_file():
                raise ConfigError(f"Glossary path is not a file: {self.glossary_path}")

        if require_input and self.input_epub is None:
            raise ConfigError("Input EPUB is required.")
        if self.input_epub is not None:
            if self.input_epub.suffix.lower() != ".epub":
                raise ConfigError("Input file must have an .epub extension.")
            if check_input_exists and not self.input_epub.exists():
                raise ConfigError(f"Input EPUB does not exist: {self.input_epub}")
            if check_input_exists and not self.input_epub.is_file():
                raise ConfigError(f"Input EPUB is not a file: {self.input_epub}")
