from __future__ import annotations

import os
from typing import Optional

from .base import ProviderError, ProviderInfo, TranslationProvider


class OpenAICompatibleProvider(TranslationProvider):
    """Shared adapter for OpenAI-compatible Chat Completions endpoints.

    DeepSeek needs a small amount of provider-specific handling even though its
    HTTP interface is OpenAI-compatible. V4 models default to thinking mode and
    DeepSeek documents that JSON Output can occasionally return empty content.
    Structured translation/book-analysis calls therefore disable thinking, use
    JSON Output when the prompt explicitly requests JSON, and retry once without
    response_format if DeepSeek returns an empty JSON-mode response.
    """

    def __init__(
        self,
        *,
        info: ProviderInfo,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        api_key_env: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 180.0,
    ) -> None:
        self.info = info
        self._model = model or info.default_model

        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise ProviderError(
                "The 'openai' package is not installed. Run: pip install -r requirements.txt"
            ) from exc

        resolved_env = api_key_env or info.default_api_key_env
        resolved_key = api_key or (os.environ.get(resolved_env) if resolved_env else None)

        if info.requires_api_key and not resolved_key:
            env_hint = resolved_env or "the provider API key environment variable"
            raise ProviderError(
                f"{info.display_name} API key is missing. Set {env_hint} or pass --api-key-env."
            )

        if not resolved_key:
            resolved_key = "local-ollama"

        client_kwargs = {
            "api_key": resolved_key,
            "timeout": timeout,
        }
        resolved_base_url = base_url or info.default_base_url
        if resolved_base_url:
            client_kwargs["base_url"] = resolved_base_url

        self.client = OpenAI(**client_kwargs)

    @property
    def model(self) -> str:
        return self._model

    @staticmethod
    def _requests_json(system_prompt: str) -> bool:
        prompt = system_prompt.casefold()
        return (
            "return only valid json" in prompt
            or "return one complete, valid json" in prompt
            or "exact shape" in prompt and "json" in prompt
            or '"translations"' in prompt and "json" in prompt
        )

    def _completion_kwargs(
        self,
        *,
        system_prompt: str,
        content: str,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> dict:
        kwargs = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if self.info.name == "deepseek":
            # DeepSeek V4 defaults to thinking mode. For deterministic structured
            # translation/analysis tasks this can consume generation budget before
            # a final `content` answer is produced, so explicitly disable it.
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

        return kwargs

    def _extract_text(self, response) -> tuple[str | None, str | None, str | None]:
        try:
            choice = response.choices[0]
            message = choice.message
            content = message.content
            reasoning = getattr(message, "reasoning_content", None)
            finish_reason = getattr(choice, "finish_reason", None)
            return content, reasoning, finish_reason
        except (AttributeError, IndexError, TypeError) as exc:
            raise ProviderError(
                f"{self.info.display_name} returned an unexpected response format."
            ) from exc

    def translate(
        self,
        *,
        system_prompt: str,
        content: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        wants_json = self._requests_json(system_prompt)

        try:
            response = self.client.chat.completions.create(
                **self._completion_kwargs(
                    system_prompt=system_prompt,
                    content=content,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    json_mode=wants_json,
                )
            )
        except Exception as exc:
            raise ProviderError(
                f"{self.info.display_name} request failed for model '{self._model}': {exc}"
            ) from exc

        text, reasoning, finish_reason = self._extract_text(response)
        if text and text.strip():
            return text

        # DeepSeek explicitly documents that JSON Output may occasionally return
        # empty content. Retry once without response_format while keeping thinking
        # disabled; the prompt itself still requires valid JSON.
        if self.info.name == "deepseek" and wants_json:
            try:
                fallback_response = self.client.chat.completions.create(
                    **self._completion_kwargs(
                        system_prompt=system_prompt
                        + "\n\nIMPORTANT: Return the requested JSON object as final content. "
                        "Do not return an empty answer.",
                        content=content,
                        max_tokens=max_tokens,
                        temperature=0.0,
                        json_mode=False,
                    )
                )
            except Exception as exc:
                raise ProviderError(
                    f"DeepSeek returned empty JSON content and the fallback request failed: {exc}"
                ) from exc

            fallback_text, fallback_reasoning, fallback_finish = self._extract_text(
                fallback_response
            )
            if fallback_text and fallback_text.strip():
                return fallback_text
            reasoning = fallback_reasoning or reasoning
            finish_reason = fallback_finish or finish_reason

        details: list[str] = []
        if finish_reason:
            details.append(f"finish_reason={finish_reason}")
        if reasoning and not text:
            details.append("reasoning_content was present but final content was empty")
        suffix = f" ({'; '.join(details)})" if details else ""
        raise ProviderError(f"{self.info.display_name} returned an empty response{suffix}.")

    def list_models(self) -> list[str]:
        try:
            result = self.client.models.list()
            return sorted(model.id for model in result.data)
        except Exception as exc:
            raise ProviderError(
                f"Could not list models from {self.info.display_name}: {exc}"
            ) from exc
