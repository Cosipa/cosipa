#!/usr/bin/env python3
"""Refresh marked sections of test.md; never rewrite its layout or README.md."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
import hashlib
from html import escape
import json
import math
import os
from pathlib import Path
import re
import sys
import textwrap
import tomllib
import xml.etree.ElementTree as ET
from urllib.parse import quote as url_quote

import profile_data as data

ROOT = Path(__file__).resolve().parent.parent
REGIONS = ("typing", "github-badges", "pgp", "stats", "timeline", "snake",
           "repository-placeholder", "activity", "merged", "quote", "posts47",
           "posts48a", "posts48b", "footer")
SVG_NS = "{http://www.w3.org/2000/svg}"


def inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or ".git" in path.relative_to(root.resolve()).parts:
        raise ValueError("Output paths must stay inside the repository, outside .git")
    return path


def region_pattern(name: str):
    return re.compile(r"(<!-- profile:" + re.escape(name) + r":start -->\n)(.*?)(\n<!-- profile:" + re.escape(name) + r":end -->)", re.S)


def replace_region(markdown: str, name: str, replacement: str) -> str:
    pattern = region_pattern(name)
    if len(list(pattern.finditer(markdown))) != 1:
        raise ValueError(f"Expected exactly one complete generated region: {name}")
    return pattern.sub(lambda m: m[1] + replacement.strip() + m[3], markdown)


def md(text: str) -> str:
    # Preserve rendered text while preventing source data from becoming Markdown/HTML.
    value = re.sub(r"([\\`*_[\]{}|])", r"\\\1", escape(text, quote=False))
    # Wrapping must not turn an excerpt into a heading, list, or thematic break.
    value = re.sub(r"(?<!\S)([#=+-])", r"\\\1", value)
    return re.sub(r"(?<!\S)(\d+)\.(?=\s|$)", r"\1\\.", value)


def text(x, y, value, color, size=13, *, anchor="start", weight="normal", length=None):
    sizing = f' textLength="{length}" lengthAdjust="spacingAndGlyphs"' if length else ""
    return f'<text x="{x}" y="{y}" fill="#{color}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}"{sizing}>{escape(str(value))}</text>'


def svg(width: int, height: int, title: str, body: str, background: str, description: str = "") -> str:
    document = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">'
                f'<title id="title">{escape(title)}</title><desc id="desc">{escape(description or title)}</desc>'
                f'<rect width="{width}" height="{height}" rx="5" fill="#{background}"/>'
                f'<g font-family="Verdana,DejaVu Sans,sans-serif">{body}</g></svg>\n')
    ET.fromstring(document)
    return document


# DejaVu Sans 2.37 advances at 11px, ASCII 32–126. Fixed authoring-time metrics
# avoid a font dependency in Actions; SVG textLength also prevents viewer drift.
BADGE_ADVANCES = (
    3.5, 4.41, 5.06, 9.22, 7, 10.45, 8.58, 3.02, 4.29, 4.29, 5.5, 9.22, 3.5, 3.97, 3.5, 3.71,
    7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 3.71, 3.71, 9.22, 9.22, 9.22, 5.84,
    11, 7.52, 7.55, 7.68, 8.47, 6.95, 6.33, 8.52, 8.27, 3.24, 3.24, 7.21, 6.13, 9.49, 8.23, 8.66,
    6.63, 8.66, 7.64, 6.98, 6.72, 8.05, 7.52, 10.88, 7.54, 6.72, 7.54, 4.29, 3.71, 4.29, 9.22, 5.5,
    5.5, 6.74, 6.98, 6.05, 6.98, 6.77, 3.87, 6.98, 6.97, 3.06, 3.06, 6.37, 3.06, 10.72, 6.97, 6.73,
    6.98, 6.98, 4.52, 5.73, 4.31, 6.97, 6.51, 9, 6.51, 6.51, 5.77, 7, 3.71, 7, 9.22,
)


def badge_text_width(value: str) -> float:
    return round(sum(BADGE_ADVANCES[ord(c) - 32] if 32 <= ord(c) <= 126 else 7 for c in value), 2)


def badge(label: str, value: str, label_color="555555", color="313131") -> str:
    left = math.ceil(badge_text_width(label)) + 12
    right = math.ceil(badge_text_width(value)) + 12
    width = left + right
    # Match Shields' flat style: both ends clipped, subtle bevel, text shadow.
    body = (f'<defs><linearGradient id="shade" x2="0" y2="100%">'
            '<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
            '<stop offset="1" stop-opacity=".1"/></linearGradient>'
            f'<clipPath id="badge"><rect width="{width}" height="20" rx="3"/></clipPath></defs>'
            f'<g clip-path="url(#badge)"><rect width="{left}" height="20" fill="#{label_color}"/>'
            f'<rect x="{left}" width="{right}" height="20" fill="#{color}"/>'
            f'<rect width="{width}" height="20" fill="url(#shade)"/></g>')
    for x, content in [(left / 2, label), (left + right / 2, value)]:
        length = badge_text_width(content)
        body += '<g opacity=".3">' + text(x, 15, content, "010101", 11, anchor="middle", length=length) + '</g>'
        body += text(x, 14, content, "ffffff", 11, anchor="middle", length=length)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img">'
            f'<title>{escape(label + ": " + value)}</title>'
            f'<g font-family="Verdana,Geneva,DejaVu Sans,sans-serif">{body}</g></svg>\n')


class Assets:
    def __init__(self, root: Path, relative: str):
        self.root = root
        self.directory = inside(root, relative)
        self.directory.mkdir(parents=True, exist_ok=True)

    def put(self, name: str, content: str | bytes) -> str:
        if not re.fullmatch(r"[a-z0-9-]+", name):
            raise ValueError("Invalid generated asset name")
        payload = content.encode() if isinstance(content, str) else content
        parsed = ET.fromstring(payload)
        if parsed.tag != SVG_NS + "svg":
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

    def prune(self, markdown: str):
        for path in self.directory.glob("*.svg"):
            if re.fullmatch(r"[a-z0-9-]+\.[a-f0-9]{12}\.svg", path.name):
                relative = "./" + path.relative_to(self.root).as_posix()
                if relative not in markdown:
                    path.unlink()


def themed_images(paths: dict, alt: str, *, width: int | None = None, link: str | None = None) -> str:
    width_attr = f' width="{width}"' if width else ""
    # GitHub applies these markers to anchor hrefs using its selected site theme.
    # An SVG or <picture> media query only knows the browser/OS colour scheme.
    images = []
    for theme in ("dark", "light"):
        target = (link or paths[theme]) + f"#gh-{theme}-mode-only"
        images.append(f'<a href="{escape(target, quote=True)}">\n'
                      f'  <img src="{escape(paths[theme], quote=True)}" alt="{escape(alt, quote=True)}"{width_attr}>\n'
                      '</a>')
    return "\n".join(images)


def pending(title: str, colors: dict, detail="Awaiting the first successful GitHub Actions run.", width=467, height=145) -> str:
    body = text(20, 35, title, colors["title"], 18)
    for i, line in enumerate(textwrap.wrap(detail, max(30, (width - 40) // 7))):
        body += text(20, 70 + i * 21, line, colors["text"], 12)
    return svg(width, height, title, body, colors["background"], detail)


def stats_card(username: str, facts: dict | None, today: date, colors: dict) -> str:
    if not facts or facts.get("year") != today.year:
        return pending(f"{username}'s GitHub stats", colors,
                       "Accurate calendar-year counts await the workflow's GitHub token. No estimated totals are shown.")
    private = facts["published_private"]
    rows = [("Public commit contributions", f'{facts["public_commits"]:,}'),
            ("Public PRs opened", f'{facts["public_prs"]:,}'),
            ("Public issues opened", f'{facts["public_issues"]:,}'),
            ("Public PR reviews", f'{facts["public_reviews"]:,}'),
            ("Published restricted contributions", f"{private:,}" if private is not None else "Not published / none")]
    body = text(20, 30, f"{username}'s GitHub stats", colors["accent"], 18)
    body += text(20, 52, f'{facts["year"]} YTD through {facts["as_of"]} (UTC)', colors["text"], 11)
    for i, (label, count) in enumerate(rows):
        body += text(20, 82 + i * 23, label, colors["text"], 12)
        body += text(445, 82 + i * 23, count, colors["accent"], 12, anchor="end")
    body += text(20, 211, "Restricted private activity: all types, not just commits.", colors["text"], 10)
    return svg(467, 229, f"{username}'s public contribution stats", body, colors["background"],
               "Public commit contributions are eligible commits to public repositories, not every Git commit on every branch. Private counts are only anonymized totals published by GitHub.")


def timeline_card(username: str, facts: dict | None, colors: dict) -> str:
    if not facts:
        return pending(f"{username}'s contributions", colors, width=846, height=190)
    # JSON keys are sorted when cached; explicitly sort dates before charting.
    values = [facts["days"][d] for d in sorted(facts["days"])]
    weeks = [sum(values[i:i + 7]) for i in range(0, len(values), 7)]
    maximum = max(max(weeks), 1)
    coordinates = [(24 + i * 798 / max(1, len(weeks) - 1), 166 - v * 90 / maximum) for i, v in enumerate(weeks)]
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coordinates)
    body = (f'<defs><linearGradient id="line"><stop stop-color="#{colors["accent"]}"/>'
            f'<stop offset="1" stop-color="#{colors["secondary"]}"/></linearGradient>'
            f'<linearGradient id="area" x2="0" y2="1"><stop stop-color="#{colors["accent"]}" stop-opacity=".35"/>'
            f'<stop offset="1" stop-color="#{colors["secondary"]}" stop-opacity=".02"/></linearGradient></defs>'
            f'<rect x=".5" y=".5" width="845" height="207" rx="5" fill="none" stroke="#{colors["border"]}"/>')
    body += text(24, 31, username, colors["title"], 20, weight="bold")
    body += text(822, 31, f'{facts["calendar_total"]:,} contributions', colors["secondary"], 19, anchor="end", weight="bold")
    body += text(24, 54, f'365 days: {facts["calendar_start"]} – {facts["calendar_end"]}', colors["text"], 11)
    for y in [76, 106, 136, 166]:
        body += f'<path d="M24 {y}H822" stroke="#{colors["border"]}" stroke-dasharray="3 6"/>'
    body += f'<polygon points="24,166 {points} 822,166" fill="url(#area)"/>'
    body += f'<polyline points="{points}" fill="none" stroke="url(#line)" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>'
    peak = weeks.index(max(weeks))
    x, y = coordinates[peak]
    body += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#{colors["secondary"]}" stroke="#{colors["background"]}" stroke-width="2"><title>Peak week: {max(weeks):,} contributions</title></circle>'
    body += text(24, 193, "Weekly totals · includes anonymized private activity only when publicly visible", colors["text"], 10)
    return svg(846, 208, f"{username}'s 365-day contribution timeline", body, colors["background"])


def quote_entries(source: str) -> list[tuple[str, str]]:
    result = []
    for line in source.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        quote, _, author = line.partition("\t")
        if quote.strip():
            result.append((quote.strip(), author.strip()))
    return result


def quote_card(entries: list, today: date, colors: dict) -> str:
    if not entries:
        return pending("No quotes configured", colors, "Add your own quotes to quotes.txt. Nothing is fetched or attributed to you.", width=600)
    quote, author = entries[today.toordinal() % len(entries)]
    lines = textwrap.wrap(quote, 58, break_long_words=False, break_on_hyphens=False)
    last_baseline = 42 + 23 * (len(lines) - 1)
    height = max(96, last_baseline + (52 if author else 26))
    body = f'<path d="M22 20V{height - 20}" stroke="#{colors["accent"]}" stroke-width="3" stroke-linecap="round"/>'
    body += text(35, 56, "“", colors["accent"], 42)
    body += '<g font-style="italic">' + "".join(
        text(62, 42 + i * 23, line + ("”" if i == len(lines) - 1 else ""), colors["title"], 15)
        for i, line in enumerate(lines)) + '</g>'
    if author:
        body += text(62, last_baseline + 28, "— " + author, colors["text"], 12)
    return svg(600, height, "Quote from quotes.txt", body, colors["background"], quote + (f" — {author}" if author else ""))


def typing_card(content: bytes, colors: dict) -> bytes:
    """Recolour outlined glyphs; never change character steps or line timing."""
    ET.register_namespace("", SVG_NS[1:-1])
    root = ET.fromstring(content)
    lettering = root.find('.//*[@id="typing-text"]')
    if lettering is None:
        raise ValueError("Outlined typing SVG is missing its lettering group")
    lettering.set("fill", "#" + colors["typing"])
    return ET.tostring(root, encoding="utf-8")


def snake_card(content: bytes, colors: dict) -> bytes:
    """Theme fresh or cached snk output without changing its animation or data."""
    ET.register_namespace("", SVG_NS[1:-1])
    root = ET.fromstring(content)
    style = root.find(SVG_NS + "style")
    if style is None or not style.text:
        raise ValueError("Snake SVG is missing its palette")
    palette = {"cb": "1b1f230a", "cs": colors["snake"], "ce": colors["dots"][0],
               **{f"c{i}": color for i, color in enumerate(colors["dots"])}}
    for name, color in palette.items():
        style.text, count = re.subn(r"--" + name + r":[^;}]+", f"--{name}:#{color}", style.text, count=1)
        if count != 1:
            raise ValueError(f"Snake SVG is missing palette entry {name}")
    background = root.find(f'{SVG_NS}rect[@id="snake-background"]')
    if background is None:
        background = ET.Element(SVG_NS + "rect", {"id": "snake-background"})
        root.insert(0, background)
    x, y, width, height = root.attrib["viewBox"].split()
    background.attrib.update(x=x, y=y, width=width, height=height, rx="8", fill="#" + colors["background"])
    return ET.tostring(root, encoding="utf-8")


def post_date(post: dict, short=False) -> str:
    dt = datetime.fromisoformat(post["published"])
    return dt.strftime("%b %d, %Y") if short else f"{dt:%B} {dt.day}, {dt.year}"


def post_link(post: dict) -> str:
    url = url_quote(post["url"], safe=":/?#&=%+-.~@_")
    return f'[{md(post["title"])}]({url})'


def quoted(excerpt: str) -> str:
    return "\n".join("> " + line for line in textwrap.wrap(md(excerpt), 86, break_long_words=False, break_on_hyphens=False))


def post_rows(posts: list[dict]) -> str:
    parts = ["<table>"]
    for post in posts:
        parts.append('<tr>\n<td width="20%" valign="top">' + post_date(post) + '</td>\n<td valign="top">\n\n'
                     f'**{post_link(post)}**\n\n{quoted(post["excerpt"])}\n\n</td>\n</tr>')
    return "\n".join(parts + ["</table>"])


def post_excerpts(posts: list[dict], kind: str) -> str:
    parts = []
    for post in posts:
        heading = f'**{post_link(post)}** · <sub>{post_date(post, short=True)}</sub>'
        if kind == "plain":
            parts.append(heading + "\n\n" + "\n".join(textwrap.wrap(md(post["excerpt"]), 86, break_long_words=False, break_on_hyphens=False)))
        elif kind == "quote":
            parts.append("> " + heading + "\n>\n" + quoted(post["excerpt"]))
        else:
            raise ValueError(f"Unknown excerpt layout: {kind}")
    return ("\n\n---\n\n" if kind == "plain" else "\n\n<!-- -->\n\n").join(parts)


def activity_table(facts: dict, assets: Assets, *, merged=False) -> str:
    status = "merged" if merged else "open"

    def status_image(kind):
        name = f"status-{kind}-{status}"
        return assets.put(name, (ROOT / f"profile-showcase/static/{name}.svg").read_bytes())

    headers = ["Status", "Repository", "Title"] + (["Merged (UTC)"] if merged else [])
    parts = ["| " + " | ".join(headers) + " |", "| " + " | ".join([":---:"] + [":--"] * (len(headers) - 1)) + " |"]
    for item in facts["items"]:
        kind = "pr" if merged or item["kind"] == "pr" else "issue"
        label = "PR" if kind == "pr" else "Issue"
        # The cell is vertically middle-aligned. Align the image to its line-box
        # top (not the cell top) to remove the inline baseline/descender gap.
        image = f'<img src="{escape(status_image(kind), quote=True)}" alt="{label} {status}" align="top">'
        cells = [image, f'`{item["repository"]}`',
                 f'{post_link({"title": item["title"], "url": item["url"]})} · #{item["number"]}']
        if merged:
            cells.append(datetime.fromisoformat(item["merged_at"]).date().isoformat())
        parts.append("| " + " | ".join(cells) + " |")
    if not facts["items"]:
        message = ("Awaiting a successful public GitHub API fetch." if facts.get("pending") else
                   "No merged public pull requests found." if merged else "No open public pull requests or issues.")
        cells = ["—", "—", message] + (["—"] if merged else [])
        parts.append("| " + " | ".join(cells) + " |")
    table = "\n".join(parts)
    if merged and not facts["items"]:
        # Preview the requested style without fabricating a merged PR row.
        table = f'<sub>Status style preview:</sub> ![Merged]({status_image("pr")})\n\n' + table
    return table


def render(markdown: str, config: dict, state: dict, assets: Assets, today: date, snake_dir: Path | None) -> str:
    user, repo = config["username"], config["repository"]
    sources = state["sources"]
    colors = config["colors"]
    typing_source = (ROOT / "profile-showcase/static/typing-iosevka.svg").read_bytes()
    typing_paths = {theme: assets.put(f"typing-iosevka-{theme}", typing_card(typing_source, palette))
                    for theme, palette in colors.items()}
    replacements = {
        "footer": '![Decorative waving footer](./profile-showcase/static/footer-wave.svg)',
        "typing": themed_images(typing_paths, "Typing introduction — outlined Iosevka"),
    }
    profile = sources.get("github")
    if profile:
        values = [("followers", str(profile["followers"]), f"https://github.com/{user}?tab=followers"),
                  ("stars", str(profile["repository_stars"]) if profile["repository_stars"] is not None else "unavailable", f"https://github.com/{repo}/stargazers"),
                  ("updated", profile["repository_updated"] or "unavailable", f"https://github.com/{repo}/commits"),
                  ("repos", str(profile["public_repos"]), f"https://github.com/{user}?tab=repositories")]
        replacements["github-badges"] = "\n".join(f'[![{label}]({assets.put(label, badge(label, value))})]({link})' for label, value, link in values)
    else:
        replacements["github-badges"] = f'![GitHub data pending]({assets.put("github-pending", badge("github", "awaiting data"))})'
    fingerprint = config["pgp"]["fingerprint"]
    if not re.fullmatch(r"[A-Fa-f0-9]{40,64}", fingerprint):
        raise ValueError("Invalid configured public PGP fingerprint")
    replacements["pgp"] = f'[![PGP key]({assets.put("pgp", badge("pgp", "0x" + fingerprint[-16:].upper()))})](https://github.com/{user}.gpg)'
    facts = sources.get("contributions")
    for region, title, factory in [
        ("stats", f"{user}'s public GitHub contribution statistics", lambda c: stats_card(user, facts, today, c)),
        ("timeline", f"{user}'s 365-day contribution timeline", lambda c: timeline_card(user, sources.get("calendar"), c)),
        ("repository-placeholder", "Repository preview placeholder", lambda c: pending("Repository preview", c, "Placeholder — no featured repository selected.", 400)),
    ]:
        paths = {theme: assets.put(f"{region}-{theme}", factory(palette)) for theme, palette in colors.items()}
        replacements[region] = themed_images(paths, title, width=467 if region == "stats" else 400 if region == "repository-placeholder" else None)
    entries = quote_entries(inside(assets.root, config["quotes"]).read_text())
    paths = {theme: assets.put(f"quote-{theme}", quote_card(entries, today, palette)) for theme, palette in colors.items()}
    replacements["quote"] = themed_images(paths, "Quote card from quotes.txt", link="./quotes.txt")
    snake_paths = state.get("snake", {})
    for theme in colors:
        candidate = snake_dir / f"snake-{theme}.svg" if snake_dir else None
        cached = inside(assets.root, snake_paths[theme]) if snake_paths.get(theme) else None
        if candidate and candidate.is_file():
            content = candidate.read_bytes()
        elif cached and cached.is_file() and f"/snake-{theme}-pending." not in snake_paths[theme]:
            content = cached.read_bytes()
        else:
            snake_paths[theme] = assets.put(f"snake-{theme}-pending", pending("Contribution snake", colors[theme], "The pinned Action generates your public grid once this profile repository is public. No other account's data is shown.", width=880))
            continue
        snake_paths[theme] = assets.put(f"snake-{theme}", snake_card(content, colors[theme]))
    state["snake"] = snake_paths
    replacements["snake"] = themed_images(snake_paths, f"{user}'s contribution snake", width=1000)
    if "activity" in sources:
        replacements["activity"] = activity_table(sources["activity"], assets)
    else:
        replacements["activity"] = activity_table({"items": [], "pending": True}, assets)
    replacements["merged"] = activity_table(sources.get("merged", {"items": [], "pending": True}), assets, merged=True)
    if "posts" in sources:
        posts = sources["posts"]["items"]
        replacements["posts47"] = post_rows(posts[:config["blog"]["rows"]])
        for region, kind in [("posts48a", "quote"), ("posts48b", "plain")]:
            replacements[region] = post_excerpts(posts[:config["blog"]["excerpts"]], kind)
    for name, value in replacements.items():
        markdown = replace_region(markdown, name, value)
    return markdown


def validate(root: Path, config: dict, markdown: str):
    for name in REGIONS:
        if len(list(region_pattern(name).finditer(markdown))) != 1:
            raise ValueError(f"Missing or duplicate generated region: {name}")
    for relative in re.findall(r"\./profile-showcase/[\w./-]+\.svg", markdown):
        path = inside(root, relative)
        if not path.is_file():
            raise ValueError(f"Missing SVG: {relative}")
        ET.parse(path)
    for url in re.findall(r'https://(?:img\.shields\.io|capsule-render\.vercel\.app|quotes-github-readme\.vercel\.app|github-readme-stats-fast\.vercel\.app|github-profile-summary-cards\.vercel\.app|readme-typing-svg\.demolab\.com)[^\s)"<]*', markdown):
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
    config = tomllib.loads((ROOT / "profile.toml").read_text())
    markdown_path = inside(ROOT, config["markdown"])
    original = markdown_path.read_text()
    if args.check:
        validate(ROOT, config, original)
        print("Profile regions and local assets are valid.")
        return
    # Check all markers before network requests or any output changes.
    for name in REGIONS:
        if len(list(region_pattern(name).finditer(original))) != 1:
            raise ValueError(f"Missing or duplicate generated region: {name}")
    cache_path = inside(ROOT, config["cache"])
    state = json.loads(cache_path.read_text()) if cache_path.exists() else {"schema": 1, "sources": {}}
    if state.get("schema") != 1 or not isinstance(state.get("sources"), dict):
        raise ValueError("Unsupported profile cache; refusing to overwrite it")
    now = datetime.now(UTC)
    warnings = [] if args.offline else refresh(config, state, now)
    assets = Assets(ROOT, config["generated_dir"])
    updated = render(original, config, state, assets, now.date(), args.snake_dir)
    validate(ROOT, config, updated)
    if updated != original:
        markdown_path.write_text(updated)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if not cache_path.exists() or cache_path.read_text() != cache:
        cache_path.write_text(cache)
    assets.prune(updated)
    print(f"Profile {'updated' if updated != original else 'unchanged'}; {len(warnings)} data-source warning(s).")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as out:
            out.write("## Profile refresh\n\n" + ("\n".join("- " + w for w in warnings) if warnings else "All public data sources refreshed successfully.") + "\n")


if __name__ == "__main__":
    main()
