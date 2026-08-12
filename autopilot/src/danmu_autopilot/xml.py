"""Safe Bilibili-style XML parsing and loss-aware timeline transforms."""

from __future__ import annotations

import html
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence

from .domain import Comment, Segment

_MAX_XML_BYTES = 32 * 1024 * 1024
_MAX_COMMENTS = 500_000


def _parse_tree(data: bytes) -> ET.Element:
    if len(data) > _MAX_XML_BYTES:
        raise ValueError("danmaku XML exceeds configured size limit")
    # defusedxml is declared by the project. Keep a tiny fallback for source
    # checkouts before dependencies are installed; production images always use
    # the hardened parser.
    try:
        from defusedxml import ElementTree as safe_et

        return safe_et.fromstring(data)
    except ImportError:
        return ET.fromstring(data)


def parse_xml(data: bytes, source_id: str) -> tuple[Comment, ...]:
    root = _parse_tree(data)
    comments: list[Comment] = []
    for node in root.iter("d"):
        if len(comments) >= _MAX_COMMENTS:
            raise ValueError("danmaku XML exceeds configured comment limit")
        descriptor = node.attrib.get("p", "").split(",")
        if len(descriptor) < 4:
            continue
        try:
            time_ms = max(0, round(float(descriptor[0]) * 1000))
            mode = int(float(descriptor[1]))
            size = int(float(descriptor[2]))
            color = int(float(descriptor[3]))
        except (TypeError, ValueError):
            continue
        comments.append(Comment(time_ms, mode, color, size, node.text or "", source_id))
    return tuple(comments)


def map_timeline(comments: Sequence[Comment], pieces: Sequence[Segment]) -> tuple[Comment, ...]:
    """Map source timestamps to target timestamps using half-open source ranges."""

    mapped: list[Comment] = []
    for comment in comments:
        for piece in pieces:
            if piece.source_start_ms <= comment.time_ms < piece.source_end_ms:
                target = piece.target_start_ms + comment.time_ms - piece.source_start_ms
                mapped.append(
                    Comment(target, comment.mode, comment.color, comment.size, comment.text, comment.source_id)
                )
                break
    mapped.sort(key=lambda item: (item.time_ms, item.source_id, item.text))
    return tuple(mapped)


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def deduplicate(
    comments: Sequence[Comment],
    window_ms: int = 250,
    source_priority: Mapping[str, int] | None = None,
) -> tuple[Comment, ...]:
    """Stable de-duplication by mode, color and text within a time window."""

    priorities = source_priority or {}
    ordered = sorted(comments, key=lambda c: (c.time_ms, priorities.get(c.source_id, 10_000), c.source_id))
    kept: list[Comment] = []
    for comment in ordered:
        key = (comment.mode, comment.color, _normalized_text(comment.text))
        duplicate_index = next(
            (
                index
                for index, prior in enumerate(kept)
                if (prior.mode, prior.color, _normalized_text(prior.text)) == key
                and abs(prior.time_ms - comment.time_ms) <= window_ms
            ),
            None,
        )
        if duplicate_index is None:
            kept.append(comment)
        elif priorities.get(comment.source_id, 10_000) < priorities.get(kept[duplicate_index].source_id, 10_000):
            kept[duplicate_index] = comment
    kept.sort(key=lambda c: c.time_ms)
    return tuple(kept)


def serialize_xml(comments: Sequence[Comment], provenance: Mapping[str, object] | None = None) -> bytes:
    root = ET.Element("i")
    if provenance:
        meta = ET.SubElement(root, "metadata")
        for key, value in sorted(provenance.items()):
            meta.set(str(key), str(value))
    for comment in comments:
        node = ET.SubElement(
            root,
            "d",
            {"p": f"{comment.time_ms / 1000:.3f},{comment.mode},{comment.size},{comment.color},0,0,0,0"},
        )
        node.text = comment.text
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
