from pathlib import Path

from core import build_chunks, parse_document


def test_parser_skips_non_translatable_blocks(tmp_path: Path) -> None:
    path = tmp_path / "chapter.xhtml"
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p id="p1"> Hello <em>world</em>.</p>'
        '<style>body{color:red}</style><script>noop()</script>'
        '</body></html>',
        encoding="utf-8",
    )
    doc = parse_document(path)
    assert [segment.text for segment in doc.segments] == ["Hello", "world"]

    chunks = build_chunks(doc.segments, max_tokens=2)
    translations = {
        segment.id: "TR:" + segment.text
        for chunk in chunks
        for segment in chunk.segments
    }
    doc.apply_translations(translations)
    rendered = doc.serialize().decode("utf-8")

    assert 'id="p1"' in rendered
    assert "TR:Hello" in rendered
    assert "TR:world" in rendered
    assert "body{color:red}" in rendered
    assert "noop()" in rendered


def test_large_node_is_split() -> None:
    from core.xhtml import TextSegment

    segment = TextSegment(
        id="s000001",
        text="one two three four five six seven eight nine ten",
        node_key="s000001",
    )
    chunks = build_chunks([segment], max_tokens=3)
    ids = [sid for chunk in chunks for sid in chunk.segment_ids]
    assert len(ids) > 1
    assert all("__part" in sid for sid in ids)


def test_glossary_json_roundtrip_and_relevance(tmp_path: Path) -> None:
    from core import Glossary, GlossaryEntry

    glossary = Glossary(
        [
            GlossaryEntry(
                source="The Watcher",
                target="Gözcü",
                note="Character title",
            ),
            GlossaryEntry(source="Maester", target="Üstat"),
            GlossaryEntry(
                source="NASA",
                target="NASA",
                case_sensitive=True,
            ),
        ]
    )
    path = tmp_path / "glossary.json"
    glossary.save_json(path)
    loaded = Glossary.load_json(path)

    assert loaded.entries == glossary.entries
    relevant = loaded.relevant_entries(
        ["The Watcher entered the hall.", "A maester waited there.", "nasa was absent."]
    )
    assert [entry.source for entry in relevant] == ["The Watcher", "Maester"]


def test_glossary_whole_word_avoids_partial_match() -> None:
    from core import Glossary, GlossaryEntry

    glossary = Glossary([GlossaryEntry(source="art", target="sanat")])
    assert glossary.relevant_entries("earth") == ()
    assert glossary.relevant_entries("art matters")[0].target == "sanat"


def test_only_relevant_glossary_entries_are_injected() -> None:
    from core import Glossary, GlossaryEntry
    from core.xhtml import TextSegment
    import sys
    import types

    if "openai" not in sys.modules:
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = object
        sys.modules["openai"] = fake_openai

    from translate_epub import _translate_chunk, build_system_prompt

    class FakeProvider:
        def __init__(self) -> None:
            self.prompts = []

        def translate(self, *, system_prompt, content, max_tokens, temperature):
            import json

            self.prompts.append(system_prompt)
            payload = json.loads(content)
            return json.dumps(
                {
                    "translations": {
                        segment["id"]: ("TR:" + segment["text"]).replace("Watcher", "Gözcü")
                        for segment in payload["segments"]
                    }
                },
                ensure_ascii=False,
            )

    glossary = Glossary(
        [
            GlossaryEntry(source="Watcher", target="Gözcü"),
            GlossaryEntry(source="Winterfell", target="Kışyarı"),
        ]
    )
    chunk = build_chunks(
        [TextSegment(id="s1", text="The Watcher arrived.", node_key="s1")],
        max_tokens=100,
    )[0]
    provider = FakeProvider()

    result = _translate_chunk(
        provider=provider,
        system_prompt=build_system_prompt("Turkish"),
        chunk=chunk,
        max_tokens=1000,
        temperature=0.2,
        max_retries=1,
        fname="chapter.xhtml",
        glossary=glossary,
        enforce_glossary=True,
    )

    assert result["s1"] == "TR:The Gözcü arrived."
    prompt = provider.prompts[0]
    assert "Watcher => Gözcü" in prompt
    assert "Winterfell" not in prompt
    assert "MANDATORY" in prompt


def test_generated_glossary_metadata_roundtrip(tmp_path: Path) -> None:
    from core import Glossary, GlossaryEntry

    glossary = Glossary([
        GlossaryEntry(
            source="The Watcher",
            target="Gözcü",
            category="title",
            confidence=0.91,
            note="Recurring epithet",
        )
    ])
    path = tmp_path / "generated.json"
    glossary.save_json(path)
    loaded = Glossary.load_json(path)
    assert loaded.entries[0].category == "title"
    assert loaded.entries[0].confidence == 0.91


def test_manual_glossary_wins_when_merged() -> None:
    from core import Glossary, GlossaryEntry

    manual = Glossary([GlossaryEntry(source="Watcher", target="Gözcü")])
    generated = Glossary([
        GlossaryEntry(source="Watcher", target="İzleyici", confidence=0.95),
        GlossaryEntry(source="Maester", target="Üstat", confidence=0.9),
    ])
    merged = manual.merged(generated)
    assert [(entry.source, entry.target) for entry in merged.entries] == [
        ("Watcher", "Gözcü"),
        ("Maester", "Üstat"),
    ]


def test_book_analysis_builds_glossary_from_epub(tmp_path: Path) -> None:
    import json
    import zipfile
    from core import analyze_book

    epub = tmp_path / "book.epub"
    chapter = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p>The Watcher arrived at Winterfell.</p>'
        '<p>The Watcher spoke to the Maester.</p>'
        '</body></html>'
    )
    with zipfile.ZipFile(epub, "w") as archive:
        archive.writestr("OEBPS/chapter.xhtml", chapter)

    class FakeProvider:
        def translate(self, *, system_prompt, content, max_tokens, temperature):
            payload = json.loads(content)
            joined = " ".join(payload["excerpts"])
            entries = []
            if "Watcher" in joined:
                entries.append({
                    "source": "The Watcher",
                    "target": "Gözcü",
                    "category": "title",
                    "note": "Recurring title",
                    "confidence": 0.95,
                })
            if "Winterfell" in joined:
                entries.append({
                    "source": "Winterfell",
                    "target": "Kışyarı",
                    "category": "place",
                    "confidence": 0.9,
                })
            return json.dumps({"entries": entries}, ensure_ascii=False)

    result = analyze_book(
        epub_path=epub,
        provider=FakeProvider(),
        target_language="Turkish",
        chunk_tokens=100,
        max_output_tokens=1000,
        max_terms=10,
        min_confidence=0.5,
        retries=1,
    )
    assert result.analyzed_files == 1
    assert result.analyzed_segments == 2
    assert {entry.source for entry in result.glossary.entries} == {"The Watcher", "Winterfell"}


def test_book_analysis_recovers_from_truncated_json(tmp_path: Path) -> None:
    import json
    import zipfile
    from core import analyze_book

    epub = tmp_path / "book.epub"
    chapter = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p>The Watcher arrived at Winterfell.</p>'
        '</body></html>'
    )
    with zipfile.ZipFile(epub, "w") as archive:
        archive.writestr("OEBPS/chapter.xhtml", chapter)

    class TruncatingThenConciseProvider:
        def __init__(self) -> None:
            self.calls = 0
            self.prompts = []

        def translate(self, *, system_prompt, content, max_tokens, temperature):
            self.calls += 1
            self.prompts.append(system_prompt)
            if self.calls == 1:
                return '{"entries":[{"source":"The Watcher","target":"Gözcü"'
            return json.dumps({
                "entries": [{
                    "source": "The Watcher",
                    "target": "Gözcü",
                    "category": "title",
                    "confidence": 0.95,
                }]
            }, ensure_ascii=False)

    provider = TruncatingThenConciseProvider()
    result = analyze_book(
        epub_path=epub,
        provider=provider,
        target_language="Turkish",
        chunk_tokens=100,
        max_output_tokens=100,
        max_terms=10,
        min_confidence=0.5,
        retries=2,
    )
    assert provider.calls == 2
    assert "at most 20 entries" in provider.prompts[1]
    assert result.glossary.entries[0].target == "Gözcü"


def test_translation_chunk_recovers_by_splitting_after_invalid_json() -> None:
    import json
    import sys
    import types
    from core import build_chunks
    from core.xhtml import TextSegment

    if "openai" not in sys.modules:
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = object
        sys.modules["openai"] = fake_openai

    from translate_epub import _translate_chunk, build_system_prompt

    class SizeSensitiveProvider:
        def __init__(self) -> None:
            self.calls = []

        def translate(self, *, system_prompt, content, max_tokens, temperature):
            payload = json.loads(content)
            ids = [item["id"] for item in payload["segments"]]
            self.calls.append(ids)
            if len(ids) > 2:
                return '{"translations":{"' + ids[0] + '":"broken"'
            return json.dumps({
                "translations": {
                    item["id"]: "TR:" + item["text"]
                    for item in payload["segments"]
                }
            }, ensure_ascii=False)

    segments = [
        TextSegment(id=f"s{i:06d}", text=f"sentence {i}", node_key=f"s{i:06d}")
        for i in range(8)
    ]
    chunk = build_chunks(segments, max_tokens=1000)[0]
    provider = SizeSensitiveProvider()
    logs = []

    result = _translate_chunk(
        provider=provider,
        system_prompt=build_system_prompt("Turkish"),
        chunk=chunk,
        max_tokens=1000,
        temperature=0.2,
        max_retries=3,
        fname="chapter.xhtml",
        log_callback=logs.append,
    )

    assert len(result) == 8
    assert all(result[f"s{i:06d}"] == f"TR:sentence {i}" for i in range(8))
    assert any("splitting" in line for line in logs)
    assert any(len(call) <= 2 for call in provider.calls)


def test_translation_chunk_recovers_from_omitted_segment_ids() -> None:
    import json
    import sys
    import types
    from core import build_chunks
    from core.xhtml import TextSegment

    if "openai" not in sys.modules:
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = object
        sys.modules["openai"] = fake_openai

    from translate_epub import _translate_chunk, build_system_prompt

    class OmittingProvider:
        def translate(self, *, system_prompt, content, max_tokens, temperature):
            payload = json.loads(content)
            items = payload["segments"]
            if len(items) > 1:
                items = items[:1]
            return json.dumps({
                "translations": {
                    item["id"]: "TR:" + item["text"] for item in items
                }
            }, ensure_ascii=False)

    segments = [
        TextSegment(id=f"s{i:06d}", text=f"line {i}", node_key=f"s{i:06d}")
        for i in range(4)
    ]
    chunk = build_chunks(segments, max_tokens=1000)[0]
    result = _translate_chunk(
        provider=OmittingProvider(),
        system_prompt=build_system_prompt("Turkish"),
        chunk=chunk,
        max_tokens=1000,
        temperature=0.2,
        max_retries=3,
        fname="chapter.xhtml",
    )

    assert len(result) == 4
    assert result["s000003"] == "TR:line 3"


def test_translation_parser_recovers_back_to_back_json_objects() -> None:
    import json
    import sys
    import types

    if "openai" not in sys.modules:
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = object
        sys.modules["openai"] = fake_openai

    from translate_epub import _parse_chunk_response

    response = (
        json.dumps({"translations": {"s1": "Bir"}}, ensure_ascii=False)
        + "\n"
        + json.dumps({"translations": {"s2": "İki"}}, ensure_ascii=False)
    )
    assert _parse_chunk_response(response, ("s1", "s2")) == {
        "s1": "Bir",
        "s2": "İki",
    }


def test_glossary_miss_warns_but_does_not_fail_valid_translation() -> None:
    import json
    import sys
    import types

    if "openai" not in sys.modules:
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = object
        sys.modules["openai"] = fake_openai

    from core import Glossary, GlossaryEntry
    from core.xhtml import TextSegment
    from translate_epub import _translate_chunk, build_system_prompt

    class FakeProvider:
        def translate(self, *, system_prompt, content, max_tokens, temperature):
            payload = json.loads(content)
            return json.dumps({
                "translations": {
                    item["id"]: "Muhafazakar Parti hakkında not."
                    for item in payload["segments"]
                }
            }, ensure_ascii=False)

    chunk = build_chunks(
        [TextSegment(id="s1", text="Conservative Party note.", node_key="s1")],
        max_tokens=100,
    )[0]
    logs = []
    result = _translate_chunk(
        provider=FakeProvider(),
        system_prompt=build_system_prompt("Turkish"),
        chunk=chunk,
        max_tokens=1000,
        temperature=0.2,
        max_retries=1,
        fname="notes.xhtml",
        glossary=Glossary([
            GlossaryEntry(source="Conservative Party", target="Muhafazakâr Parti")
        ]),
        enforce_glossary=True,
        log_callback=logs.append,
    )
    assert result["s1"] == "Muhafazakar Parti hakkında not."
    assert any("accepting valid translation after glossary retries" in line for line in logs)


def test_many_tiny_segments_are_pre_split_before_provider_call() -> None:
    import json
    import sys
    import types

    if "openai" not in sys.modules:
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = object
        sys.modules["openai"] = fake_openai

    from core import TextChunk
    from core.xhtml import TextSegment
    from translate_epub import _translate_chunk, build_system_prompt

    class FakeProvider:
        def __init__(self):
            self.max_seen = 0

        def translate(self, *, system_prompt, content, max_tokens, temperature):
            payload = json.loads(content)
            self.max_seen = max(self.max_seen, len(payload["segments"]))
            assert len(payload["segments"]) <= 64
            return json.dumps({
                "translations": {
                    item["id"]: "TR:" + item["text"]
                    for item in payload["segments"]
                }
            }, ensure_ascii=False)

    segments = tuple(
        TextSegment(id=f"s{i:06d}", text=f"note {i}", node_key=f"n{i}")
        for i in range(130)
    )
    chunk = TextChunk(index=0, segments=segments, estimated_tokens=130)
    provider = FakeProvider()
    result = _translate_chunk(
        provider=provider,
        system_prompt=build_system_prompt("Turkish"),
        chunk=chunk,
        max_tokens=4000,
        temperature=0.2,
        max_retries=1,
        fname="notes.xhtml",
    )
    assert len(result) == 130
    assert provider.max_seen <= 64


def test_translation_parser_accepts_direct_segment_map() -> None:
    import json
    import sys
    import types

    if "openai" not in sys.modules:
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = object
        sys.modules["openai"] = fake_openai

    from translate_epub import _parse_chunk_response

    response = json.dumps({"s1": "Bir", "s2": "Iki"}, ensure_ascii=False)
    assert _parse_chunk_response(response, ("s1", "s2")) == {
        "s1": "Bir",
        "s2": "Iki",
    }


def test_source_equals_target_glossary_does_not_trigger_retry() -> None:
    import json
    import sys
    import types

    if "openai" not in sys.modules:
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = object
        sys.modules["openai"] = fake_openai

    from core import Glossary, GlossaryEntry, build_chunks
    from core.xhtml import TextSegment
    from translate_epub import _translate_chunk, build_system_prompt

    class CountingProvider:
        def __init__(self) -> None:
            self.calls = 0

        def translate(self, *, system_prompt, content, max_tokens, temperature):
            self.calls += 1
            payload = json.loads(content)
            return json.dumps({
                "translations": {
                    item["id"]: "Sinav hakkinda bir cumle."
                    for item in payload["segments"]
                }
            }, ensure_ascii=False)

    provider = CountingProvider()
    chunk = build_chunks(
        [TextSegment(id="s1", text="SAT is discussed here.", node_key="s1")],
        max_tokens=100,
    )[0]
    result = _translate_chunk(
        provider=provider,
        system_prompt=build_system_prompt("Turkish"),
        chunk=chunk,
        max_tokens=1000,
        temperature=0.2,
        max_retries=3,
        fname="chapter.xhtml",
        glossary=Glossary([GlossaryEntry(source="SAT", target="SAT")]),
        enforce_glossary=True,
    )
    assert result["s1"] == "Sinav hakkinda bir cumle."
    assert provider.calls == 1


def test_single_segment_structural_failure_uses_plain_text_fallback() -> None:
    import json
    import sys
    import types

    if "openai" not in sys.modules:
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = object
        sys.modules["openai"] = fake_openai

    from core import build_chunks
    from core.xhtml import TextSegment
    from translate_epub import _translate_chunk, build_system_prompt

    class JsonBrokenPlainGoodProvider:
        def __init__(self) -> None:
            self.calls = []

        def translate(self, *, system_prompt, content, max_tokens, temperature):
            self.calls.append(content)
            if content.lstrip().startswith("{"):
                return '{"translations": {'
            return "Duz metin ceviri"

    provider = JsonBrokenPlainGoodProvider()
    chunk = build_chunks(
        [TextSegment(id="s1", text="A short sentence.", node_key="s1")],
        max_tokens=100,
    )[0]
    logs = []
    result = _translate_chunk(
        provider=provider,
        system_prompt=build_system_prompt("Turkish"),
        chunk=chunk,
        max_tokens=1000,
        temperature=0.2,
        max_retries=3,
        fname="chapter.xhtml",
        log_callback=logs.append,
    )
    assert result == {"s1": "Duz metin ceviri"}
    assert len(provider.calls) == 2
    assert any("plain-text fallback" in line for line in logs)


def test_many_tiny_segments_are_pre_split_at_24() -> None:
    import json
    import sys
    import types

    if "openai" not in sys.modules:
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = object
        sys.modules["openai"] = fake_openai

    from core import TextChunk
    from core.xhtml import TextSegment
    from translate_epub import _translate_chunk, build_system_prompt

    class FakeProvider:
        def __init__(self):
            self.max_seen = 0

        def translate(self, *, system_prompt, content, max_tokens, temperature):
            payload = json.loads(content)
            self.max_seen = max(self.max_seen, len(payload["segments"]))
            assert len(payload["segments"]) <= 24
            return json.dumps({
                "translations": {
                    item["id"]: "TR:" + item["text"]
                    for item in payload["segments"]
                }
            }, ensure_ascii=False)

    segments = tuple(
        TextSegment(id=f"s{i:06d}", text=f"note {i}", node_key=f"n{i}")
        for i in range(100)
    )
    chunk = TextChunk(index=0, segments=segments, estimated_tokens=100)
    provider = FakeProvider()
    result = _translate_chunk(
        provider=provider,
        system_prompt=build_system_prompt("Turkish"),
        chunk=chunk,
        max_tokens=4000,
        temperature=0.2,
        max_retries=1,
        fname="notes.xhtml",
    )
    assert len(result) == 100
    assert provider.max_seen <= 24
