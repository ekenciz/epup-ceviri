from __future__ import annotations

import json
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .chunker import build_chunks
from .glossary import Glossary, GlossaryEntry
from .xhtml import TextSegment, parse_document


class BookAnalysisError(RuntimeError):
    """Raised when EPUB analysis or glossary generation fails."""


ALLOWED_CATEGORIES = {
    "character",
    "place",
    "organization",
    "title",
    "term",
    "object",
    "species",
    "other",
}


@dataclass(frozen=True)
class GlossaryCandidate:
    source: str
    target: str
    category: str = "term"
    note: str | None = None
    confidence: float = 0.75

    def __post_init__(self) -> None:
        source = self.source.strip()
        target = self.target.strip()
        category = self.category.strip().lower() or "term"
        if category not in ALLOWED_CATEGORIES:
            category = "other"
        confidence = min(1.0, max(0.0, float(self.confidence)))
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "confidence", confidence)
        if self.note is not None:
            note = self.note.strip()
            object.__setattr__(self, "note", note or None)

    def to_glossary_entry(self) -> GlossaryEntry:
        return GlossaryEntry(
            source=self.source,
            target=self.target,
            note=self.note,
            category=self.category,
            confidence=self.confidence,
        )


@dataclass(frozen=True)
class BookAnalysisResult:
    glossary: Glossary
    analyzed_files: int
    analyzed_segments: int
    analysis_chunks: int
    raw_candidates: int


ANALYSIS_SYSTEM_PROMPT = """You are a literary translation terminology analyst.
Analyze the supplied excerpts from an English-language book and propose only glossary-worthy terms that should stay consistent across the full translation.

Include terms such as:
- character names or recurring epithets when they require a translation decision
- place names that should be translated consistently
- organizations, factions, institutions, ranks, titles and honorifics
- fictional species, objects, magic systems, invented terminology and recurring technical concepts
- repeated expressions whose translation consistency materially affects the book

Do NOT include:
- ordinary common words with no special book-specific meaning
- full sentences or long quotations
- terms that should obviously remain unchanged unless the glossary still helps explain that decision
- duplicate variants of the same source term

Return ONLY valid JSON in this exact shape:
{"entries":[{"source":"...","target":"...","category":"character|place|organization|title|term|object|species|other","note":"short optional context","confidence":0.0}]}

Rules:
1. Translate proposed targets into the requested target language.
2. Keep source terms exactly as they appear in the excerpt when practical.
3. confidence must be between 0 and 1.
4. Prefer precision over quantity.
5. Never add Markdown fences or explanatory prose.
6. Return at most 40 entries for a single analysis request.
7. Keep note fields concise (maximum about 80 characters).
8. Keep source and target values concise glossary terms, never paragraphs."""


def _strip_markdown_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_candidate_response(text: str) -> list[GlossaryCandidate]:
    try:
        payload = json.loads(_strip_markdown_fence(text))
    except json.JSONDecodeError as exc:
        raise BookAnalysisError(f"Analysis model returned invalid JSON: {exc}") from exc

    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise BookAnalysisError("Analysis response must contain an 'entries' array.")

    candidates: list[GlossaryCandidate] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip()
        target = str(item.get("target", "")).strip()
        if not source or not target:
            continue
        try:
            confidence = float(item.get("confidence", 0.75))
        except (TypeError, ValueError):
            confidence = 0.75
        candidates.append(
            GlossaryCandidate(
                source=source,
                target=target,
                category=str(item.get("category", "term")),
                note=None if item.get("note") is None else str(item.get("note")),
                confidence=confidence,
            )
        )
    return candidates



def _analysis_prompt(*, entry_limit: int, compact: bool = False) -> str:
    prompt = ANALYSIS_SYSTEM_PROMPT + (
        f"\nIMPORTANT FOR THIS REQUEST: Return at most {max(1, entry_limit)} entries."
    )
    if compact:
        prompt += (
            "\nThe previous response was too large or invalid. Be extremely concise: "
            "omit nonessential notes and include only the strongest glossary candidates."
        )
    return prompt


def _is_recoverable_analysis_error(exc: Exception) -> bool:
    """Errors where a smaller/shorter structured request is worth retrying."""
    message = str(exc).casefold()
    markers = (
        "invalid json",
        "empty response",
        "final content was empty",
        "finish_reason=length",
    )
    return any(marker in message for marker in markers)


def _split_chunk_for_retry(chunk):
    """Split a troublesome analysis chunk without losing source text."""
    segments = list(chunk.segments)
    if len(segments) > 1:
        midpoint = len(segments) // 2
        left = build_chunks(segments[:midpoint], max_tokens=max(1, chunk.estimated_tokens))[0]
        right = build_chunks(segments[midpoint:], max_tokens=max(1, chunk.estimated_tokens))[0]
        return [left, right]

    # One oversized segment: ask the regular chunker to split the text more finely.
    smaller_budget = max(256, chunk.estimated_tokens // 2)
    smaller = build_chunks(segments, max_tokens=smaller_budget)
    return smaller if len(smaller) > 1 else []


def _analyze_chunk_with_recovery(
    *,
    chunk,
    provider,
    target_language: str,
    max_output_tokens: int,
    temperature: float,
    retries: int,
    split_depth: int = 0,
    max_split_depth: int = 4,
) -> list[GlossaryCandidate]:
    excerpts = [segment.text for segment in chunk.segments]
    content = json.dumps(
        {"target_language": target_language, "excerpts": excerpts},
        ensure_ascii=False,
        separators=(",", ":"),
    )

    last_error: Exception | None = None
    entry_limit = 40
    for attempt in range(1, retries + 1):
        try:
            response = provider.translate(
                system_prompt=_analysis_prompt(
                    entry_limit=entry_limit,
                    compact=attempt > 1,
                ),
                content=content,
                max_tokens=max_output_tokens,
                temperature=temperature,
            )
            return _parse_candidate_response(response)
        except Exception as exc:
            last_error = exc
            if _is_recoverable_analysis_error(exc):
                # A response cut at max_tokens commonly leaves an unterminated JSON
                # string. Each retry asks for substantially less output.
                entry_limit = max(5, entry_limit // 2)

    if (
        last_error is not None
        and _is_recoverable_analysis_error(last_error)
        and split_depth < max_split_depth
    ):
        smaller_chunks = _split_chunk_for_retry(chunk)
        if smaller_chunks:
            recovered: list[GlossaryCandidate] = []
            for smaller_chunk in smaller_chunks:
                recovered.extend(
                    _analyze_chunk_with_recovery(
                        chunk=smaller_chunk,
                        provider=provider,
                        target_language=target_language,
                        max_output_tokens=max_output_tokens,
                        temperature=temperature,
                        retries=retries,
                        split_depth=split_depth + 1,
                        max_split_depth=max_split_depth,
                    )
                )
            return recovered

    if last_error is not None:
        raise last_error
    return []

def _iter_epub_text(epub_path: Path) -> tuple[list[str], int]:
    texts: list[str] = []
    analyzed_files = 0
    try:
        archive = zipfile.ZipFile(epub_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise BookAnalysisError(f"Could not open EPUB for analysis: {exc}") from exc

    with archive, tempfile.TemporaryDirectory(prefix="translate_epub_analysis_") as temp_dir:
        temp_root = Path(temp_dir)
        for index, info in enumerate(archive.infolist()):
            suffix = Path(info.filename).suffix.lower()
            if suffix not in {".xhtml", ".html", ".ncx"} or info.is_dir():
                continue
            try:
                raw = archive.read(info)
            except (KeyError, RuntimeError, OSError) as exc:
                raise BookAnalysisError(f"Could not read {info.filename}: {exc}") from exc

            temp_path = temp_root / f"doc-{index:06d}{suffix}"
            temp_path.write_bytes(raw)
            try:
                document = parse_document(temp_path)
            except Exception:
                # Some EPUBs contain malformed ancillary HTML/NCX. Translation will
                # report those files later; glossary analysis can safely skip them.
                continue
            analyzed_files += 1
            texts.extend(segment.text for segment in document.segments if segment.text.strip())

    return texts, analyzed_files


def _build_analysis_chunks(texts: Iterable[str], max_tokens: int):
    segments = [
        TextSegment(id=f"a{index:07d}", text=text, node_key=f"a{index:07d}")
        for index, text in enumerate(texts)
    ]
    return build_chunks(segments, max_tokens=max_tokens)


def _merge_candidates(
    candidates: Iterable[GlossaryCandidate],
    *,
    min_confidence: float,
    max_terms: int,
) -> Glossary:
    # Aggregate repeated proposals. Recurrence across different book chunks is a
    # useful signal that a term is genuinely book-wide rather than incidental.
    buckets: dict[tuple[str, str], list[GlossaryCandidate]] = {}
    for candidate in candidates:
        if candidate.confidence < min_confidence:
            continue
        if len(candidate.source.split()) > 8:
            continue
        if len(candidate.source) < 2 or len(candidate.target) < 1:
            continue
        key = (candidate.source.casefold(), candidate.target.casefold())
        buckets.setdefault(key, []).append(candidate)

    ranked: list[tuple[int, float, GlossaryCandidate]] = []
    for group in buckets.values():
        best = max(group, key=lambda item: item.confidence)
        average_confidence = sum(item.confidence for item in group) / len(group)
        ranked.append((len(group), average_confidence, best))

    ranked.sort(key=lambda item: (-item[0], -item[1], item[2].source.casefold()))

    # Resolve conflicting targets for the same source by keeping the strongest
    # aggregate proposal only.
    selected: list[GlossaryEntry] = []
    seen_sources: set[str] = set()
    for support, avg_confidence, candidate in ranked:
        source_key = candidate.source.casefold()
        if source_key in seen_sources:
            continue
        seen_sources.add(source_key)
        note_parts = []
        if candidate.note:
            note_parts.append(candidate.note)
        if support > 1:
            note_parts.append(f"Detected in {support} analysis chunks")
        selected.append(
            GlossaryEntry(
                source=candidate.source,
                target=candidate.target,
                note="; ".join(note_parts) or None,
                category=candidate.category,
                confidence=round(avg_confidence, 3),
            )
        )
        if len(selected) >= max_terms:
            break

    return Glossary(selected)


def analyze_book(
    *,
    epub_path: str | Path,
    provider,
    target_language: str,
    chunk_tokens: int = 6000,
    max_output_tokens: int = 4000,
    temperature: float = 0.1,
    retries: int = 3,
    min_confidence: float = 0.65,
    max_terms: int = 250,
    progress_callback=None,
) -> BookAnalysisResult:
    epub_path = Path(epub_path)
    texts, analyzed_files = _iter_epub_text(epub_path)
    chunks = _build_analysis_chunks(texts, max_tokens=chunk_tokens)
    all_candidates: list[GlossaryCandidate] = []

    for chunk_index, chunk in enumerate(chunks, start=1):
        try:
            all_candidates.extend(
                _analyze_chunk_with_recovery(
                    chunk=chunk,
                    provider=provider,
                    target_language=target_language,
                    max_output_tokens=max_output_tokens,
                    temperature=temperature,
                    retries=retries,
                )
            )
        except Exception as exc:
            raise BookAnalysisError(
                f"Book analysis failed on chunk {chunk_index}/{len(chunks)}: {exc}"
            ) from exc
        if progress_callback is not None:
            progress_callback(chunk_index, len(chunks), len(all_candidates))

    glossary = _merge_candidates(
        all_candidates,
        min_confidence=min_confidence,
        max_terms=max_terms,
    )
    return BookAnalysisResult(
        glossary=glossary,
        analyzed_files=analyzed_files,
        analyzed_segments=len(texts),
        analysis_chunks=len(chunks),
        raw_candidates=len(all_candidates),
    )
