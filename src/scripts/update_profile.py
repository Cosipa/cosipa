#!/usr/bin/env python3
"""Refresh configured regions in the profile README."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import textwrap
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from html import escape
from pathlib import Path
from urllib.parse import quote as url_quote

if __package__:
    from . import profile_cards as cards
    from . import profile_data as data
    from .profile_templates import render as render_template
else:
    import profile_cards as cards
    import profile_data as data
    from profile_templates import render as render_template

ROOT = Path(__file__).resolve().parents[2]
# Markdown destinations, HTML tags, and their URL attributes
# The lookbehind skips escaped Markdown brackets: \](...).
MARKDOWN_LINK = re.compile(r"(?<!\\)\]\(([^)\s]+)")
HTML_TAG = re.compile(r"<(?:a|img)\b[^>]*>", re.IGNORECASE)
HTML_LINK = re.compile(r'''\b(?:href|src)\s*=\s*["']([^"']+)["']''', re.IGNORECASE)
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


def inside(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or ".git" in path.relative_to(root).parts:
        raise ValueError("Output paths must stay inside the repository, outside .git")
    return path


def local_links(markdown: str) -> Iterator[tuple[int, int, str]]:
    """Yield each local path and its source offsets, leaving fragments untouched."""
    spans = [match.span(1) for match in MARKDOWN_LINK.finditer(markdown)]
    for tag in HTML_TAG.finditer(markdown):
        for attribute in HTML_LINK.finditer(tag.group()):
            start, end = attribute.span(1)
            spans.append((tag.start() + start, tag.start() + end))

    for start, end in sorted(spans):
        path = markdown[start:end].partition("#")[0]
        if path.startswith(("./", "../")):
            yield start, start + len(path), path


def linked_files(root: Path, markdown: str, document: Path | None = None) -> set[Path]:
    """Resolve local Markdown/image links relative to their containing document."""
    directory = document.parent if document else root
    return {
        inside(root, str(directory / path)) for _, _, path in local_links(markdown)
    }


def document_links(markdown: str, root: Path, document: Path) -> str:
    """Convert generated repository-relative links to document-relative links."""

    # Work backwards so replacements do not shift the remaining source offsets.
    for start, end, path in reversed(list(local_links(markdown))):
        target = inside(root, path)
        relative = Path(os.path.relpath(target, document.parent)).as_posix()
        if not relative.startswith("../"):
            relative = "./" + relative
        markdown = markdown[:start] + relative + markdown[end:]

    return markdown


def region_pattern(name: str) -> re.Pattern:
    marker = re.escape(name)
    return re.compile(
        rf"(<!-- profile:{marker}:start -->\n)(.*?)(\n<!-- profile:{marker}:end -->)",
        re.DOTALL,
    )


def replace_region(markdown: str, name: str, replacement: str) -> str:
    matches = list(region_pattern(name).finditer(markdown))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one complete generated region: {name}")
    start, end = matches[0].span(2)
    return markdown[:start] + replacement.strip() + markdown[end:]


class Assets:
    """Validate, content-address and prune the generated SVG files."""

    def __init__(self, root: Path, relative: str):
        self.root = root
        self.directory = inside(root, relative)
        self.directory.mkdir(parents=True, exist_ok=True)

    def put(self, name: str, content: str | bytes) -> str:
        if not re.fullmatch(r"[a-z0-9-]+", name):
            raise ValueError("Invalid generated asset name")
        payload = content.encode() if isinstance(content, str) else content
        parsed = ET.fromstring(payload)
        if parsed.tag != cards.SVG_NS + "svg":
            raise ValueError("Generated asset is not an SVG")
        for node in parsed.iter():
            if node.tag.split("}")[-1] in ("script", "foreignObject"):
                raise ValueError("Active SVG content is forbidden")
            for key, value in node.attrib.items():
                if key.lower().startswith("on") or (
                    key.split("}")[-1] == "href" and not value.startswith("#")
                ):
                    raise ValueError("External/active SVG references are forbidden")
        digest = hashlib.sha256(payload).hexdigest()[:12]
        path = self.directory / f"{name}.{digest}.svg"
        if not path.exists():
            path.write_bytes(payload)
        return "./" + path.relative_to(self.root).as_posix()

    def prune(self, markdown: str, document: Path):
        referenced = linked_files(self.root, markdown, document)
        for path in self.directory.glob("*.svg"):
            if re.fullmatch(r"[a-z0-9-]+\.[a-f0-9]{12}\.svg", path.name) and path not in referenced:
                path.unlink()


def md(text: str) -> str:
    # Preserve rendered text while preventing source data from becoming Markdown/HTML.
    value = re.sub(r"([\\`*_[\]{}|])", r"\\\1", escape(text, quote=False))
    # Wrapping must not turn an excerpt into a heading, list, or thematic break.
    value = re.sub(r"(?<!\S)([#=+-])", r"\\\1", value)
    return re.sub(r"(?<!\S)(\d+)\.(?=\s|$)", r"\1\\.", value)


def themed_images(
    paths: dict, alt: str, *, width: int | None = None, link: str | None = None
) -> str:
    width_attr = f' width="{width}"' if width else ""
    # GitHub applies these markers to anchor hrefs using its selected site theme.
    # An SVG or <picture> media query only knows the browser/OS colour scheme.
    images = []
    for theme in ("dark", "light"):
        target = (link or paths[theme]) + f"#gh-{theme}-mode-only"
        images.append(
            render_template(
                "html/themed-image.html",
                target=target,
                path=paths[theme],
                alt=alt,
                fragments={"width_attribute": width_attr},
            ).rstrip()
        )
    return "\n".join(images)


def post_date(post: dict) -> str:
    published = datetime.fromisoformat(post["published"])
    return f"{published:%B} {published.day}, {published.year}"


def post_link(post: dict) -> str:
    url = url_quote(post["url"], safe=":/?#&=%+-.~@_")
    return f'[{md(post["title"])}]({url})'


def wrapped_excerpt(excerpt: str) -> str:
    lines = textwrap.wrap(md(excerpt), 86, break_long_words=False, break_on_hyphens=False)
    return "\n".join("> " + line for line in lines)


def post_rows(posts: list[dict]) -> str:
    parts = ["<table>"]
    for post in posts:
        parts.append(
            render_template(
                "html/post-row.html",
                date=post_date(post),
                fragments={
                    "link": post_link(post),
                    "excerpt": wrapped_excerpt(post["excerpt"]),
                },
            ).rstrip()
        )
    return "\n".join(parts + ["</table>"])


def activity_table(facts: dict, assets: Assets, *, merged=False) -> str:
    status = "merged" if merged else "open"

    headers = ["Status", "Repository", "Title"] + (["Merged (UTC)"] if merged else [])
    alignment = [":---:"] + [":--"] * (len(headers) - 1)
    parts = ["| " + " | ".join(headers) + " |", "| " + " | ".join(alignment) + " |"]

    for item in facts["items"]:
        kind = "pr" if merged or item["kind"] == "pr" else "issue"
        label = "PR" if kind == "pr" else "Issue"
        name = f"status-{kind}-{status}"
        path = assets.put(name, (ROOT / f"src/assets/static/{name}.svg").read_bytes())
        # Align the image to its line-box top to remove the baseline/descender gap.
        image = render_template(
            "html/status-image.html",
            path=path,
            label=label,
            status=status,
        ).rstrip()
        cells = [image, f'`{item["repository"]}`', f'{post_link(item)} · #{item["number"]}']
        if merged:
            cells.append(datetime.fromisoformat(item["merged_at"]).date().isoformat())
        parts.append("| " + " | ".join(cells) + " |")

    if not facts["items"]:
        if facts.get("pending"):
            message = "Awaiting a successful public GitHub API fetch."
        elif merged:
            message = "No merged public pull requests found."
        else:
            message = "No open public pull requests or issues."
        cells = ["—", "—", message] + (["—"] if merged else [])
        parts.append("| " + " | ".join(cells) + " |")
    return "\n".join(parts)


def snake_images(
    state: dict, palettes: dict, assets: Assets, snake_dir: Path | None
) -> dict[str, str]:
    """Prefer fresh animation, then cached animation, otherwise an honest placeholder."""
    paths = state.get("snake", {})
    for theme, palette in palettes.items():
        candidate = snake_dir / f"snake-{theme}.svg" if snake_dir else None
        cached = inside(assets.root, paths[theme]) if paths.get(theme) else None
        if candidate and candidate.is_file():
            content = candidate.read_bytes()
        elif cached and cached.is_file() and f"/snake-{theme}-pending." not in paths[theme]:
            content = cached.read_bytes()
        else:
            placeholder = cards.pending(
                "Contribution snake",
                palette,
                "The pinned Action generates your public grid once this profile repository is public. "
                "No other account's data is shown.",
                width=880,
            )
            paths[theme] = assets.put(f"snake-{theme}-pending", placeholder)
            continue
        paths[theme] = assets.put(f"snake-{theme}", cards.snake_card(content, palette))
    state["snake"] = paths
    return paths


def render(
    markdown: str,
    config: dict,
    state: dict,
    assets: Assets,
    today: date,
    snake_dir: Path | None,
    *,
    regions=REGIONS,
    document: Path | None = None,
) -> str:
    username = config["username"]
    sources = state["sources"]
    palettes = config["colors"]
    typing_source = (ROOT / "src/assets/static/typing-iosevka.svg").read_bytes()
    entries = cards.quote_entries(inside(assets.root, config["quotes"]).read_text())
    paths: dict[str, dict[str, str]] = {
        "typing-iosevka": {}, "stats": {}, "timeline": {}, "quote": {},
    }
    for theme, palette in palettes.items():
        rendered_cards = {
            "typing-iosevka": cards.typing_card(typing_source, palette),
            "stats": cards.stats_card(username, sources.get("contributions"), today, palette),
            "timeline": cards.timeline_card(username, sources.get("calendar"), palette),
            "quote": cards.quote_card(entries, today, palette),
        }
        for name, content in rendered_cards.items():
            paths[name][theme] = assets.put(f"{name}-{theme}", content)

    replacements = {
        "typing": themed_images(paths["typing-iosevka"], "Typing introduction — outlined Iosevka"),
        "stats": themed_images(
            paths["stats"], f"{username}'s public GitHub contribution statistics", width=467,
        ),
        "timeline": themed_images(paths["timeline"], f"{username}'s 365-day contribution timeline"),
        "quote": themed_images(
            paths["quote"], "Quote card from quotes.txt", link="./" + config["quotes"],
        ),
    }
    fingerprint = config["pgp"]["fingerprint"]
    if not re.fullmatch(r"[A-Fa-f0-9]{40,64}", fingerprint):
        raise ValueError("Invalid configured public PGP fingerprint")
    pgp_path = assets.put("pgp", cards.badge("pgp", "0x" + fingerprint[-16:].upper()))
    replacements["pgp"] = f'[![PGP key]({pgp_path})](https://github.com/{username}.gpg)'

    snake_paths = snake_images(state, palettes, assets, snake_dir)
    replacements["snake"] = themed_images(snake_paths, f"{username}'s contribution snake", width=1000)
    for region in ("activity", "merged"):
        facts = sources.get(region, {"items": [], "pending": True})
        replacements[region] = activity_table(facts, assets, merged=region == "merged")
    if "posts" in sources:
        posts = sources["posts"]["items"]
        replacements["posts47"] = post_rows(posts[:config["blog"]["rows"]])
    for name, value in replacements.items():
        if name not in regions:
            continue
        if document is not None:
            value = document_links(value, assets.root, document)
        markdown = replace_region(markdown, name, value)
    return markdown


def validate_regions(markdown: str, regions=REGIONS):
    if not regions or len(set(regions)) != len(regions) or set(regions) - set(REGIONS):
        raise ValueError("Configured regions must be unique, known region names")
    markers = re.findall(r"<!-- profile:([\w-]+):(start|end) -->", markdown)
    if {name for name, _ in markers} - set(regions):
        raise ValueError("Unexpected generated region for this document")
    for name in regions:
        if (
            len(list(region_pattern(name).finditer(markdown))) != 1
            or markers.count((name, "start")) != 1
            or markers.count((name, "end")) != 1
        ):
            raise ValueError(f"Missing or duplicate generated region: {name}")


def validate(
    root: Path,
    config: dict,
    markdown: str,
    *,
    regions=REGIONS,
    document: Path | None = None,
) -> None:
    validate_regions(markdown, regions)
    for path in linked_files(root, markdown, document):
        if path.suffix != ".svg":
            continue
        if not path.is_file():
            raise ValueError(f"Missing SVG: {path.relative_to(root)}")
        ET.parse(path)
    hosted_widgets = (
        "img.shields.io",
        "capsule-render.vercel.app",
        "quotes-github-readme.vercel.app",
        "github-readme-stats-fast.vercel.app",
        "github-profile-summary-cards.vercel.app",
        "readme-typing-svg.demolab.com",
    )
    hosts = "|".join(re.escape(host) for host in hosted_widgets)
    for url in re.findall(rf'https://(?:{hosts})[^\s)"<]*', markdown):
        raise ValueError(f"Unexpected hosted widget dependency: {url.split('?')[0]}")
    if "<details" in markdown:
        raise ValueError("Collapsible sections must not be introduced")


def refresh(config: dict, state: dict, now: datetime) -> list[str]:
    token = os.environ.get("GITHUB_TOKEN", "")
    sources = state["sources"]
    username = config["username"]
    today = now.date()
    jobs: list[tuple[str, Callable[..., dict], tuple]] = [
        ("contributions", data.contributions, (username, now, token)),
        ("calendar", data.public_calendar, (username, today)),
        ("activity", data.activity, (username, today, token)),
        ("merged", data.recently_merged, (username, today, token)),
        ("posts", data.posts, (config["blog"]["feed"], today)),
    ]
    warnings = []
    for name, fetcher, arguments in jobs:
        try:
            sources[name] = fetcher(*arguments)
        except (ValueError, KeyError, TypeError, ET.ParseError, OSError) as exc:
            warning = f"{name}: {exc}; retaining previous successful data if available"
            warnings.append(warning)
            print("WARNING: " + warning, file=sys.stderr)
    return warnings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline", action="store_true", help="Render cached data without any network requests"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate marked sections and local assets without changes/network",
    )
    parser.add_argument("--snake-dir", type=Path)
    args = parser.parse_args()
    config = tomllib.loads((ROOT / "src/data/profile.toml").read_text())
    path = inside(ROOT, config["markdown"])
    regions = config.get("regions", REGIONS)
    original = path.read_text()
    # Check the README before network requests or any output changes.
    validate_regions(original, regions)
    if args.check:
        validate(ROOT, config, original, regions=regions, document=path)
        print("Profile regions and local assets are valid.")
        return
    cache_path = inside(ROOT, config["cache"])
    state = (
        json.loads(cache_path.read_text()) if cache_path.exists() else {"schema": 1, "sources": {}}
    )
    if state.get("schema") != 1 or not isinstance(state.get("sources"), dict):
        raise ValueError("Unsupported profile cache; refusing to overwrite it")
    now = datetime.now(UTC)
    warnings = [] if args.offline else refresh(config, state, now)
    assets = Assets(ROOT, config["generated_dir"])
    updated = render(
        original, config, state, assets, now.date(), args.snake_dir,
        regions=regions, document=path,
    )
    validate(ROOT, config, updated, regions=regions, document=path)
    if updated != original:
        path.write_text(updated)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if not cache_path.exists() or cache_path.read_text() != cache:
        cache_path.write_text(cache)
    assets.prune(updated, path)
    changed = updated != original
    print(
        f"Profile {'updated' if changed else 'unchanged'}; {len(warnings)} data-source warning(s)."
    )
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        details = (
            "\n".join("- " + warning for warning in warnings)
            if warnings
            else "All public data sources refreshed successfully."
        )
        with open(summary, "a", encoding="utf-8") as out:
            out.write("## Profile refresh\n\n" + details + "\n")


if __name__ == "__main__":
    main()
