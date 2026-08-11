"""Deterministic media-name parsing and alias expansion."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .domain import MatchContext


@dataclass(frozen=True, slots=True)
class AliasCatalog:
    local: Mapping[str, Sequence[str]]
    metadata: Mapping[str, Sequence[str]]
    learned: Mapping[str, Sequence[str]]

_EXTENSIONS = re.compile(r"\.(?:mkv|mp4|m4v|avi|mov|ts|webm|flv)$", re.I)
_SEASON_EPISODE = re.compile(r"(?:^|[. _-])[Ss](\d{1,3})[ ._-]*[Ee](\d{1,4})(?:$|[. _-])")
_CN_SEASON = re.compile(r"第\s*(\d{1,3})\s*季")
_CN_EPISODE = re.compile(r"第\s*(\d{1,4})\s*(?:集|话)")
_TRAILING_EPISODE = re.compile(r"(?:^|[ ._-])(?:-|#)?\s*(\d{1,4})\s*$")
_NOISE = re.compile(
    r"(?:\b(?:2160p|1440p|1080p|720p|480p|4k|8k|web[- .]?dl|bluray|bdrip|webrip|hdtv|hdr|dv|x264|x265|hevc|av1|aac|flac|proper|repack)\b|\[[^\]]*\]|\([^)]*\))",
    re.I,
)


def _clean_title(value: str) -> str:
    value = _NOISE.sub(" ", value)
    value = re.sub(r"[._]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -_")


def parse_match_context(filename: str) -> MatchContext:
    """Parse common multilingual filename conventions without network calls."""

    original = Path(filename).name
    stem = _EXTENSIONS.sub("", original)
    stem = unicodedata.normalize("NFKC", stem)
    season: int | None = None
    episode: int | None = None

    match = _SEASON_EPISODE.search(stem)
    if match:
        season, episode = int(match.group(1)), int(match.group(2))
        title_part = stem[: match.start()] + " " + stem[match.end() :]
    else:
        season_match = _CN_SEASON.search(stem)
        episode_match = _CN_EPISODE.search(stem)
        if season_match:
            season = int(season_match.group(1))
            title_part = stem[: season_match.start()] + " " + stem[season_match.end() :]
        else:
            title_part = stem
        if episode_match:
            episode = int(episode_match.group(1))
            title_part = title_part.replace(episode_match.group(0), " ")
        elif not match:
            trailing = _TRAILING_EPISODE.search(title_part)
            if trailing:
                candidate = int(trailing.group(1))
                # A bare number is an episode only for a title-like prefix.  This
                # prevents years and resolution tokens from becoming episodes.
                prefix = title_part[: trailing.start()].strip(" .-_\t")
                if prefix and not re.fullmatch(r"(?:19|20)\d{2}", str(candidate)):
                    episode = candidate
                    title_part = prefix

    title = _clean_title(title_part)
    if not title:
        title = _clean_title(stem)
    try:
        return MatchContext(original_filename=original, title=title, season=season or 1, episode=episode)
    except TypeError:
        return MatchContext(filename=original, title=title, season=season or 1, episode=episode)


def _values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(item) for item in value if str(item).strip()]
    return []


def expand_aliases(title: str, catalog: AliasCatalog | Mapping[str, Mapping[str, Sequence[str]]]) -> tuple[str, ...]:
    """Return aliases in learned > metadata > local > original order."""

    seen: set[str] = set()
    result: list[str] = []
    for tier in ("learned", "metadata", "local"):
        tier_catalog = getattr(catalog, tier) if isinstance(catalog, AliasCatalog) else catalog.get(tier, {})
        for alias in _values(tier_catalog.get(title, ())):
            alias = unicodedata.normalize("NFKC", alias).strip()
            if alias and alias not in seen and alias != title:
                seen.add(alias)
                result.append(alias)
    if title not in seen:
        result.append(title)
    return tuple(result)
