import json
import sys
import types
import zipfile
from pathlib import Path


def _response(content=None, reasoning=None, finish_reason="stop"):
    message = types.SimpleNamespace(content=content, reasoning_content=reasoning)
    choice = types.SimpleNamespace(message=message, finish_reason=finish_reason)
    return types.SimpleNamespace(choices=[choice])


def test_deepseek_disables_thinking_and_falls_back_from_empty_json(monkeypatch):
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return _response(content="", reasoning="long reasoning")
            return _response(content='{"entries":[]}')

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = types.SimpleNamespace(completions=Completions())
            self.models = types.SimpleNamespace(list=lambda: types.SimpleNamespace(data=[]))

    fake_module = types.ModuleType("openai")
    fake_module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_module)

    from providers.factory import create_provider

    provider = create_provider("deepseek", api_key="test-key", model="deepseek-v4-flash")
    result = provider.translate(
        system_prompt="Return ONLY valid JSON in this exact shape: {\"entries\":[]}",
        content='{"excerpts":["hello"]}',
        max_tokens=4000,
        temperature=0.1,
    )

    assert result == '{"entries":[]}'
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[1]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "response_format" not in calls[1]
    assert calls[1]["temperature"] == 0.0


def test_book_analysis_retries_provider_empty_response(tmp_path: Path):
    from core import analyze_book
    from providers.base import ProviderError

    epub = tmp_path / "book.epub"
    chapter = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p>The Watcher arrived.</p>'
        '</body></html>'
    )
    with zipfile.ZipFile(epub, "w") as archive:
        archive.writestr("OEBPS/chapter.xhtml", chapter)

    class EmptyThenGoodProvider:
        def __init__(self):
            self.calls = 0

        def translate(self, *, system_prompt, content, max_tokens, temperature):
            self.calls += 1
            if self.calls == 1:
                raise ProviderError("DeepSeek returned an empty response.")
            return json.dumps({
                "entries": [{
                    "source": "The Watcher",
                    "target": "Gözcü",
                    "category": "title",
                    "confidence": 0.95,
                }]
            }, ensure_ascii=False)

    provider = EmptyThenGoodProvider()
    result = analyze_book(
        epub_path=epub,
        provider=provider,
        target_language="Turkish",
        chunk_tokens=100,
        max_output_tokens=1000,
        max_terms=10,
        min_confidence=0.5,
        retries=2,
    )
    assert provider.calls == 2
    assert result.glossary.entries[0].target == "Gözcü"
