from __future__ import annotations

from typing import Optional

from .base import ProviderInfo, TranslationProvider
from .openai_compatible import OpenAICompatibleProvider


PROVIDERS: dict[str, ProviderInfo] = {
    "openrouter": ProviderInfo(
        name="openrouter",
        display_name="OpenRouter",
        requires_api_key=True,
        default_api_key_env="OPENROUTER_API_KEY",
        default_base_url="https://openrouter.ai/api/v1",
        default_model="deepseek/deepseek-v4-flash",
    ),
    "openai": ProviderInfo(
        name="openai",
        display_name="OpenAI",
        requires_api_key=True,
        default_api_key_env="OPENAI_API_KEY",
        default_base_url=None,
        default_model="gpt-5",
    ),
    "deepseek": ProviderInfo(
        name="deepseek",
        display_name="DeepSeek",
        requires_api_key=True,
        default_api_key_env="DEEPSEEK_API_KEY",
        default_base_url="https://api.deepseek.com",
        default_model="deepseek-v4-flash",
    ),
    "google": ProviderInfo(
        name="google",
        display_name="Google Gemini",
        requires_api_key=True,
        default_api_key_env="GEMINI_API_KEY",
        default_base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-3.6-flash",
    ),
    "ollama": ProviderInfo(
        name="ollama",
        display_name="Ollama",
        requires_api_key=False,
        default_api_key_env=None,
        default_base_url="http://localhost:11434/v1/",
        default_model="llama3.2",
    ),
}


def get_provider_names() -> list[str]:
    return list(PROVIDERS.keys())


def create_provider(
    provider_name: str,
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    api_key_env: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 180.0,
) -> TranslationProvider:
    key = provider_name.strip().lower()
    if key not in PROVIDERS:
        supported = ", ".join(PROVIDERS)
        raise ValueError(f"Unknown provider '{provider_name}'. Supported: {supported}")

    return OpenAICompatibleProvider(
        info=PROVIDERS[key],
        model=model,
        api_key=api_key,
        api_key_env=api_key_env,
        base_url=base_url,
        timeout=timeout,
    )
