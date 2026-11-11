#!/usr/bin/env python3
"""Refresh marked sections of test.md; never rewrite its layout or README.md."""

from __future__ import annotations

import argparse
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

import profile_data as data

ROOT = Path(__file__).resolve().parent.parent
REGIONS = ("header", "typing", "github-badges", "pgp", "stats", "timeline", "snake",
           "repository-placeholder", "activity", "quote", "posts42", "posts47",
           "posts48a", "posts48b", "posts48c", "footer")
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


def text(x, y, value, color, size=13, *, anchor="start", weight="normal"):
    return f'<text x="{x}" y="{y}" fill="#{color}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}">{escape(str(value))}</text>'


def svg(width: int, height: int, title: str, body: str, background: str, description: str = "") -> str:
    document = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">'
                f'<title id="title">{escape(title)}</title><desc id="desc">{escape(description or title)}</desc>'
                f'<rect width="{width}" height="{height}" rx="5" fill="#{background}"/>'
                f'<g font-family="Verdana,DejaVu Sans,sans-serif">{body}</g></svg>\n')
    ET.fromstring(document)
    return document


def badge(label: str, value: str, label_color="545454", color="313131") -> str:
    left = max(28, len(label) * 7 + 12)
    right = max(24, len(value) * 7 + 12)
    body = (f'<path fill="#{color}" d="M{left} 0h{right}v20H{left}z"/>'
            + text(left / 2, 14, label, "ffffff", 11, anchor="middle")
            + text(left + right / 2, 14, value, "ffffff", 11, anchor="middle"))
    return svg(left + right, 20, f"{label}: {value}", body, label_color)


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


def picture(paths: dict, alt: str, *, width: int | None = None, link: str | None = None) -> str:
    width_attr = f' width="{width}"' if width else ""
    result = (f'<picture>\n'
              f'  <source media="(prefers-color-scheme: dark)" srcset="{escape(paths["dark"], quote=True)}">\n'
              f'  <source media="(prefers-color-scheme: light)" srcset="{escape(paths["light"], quote=True)}">\n'
              f'  <img src="{escape(paths["light"], quote=True)}" alt="{escape(alt, quote=True)}"{width_attr}>\n'
              f'</picture>')
    return f'<a href="{escape(link, quote=True)}">\n{result}\n</a>' if link else result


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
    body = text(20, 30, f"{username}'s GitHub stats", colors["title"], 18)
    body += text(20, 52, f'{facts["year"]} YTD through {facts["as_of"]} (UTC)', colors["text"], 11)
    for i, (label, count) in enumerate(rows):
        body += text(20, 82 + i * 23, label, colors["text"], 12)
        body += text(445, 82 + i * 23, count, colors["title"], 12, anchor="end")
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
    points = " ".join(f"{24 + i * 798 / max(1, len(weeks) - 1):.1f},{160 - v * 78 / maximum:.1f}" for i, v in enumerate(weeks))
    body = text(24, 31, username, colors["title"], 20)
    body += text(822, 31, f'{facts["calendar_total"]:,} contributions', colors["title"], 19, anchor="end")
    body += text(24, 54, f'365 days: {facts["calendar_start"]} – {facts["calendar_end"]}', colors["text"], 11)
    body += f'<path d="M24 160H822" stroke="#{colors["text"]}" opacity=".25"/>'
    body += f'<polyline points="{points}" fill="none" stroke="#{colors["accent"]}" stroke-width="2"/>'
    body += text(24, 189, "Weekly totals · includes anonymized private activity only when publicly visible", colors["text"], 10)
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
    lines = textwrap.wrap(quote, 65, break_long_words=False, break_on_hyphens=False)
    height = 70 + 23 * len(lines) + (25 if author else 0)
    body = "".join(text(24, 38 + i * 23, line, colors["title"], 14) for i, line in enumerate(lines))
    if author:
        body += text(576, height - 25, author, colors["text"], 12, anchor="end")
    return svg(600, height, "Quote from quotes.txt", body, colors["background"], quote + (f" — {author}" if author else ""))


def typing_card(lines: list[str]) -> str:
    if not lines:
        raise ValueError("Configure at least one typing line")
    duration = 5 * len(lines)
    body = ""
    for i, line in enumerate(lines):
        start = i / len(lines)
        end = (i + 1) / len(lines)
        # Each frame has its own clipping rectangle; animation needs no JavaScript.
        times = sorted(set([0.0, start, min(start + .001, 1), max(start, end - .001), end, 1.0]))
        opacity = ["1" if start <= t < end else "0" for t in times]
        body += (f'<defs><clipPath id="line{i}"><rect width="0" height="70">'
                 f'<animate attributeName="width" values="0;0;950;950;0" keyTimes="0;{start:.6f};{min(start + .55 / len(lines), 1):.6f};{end:.6f};1" dur="{duration}s" repeatCount="indefinite"/>'
                 '</rect></clipPath></defs>'
                 f'<g opacity="0" clip-path="url(#line{i})">'
                 f'<animate attributeName="opacity" values="{";".join(opacity)}" keyTimes="{";".join(f"{t:.6f}" for t in times)}" calcMode="discrete" dur="{duration}s" repeatCount="indefinite"/>'
                 + text(0, 41, line, "c4a7e7", 23) + '</g>')
    return svg(950, 70, "Typing introduction", body, "00000000", " / ".join(lines))


def post_date(post: dict, short=False) -> str:
    dt = datetime.fromisoformat(post["published"])
    return dt.strftime("%b %d, %Y") if short else f"{dt:%B} {dt.day}, {dt.year}"


def post_link(post: dict) -> str:
    url = url_quote(post["url"], safe=":/?#&=%+-.~@_")
    return f'[{md(post["title"])}]({url})'


def quoted(excerpt: str) -> str:
    return "\n".join("> " + line for line in textwrap.wrap(md(excerpt), 86, break_long_words=False, break_on_hyphens=False))


def post_cards(posts: list[dict]) -> str:
    parts = ["<table>"]
    for i in range(0, len(posts), 2):
        parts.append("<tr>")
        for post in posts[i:i + 2]:
            parts.append('<td width="50%" valign="top">\n\n'
                         f'### {post_link(post)}\n\n<sub>{post_date(post)}</sub>\n\n'
                         f'{quoted(post["excerpt"])}\n\n</td>')
        parts.append("</tr>")
    return "\n".join(parts + ["</table>"])


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
        else:
            prefix = "> [!TIP]\n" if kind == "tip" else ""
            parts.append(prefix + "> " + heading + "\n>\n" + quoted(post["excerpt"]))
    return ("\n\n---\n\n" if kind == "plain" else "\n\n<!-- -->\n\n").join(parts)


def activity_table(facts: dict, assets: Assets) -> str:
    parts = ["| Status | Repository | Title |", "| :-- | :-- | :-- |"]
    for item in facts["items"]:
        kind = "PR" if item["kind"] == "pr" else "issue"
        image = f'./profile-showcase/static/badge-{item["kind"]}-open.svg'
        parts.append(f'| ![{kind} open]({image}) | `{item["repository"]}` | {post_link({"title": item["title"], "url": item["url"]})} · #{item["number"]} |')
    if not facts["items"]:
        parts.append("| — | — | No open public pull requests or issues. |")
    return "\n".join(parts)


def render(markdown: str, config: dict, state: dict, assets: Assets, today: date, snake_dir: Path | None) -> str:
    user, repo = config["username"], config["repository"]
    sources = state["sources"]
    colors = config["colors"]
    replacements = {
        "header": '![Cosipa profile shortlist](./profile-showcase/static/header-wave.svg)',
        "footer": '![Decorative waving footer](./profile-showcase/static/footer-wave.svg)',
        "typing": f'![Typing introduction]({assets.put("typing", typing_card(config["typing"]["lines"]))})',
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
        replacements[region] = picture(paths, title, width=467 if region == "stats" else 400 if region == "repository-placeholder" else None)
    entries = quote_entries(inside(assets.root, config["quotes"]).read_text())
    paths = {theme: assets.put(f"quote-{theme}", quote_card(entries, today, palette)) for theme, palette in colors.items()}
    replacements["quote"] = picture(paths, "Quote card from quotes.txt", link="./quotes.txt")
    snake_paths = state.get("snake", {})
    for theme in colors:
        candidate = snake_dir / f"snake-{theme}.svg" if snake_dir else None
        if candidate and candidate.is_file():
            snake_paths[theme] = assets.put(f"snake-{theme}", candidate.read_bytes())
        elif (not snake_paths.get(theme) or f"/snake-{theme}-pending." in snake_paths[theme]
              or not inside(assets.root, snake_paths[theme]).is_file()):
            snake_paths[theme] = assets.put(f"snake-{theme}-pending", pending("Contribution snake", colors[theme], "The pinned Action generates your public grid once this profile repository is public. No other account's data is shown.", width=880))
    state["snake"] = snake_paths
    replacements["snake"] = picture(snake_paths, f"{user}'s contribution snake", width=1000)
    if "activity" in sources:
        replacements["activity"] = activity_table(sources["activity"], assets)
    else:
        replacements["activity"] = "| Status | Repository | Title |\n| :-- | :-- | :-- |\n| — | — | Awaiting a successful public GitHub API fetch. |"
    if "posts" in sources:
        posts = sources["posts"]["items"]
        replacements["posts42"] = post_cards(posts[:config["blog"]["cards"]])
        replacements["posts47"] = post_rows(posts[:config["blog"]["rows"]])
        for region, kind in [("posts48a", "quote"), ("posts48b", "plain"), ("posts48c", "tip")]:
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
