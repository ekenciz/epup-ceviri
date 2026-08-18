from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


class GlossaryError(ValueError):
    """Raised when glossary data is invalid or cannot be loaded."""


@dataclass(frozen=True)
class GlossaryEntry:
    source: str
    target: str
    note: str | None = None
    case_sensitive: bool = False
    whole_word: bool = True
    category: str | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        source = self.source.strip()
        target = self.target.strip()
        if not source:
            raise GlossaryError("Glossary source term cannot be empty.")
        if not target:
            raise GlossaryError(f"Glossary target for '{source}' cannot be empty.")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "target", target)
        if self.note is not None:
            note = self.note.strip()
            object.__setattr__(self, "note", note or None)
        if self.category is not None:
            category = self.category.strip().lower()
            object.__setattr__(self, "category", category or None)
        if self.confidence is not None:
            confidence = float(self.confidence)
            if not 0.0 <= confidence <= 1.0:
                raise GlossaryError(
                    f"Glossary confidence for '{source}' must be between 0 and 1."
                )
            object.__setattr__(self, "confidence", confidence)

    def matches(self, text: str) -> bool:
        flags = 0 if self.case_sensitive else re.IGNORECASE
        pattern = re.escape(self.source)
        if self.whole_word:
            pattern = rf"(?<!\w){pattern}(?!\w)"
        return re.search(pattern, text, flags=flags) is not None

    def to_dict(self) -> dict:
        data = {
            "source": self.source,
            "target": self.target,
            "case_sensitive": self.case_sensitive,
            "whole_word": self.whole_word,
        }
        if self.note:
            data["note"] = self.note
        if self.category:
            data["category"] = self.category
        if self.confidence is not None:
            data["confidence"] = self.confidence
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "GlossaryEntry":
        if not isinstance(data, dict):
            raise GlossaryError("Each glossary entry must be a JSON object.")
        confidence = data.get("confidence")
        return cls(
            source=str(data.get("source", "")),
            target=str(data.get("target", "")),
            note=None if data.get("note") is None else str(data.get("note")),
            case_sensitive=bool(data.get("case_sensitive", False)),
            whole_word=bool(data.get("whole_word", True)),
            category=None if data.get("category") is None else str(data.get("category")),
            confidence=None if confidence is None else float(confidence),
        )


class Glossary:
    FORMAT_VERSION = 1

    def __init__(self, entries: Iterable[GlossaryEntry] = ()) -> None:
        self._entries = tuple(entries)
        self._validate_duplicates()

    @property
    def entries(self) -> tuple[GlossaryEntry, ...]:
        return self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)

    @staticmethod
    def _entry_key(entry: GlossaryEntry) -> tuple[str, bool, bool]:
        normalized = entry.source if entry.case_sensitive else entry.source.casefold()
        return (normalized, entry.case_sensitive, entry.whole_word)

    def _validate_duplicates(self) -> None:
        seen: dict[tuple[str, bool, bool], GlossaryEntry] = {}
        for entry in self._entries:
            key = self._entry_key(entry)
            if key in seen:
                raise GlossaryError(f"Duplicate glossary source term: '{entry.source}'.")
            seen[key] = entry

    def relevant_entries(self, texts: str | Sequence[str]) -> tuple[GlossaryEntry, ...]:
        if isinstance(texts, str):
            haystack = texts
        else:
            haystack = "\n".join(texts)
        if not haystack:
            return ()
        return tuple(entry for entry in self._entries if entry.matches(haystack))

    def merged(self, other: "Glossary", *, prefer_self: bool = True) -> "Glossary":
        """Merge two glossaries while resolving duplicate source terms.

        Manual/user-supplied glossaries can call `manual.merged(generated)` so
        existing decisions win over AI-generated suggestions.
        """
        first, second = (self, other) if prefer_self else (other, self)
        result: list[GlossaryEntry] = []
        seen: set[tuple[str, bool, bool]] = set()
        for glossary in (first, second):
            for entry in glossary.entries:
                key = self._entry_key(entry)
                if key in seen:
                    continue
                seen.add(key)
                result.append(entry)
        return Glossary(result)

    def to_dict(self) -> dict:
        return {
            "version": self.FORMAT_VERSION,
            "entries": [entry.to_dict() for entry in self._entries],
        }

    def save_json(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = destination.with_suffix(destination.suffix + ".tmp")
        try:
            tmp.write_text(
                json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp.replace(destination)
        except OSError as exc:
            raise GlossaryError(f"Could not save glossary to {destination}: {exc}") from exc
        return destination

    @classmethod
    def from_dict(cls, data: dict | list) -> "Glossary":
        if isinstance(data, list):
            raw_entries = data
        elif isinstance(data, dict):
            version = data.get("version", cls.FORMAT_VERSION)
            if version != cls.FORMAT_VERSION:
                raise GlossaryError(
                    f"Unsupported glossary version {version}; expected {cls.FORMAT_VERSION}."
                )
            raw_entries = data.get("entries")
            if not isinstance(raw_entries, list):
                raise GlossaryError("Glossary JSON must contain an 'entries' array.")
        else:
            raise GlossaryError("Glossary JSON must be an object or array.")

        return cls(GlossaryEntry.from_dict(item) for item in raw_entries)

    @classmethod
    def load_json(cls, path: str | Path) -> "Glossary":
        source = Path(path)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise GlossaryError(f"Glossary file does not exist: {source}") from exc
        except json.JSONDecodeError as exc:
            raise GlossaryError(f"Glossary JSON is invalid: {exc}") from exc
        except OSError as exc:
            raise GlossaryError(f"Could not read glossary {source}: {exc}") from exc
        return cls.from_dict(data)
