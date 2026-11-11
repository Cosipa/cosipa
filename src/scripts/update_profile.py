#!/usr/bin/env python3
"""Refresh configured regions in the profile README and component showcase."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import UTC, date, datetime
import hashlib
from html import escape
import json
import os
from pathlib import Path
import re
import sys
import textwrap
import tomllib
import xml.etree.ElementTree as ET
from urllib.parse import quote as url_quote

import profile_cards as cards
import profile_data as data

ROOT = Path(__file__).resolve().parents[2]
LOCAL_LINKS = re.compile(
    r'''(?P<prefix>(?<!\\)\]\(|<(?:a|img)\b[^>]*?\b(?:href|src)=["'])'''
    r'''(?P<path>\.\.?/[^\s)"'<>#]+)'''
)
REGIONS = (
    "typing", "github-badges", "pgp", "stats", "timeline", "snake",
    "repository-placeholder", "activity", "merged", "quote", "posts47",
    "posts48a", "posts48b", "footer",
)


def inside(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or ".git" in path.relative_to(root).parts:
        raise ValueError("Output paths must stay inside the repository, outside .git")
    return path


def linked_files(root: Path, markdown: str, document: Path | None = None) -> set[Path]:
    """Resolve local Markdown/image links relative to their containing document."""
    directory = document.parent if document else root
    return {inside(root, str(directory / match["path"])) for match in LOCAL_LINKS.finditer(markdown)}


def document_links(markdown: str, root: Path, document: Path) -> str:
    """Convert generated repository-relative links to document-relative links."""
    def relative_link(match):
        target = inside(root, match["path"])
        relative = Path(os.path.relpath(target, document.parent)).as_posix()
        if not relative.startswith("../"):
            relative = "./" + relative
        return match["prefix"] + relative

    return LOCAL_LINKS.sub(relative_link, markdown)


def region_pattern(name: str) -> re.Pattern:
    marker = re.escape(name)
    return re.compile(
        rf"(<!-- profile:{marker}:start -->\n)(.*?)(\n<!-- profile:{marker}:end -->)",
        re.DOTALL,
    )


def replace_region(markdown: str, name: str, replacement: str) -> str:
    pattern = region_pattern(name)
    if len(list(pattern.finditer(markdown))) != 1:
        raise ValueError(f"Expected exactly one complete generated region: {name}")
    return pattern.sub(lambda match: match[1] + replacement.strip() + match[3], markdown)


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
                if key.lower().startswith("on") or (key.split("}")[-1] == "href" and not value.startswith("#")):
                    raise ValueError("External/active SVG references are forbidden")
        digest = hashlib.sha256(payload).hexdigest()[:12]
        path = self.directory / f"{name}.{digest}.svg"
        if not path.exists():
            path.write_bytes(payload)
        return "./" + path.relative_to(self.root).as_posix()

    def themed(self, name: str, palettes: dict, make_card: Callable[[dict], str | bytes]) -> dict[str, str]:
        """Store one variant per palette, using the same naming rule for every card."""
        return {
            theme: self.put(f"{name}-{theme}", make_card(palette))
            for theme, palette in palettes.items()
        }

    def prune(self, documents: list[tuple[Path, str]]):
        referenced = set()
        for document, markdown in documents:
            referenced.update(linked_files(self.root, markdown, document))
        for path in self.directory.glob("*.svg"):
            if re.fullmatch(r"[a-z0-9-]+\.[a-f0-9]{12}\.svg", path.name) and path not in referenced:
                path.unlink()


def md(text: str) -> str:
    # Preserve rendered text while preventing source data from becoming Markdown/HTML.
    value = re.sub(r"([\\`*_[\]{}|])", r"\\\1", escape(text, quote=False))
    # Wrapping must not turn an excerpt into a heading, list, or thematic break.
    value = re.sub(r"(?<!\S)([#=+-])", r"\\\1", value)
    return re.sub(r"(?<!\S)(\d+)\.(?=\s|$)", r"\1\\.", value)


def themed_images(paths: dict, alt: str, *, width: int | None = None, link: str | None = None) -> str:
    width_attr = f' width="{width}"' if width else ""
    # GitHub applies these markers to anchor hrefs using its selected site theme.
    # An SVG or <picture> media query only knows the browser/OS colour scheme.
    images = []
    for theme in ("dark", "light"):
        target = (link or paths[theme]) + f"#gh-{theme}-mode-only"
        images.append(
            f'<a href="{escape(target, quote=True)}">\n'
            f'  <img src="{escape(paths[theme], quote=True)}" alt="{escape(alt, quote=True)}"{width_attr}>\n'
            '</a>'
        )
    return "\n".join(images)


def post_date(post: dict, short=False) -> str:
    published = datetime.fromisoformat(post["published"])
    return published.strftime("%b %d, %Y") if short else f"{published:%B} {published.day}, {published.year}"


def post_link(post: dict) -> str:
    url = url_quote(post["url"], safe=":/?#&=%+-.~@_")
    return f'[{md(post["title"])}]({url})'


def wrapped_excerpt(excerpt: str, *, quoted=False) -> str:
    lines = textwrap.wrap(md(excerpt), 86, break_long_words=False, break_on_hyphens=False)
    prefix = "> " if quoted else ""
    return "\n".join(prefix + line for line in lines)


def post_rows(posts: list[dict]) -> str:
    parts = ["<table>"]
    for post in posts:
        parts.append(
            '<tr>\n<td width="20%" valign="top">' + post_date(post) + '</td>\n<td valign="top">\n\n'
            f'**{post_link(post)}**\n\n{wrapped_excerpt(post["excerpt"], quoted=True)}\n\n</td>\n</tr>'
        )
    return "\n".join(parts + ["</table>"])


def post_excerpts(posts: list[dict], kind: str) -> str:
    parts = []
    for post in posts:
        heading = f'**{post_link(post)}** · <sub>{post_date(post, short=True)}</sub>'
        if kind == "plain":
            parts.append(heading + "\n\n" + wrapped_excerpt(post["excerpt"]))
        elif kind == "quote":
            parts.append("> " + heading + "\n>\n" + wrapped_excerpt(post["excerpt"], quoted=True))
        else:
            raise ValueError(f"Unknown excerpt layout: {kind}")
    separator = "\n\n---\n\n" if kind == "plain" else "\n\n<!-- -->\n\n"
    return separator.join(parts)


def activity_table(facts: dict, assets: Assets, *, merged=False) -> str:
    status = "merged" if merged else "open"

    def status_image(kind):
        name = f"status-{kind}-{status}"
        return assets.put(name, (ROOT / f"src/assets/static/{name}.svg").read_bytes())

    headers = ["Status", "Repository", "Title"] + (["Merged (UTC)"] if merged else [])
    parts = ["| " + " | ".join(headers) + " |", "| " + " | ".join([":---:"] + [":--"] * (len(headers) - 1)) + " |"]
    for item in facts["items"]:
        kind = "pr" if merged or item["kind"] == "pr" else "issue"
        label = "PR" if kind == "pr" else "Issue"
        # Align the image to its line-box top to remove the baseline/descender gap.
        image = f'<img src="{escape(status_image(kind), quote=True)}" alt="{label} {status}" align="top">'
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


def github_badges(profile: dict | None, username: str, repository: str, assets: Assets) -> str:
    if not profile:
        path = assets.put("github-pending", cards.badge("github", "awaiting data"))
        return f'![GitHub data pending]({path})'
    stars = profile["repository_stars"]
    values = [
        ("followers", str(profile["followers"]), f"https://github.com/{username}?tab=followers"),
        ("stars", str(stars) if stars is not None else "unavailable", f"https://github.com/{repository}/stargazers"),
        ("updated", profile["repository_updated"] or "unavailable", f"https://github.com/{repository}/commits"),
        ("repos", str(profile["public_repos"]), f"https://github.com/{username}?tab=repositories"),
    ]
    return "\n".join(
        f'[![{label}]({assets.put(label, cards.badge(label, value))})]({link})'
        for label, value, link in values
    )


def snake_images(state: dict, palettes: dict, assets: Assets, snake_dir: Path | None) -> dict[str, str]:
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
                "Contribution snake", palette,
                "The pinned Action generates your public grid once this profile repository is public. "
                "No other account's data is shown.", width=880,
            )
            paths[theme] = assets.put(f"snake-{theme}-pending", placeholder)
            continue
        paths[theme] = assets.put(f"snake-{theme}", cards.snake_card(content, palette))
    state["snake"] = paths
    return paths


def render(
    markdown: str, config: dict, state: dict, assets: Assets, today: date, snake_dir: Path | None,
    *, regions=REGIONS, document: Path | None = None,
) -> str:
    username = config["username"]
    sources = state["sources"]
    palettes = config["colors"]
    typing_source = (ROOT / "src/assets/static/typing-iosevka.svg").read_bytes()
    typing_paths = assets.themed("typing-iosevka", palettes, lambda palette: cards.typing_card(typing_source, palette))
    replacements = {
        "footer": '![Decorative waving footer](./src/assets/static/footer-wave.svg)',
        "typing": themed_images(typing_paths, "Typing introduction — outlined Iosevka"),
        "github-badges": github_badges(sources.get("github"), username, config["repository"], assets),
    }
    fingerprint = config["pgp"]["fingerprint"]
    if not re.fullmatch(r"[A-Fa-f0-9]{40,64}", fingerprint):
        raise ValueError("Invalid configured public PGP fingerprint")
    pgp_path = assets.put("pgp", cards.badge("pgp", "0x" + fingerprint[-16:].upper()))
    replacements["pgp"] = f'[![PGP key]({pgp_path})](https://github.com/{username}.gpg)'

    # Each card declares its title, display width and palette-dependent renderer.
    card_specs = [
        ("stats", f"{username}'s public GitHub contribution statistics", 467,
         lambda palette: cards.stats_card(username, sources.get("contributions"), today, palette)),
        ("timeline", f"{username}'s 365-day contribution timeline", None,
         lambda palette: cards.timeline_card(username, sources.get("calendar"), palette)),
        ("repository-placeholder", "Repository preview placeholder", 400,
         lambda palette: cards.pending("Repository preview", palette, "Placeholder — no featured repository selected.", 400)),
    ]
    for region, title, width, make_card in card_specs:
        paths = assets.themed(region, palettes, make_card)
        replacements[region] = themed_images(paths, title, width=width)

    entries = cards.quote_entries(inside(assets.root, config["quotes"]).read_text())
    paths = assets.themed("quote", palettes, lambda palette: cards.quote_card(entries, today, palette))
    replacements["quote"] = themed_images(paths, "Quote card from quotes.txt", link="./" + config["quotes"])
    paths = snake_images(state, palettes, assets, snake_dir)
    replacements["snake"] = themed_images(paths, f"{username}'s contribution snake", width=1000)
    for region in ("activity", "merged"):
        facts = sources.get(region, {"items": [], "pending": True})
        replacements[region] = activity_table(facts, assets, merged=region == "merged")
    if "posts" in sources:
        posts = sources["posts"]["items"]
        replacements["posts47"] = post_rows(posts[:config["blog"]["rows"]])
        for region, kind in [("posts48a", "quote"), ("posts48b", "plain")]:
            replacements[region] = post_excerpts(posts[:config["blog"]["excerpts"]], kind)
    for name, value in replacements.items():
        if name in regions:
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
        if (len(list(region_pattern(name).finditer(markdown))) != 1
                or markers.count((name, "start")) != 1 or markers.count((name, "end")) != 1):
            raise ValueError(f"Missing or duplicate generated region: {name}")


def validate(
    root: Path, config: dict, markdown: str, *, regions=REGIONS, document: Path | None = None,
):
    validate_regions(markdown, regions)
    for path in linked_files(root, markdown, document):
        if path.suffix != ".svg":
            continue
        if not path.is_file():
            raise ValueError(f"Missing SVG: {path.relative_to(root)}")
        ET.parse(path)
    hosted_widgets = (
        "img.shields.io", "capsule-render.vercel.app", "quotes-github-readme.vercel.app",
        "github-readme-stats-fast.vercel.app", "github-profile-summary-cards.vercel.app",
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
    jobs = {
        "github": lambda: data.public_profile(config["username"], config["repository"], now.date(), token),
        "contributions": lambda: data.contributions(config["username"], now, token),
        "calendar": lambda: data.public_calendar(config["username"], now.date()),
        "activity": lambda: data.activity(config["username"], now.date(), token),
        "merged": lambda: data.recently_merged(config["username"], now.date(), token),
        "posts": lambda: data.posts(config["blog"]["feed"], now.date()),
    }
    warnings = []
    for name, fetcher in jobs.items():
        try:
            sources[name] = fetcher()
        except (ValueError, KeyError, TypeError, ET.ParseError, OSError) as exc:
            warning = f"{name}: {exc}; retaining previous successful data if available"
            warnings.append(warning)
            print("WARNING: " + warning, file=sys.stderr)
    return warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Render cached data without any network requests")
    parser.add_argument("--check", action="store_true", help="Validate marked sections and local assets without changes/network")
    parser.add_argument("--snake-dir", type=Path)
    args = parser.parse_args()
    config = tomllib.loads((ROOT / "src/data/profile.toml").read_text())
    targets = [(config["markdown"], config.get("regions", REGIONS))]
    if config.get("showcase_markdown"):
        targets.append((config["showcase_markdown"], config.get("showcase_regions", REGIONS)))
    documents = []
    for relative, regions in targets:
        path = inside(ROOT, relative)
        documents.append((path, regions, path.read_text()))
    if len({path for path, _, _ in documents}) != len(documents):
        raise ValueError("Markdown output paths must be distinct")
    # Check every document before network requests or any output changes.
    for path, regions, original in documents:
        validate_regions(original, regions)
        if args.check:
            validate(ROOT, config, original, regions=regions, document=path)
    if args.check:
        print("Profile regions and local assets are valid.")
        return
    cache_path = inside(ROOT, config["cache"])
    state = json.loads(cache_path.read_text()) if cache_path.exists() else {"schema": 1, "sources": {}}
    if state.get("schema") != 1 or not isinstance(state.get("sources"), dict):
        raise ValueError("Unsupported profile cache; refusing to overwrite it")
    now = datetime.now(UTC)
    warnings = [] if args.offline else refresh(config, state, now)
    assets = Assets(ROOT, config["generated_dir"])
    rendered = [(path, regions, original,
                 render(original, config, state, assets, now.date(), args.snake_dir, regions=regions, document=path))
                for path, regions, original in documents]
    for path, regions, _, updated in rendered:
        validate(ROOT, config, updated, regions=regions, document=path)
    for path, _, original, updated in rendered:
        if updated != original:
            path.write_text(updated)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if not cache_path.exists() or cache_path.read_text() != cache:
        cache_path.write_text(cache)
    # Catalogue-only assets must survive pruning even when absent from the README.
    assets.prune([(path, updated) for path, _, _, updated in rendered])
    changed = any(updated != original for _, _, original, updated in rendered)
    print(f"Profile {'updated' if changed else 'unchanged'}; {len(warnings)} data-source warning(s).")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        details = "\n".join("- " + warning for warning in warnings) if warnings else "All public data sources refreshed successfully."
        with open(summary, "a") as out:
            out.write("## Profile refresh\n\n" + details + "\n")


if __name__ == "__main__":
    main()
