from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core import (
    BookAnalysisError,
    Glossary,
    GlossaryEntry,
    GlossaryError,
    XHTMLProcessingError,
    analyze_book,
    build_chunks,
    parse_document,
)
from models import (
    BookAnalysisConfig,
    ConfigError,
    ProviderConfig,
    TranslationConfig,
    DEFAULT_ANALYSIS_CHUNK_TOKENS,
    DEFAULT_ANALYSIS_MAX_TERMS,
    DEFAULT_ANALYSIS_MAX_TOKENS,
    DEFAULT_ANALYSIS_MIN_CONFIDENCE,
    DEFAULT_ANALYSIS_TEMPERATURE,
    DEFAULT_CHUNK_TOKENS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_PROVIDER,
    DEFAULT_TARGET_LANGUAGE,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT,
    DEFAULT_WORKERS,
)
from providers import ProviderError, create_provider, get_provider_names

TEMP_FILE = "translation_progress.json"

lock = threading.RLock()
completed_count = 0
total_count = 0
failed_files: list[str] = []


def build_system_prompt(target_lang: str) -> str:
    return f"""You are a professional literary translator.
Translate each supplied text segment from English to {target_lang}.

STRICT RULES:
1. The input is JSON and contains segment IDs plus human-readable text only.
2. Translate only the text values. Never translate, rename, omit, or invent segment IDs.
3. Preserve meaning, tone, punctuation, and inline spacing as naturally as possible.
4. Return ONLY valid JSON in exactly this shape:
   {{"translations": {{"segment-id": "translated text"}}}}
5. Return one translation for every supplied segment ID and no additional IDs.
6. Do not use Markdown fences and do not add explanations."""



def build_glossary_prompt(
    base_prompt: str,
    entries: tuple[GlossaryEntry, ...],
    *,
    enforce: bool,
) -> str:
    if not entries:
        return base_prompt

    mode = (
        "These glossary translations are MANDATORY whenever the source term has the same meaning. "
        "Do not replace them with synonyms or alternate translations."
        if enforce
        else
        "Prefer these glossary translations whenever the source term has the same meaning, unless context makes them clearly inappropriate."
    )
    lines = ["", "GLOSSARY FOR THIS CHUNK:", mode]
    for entry in entries:
        line = f"- {entry.source} => {entry.target}"
        if entry.note:
            line += f" | Note: {entry.note}"
        lines.append(line)
    return base_prompt + "\n" + "\n".join(lines)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Translate EPUB text nodes using selectable AI providers."
    )
    parser.add_argument("input_epub", nargs="?", help="Input .epub file")
    parser.add_argument(
        "--provider",
        choices=get_provider_names(),
        default=DEFAULT_PROVIDER,
        help=f"AI provider (default: {DEFAULT_PROVIDER})",
    )
    parser.add_argument("--model", help="Provider model ID. Uses provider default if omitted.")
    parser.add_argument(
        "--target",
        default=DEFAULT_TARGET_LANGUAGE,
        help=f"Target language (default: {DEFAULT_TARGET_LANGUAGE})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel files (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--chunk-tokens",
        type=int,
        default=DEFAULT_CHUNK_TOKENS,
        help=(
            "Approximate maximum input tokens per translation chunk "
            f"(default: {DEFAULT_CHUNK_TOKENS})"
        ),
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"Maximum provider output tokens per chunk (default: {DEFAULT_MAX_TOKENS})",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help=f"Sampling temperature (default: {DEFAULT_TEMPERATURE})",
    )
    parser.add_argument("--retries", type=int, default=DEFAULT_MAX_RETRIES, help="Retries per chunk")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"API timeout in seconds (default: {DEFAULT_TIMEOUT:g})",
    )
    parser.add_argument(
        "--api-key-env",
        help="Override the provider's default API-key environment variable",
    )
    parser.add_argument(
        "--base-url",
        help="Override provider base URL (useful for remote Ollama or compatible servers)",
    )
    parser.add_argument(
        "--glossary",
        help="Path to glossary JSON file. Only matching entries are injected into each chunk.",
    )
    parser.add_argument(
        "--no-enforce-glossary",
        action="store_true",
        help="Provide glossary as preferred terminology instead of mandatory terminology.",
    )
    parser.add_argument(
        "--analyze-book",
        action="store_true",
        help="Analyze the EPUB, generate a glossary JSON, then exit.",
    )
    parser.add_argument(
        "--auto-glossary",
        action="store_true",
        help="Generate a glossary before translation and use it automatically.",
    )
    parser.add_argument(
        "--analysis-output",
        help="Output path for the generated glossary JSON (default: <book>-glossary.json).",
    )
    parser.add_argument(
        "--analysis-chunk-tokens",
        type=int,
        default=DEFAULT_ANALYSIS_CHUNK_TOKENS,
        help=f"Approximate input tokens per book-analysis request (default: {DEFAULT_ANALYSIS_CHUNK_TOKENS}).",
    )
    parser.add_argument(
        "--analysis-max-tokens",
        type=int,
        default=DEFAULT_ANALYSIS_MAX_TOKENS,
        help=f"Maximum output tokens per book-analysis request (default: {DEFAULT_ANALYSIS_MAX_TOKENS}).",
    )
    parser.add_argument(
        "--analysis-max-terms",
        type=int,
        default=DEFAULT_ANALYSIS_MAX_TERMS,
        help=f"Maximum generated glossary entries (default: {DEFAULT_ANALYSIS_MAX_TERMS}).",
    )
    parser.add_argument(
        "--analysis-min-confidence",
        type=float,
        default=DEFAULT_ANALYSIS_MIN_CONFIDENCE,
        help=f"Minimum generated-term confidence from 0 to 1 (default: {DEFAULT_ANALYSIS_MIN_CONFIDENCE}).",
    )
    parser.add_argument(
        "--analysis-temperature",
        type=float,
        default=DEFAULT_ANALYSIS_TEMPERATURE,
        help=f"Book-analysis sampling temperature (default: {DEFAULT_ANALYSIS_TEMPERATURE}).",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List models visible to the selected provider, then exit",
    )
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> TranslationConfig:
    return TranslationConfig(
        input_epub=Path(args.input_epub) if args.input_epub else None,
        target_language=args.target,
        workers=args.workers,
        chunk_tokens=args.chunk_tokens,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        retries=args.retries,
        glossary_path=Path(args.glossary) if args.glossary else None,
        enforce_glossary=not args.no_enforce_glossary,
        analysis=BookAnalysisConfig(
            enabled=args.analyze_book or args.auto_glossary,
            analysis_only=args.analyze_book,
            output_path=Path(args.analysis_output) if args.analysis_output else None,
            chunk_tokens=args.analysis_chunk_tokens,
            max_tokens=args.analysis_max_tokens,
            max_terms=args.analysis_max_terms,
            min_confidence=args.analysis_min_confidence,
            temperature=args.analysis_temperature,
        ),
        provider=ProviderConfig(
            name=args.provider,
            model=args.model,
            api_key_env=args.api_key_env,
            base_url=args.base_url,
            timeout=args.timeout,
        ),
    )


def load_progress(progress_file: str) -> dict:
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_progress_atomic(progress_file: str, progress_data: dict) -> None:
    with lock:
        tmp_file = progress_file + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(progress_data, f, indent=2)
        os.replace(tmp_file, progress_file)


def extract_epub_if_needed(epub_path: str, extract_to: str) -> None:
    if not os.path.exists(extract_to):
        print(f"📦 Extracting '{epub_path}'...")
        with zipfile.ZipFile(epub_path, "r") as zip_ref:
            zip_ref.extractall(extract_to)
    else:
        print(f"🔄 Resuming existing workspace '{extract_to}'...")


def create_epub(source_dir: str, output_epub: str) -> None:
    with zipfile.ZipFile(output_epub, "w") as zip_out:
        mimetype_path = os.path.join(source_dir, "mimetype")
        if os.path.exists(mimetype_path):
            zip_out.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
        for root, _dirs, files in os.walk(source_dir):
            for file in files:
                if file in ("mimetype", TEMP_FILE) or file.endswith(".tmp"):
                    continue
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, source_dir)
                zip_out.write(file_path, arcname, compress_type=zipfile.ZIP_DEFLATED)


def _strip_markdown_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _build_chunk_payload(chunk) -> str:
    return json.dumps(
        {
            "segments": [
                {"id": segment.id, "text": segment.text}
                for segment in chunk.segments
            ]
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _parse_chunk_response(response_text: str, expected_ids: tuple[str, ...]) -> dict[str, str]:
    cleaned = _strip_markdown_fence(response_text)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model returned invalid JSON: {exc}") from exc

    translations = payload.get("translations") if isinstance(payload, dict) else None
    if not isinstance(translations, dict):
        raise ValueError("Model response must contain a 'translations' JSON object.")

    expected = set(expected_ids)
    actual = set(translations.keys())
    missing = expected - actual
    extra = actual - expected
    if missing:
        raise ValueError(f"Model omitted segment IDs: {', '.join(sorted(missing))}")
    if extra:
        raise ValueError(f"Model invented segment IDs: {', '.join(sorted(extra))}")

    for segment_id, value in translations.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Translation for {segment_id} is empty or not a string.")

    return translations


def _validate_glossary_compliance(
    translations: dict[str, str],
    entries: tuple[GlossaryEntry, ...],
) -> None:
    if not entries:
        return
    translated_text = "\n".join(translations.values()).casefold()
    missing = [entry for entry in entries if entry.target.casefold() not in translated_text]
    if missing:
        terms = ", ".join(f"{entry.source} => {entry.target}" for entry in missing)
        raise ValueError(f"Glossary terms were not respected: {terms}")


def _is_structural_translation_error(exc: Exception) -> bool:
    """Return True when retrying the same large payload is unlikely to help.

    These failures normally mean the model produced truncated/malformed JSON or
    lost one or more segment IDs. In that case a smaller request is safer than
    repeatedly sending the exact same chunk.
    """
    message = str(exc).casefold()
    markers = (
        "invalid json",
        "omitted segment ids",
        "invented segment ids",
        "empty or not a string",
        "translations' json object",
        'translations" json object',
        "empty response",
        "final content was empty",
        "finish_reason=length",
    )
    return any(marker in message for marker in markers)


def _split_text_for_recovery(text: str) -> tuple[str, str] | None:
    """Split one segment near its midpoint without dropping source text."""
    if len(text) < 24:
        return None

    midpoint = len(text) // 2
    # Prefer a sentence/whitespace boundary close to the midpoint.
    candidates: list[int] = []
    for offset in range(0, min(midpoint, 1200) + 1):
        for pos in (midpoint - offset, midpoint + offset):
            if pos <= 0 or pos >= len(text):
                continue
            if text[pos].isspace():
                candidates.append(pos)
                break
        if candidates:
            break

    cut = candidates[0] if candidates else midpoint
    left = text[:cut].rstrip()
    right = text[cut:].lstrip()
    if not left or not right:
        return None
    return left, right


def _split_chunk_for_recovery(chunk):
    """Bisect a failing translation chunk.

    Multiple-segment chunks are split on segment boundaries. If only one text
    node remains, temporary child IDs are used and the caller later rejoins the
    two translated halves into the original segment ID.
    """
    from core import TextChunk, TextSegment, estimate_tokens

    segments = list(chunk.segments)
    if len(segments) >= 2:
        midpoint = max(1, len(segments) // 2)
        groups = (segments[:midpoint], segments[midpoint:])
        children = []
        for child_index, group in enumerate(groups):
            if not group:
                continue
            children.append(
                TextChunk(
                    index=chunk.index,
                    segments=tuple(group),
                    estimated_tokens=sum(estimate_tokens(s.text) for s in group),
                )
            )
        return tuple(children), None

    if not segments:
        return (), None

    original = segments[0]
    pieces = _split_text_for_recovery(original.text)
    if pieces is None:
        return (), None

    left, right = pieces
    children = (
        TextChunk(
            index=chunk.index,
            segments=(TextSegment(
                id=f"{original.id}__recoveryA",
                text=left,
                node_key=original.node_key,
            ),),
            estimated_tokens=estimate_tokens(left),
        ),
        TextChunk(
            index=chunk.index,
            segments=(TextSegment(
                id=f"{original.id}__recoveryB",
                text=right,
                node_key=original.node_key,
            ),),
            estimated_tokens=estimate_tokens(right),
        ),
    )
    return children, original.id


def _translate_chunk(
    *,
    provider,
    system_prompt: str,
    chunk,
    max_tokens: int,
    temperature: float,
    max_retries: int,
    fname: str,
    glossary: Glossary | None = None,
    enforce_glossary: bool = True,
    recovery_depth: int = 0,
    max_recovery_depth: int = 8,
    log_callback=None,
) -> dict[str, str]:
    """Translate one chunk with adaptive recovery for malformed model output.

    A large chunk that repeatedly returns malformed JSON or missing segment IDs
    is bisected recursively. This avoids failing an entire XHTML file because a
    local model cannot reliably emit one large JSON response.
    """
    payload = _build_chunk_payload(chunk)
    relevant_entries = (
        glossary.relevant_entries([segment.text for segment in chunk.segments])
        if glossary
        else ()
    )
    chunk_system_prompt = build_glossary_prompt(
        system_prompt, relevant_entries, enforce=enforce_glossary
    )
    last_error: Exception | None = None
    structural_failures = 0

    def emit(message: str) -> None:
        print(message)
        if log_callback is not None:
            log_callback(message)

    # Re-sending the same malformed large JSON three or more times usually just
    # wastes tokens. After two structural failures we prefer a smaller payload.
    direct_attempt_limit = min(max_retries, 2)

    for attempt in range(1, max_retries + 1):
        try:
            retry_prompt = chunk_system_prompt
            retry_temperature = temperature
            if attempt > 1:
                retry_temperature = 0.0
                retry_prompt += (
                    "\n\nRESPONSE RECOVERY RULES:\n"
                    "Return one complete, valid JSON object only. Do not use markdown.\n"
                    "Every input segment ID must appear exactly once in translations.\n"
                    "Do not add commentary before or after the JSON."
                )

            response = provider.translate(
                system_prompt=retry_prompt,
                content=payload,
                max_tokens=max_tokens,
                temperature=retry_temperature,
            )
            translations = _parse_chunk_response(response, chunk.segment_ids)
            if enforce_glossary:
                _validate_glossary_compliance(translations, relevant_entries)
            return translations
        except Exception as exc:
            last_error = exc
            structural = _is_structural_translation_error(exc)
            if structural:
                structural_failures += 1

            if attempt < max_retries:
                emit(
                    f"⚠️ {fname}: chunk {chunk.index + 1} attempt "
                    f"{attempt}/{max_retries} failed: {exc}"
                )

            should_split = (
                structural
                and structural_failures >= direct_attempt_limit
                and recovery_depth < max_recovery_depth
            )
            if should_split:
                children, rejoin_id = _split_chunk_for_recovery(chunk)
                if children:
                    emit(
                        f"↳ {fname}: chunk {chunk.index + 1} response is structurally "
                        f"invalid; splitting {len(chunk.segments)} segment(s) into "
                        f"{len(children)} smaller request(s) (recovery depth "
                        f"{recovery_depth + 1})."
                    )
                    merged: dict[str, str] = {}
                    for child in children:
                        child_result = _translate_chunk(
                            provider=provider,
                            system_prompt=system_prompt,
                            chunk=child,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            max_retries=max_retries,
                            fname=fname,
                            glossary=glossary,
                            enforce_glossary=enforce_glossary,
                            recovery_depth=recovery_depth + 1,
                            max_recovery_depth=max_recovery_depth,
                            log_callback=log_callback,
                        )
                        merged.update(child_result)

                    if rejoin_id is not None:
                        left_id = f"{rejoin_id}__recoveryA"
                        right_id = f"{rejoin_id}__recoveryB"
                        left_value = merged.pop(left_id)
                        right_value = merged.pop(right_id)
                        merged[rejoin_id] = left_value.rstrip() + " " + right_value.lstrip()
                    return merged

            if attempt < max_retries:
                time.sleep(2 * attempt)

    assert last_error is not None
    raise last_error


def translate_single_file(
    *,
    file_path: str,
    work_dir: str,
    progress_file: str,
    progress_data: dict,
    provider,
    system_prompt: str,
    chunk_tokens: int,
    max_tokens: int,
    temperature: float,
    max_retries: int,
    glossary: Glossary | None = None,
    enforce_glossary: bool = True,
) -> None:
    global completed_count

    fname = os.path.basename(file_path)
    rel_path = os.path.relpath(file_path, work_dir)

    if progress_data.get(rel_path) == "COMPLETED":
        with lock:
            completed_count += 1
            percent = (completed_count / total_count) * 100
            print(
                f"[{completed_count:02d}/{total_count:02d}] "
                f"({percent:5.1f}%) [⏩] Already done: {fname}"
            )
        return

    start_time = time.time()

    try:
        document = parse_document(file_path)
        chunks = build_chunks(document.segments, chunk_tokens)

        if not chunks:
            progress_data[rel_path] = "COMPLETED"
            save_progress_atomic(progress_file, progress_data)
            with lock:
                completed_count += 1
                percent = (completed_count / total_count) * 100
                print(
                    f"[{completed_count:02d}/{total_count:02d}] "
                    f"({percent:5.1f}%) [–] No translatable text: {fname}"
                )
            return

        translated_segments: dict[str, str] = {}
        for chunk in chunks:
            chunk_result = _translate_chunk(
                provider=provider,
                system_prompt=system_prompt,
                chunk=chunk,
                max_tokens=max_tokens,
                temperature=temperature,
                max_retries=max_retries,
                fname=fname,
                glossary=glossary,
                enforce_glossary=enforce_glossary,
            )
            translated_segments.update(chunk_result)

        document.apply_translations(translated_segments)
        rendered = document.serialize()

        tmp_file = file_path + ".tmp"
        with open(tmp_file, "wb") as f:
            f.write(rendered)
        os.replace(tmp_file, file_path)

        progress_data[rel_path] = "COMPLETED"
        save_progress_atomic(progress_file, progress_data)

        elapsed = time.time() - start_time
        with lock:
            completed_count += 1
            percent = (completed_count / total_count) * 100
            print(
                f"[{completed_count:02d}/{total_count:02d}] ({percent:5.1f}%) "
                f"[✓] Finished: {fname:<35} "
                f"({len(chunks)} chunks, {elapsed:4.1f}s)"
            )

    except Exception as exc:
        with lock:
            completed_count += 1
            failed_files.append(rel_path)
            print(
                f"[{completed_count:02d}/{total_count:02d}] "
                f"[❌] Failed: {fname} ({exc})"
            )


def _default_analysis_output(input_epub: Path) -> Path:
    return input_epub.with_name(f"{input_epub.stem}-glossary.json")


def _run_book_analysis(config: TranslationConfig, provider, existing_glossary: Glossary | None) -> tuple[Glossary, Path]:
    assert config.input_epub is not None
    output_path = config.analysis.output_path or _default_analysis_output(config.input_epub)

    print("\n🔎 Analyzing book terminology...")

    def report(current: int, total: int, candidates: int) -> None:
        print(f"   [{current:02d}/{total:02d}] analysis chunk complete — {candidates} raw candidates")

    result = analyze_book(
        epub_path=config.input_epub,
        provider=provider,
        target_language=config.target_language,
        chunk_tokens=config.analysis.chunk_tokens,
        max_output_tokens=config.analysis.max_tokens,
        temperature=config.analysis.temperature,
        retries=config.retries,
        min_confidence=config.analysis.min_confidence,
        max_terms=config.analysis.max_terms,
        progress_callback=report,
    )
    generated = result.glossary
    final_glossary = (
        existing_glossary.merged(generated, prefer_self=True)
        if existing_glossary
        else generated
    )
    final_glossary.save_json(output_path)

    print(f"📖 Analyzed files: {result.analyzed_files}")
    print(f"🧾 Analyzed text segments: {result.analyzed_segments}")
    print(f"🧠 Analysis requests: {result.analysis_chunks}")
    print(f"🔤 Raw glossary candidates: {result.raw_candidates}")
    print(f"📚 Final glossary entries: {len(final_glossary)}")
    print(f"💾 Glossary saved: {output_path}")
    return final_glossary, output_path


def main() -> None:
    global total_count, completed_count, failed_files

    args = parse_args()
    config = config_from_args(args)
    completed_count = 0
    failed_files = []

    try:
        config.validate(
            supported_providers=get_provider_names(),
            require_input=not args.list_models,
            check_input_exists=not args.list_models,
        )
        provider = create_provider(
            config.provider.name,
            model=config.provider.model,
            api_key=config.provider.api_key,
            api_key_env=config.provider.api_key_env,
            base_url=config.provider.base_url,
            timeout=config.provider.timeout,
        )
    except (ConfigError, ProviderError, ValueError) as exc:
        print(f"❌ Configuration error: {exc}")
        sys.exit(2)

    glossary: Glossary | None = None
    if config.glossary_path is not None:
        try:
            glossary = Glossary.load_json(config.glossary_path)
        except GlossaryError as exc:
            print(f"❌ Glossary error: {exc}")
            sys.exit(2)

    if args.list_models:
        try:
            for model_id in provider.list_models():
                print(model_id)
        except ProviderError as exc:
            print(f"❌ {exc}")
            sys.exit(2)
        return

    if config.analysis.enabled:
        try:
            glossary, _analysis_output = _run_book_analysis(config, provider, glossary)
        except (BookAnalysisError, GlossaryError, ProviderError, OSError, ValueError) as exc:
            print(f"❌ Book analysis error: {exc}")
            sys.exit(2)
        if config.analysis.analysis_only:
            return

    input_epub = str(config.input_epub)
    base_name = os.path.splitext(input_epub)[0]
    work_dir = "epub_quick_work"
    progress_file = os.path.join(work_dir, TEMP_FILE)
    output_epub = f"{base_name}-translated.epub"

    extract_epub_if_needed(input_epub, work_dir)
    progress_data = load_progress(progress_file)

    target_files: list[str] = []
    for root, _dirs, files in os.walk(work_dir):
        for file in files:
            if file.lower().endswith((".xhtml", ".html", ".ncx")):
                target_files.append(os.path.join(root, file))

    total_count = len(target_files)
    system_prompt = build_system_prompt(config.target_language)

    print(f"🔌 Provider: {provider.info.display_name}")
    print(f"🤖 Model: {provider.model}")
    print(f"🌍 Target: {config.target_language}")
    print(f"🧩 Chunk budget: ~{config.chunk_tokens} input tokens")
    print(f"📤 Max output: {config.max_tokens} tokens/chunk")
    if glossary:
        mode = "mandatory" if config.enforce_glossary else "preferred"
        print(f"📚 Glossary: {len(glossary)} entries ({mode}; relevant terms per chunk only)")
    print(f"🚀 Processing {total_count} files in parallel ({config.workers} threads)...\n")

    total_start = time.time()

    try:
        with ThreadPoolExecutor(max_workers=config.workers) as executor:
            futures = [
                executor.submit(
                    translate_single_file,
                    file_path=fp,
                    work_dir=work_dir,
                    progress_file=progress_file,
                    progress_data=progress_data,
                    provider=provider,
                    system_prompt=system_prompt,
                    chunk_tokens=config.chunk_tokens,
                    max_tokens=config.max_tokens,
                    temperature=config.temperature,
                    max_retries=config.retries,
                    glossary=glossary,
                    enforce_glossary=config.enforce_glossary,
                )
                for fp in target_files
            ]
            for future in futures:
                future.result()

    except KeyboardInterrupt:
        print("\n\n🛑 Process stopped by user (Ctrl+C).")
        print("💾 All completed files are safely saved in progress.")
        print("💡 Run the same command again whenever you want to resume.\n")
        sys.exit(0)

    total_time = time.time() - total_start

    if failed_files:
        print(
            f"\n⚠️ Finished with {len(failed_files)} failed file(s): "
            f"{', '.join(failed_files)}"
        )
        print("💡 Re-run the same command to retry the remaining files.")
    else:
        print(f"\n📦 Packaging into '{output_epub}'...")
        create_epub(work_dir, output_epub)
        shutil.rmtree(work_dir)
        print(f"\n🎉 DONE! All {total_count} files completed in {total_time:.1f}s.")
        print(f"📁 Output File: {output_epub}")


if __name__ == "__main__":
    main()
