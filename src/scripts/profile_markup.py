"""Markdown boundaries: generated regions, local links, and escaped source text.

Keep source-offset and regex details here so rendering code deals with content,
not Markdown syntax. This is intentionally not a general-purpose Markdown parser.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Sequence
from html import escape
from pathlib import Path

REGIONS = (
    "typing",
    "pgp",
    "stats",
    "timeline",
    "snake",
    "activity",
    "merged",
    "quote",
    "posts47",
)

# The lookbehind skips escaped Markdown brackets: \](...).
MARKDOWN_LINK = re.compile(r"(?<!\\)\]\((?P<path>[^)\s]+)")
HTML_TAG = re.compile(r"<(?:a|img)\b[^>]*>", re.IGNORECASE)
HTML_LINK = re.compile(
    r"""\b(?:href|src)\s*=\s*["'](?P<path>[^"']+)["']""", re.IGNORECASE
)
REGION_MARKER = re.compile(r"<!-- profile:([\w-]+):(start|end) -->")
MARKDOWN_SPECIAL = re.compile(r"([\\`*_[\]{}|])")
BLOCK_PREFIX = re.compile(r"(?<!\S)([#=+-])")
ORDERED_LIST_PREFIX = re.compile(r"(?<!\S)(\d+)\.(?=\s|$)")

HOSTED_WIDGETS = (
    "img.shields.io",
    "capsule-render.vercel.app",
    "quotes-github-readme.vercel.app",
    "github-readme-stats-fast.vercel.app",
    "github-profile-summary-cards.vercel.app",
    "readme-typing-svg.demolab.com",
)
HOSTED_WIDGET_URL = re.compile(
    r"https://(?:"
    + "|".join(re.escape(host) for host in HOSTED_WIDGETS)
    + r""")[^\s)"<]*"""
)


def resolve_repository_path(root: Path, relative: str) -> Path:
    """Resolve a repository path without allowing traversal or access to .git."""
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or ".git" in path.relative_to(root).parts:
        raise ValueError("Output paths must stay inside the repository, outside .git")
    return path


def iter_link_spans(markdown: str) -> Iterator[tuple[int, int]]:
    """Find URL offsets in Markdown destinations and actual HTML link/image tags."""
    yield from (match.span("path") for match in MARKDOWN_LINK.finditer(markdown))
    for tag in HTML_TAG.finditer(markdown):
        for attribute in HTML_LINK.finditer(tag.group()):
            start, end = attribute.span("path")
            yield tag.start() + start, tag.start() + end


def iter_local_links(markdown: str) -> Iterator[tuple[int, int, str]]:
    """Yield each local path and its source offsets, leaving fragments untouched."""
    for start, end in sorted(iter_link_spans(markdown)):
        path = markdown[start:end].partition("#")[0]
        if path.startswith(("./", "../")):
            yield start, start + len(path), path


def resolve_linked_files(
    root: Path, markdown: str, document: Path | None = None
) -> set[Path]:
    """Resolve local Markdown/image links relative to their containing document."""
    directory = document.parent if document else root
    return {
        resolve_repository_path(root, str(directory / path))
        for _, _, path in iter_local_links(markdown)
    }


def rewrite_document_links(markdown: str, root: Path, document: Path) -> str:
    """Convert generated repository-relative links to document-relative links."""
    # Work backwards so replacements do not shift the remaining source offsets.
    for start, end, path in reversed(list(iter_local_links(markdown))):
        target = resolve_repository_path(root, path)
        relative = Path(os.path.relpath(target, document.parent)).as_posix()
        if not relative.startswith("../"):
            relative = "./" + relative
        markdown = markdown[:start] + relative + markdown[end:]
    return markdown


def compile_region_pattern(name: str) -> re.Pattern[str]:
    marker = re.escape(name)
    return re.compile(
        rf"<!-- profile:{marker}:start -->\n(?P<content>.*?)\n<!-- profile:{marker}:end -->",
        re.DOTALL,
    )


def replace_region(markdown: str, name: str, replacement: str) -> str:
    matches = list(compile_region_pattern(name).finditer(markdown))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one complete generated region: {name}")
    start, end = matches[0].span("content")
    return markdown[:start] + replacement.strip() + markdown[end:]


def validate_regions(markdown: str, regions: Sequence[str] = REGIONS) -> None:
    if not regions or len(set(regions)) != len(regions) or set(regions) - set(REGIONS):
        raise ValueError("Configured regions must be unique, known region names")
    markers = REGION_MARKER.findall(markdown)
    if {name for name, _ in markers} - set(regions):
        raise ValueError("Unexpected generated region for this document")
    for name in regions:
        complete_regions = list(compile_region_pattern(name).finditer(markdown))
        has_one_pair = (
            markers.count((name, "start")) == markers.count((name, "end")) == 1
        )
        if len(complete_regions) != 1 or not has_one_pair:
            raise ValueError(f"Missing or duplicate generated region: {name}")


def escape_markdown(text: str) -> str:
    """Preserve rendered text without letting source data introduce markup."""
    value = MARKDOWN_SPECIAL.sub(r"\\\1", escape(text, quote=False))
    # Wrapping must not turn an excerpt into a heading, list, or thematic break.
    value = BLOCK_PREFIX.sub(r"\\\1", value)
    return ORDERED_LIST_PREFIX.sub(r"\1\\.", value)


def validate_document_content(markdown: str) -> None:
    match = HOSTED_WIDGET_URL.search(markdown)
    if match:
        url = match.group().split("?")[0]
        raise ValueError(f"Unexpected hosted widget dependency: {url}")
    if "<details" in markdown:
        raise ValueError("Collapsible sections must not be introduced")
