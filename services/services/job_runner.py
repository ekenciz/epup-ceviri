from __future__ import annotations

import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core import Glossary, GlossaryEntry, analyze_book, build_chunks, parse_document
from models import TranslationConfig
from providers import create_provider, get_provider_names
from translate_epub import (
    TEMP_FILE,
    _default_analysis_output,
    _translate_chunk,
    build_system_prompt,
    create_epub,
    extract_epub_if_needed,
    load_progress,
    save_progress_atomic,
)

LogCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int, str], None]
AnalysisProgressCallback = Callable[[int, int, int], None]


class JobCancelled(RuntimeError):
    """Raised when a GUI/user cancellation request stops a job safely."""


@dataclass(frozen=True)
class JobResult:
    output_path: Path | None = None
    glossary_path: Path | None = None
    glossary: Glossary | None = None
    failed_files: tuple[str, ...] = ()


def _log(callback: LogCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _provider_from_config(config: TranslationConfig):
    config.validate(
        supported_providers=get_provider_names(),
        require_input=True,
        check_input_exists=True,
    )
    return create_provider(
        config.provider.name,
        model=config.provider.model,
        api_key=config.provider.api_key,
        api_key_env=config.provider.api_key_env,
        base_url=config.provider.base_url,
        timeout=config.provider.timeout,
    )


def _safe_work_dir(input_epub: Path) -> Path:
    # One workspace per source book prevents progress from another EPUB being reused.
    return input_epub.parent / f".{input_epub.stem}.translate-epub-work"


def run_book_analysis_job(
    config: TranslationConfig,
    *,
    existing_glossary: Glossary | None = None,
    log_callback: LogCallback | None = None,
    progress_callback: AnalysisProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> JobResult:
    provider = _provider_from_config(config)
    assert config.input_epub is not None
    output_path = config.analysis.output_path or _default_analysis_output(config.input_epub)

    _log(log_callback, f"Book analysis started: {config.input_epub.name}")

    def report(current: int, total: int, candidates: int) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise JobCancelled("Book analysis cancelled.")
        if progress_callback is not None:
            progress_callback(current, total, candidates)
        _log(log_callback, f"Analysis {current}/{total} - {candidates} raw candidates")

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
    if cancel_event is not None and cancel_event.is_set():
        raise JobCancelled("Book analysis cancelled.")

    generated = result.glossary
    final_glossary = existing_glossary.merged(generated, prefer_self=True) if existing_glossary else generated
    final_glossary.save_json(output_path)

    _log(log_callback, f"Analyzed files: {result.analyzed_files}")
    _log(log_callback, f"Analyzed text segments: {result.analyzed_segments}")
    _log(log_callback, f"Raw glossary candidates: {result.raw_candidates}")
    _log(log_callback, f"Final glossary entries: {len(final_glossary)}")
    _log(log_callback, f"Glossary saved: {output_path}")
    return JobResult(glossary_path=output_path, glossary=final_glossary)


def _translate_file(
    *,
    file_path: str,
    work_dir: str,
    progress_file: str,
    progress_data: dict,
    provider,
    config: TranslationConfig,
    glossary: Glossary | None,
    cancel_event: threading.Event | None,
    log_callback: LogCallback | None,
    progress_lock: threading.Lock,
) -> tuple[str, bool]:
    if cancel_event is not None and cancel_event.is_set():
        raise JobCancelled("Translation cancelled.")

    rel_path = os.path.relpath(file_path, work_dir)
    fname = os.path.basename(file_path)
    if progress_data.get(rel_path) == "COMPLETED":
        _log(log_callback, f"Already completed: {fname}")
        return rel_path, True

    document = parse_document(file_path)
    chunks = build_chunks(document.segments, config.chunk_tokens)
    if not chunks:
        with progress_lock:
            progress_data[rel_path] = "COMPLETED"
            save_progress_atomic(progress_file, progress_data)
        _log(log_callback, f"No translatable text: {fname}")
        return rel_path, True

    translated_segments: dict[str, str] = {}
    system_prompt = build_system_prompt(config.target_language)
    started = time.time()
    for chunk in chunks:
        if cancel_event is not None and cancel_event.is_set():
            raise JobCancelled("Translation cancelled.")
        chunk_result = _translate_chunk(
            provider=provider,
            system_prompt=system_prompt,
            chunk=chunk,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            max_retries=config.retries,
            fname=fname,
            glossary=glossary,
            enforce_glossary=config.enforce_glossary,
            log_callback=log_callback,
        )
        translated_segments.update(chunk_result)

    document.apply_translations(translated_segments)
    tmp_file = file_path + ".tmp"
    with open(tmp_file, "wb") as handle:
        handle.write(document.serialize())
    os.replace(tmp_file, file_path)
    with progress_lock:
        progress_data[rel_path] = "COMPLETED"
        save_progress_atomic(progress_file, progress_data)
    _log(log_callback, f"Finished: {fname} ({len(chunks)} chunks, {time.time() - started:.1f}s)")
    return rel_path, True


def run_translation_job(
    config: TranslationConfig,
    *,
    glossary_override: Glossary | None = None,
    log_callback: LogCallback | None = None,
    progress_callback: ProgressCallback | None = None,
    analysis_progress_callback: AnalysisProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> JobResult:
    provider = _provider_from_config(config)
    assert config.input_epub is not None

    glossary = glossary_override
    if glossary is None and config.glossary_path is not None:
        glossary = Glossary.load_json(config.glossary_path)

    generated_path: Path | None = None
    if config.analysis.enabled:
        analysis_result = run_book_analysis_job(
            config,
            existing_glossary=glossary,
            log_callback=log_callback,
            progress_callback=analysis_progress_callback,
            cancel_event=cancel_event,
        )
        glossary = analysis_result.glossary
        generated_path = analysis_result.glossary_path
        if config.analysis.analysis_only:
            return analysis_result

    if cancel_event is not None and cancel_event.is_set():
        raise JobCancelled("Translation cancelled.")

    work_dir = _safe_work_dir(config.input_epub)
    progress_file = work_dir / TEMP_FILE
    output_epub = config.input_epub.with_name(f"{config.input_epub.stem}-translated.epub")
    extract_epub_if_needed(str(config.input_epub), str(work_dir))
    progress_data = load_progress(str(progress_file))

    target_files: list[str] = []
    for root, _dirs, files in os.walk(work_dir):
        for file in files:
            if file.lower().endswith((".xhtml", ".html", ".ncx")):
                target_files.append(os.path.join(root, file))
    target_files.sort()
    total = len(target_files)
    completed = 0
    failed: list[str] = []
    progress_lock = threading.Lock()
    _log(log_callback, f"Provider: {provider.info.display_name}")
    _log(log_callback, f"Model: {provider.model}")
    _log(log_callback, f"Processing {total} files with {config.workers} worker(s)")

    def report(path: str, ok: bool) -> None:
        nonlocal completed
        completed += 1
        if not ok:
            failed.append(path)
        if progress_callback is not None:
            progress_callback(completed, total, path)

    with ThreadPoolExecutor(max_workers=config.workers) as executor:
        future_map = {
            executor.submit(
                _translate_file,
                file_path=fp,
                work_dir=str(work_dir),
                progress_file=str(progress_file),
                progress_data=progress_data,
                provider=provider,
                config=config,
                glossary=glossary,
                cancel_event=cancel_event,
                log_callback=log_callback,
                progress_lock=progress_lock,
            ): fp
            for fp in target_files
        }
        for future in as_completed(future_map):
            fp = future_map[future]
            try:
                rel_path, ok = future.result()
                report(rel_path, ok)
            except JobCancelled:
                if cancel_event is not None:
                    cancel_event.set()
                for pending in future_map:
                    pending.cancel()
                raise
            except Exception as exc:
                rel_path = os.path.relpath(fp, work_dir)
                failed.append(rel_path)
                completed += 1
                _log(log_callback, f"FAILED: {rel_path} ({exc})")
                if progress_callback is not None:
                    progress_callback(completed, total, rel_path)

    if cancel_event is not None and cancel_event.is_set():
        raise JobCancelled("Translation cancelled. Completed files are preserved for resume.")

    if failed:
        _log(log_callback, f"Finished with {len(failed)} failed file(s). Re-run to retry them.")
        return JobResult(glossary_path=generated_path, glossary=glossary, failed_files=tuple(failed))

    _log(log_callback, f"Packaging: {output_epub.name}")
    create_epub(str(work_dir), str(output_epub))
    shutil.rmtree(work_dir)
    _log(log_callback, f"Done: {output_epub}")
    return JobResult(output_path=output_epub, glossary_path=generated_path, glossary=glossary)
