from __future__ import annotations

import zipfile
from pathlib import Path

from models import BookAnalysisConfig, ProviderConfig, TranslationConfig
from services import job_runner


class FakeInfo:
    display_name = "Fake"


class FakeProvider:
    info = FakeInfo()
    model = "fake-model"

    def translate(self, *, system_prompt: str, content: str, max_tokens: int, temperature: float) -> str:
        import json
        payload = json.loads(content)
        return json.dumps({
            "translations": {
                item["id"]: "TR:" + item["text"]
                for item in payload["segments"]
            }
        }, ensure_ascii=False)


def make_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("OEBPS/chapter.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Hello world.</p></body></html>')


def test_programmatic_translation_job(tmp_path, monkeypatch):
    source = tmp_path / "book.epub"
    make_epub(source)
    monkeypatch.setattr(job_runner, "_provider_from_config", lambda config: FakeProvider())
    config = TranslationConfig(
        input_epub=source,
        target_language="Turkish",
        workers=1,
        chunk_tokens=1000,
        max_tokens=1000,
        provider=ProviderConfig(name="ollama", model="fake-model"),
        analysis=BookAnalysisConfig(enabled=False),
    )
    progress = []
    result = job_runner.run_translation_job(
        config,
        progress_callback=lambda current, total, path: progress.append((current, total, path)),
    )
    assert result.output_path is not None
    assert result.output_path.exists()
    assert progress and progress[-1][0] == progress[-1][1] == 1
    with zipfile.ZipFile(result.output_path) as zf:
        chapter = zf.read("OEBPS/chapter.xhtml").decode("utf-8")
    assert "TR:Hello world." in chapter
    assert not (tmp_path / ".book.translate-epub-work").exists()
