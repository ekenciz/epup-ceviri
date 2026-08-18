from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Sequence

from .xhtml import TextSegment


# Provider tokenizers differ. This estimator is intentionally conservative and
# dependency-free: words/numbers/punctuation are counted, then a character
# based floor is applied for languages or strings that tokenize more densely.
_TOKEN_PARTS_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    lexical = len(_TOKEN_PARTS_RE.findall(text))
    char_floor = (len(text) + 3) // 4
    return max(1, lexical, char_floor)


@dataclass(frozen=True)
class TextChunk:
    index: int
    segments: tuple[TextSegment, ...]
    estimated_tokens: int

    @property
    def segment_ids(self) -> tuple[str, ...]:
        return tuple(segment.id for segment in self.segments)


def _split_large_text(text: str, max_tokens: int) -> list[str]:
    """Split one oversized text node while preserving all characters."""
    if estimate_tokens(text) <= max_tokens:
        return [text]

    # Split at whitespace boundaries when possible. Keep the separator in the
    # preceding piece so concatenating pieces reproduces the original string.
    parts = re.split(r"(?<=\s)", text)
    result: list[str] = []
    current = ""

    for part in parts:
        candidate = current + part
        if current and estimate_tokens(candidate) > max_tokens:
            result.append(current)
            current = part
        else:
            current = candidate

        # A single whitespace-free token can still exceed the limit.
        while current and estimate_tokens(current) > max_tokens:
            # Four characters/token is the estimator floor; use a slightly
            # smaller slice to remain below budget.
            cut = max(1, max_tokens * 3)
            result.append(current[:cut])
            current = current[cut:]

    if current:
        result.append(current)
    return result


def build_chunks(
    segments: Sequence[TextSegment] | Iterable[TextSegment],
    max_tokens: int,
) -> list[TextChunk]:
    if max_tokens < 1:
        raise ValueError("Chunk token budget must be at least 1.")

    expanded: list[TextSegment] = []
    for segment in segments:
        pieces = _split_large_text(segment.text, max_tokens)
        if len(pieces) == 1:
            expanded.append(segment)
            continue
        for part_index, piece in enumerate(pieces):
            expanded.append(
                TextSegment(
                    id=f"{segment.id}__part{part_index:03d}",
                    text=piece,
                    node_key=segment.node_key,
                    part_index=part_index,
                    part_count=len(pieces),
                )
            )

    chunks: list[TextChunk] = []
    current: list[TextSegment] = []
    current_tokens = 0

    for segment in expanded:
        segment_tokens = estimate_tokens(segment.text)
        if current and current_tokens + segment_tokens > max_tokens:
            chunks.append(
                TextChunk(
                    index=len(chunks),
                    segments=tuple(current),
                    estimated_tokens=current_tokens,
                )
            )
            current = []
            current_tokens = 0

        current.append(segment)
        current_tokens += segment_tokens

    if current:
        chunks.append(
            TextChunk(
                index=len(chunks),
                segments=tuple(current),
                estimated_tokens=current_tokens,
            )
        )

    return chunks
