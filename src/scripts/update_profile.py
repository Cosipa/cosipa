#!/usr/bin/env python3
"""Refresh configured regions in the profile README."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import quote as url_quote

if __package__:
    from . import profile_cards as cards
    from . import profile_data as data
    from . import profile_svg as svg_assets
    from .profile_markup import (
        REGIONS,
        escape_markdown,
        replace_region,
        resolve_linked_files,
        resolve_repository_path,
        rewrite_document_links,
        validate_document_content,
        validate_regions,
    )

    # Re-export the link iterator alongside the other Markdown helpers.
    from .profile_markup import iter_local_links as iter_local_links
    from .profile_templates import render as render_template
    from .profile_text import wrap_prose
else:
    import profile_cards as cards
    import profile_data as data
    import profile_svg as svg_assets
    from profile_markup import (
        REGIONS,
        escape_markdown,
        replace_region,
        resolve_linked_files,
        resolve_repository_path,
        rewrite_document_links,
        validate_document_content,
        validate_regions,
    )
    from profile_markup import iter_local_links as iter_local_links
    from profile_templates import render as render_template
    from profile_text import wrap_prose

ROOT = Path(__file__).resolve().parents[2]
EXCERPT_WRAP_COLUMNS = 86
SNAKE_PLACEHOLDER_WIDTH = 880
SNAKE_DISPLAY_WIDTH = 1000
CACHE_SCHEMA_VERSION = 1
CACHE_INDENT_SPACES = 2


class Assets:
    """Validate, content-address and prune the generated SVG files."""

    def __init__(self, root: Path, relative: str):
        self.root = root
        self.directory = resolve_repository_path(root, relative)
        self.directory.mkdir(parents=True, exist_ok=True)

    def put(self, name: str, content: str | bytes) -> str:
        svg_assets.validate_asset_name(name)
        payload = content.encode() if isinstance(content, str) else content
        svg_assets.validate_svg(payload)
        digest = hashlib.sha256(payload).hexdigest()[: svg_assets.ASSET_DIGEST_LENGTH]
        path = self.directory / f"{name}.{digest}.svg"
        if not path.exists():
            path.write_bytes(payload)
        return "./" + path.relative_to(self.root).as_posix()

    def prune(self, markdown: str, document: Path) -> None:
        referenced = resolve_linked_files(self.root, markdown, document)
        for path in self.directory.glob("*.svg"):
            if svg_assets.is_generated_asset(path.name) and path not in referenced:
                path.unlink()


def render_themed_images(
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


def format_post_date(post: dict) -> str:
    published = datetime.fromisoformat(post["published"])
    return f"{published:%B} {published.day}, {published.year}"


def render_post_link(post: dict) -> str:
    url = url_quote(post["url"], safe=":/?#&=%+-.~@_")
    return f"[{escape_markdown(post['title'])}]({url})"


def render_quoted_excerpt(excerpt: str) -> str:
    lines = wrap_prose(escape_markdown(excerpt), EXCERPT_WRAP_COLUMNS)
    return "\n".join("> " + line for line in lines)


def render_posts_table(posts: list[dict]) -> str:
    parts = ["<table>"]
    for post in posts:
        parts.append(
            render_template(
                "html/post-row.html",
                date=format_post_date(post),
                fragments={
                    "link": render_post_link(post),
                    "excerpt": render_quoted_excerpt(post["excerpt"]),
                },
            ).rstrip()
        )
    return "\n".join(parts + ["</table>"])


def render_markdown_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def render_activity_status_image(item: dict, assets: Assets, *, merged: bool) -> str:
    kind = "pr" if merged or item["kind"] == "pr" else "issue"
    status = "merged" if merged else "open"
    name = f"status-{kind}-{status}"
    path = assets.put(name, (ROOT / f"src/assets/static/{name}.svg").read_bytes())
    # Align the image to its line-box top to remove the baseline/descender gap.
    return render_template(
        "html/status-image.html",
        url=item["url"],
        path=path,
        label="PR" if kind == "pr" else "Issue",
        status=status,
    ).rstrip()


def render_activity_row(item: dict, assets: Assets, *, merged: bool) -> str:
    cells = [
        render_activity_status_image(item, assets, merged=merged),
        f"`{item['repository']}`",
        f"{render_post_link(item)} · #{item['number']}",
    ]
    if merged:
        cells.append(datetime.fromisoformat(item["merged_at"]).date().isoformat())
    return render_markdown_row(cells)


def empty_activity_message(facts: dict, *, merged: bool) -> str:
    if facts.get("pending"):
        return "Awaiting a successful public GitHub API fetch."
    if merged:
        return "No merged public pull requests found."
    return "No open public pull requests or issues."


def render_activity_table(facts: dict, assets: Assets, *, merged: bool = False) -> str:
    headers = ["Status", "Repository", "Title"] + (["Merged (UTC)"] if merged else [])
    alignment = [":---:"] + [":--"] * (len(headers) - 1)
    rows = [render_markdown_row(headers), render_markdown_row(alignment)]
    rows.extend(
        render_activity_row(item, assets, merged=merged) for item in facts["items"]
    )
    if not facts["items"]:
        cells = ["—", "—", empty_activity_message(facts, merged=merged)]
        rows.append(render_markdown_row(cells + (["—"] if merged else [])))
    return "\n".join(rows)


def read_snake_source(
    root: Path, theme: str, cached_path: str | None, snake_dir: Path | None
) -> bytes | None:
    candidate = snake_dir / f"snake-{theme}.svg" if snake_dir else None
    cached = resolve_repository_path(root, cached_path) if cached_path else None
    if candidate and candidate.is_file():
        return candidate.read_bytes()
    if (
        cached_path
        and cached
        and cached.is_file()
        and f"/snake-{theme}-pending." not in cached_path
    ):
        return cached.read_bytes()
    return None


def render_and_store_snake_images(
    state: dict, palettes: dict, assets: Assets, snake_dir: Path | None
) -> dict[str, str]:
    """Prefer fresh animation, then cached animation, otherwise an honest placeholder."""
    paths = state.get("snake", {})
    for theme, palette in palettes.items():
        content = read_snake_source(assets.root, theme, paths.get(theme), snake_dir)
        if content is not None:
            paths[theme] = assets.put(
                f"snake-{theme}", cards.render_snake_card(content, palette)
            )
            continue
        placeholder = cards.render_placeholder(
            "Contribution snake",
            palette,
            "The pinned Action generates your public grid once this profile repository is public. "
            "No other account's data is shown.",
            width=SNAKE_PLACEHOLDER_WIDTH,
        )
        paths[theme] = assets.put(f"snake-{theme}-pending", placeholder)
    state["snake"] = paths
    return paths


def render_and_store_cards(
    config: dict, sources: dict, assets: Assets, today: date
) -> dict[str, dict[str, str]]:
    """Render each card once per palette and store its content-addressed path."""
    username = config["username"]
    palettes = config["colors"]
    typing_source = (ROOT / "src/assets/static/typing-iosevka.svg").read_bytes()
    entries = cards.parse_quote_entries(
        resolve_repository_path(assets.root, config["quotes"]).read_text()
    )
    paths: dict[str, dict[str, str]] = {
        "typing-iosevka": {},
        "stats": {},
        "timeline": {},
        "quote": {},
    }
    for theme, palette in palettes.items():
        rendered_cards = {
            "typing-iosevka": cards.render_typing_card(typing_source, palette),
            "stats": cards.render_stats_card(
                username, sources.get("contributions"), today, palette
            ),
            "timeline": cards.render_timeline_card(
                username, sources.get("calendar"), palette
            ),
            "quote": cards.render_quote_card(entries, today, palette),
        }
        for name, content in rendered_cards.items():
            paths[name][theme] = assets.put(f"{name}-{theme}", content)
    return paths


def build_widget_replacements(
    config: dict, state: dict, assets: Assets, today: date, snake_dir: Path | None
) -> dict[str, str]:
    username = config["username"]
    sources = state["sources"]
    paths = render_and_store_cards(config, sources, assets, today)
    replacements = {
        "typing": render_themed_images(
            paths["typing-iosevka"], "Typing introduction — outlined Iosevka"
        ),
        "stats": render_themed_images(
            paths["stats"],
            f"{username}'s public GitHub contribution statistics",
            width=cards.STATS.width,
        ),
        "timeline": render_themed_images(
            paths["timeline"], f"{username}'s 365-day contribution timeline"
        ),
        "quote": render_themed_images(
            paths["quote"],
            "Quote card from quotes.txt",
            link="./" + config["quotes"],
        ),
    }
    key_id = svg_assets.pgp_key_id(config["pgp"]["fingerprint"])
    pgp_path = assets.put("pgp", cards.render_badge("pgp", key_id))
    replacements["pgp"] = f"[![PGP key]({pgp_path})](https://github.com/{username}.gpg)"

    snake_paths = render_and_store_snake_images(
        state, config["colors"], assets, snake_dir
    )
    replacements["snake"] = render_themed_images(
        snake_paths, f"{username}'s contribution snake", width=SNAKE_DISPLAY_WIDTH
    )
    for region in ("activity", "merged"):
        facts = sources.get(region, {"items": [], "pending": True})
        replacements[region] = render_activity_table(
            facts, assets, merged=region == "merged"
        )
    if "posts" in sources:
        posts = sources["posts"]["items"]
        replacements["posts47"] = render_posts_table(posts[: config["blog"]["rows"]])
    return replacements


def render_profile(
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
    replacements = build_widget_replacements(config, state, assets, today, snake_dir)
    for name, value in replacements.items():
        if name not in regions:
            continue
        if document is not None:
            value = rewrite_document_links(value, assets.root, document)
        markdown = replace_region(markdown, name, value)
    return markdown


def validate_profile(
    root: Path,
    config: dict,
    markdown: str,
    *,
    regions=REGIONS,
    document: Path | None = None,
) -> None:
    validate_regions(markdown, regions)
    for path in resolve_linked_files(root, markdown, document):
        if path.suffix != ".svg":
            continue
        if not path.is_file():
            raise ValueError(f"Missing SVG: {path.relative_to(root)}")
        ET.parse(path)
    validate_document_content(markdown)


def refresh_sources(config: dict, state: dict, now: datetime) -> list[str]:
    token = os.environ.get("GITHUB_TOKEN", "")
    sources = state["sources"]
    username = config["username"]
    today = now.date()
    jobs: list[tuple[str, Callable[..., dict], tuple]] = [
        ("contributions", data.fetch_contributions, (username, now, token)),
        ("calendar", data.fetch_public_calendar, (username, today)),
        ("activity", data.fetch_open_activity, (username, today, token)),
        ("merged", data.fetch_recently_merged_prs, (username, today, token)),
        ("posts", data.fetch_posts, (config["blog"]["feed"], today)),
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


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Render cached data without any network requests",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate marked sections and local assets without changes/network",
    )
    parser.add_argument("--snake-dir", type=Path)
    return parser.parse_args()


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {"schema": CACHE_SCHEMA_VERSION, "sources": {}}
    state = json.loads(path.read_text())
    if state.get("schema") != CACHE_SCHEMA_VERSION or not isinstance(
        state.get("sources"), dict
    ):
        raise ValueError("Unsupported profile cache; refusing to overwrite it")
    return state


def write_if_changed(path: Path, content: str) -> None:
    if path.exists() and path.read_text() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def write_workflow_summary(warnings: list[str]) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    details = (
        "\n".join("- " + warning for warning in warnings)
        if warnings
        else "All public data sources refreshed successfully."
    )
    with open(summary, "a", encoding="utf-8") as output:
        output.write("## Profile refresh\n\n" + details + "\n")


def main() -> None:
    args = parse_arguments()
    config = tomllib.loads((ROOT / "src/data/profile.toml").read_text())
    path = resolve_repository_path(ROOT, config["markdown"])
    regions = config.get("regions", REGIONS)
    original = path.read_text()
    # Check the README before network requests or any output changes.
    validate_regions(original, regions)
    if args.check:
        validate_profile(ROOT, config, original, regions=regions, document=path)
        print("Profile regions and local assets are valid.")
        return
    cache_path = resolve_repository_path(ROOT, config["cache"])
    state = load_cache(cache_path)
    now = datetime.now(UTC)
    warnings = [] if args.offline else refresh_sources(config, state, now)
    assets = Assets(ROOT, config["generated_dir"])
    updated = render_profile(
        original,
        config,
        state,
        assets,
        now.date(),
        args.snake_dir,
        regions=regions,
        document=path,
    )
    validate_profile(ROOT, config, updated, regions=regions, document=path)
    write_if_changed(path, updated)
    cache = (
        json.dumps(
            state, indent=CACHE_INDENT_SPACES, sort_keys=True, ensure_ascii=False
        )
        + "\n"
    )
    write_if_changed(cache_path, cache)
    assets.prune(updated, path)
    changed = updated != original
    print(
        f"Profile {'updated' if changed else 'unchanged'}; {len(warnings)} data-source warning(s)."
    )
    write_workflow_summary(warnings)


if __name__ == "__main__":
    main()
