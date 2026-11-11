"""Build SVG cards from already-fetched profile data (no network or file I/O)."""

from __future__ import annotations

from datetime import date
from html import escape
import math
import re
import textwrap
import xml.etree.ElementTree as ET

SVG_NS = "{http://www.w3.org/2000/svg}"


def text(x, y, value, color, size=13, *, anchor="start", weight="normal", length=None):
    sizing = f' textLength="{length}" lengthAdjust="spacingAndGlyphs"' if length else ""
    return (
        f'<text x="{x}" y="{y}" fill="#{color}" font-size="{size}" '
        f'text-anchor="{anchor}" font-weight="{weight}"{sizing}>'
        f'{escape(str(value))}</text>'
    )


def svg(width: int, height: int, title: str, body: str, background: str, description: str = "") -> str:
    document = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">'
        f'<title id="title">{escape(title)}</title><desc id="desc">{escape(description or title)}</desc>'
        f'<rect width="{width}" height="{height}" rx="5" fill="#{background}"/>'
        f'<g font-family="Verdana,DejaVu Sans,sans-serif">{body}</g></svg>\n'
    )
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
    body = (
        '<defs><linearGradient id="shade" x2="0" y2="100%">'
        '<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        '<stop offset="1" stop-opacity=".1"/></linearGradient>'
        f'<clipPath id="badge"><rect width="{width}" height="20" rx="3"/></clipPath></defs>'
        f'<g clip-path="url(#badge)"><rect width="{left}" height="20" fill="#{label_color}"/>'
        f'<rect x="{left}" width="{right}" height="20" fill="#{color}"/>'
        f'<rect width="{width}" height="20" fill="url(#shade)"/></g>'
    )
    for x, content in [(left / 2, label), (left + right / 2, value)]:
        length = badge_text_width(content)
        body += '<g opacity=".3">' + text(x, 15, content, "010101", 11, anchor="middle", length=length) + '</g>'
        body += text(x, 14, content, "ffffff", 11, anchor="middle", length=length)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img">'
        f'<title>{escape(label + ": " + value)}</title>'
        f'<g font-family="Verdana,Geneva,DejaVu Sans,sans-serif">{body}</g></svg>\n'
    )


def pending(title: str, colors: dict, detail="Awaiting the first successful GitHub Actions run.", width=467, height=145) -> str:
    body = text(20, 35, title, colors["title"], 18)
    for i, line in enumerate(textwrap.wrap(detail, max(30, (width - 40) // 7))):
        body += text(20, 70 + i * 21, line, colors["text"], 12)
    return svg(width, height, title, body, colors["background"], detail)


def stats_card(username: str, facts: dict | None, today: date, colors: dict) -> str:
    if not facts or facts.get("year") != today.year:
        return pending(
            f"{username}'s GitHub stats", colors,
            "Accurate calendar-year counts await the workflow's GitHub token. No estimated totals are shown.",
        )
    private = facts["published_private"]
    rows = [
        ("Public commit contributions", f'{facts["public_commits"]:,}'),
        ("Public PRs opened", f'{facts["public_prs"]:,}'),
        ("Public issues opened", f'{facts["public_issues"]:,}'),
        ("Public PR reviews", f'{facts["public_reviews"]:,}'),
        ("Published restricted contributions", f"{private:,}" if private is not None else "Not published / none"),
    ]
    body = text(20, 30, f"{username}'s GitHub stats", colors["accent"], 18)
    body += text(20, 52, f'{facts["year"]} YTD through {facts["as_of"]} (UTC)', colors["text"], 11)
    for i, (label, count) in enumerate(rows):
        body += text(20, 82 + i * 23, label, colors["text"], 12)
        body += text(445, 82 + i * 23, count, colors["accent"], 12, anchor="end")
    body += text(20, 211, "Restricted private activity: all types, not just commits.", colors["text"], 10)
    return svg(
        467, 229, f"{username}'s public contribution stats", body, colors["background"],
        "Public commit contributions are eligible commits to public repositories, not every Git commit on every branch. "
        "Private counts are only anonymized totals published by GitHub.",
    )


def timeline_card(username: str, facts: dict | None, colors: dict) -> str:
    if not facts:
        return pending(f"{username}'s contributions", colors, width=846, height=190)
    # JSON keys are sorted when cached; explicitly sort dates before charting.
    values = [facts["days"][day] for day in sorted(facts["days"])]
    weeks = [sum(values[i:i + 7]) for i in range(0, len(values), 7)]
    peak_total = max(weeks)
    maximum = max(peak_total, 1)
    coordinates = [
        (24 + i * 798 / max(1, len(weeks) - 1), 166 - total * 90 / maximum)
        for i, total in enumerate(weeks)
    ]
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coordinates)
    body = (
        f'<defs><linearGradient id="line"><stop stop-color="#{colors["accent"]}"/>'
        f'<stop offset="1" stop-color="#{colors["secondary"]}"/></linearGradient>'
        f'<linearGradient id="area" x2="0" y2="1"><stop stop-color="#{colors["accent"]}" stop-opacity=".35"/>'
        f'<stop offset="1" stop-color="#{colors["secondary"]}" stop-opacity=".02"/></linearGradient></defs>'
        f'<rect x=".5" y=".5" width="845" height="207" rx="5" fill="none" stroke="#{colors["border"]}"/>'
    )
    body += text(24, 31, username, colors["title"], 20, weight="bold")
    body += text(822, 31, f'{facts["calendar_total"]:,} contributions', colors["secondary"], 19, anchor="end", weight="bold")
    body += text(24, 54, f'365 days: {facts["calendar_start"]} – {facts["calendar_end"]}', colors["text"], 11)
    for y in [76, 106, 136, 166]:
        body += f'<path d="M24 {y}H822" stroke="#{colors["border"]}" stroke-dasharray="3 6"/>'
    body += f'<polygon points="24,166 {points} 822,166" fill="url(#area)"/>'
    body += (
        f'<polyline points="{points}" fill="none" stroke="url(#line)" stroke-width="3" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
    )
    x, y = coordinates[weeks.index(peak_total)]
    body += (
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#{colors["secondary"]}" '
        f'stroke="#{colors["background"]}" stroke-width="2">'
        f'<title>Peak week: {peak_total:,} contributions</title></circle>'
    )
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
        return pending(
            "No quotes configured", colors,
            "Add your own quotes to quotes.txt. Nothing is fetched or attributed to you.", width=600,
        )
    quote, author = entries[today.toordinal() % len(entries)]
    lines = textwrap.wrap(quote, 58, break_long_words=False, break_on_hyphens=False)
    last_baseline = 42 + 23 * (len(lines) - 1)
    height = max(96, last_baseline + (52 if author else 26))
    body = f'<path d="M22 20V{height - 20}" stroke="#{colors["accent"]}" stroke-width="3" stroke-linecap="round"/>'
    body += text(35, 56, "“", colors["accent"], 42)
    body += '<g font-style="italic">' + "".join(
        text(62, 42 + i * 23, line + ("”" if i == len(lines) - 1 else ""), colors["title"], 15)
        for i, line in enumerate(lines)
    ) + '</g>'
    if author:
        body += text(62, last_baseline + 28, "— " + author, colors["text"], 12)
    return svg(600, height, "Quote from quotes.txt", body, colors["background"], quote + (f" — {author}" if author else ""))


def typing_card(content: bytes, colors: dict) -> bytes:
    """Theme and center visible glyph cells without changing typing/line timing."""
    ET.register_namespace("", SVG_NS[1:-1])
    root = ET.fromstring(content)
    lettering = root.find('.//*[@id="typing-text"]')
    if lettering is None:
        raise ValueError("Outlined typing SVG is missing its lettering group")
    lettering.set("fill", "#" + colors["typing"])
    reveal = root.find(f'.//{SVG_NS}animate[@attributeName="width"]')
    if reveal is None:
        raise ValueError("Outlined typing SVG is missing its reveal animation")
    width = float(root.attrib["viewBox"].split()[2])
    cell = float(lettering.attrib["font-size"]) / 2
    revealed_widths = [float(value) for value in reveal.attrib["values"].split(";")]
    # Move each line and its local clip together, keeping the currently visible
    # text centered during typing, pauses and erasing (not just the SVG box).
    clip = lettering.attrib.pop("clip-path")
    for line in lettering.findall(SVG_NS + "g"):
        glyphs = line.find('.//*[@aria-label]')
        if glyphs is None:
            raise ValueError("Outlined typing line is missing its accessible text")
        line_width = len(glyphs.attrib["aria-label"]) * cell
        offsets = [(width - min(visible, line_width)) / 2 for visible in revealed_widths]
        line.set("clip-path", clip)
        line.set("transform", f"translate({offsets[0]:g} 0)")
        ET.SubElement(line, SVG_NS + "animateTransform", {
            "attributeName": "transform", "type": "translate",
            "values": ";".join(f"{offset:g} 0" for offset in offsets),
            **{key: reveal.attrib[key] for key in ("calcMode", "keyTimes", "dur", "repeatCount")},
        })
    return ET.tostring(root, encoding="utf-8")


def snake_card(content: bytes, colors: dict) -> bytes:
    """Theme fresh or cached snk output without changing its animation or data."""
    ET.register_namespace("", SVG_NS[1:-1])
    root = ET.fromstring(content)
    style = root.find(SVG_NS + "style")
    if style is None or not style.text:
        raise ValueError("Snake SVG is missing its palette")
    palette = {
        "cb": "1b1f230a", "cs": colors["snake"], "ce": colors["dots"][0],
        **{f"c{i}": color for i, color in enumerate(colors["dots"])},
    }
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
