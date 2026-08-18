from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from lxml import etree


SKIP_TAGS = {
    "script",
    "style",
    "code",
    "pre",
    "svg",
    "math",
}


class XHTMLProcessingError(RuntimeError):
    """Raised when an EPUB text document cannot be parsed or rebuilt safely."""


@dataclass(frozen=True)
class TextSegment:
    id: str
    text: str
    node_key: str
    part_index: int = 0
    part_count: int = 1


@dataclass
class _NodeBinding:
    element: etree._Element
    slot: str  # "text" or "tail"
    original: str


class ParsedDocument:
    def __init__(
        self,
        *,
        tree: etree._ElementTree,
        encoding: str,
        xml_declaration: bool,
        doctype: str,
        segments: list[TextSegment],
        bindings: dict[str, _NodeBinding],
    ) -> None:
        self.tree = tree
        self.encoding = encoding
        self.xml_declaration = xml_declaration
        self.doctype = doctype
        self.segments = segments
        self._bindings = bindings

    def apply_translations(self, translations: dict[str, str]) -> None:
        """Apply translated segment values back into the parsed DOM.

        Oversized nodes may have been split into __partNNN segment IDs by the
        chunker. Those pieces are reassembled before the DOM slot is replaced.
        """
        grouped: dict[str, list[tuple[int, str]]] = {}

        for segment in self.segments:
            if segment.id in translations:
                grouped.setdefault(segment.node_key, []).append(
                    (segment.part_index, translations[segment.id])
                )

        # Also accept split segment IDs created after parsing.
        for segment_id, value in translations.items():
            if "__part" not in segment_id:
                continue
            base, _, suffix = segment_id.rpartition("__part")
            if base not in self._bindings:
                continue
            try:
                part_index = int(suffix)
            except ValueError:
                continue
            grouped.setdefault(base, []).append((part_index, value))

        for node_key, pieces in grouped.items():
            binding = self._bindings.get(node_key)
            if binding is None:
                continue
            pieces.sort(key=lambda item: item[0])
            translated = "".join(value for _, value in pieces)
            original = binding.original
            leading_len = len(original) - len(original.lstrip())
            trailing_len = len(original) - len(original.rstrip())
            leading = original[:leading_len]
            trailing = original[len(original) - trailing_len:] if trailing_len else ""
            translated = leading + translated + trailing
            if binding.slot == "text":
                binding.element.text = translated
            else:
                binding.element.tail = translated

    def serialize(self) -> bytes:
        try:
            return etree.tostring(
                self.tree,
                encoding=self.encoding,
                xml_declaration=self.xml_declaration,
                doctype=self.doctype or None,
                pretty_print=False,
            )
        except (LookupError, ValueError) as exc:
            raise XHTMLProcessingError(f"Could not serialize document: {exc}") from exc


def _local_name(element: etree._Element) -> str:
    if not isinstance(element.tag, str):
        return ""
    return etree.QName(element).localname.lower()


def _has_skipped_ancestor(element: etree._Element) -> bool:
    current: Optional[etree._Element] = element
    while current is not None:
        if _local_name(current) in SKIP_TAGS:
            return True
        current = current.getparent()
    return False


def _is_translatable(text: Optional[str]) -> bool:
    if not text or not text.strip():
        return False
    # Punctuation/formatting-only nodes do not need an AI request and are safer
    # left byte-for-byte in their original DOM slot.
    return any(char.isalnum() for char in text)


def parse_document(path: str | Path) -> ParsedDocument:
    path = Path(path)
    raw = path.read_bytes()
    xml_declaration = raw.lstrip().startswith(b"<?xml")

    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        remove_blank_text=False,
        strip_cdata=False,
        recover=False,
        huge_tree=True,
    )

    try:
        tree = etree.parse(str(path), parser)
    except (etree.XMLSyntaxError, OSError) as exc:
        raise XHTMLProcessingError(f"Could not parse {path.name}: {exc}") from exc

    docinfo = tree.docinfo
    encoding = docinfo.encoding or "UTF-8"
    doctype = docinfo.doctype or ""

    segments: list[TextSegment] = []
    bindings: dict[str, _NodeBinding] = {}
    counter = 0

    for element in tree.iter():
        if not isinstance(element.tag, str):
            continue

        if not _has_skipped_ancestor(element) and _is_translatable(element.text):
            segment_id = f"s{counter:06d}"
            counter += 1
            original = element.text or ""
            core = original.strip()
            segments.append(
                TextSegment(id=segment_id, text=core, node_key=segment_id)
            )
            bindings[segment_id] = _NodeBinding(
                element=element,
                slot="text",
                original=original,
            )

        # A tail belongs visually after this element and should be skipped only
        # when an ancestor (not the element itself) is a non-translatable block.
        if _is_translatable(element.tail):
            parent = element.getparent()
            if parent is None or not _has_skipped_ancestor(parent):
                segment_id = f"s{counter:06d}"
                counter += 1
                original = element.tail or ""
                core = original.strip()
                segments.append(
                    TextSegment(id=segment_id, text=core, node_key=segment_id)
                )
                bindings[segment_id] = _NodeBinding(
                    element=element,
                    slot="tail",
                    original=original,
                )

    return ParsedDocument(
        tree=tree,
        encoding=encoding,
        xml_declaration=xml_declaration,
        doctype=doctype,
        segments=segments,
        bindings=bindings,
    )
