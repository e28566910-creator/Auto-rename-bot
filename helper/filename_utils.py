"""Pure helpers for safe media filename parsing and episode sorting."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional, Tuple

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_SPACE_RUN = re.compile(r"[\s._-]+")

QUALITY_PATTERNS = [
    (re.compile(r"(?<!\d)(2160p|4k)(?!\w)", re.I), "2160p"),
    (re.compile(r"(?<!\d)(1440p|2k)(?!\w)", re.I), "1440p"),
    (re.compile(r"(?<!\d)(1080p)(?!\w)", re.I), "1080p"),
    (re.compile(r"(?<!\d)(720p)(?!\w)", re.I), "720p"),
    (re.compile(r"(?<!\d)(480p)(?!\w)", re.I), "480p"),
    (re.compile(r"(?<!\d)(360p)(?!\w)", re.I), "360p"),
]

SEASON_EPISODE_PATTERNS = [
    re.compile(r"(?i)\bS(\d{1,2})\s*(?:E|EP)(\d{1,4})\b"),
    re.compile(r"(?i)\bSeason\s*(\d{1,2})\s*(?:Episode|Ep)\s*(\d{1,4})\b"),
    re.compile(r"(?i)\b(?:Season|S)\s*(\d{1,2})\s*[-_. ]+\s*(?:Episode|Ep|E)\s*(\d{1,4})\b"),
]
EPISODE_PATTERNS = [
    re.compile(r"(?i)\b(?:Episode|Episodes|Epi|Ep|E)\s*[-_.# ]*0*(\d{1,4})\b"),
    re.compile(r"(?i)\b#\s*0*(\d{1,4})\b"),
]

QUALITY_ORDER = {
    "360p": 0,
    "480p": 1,
    "720p": 2,
    "1080p": 3,
    "1440p": 4,
    "2160p": 5,
}


@dataclass(frozen=True)
class ParsedMediaName:
    season: Optional[int]
    episode: Optional[int]
    quality: Optional[str]
    title: str


def split_filename(filename: str) -> Tuple[str, str]:
    name = os.path.basename(filename or "file")
    stem, extension = os.path.splitext(name)
    return stem, extension


def extract_quality(filename: str) -> Optional[str]:
    for pattern, quality in QUALITY_PATTERNS:
        if pattern.search(filename):
            return quality
    return None


def _episode_match(stem: str):
    for pattern in SEASON_EPISODE_PATTERNS:
        match = pattern.search(stem)
        if match:
            return int(match.group(1)), int(match.group(2)), match.span()
    for pattern in EPISODE_PATTERNS:
        match = pattern.search(stem)
        if match:
            return None, int(match.group(1)), match.span()

    # Last numeric token is a conservative fallback for common releases such as
    # "Naruto - 012 - 1080p". Avoid resolution values and four-digit years.
    # Ignore bracketed release-group/hash tokens and quality numbers during
    # fallback detection, but preserve character positions so the returned
    # span still refers to the original filename stem.
    candidate_stem = re.sub(
        r"\[[^\]]*\]|\([^)]*\)",
        lambda match: " " * len(match.group()),
        stem,
    )
    for pattern, _quality in QUALITY_PATTERNS:
        candidate_stem = pattern.sub(lambda match: " " * len(match.group()), candidate_stem)
    tokens = list(re.finditer(r"(?<!\d)(\d{1,3})(?!\d)", candidate_stem))
    for match in reversed(tokens):
        # A fallback number must be a standalone token after a title separator;
        # this avoids treating titles such as "86 Eighty-Six" as episode 86.
        before_ok = match.start() > 0 and candidate_stem[match.start() - 1] in " ._-"
        after_ok = match.end() == len(candidate_stem) or candidate_stem[match.end()] in " ._-"
        value = int(match.group(1))
        if before_ok and after_ok and 0 <= value <= 999:
            return None, value, match.span()
    return None, None, None


def _remove_release_brackets(text: str) -> str:
    """Remove likely release-group/hash brackets without deleting bracketed titles."""
    known_groups = {
        "subsplease", "erai-raws", "erai raws", "judas", "horriblesubs",
        "anime time", "animetime", "ember", "lostyears", "asw", "golumpa",
        "tsundere-raws", "toons hub", "toonshub",
    }

    def replace(match):
        content = match.group(1).strip()
        normalized = re.sub(r"\s+", " ", content).casefold()
        is_hash = bool(re.fullmatch(r"[A-Fa-f0-9]{6,}", content))
        is_short_release_code = bool(re.fullmatch(r"[A-Z0-9_-]{2,4}", content))
        is_known_group = normalized in known_groups
        is_site_tag = bool(re.search(r"(?i)(?:www\.|\.(?:com|net|org)\b)", content))
        is_empty = not content
        return " " if (is_hash or is_short_release_code or is_known_group or is_site_tag or is_empty) else match.group(0)

    text = re.sub(r"\[([^\]]*)\]", replace, text)
    # Keep meaningful parentheses such as a film's year, but remove empty brackets.
    text = re.sub(r"\(\s*\)|\[\s*\]", " ", text)
    return text


def parse_media_name(filename: str) -> ParsedMediaName:
    stem, _extension = split_filename(filename)
    season, episode, episode_span = _episode_match(stem)
    quality = extract_quality(stem)

    title = stem
    if episode_span:
        title = title[:episode_span[0]] + " " + title[episode_span[1]:]
    for pattern, _quality in QUALITY_PATTERNS:
        title = pattern.sub(" ", title)
    title = _remove_release_brackets(title)

    # Remove common release metadata without over-stripping real title words.
    title = re.sub(
        r"(?i)\b(?:web[- .]?dl|webrip|bluray|bdrip|hdtv|x264|x265|hevc|aac|10bit|8bit|dual[ ._-]?audio|multi[ ._-]?audio|tamil[ ._-]?dub|hindi[ ._-]?dub|telugu[ ._-]?dub|tamil|hindi|telugu)\b",
        " ",
        title,
    )
    title = re.sub(r"\[[^\]]*(?:www\.|\.com|\.net|\.org)[^\]]*\]", " ", title, flags=re.I)
    title = title.replace("(", " ").replace(")", " ")
    title = _SPACE_RUN.sub(" ", title).strip(" -_.[]()")
    return ParsedMediaName(season=season, episode=episode, quality=quality, title=title or "Unknown title")


def quality_sort_key(quality: Optional[str]):
    if not quality:
        return (99, "")
    return (QUALITY_ORDER.get(quality.lower(), 98), quality.lower())


def media_sort_key(parsed: ParsedMediaName, stable_index: int = 0):
    """Sort an already-parsed file by season, numeric episode, then quality."""
    return (
        parsed.season if parsed.season is not None else 0,
        parsed.episode if parsed.episode is not None else 10**9,
        quality_sort_key(parsed.quality),
        stable_index,
    )


def safe_filename(name: str, max_length: int = 180) -> str:
    """Strip path traversal/control characters while retaining a readable name."""
    name = os.path.basename(name or "file")
    stem, ext = os.path.splitext(name)
    stem = _INVALID_FILENAME_CHARS.sub("_", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    if not stem:
        stem = "renamed_file"
    # Windows reserved names are also avoided for portable ZIP/storage use.
    if stem.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        stem = f"_{stem}"
    remaining = max(1, max_length - len(ext))
    return f"{stem[:remaining]}{ext[:20]}"


def build_renamed_filename(template: str, original_filename: str) -> str:
    """Fill supported placeholders, but leave unknown tokens unchanged."""
    parsed = parse_media_name(original_filename)
    values = {
        "season": f"{parsed.season:02d}" if parsed.season is not None else "XX",
        "episode": f"{parsed.episode:02d}" if parsed.episode is not None else "XX",
        "quality": parsed.quality or "Unknown",
        "title": parsed.title,
    }
    result = re.sub(
        r"\{(season|episode|quality|title)\}",
        lambda match: values[match.group(1).lower()],
        template,
        flags=re.I,
    )

    # Keep the original repository's plain-word placeholders working too.
    # Those legacy placeholders are case-sensitive by design, so ordinary
    # words in a custom title are not unexpectedly replaced.
    legacy_season = values["season"]
    legacy_episode = values["episode"]
    # The upstream README used Sseason / Eepisode / quality as plain tokens.
    # Also accept the full words for users who had saved those older templates.
    result = re.sub(r"Sseason\b", f"S{legacy_season}", result, flags=re.I)
    result = re.sub(r"Eepisode\b", f"E{legacy_episode}", result, flags=re.I)
    result = re.sub(r"\bSeason\b", legacy_season, result)
    result = re.sub(r"\bEpisode\b", legacy_episode, result)
    result = re.sub(r"\bquality\b", parsed.quality or "Unknown", result)
    result = re.sub(r"\bQUALITY\b", parsed.quality or "Unknown", result)

    _old_stem, extension = split_filename(original_filename)
    # Preserve the exact source extension. Only avoid adding it twice when the
    # user already included that same extension in the template.
    if extension and result.lower().endswith(extension.lower()):
        return safe_filename(result)
    return safe_filename(result + extension)
