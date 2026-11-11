"""Prepare card layouts from fetched data and render local SVG templates."""

from __future__ import annotations

import json
import math
import re
import textwrap
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

if __package__:
    from .profile_templates import render
else:
    from profile_templates import render

SVG_NS = "{http://www.w3.org/2000/svg}"


def text(
    x: float,
    y: float,
    value: str,
    color: str,
    size: int = 13,
    *,
    anchor: str = "start",
    weight: str = "normal",
) -> str:
    return render(
        "svg/text.svg",
        x=x,
        y=y,
        value=value,
        color=color,
        size=size,
        anchor=anchor,
        weight=weight,
    )


def svg(
    width: int, height: int, title: str, body: str, background: str, description: str = ""
) -> str:
    document = render(
        "svg/card.svg",
        width=width,
        height=height,
        title=title,
        description=description or title,
        background=background,
        fragments={"body": body},
    )
    ET.fromstring(document)
    return document


# Fixed authoring-time metrics avoid a font dependency in Actions.
# SVG textLength also prevents viewer drift.
BADGE_FONT = json.loads(
    (Path(__file__).resolve().parents[1] / "data/badge-font.json").read_text(encoding="utf-8")
)


def badge_text_width(value: str) -> float:
    advances = BADGE_FONT["advances"]
    first_codepoint = BADGE_FONT["first_codepoint"]
    width = 0.0
    for character in value:
        index = ord(character) - first_codepoint
        width += advances[index] if 0 <= index < len(advances) else 7
    return round(width, 2)


def badge(label: str, value: str, label_color: str = "555555", color: str = "313131") -> str:
    left = math.ceil(badge_text_width(label)) + 12
    right = math.ceil(badge_text_width(value)) + 12
    width = left + right
    labels = []
    for x, content in [(left / 2, label), (left + right / 2, value)]:
        labels.append(
            render(
                "svg/badge-label.svg",
                x=x,
                value=content,
                length=badge_text_width(content),
            )
        )
    return render(
        "svg/badge.svg",
        width=width,
        left=left,
        right=right,
        title=f"{label}: {value}",
        label_color=label_color,
        color=color,
        fragments={"labels": "".join(labels)},
    )


def pending(
    title: str,
    colors: dict,
    detail: str = "Awaiting the first successful GitHub Actions run.",
    width: int = 467,
    height: int = 145,
) -> str:
    lines = textwrap.wrap(detail, max(30, (width - 40) // 7))
    elements = [text(20, 35, title, colors["title"], 18)]
    for index, line in enumerate(lines):
        elements.append(text(20, 70 + index * 21, line, colors["text"], 12))
    return svg(width, height, title, "".join(elements), colors["background"], detail)


def stats_card(username: str, facts: dict | None, today: date, colors: dict) -> str:
    if not facts or facts.get("year") != today.year:
        return pending(
            f"{username}'s GitHub stats",
            colors,
            "Accurate calendar-year counts await the workflow's GitHub token. No estimated totals are shown.",
        )
    private = facts["published_private"]
    rows = [
        ("Public commit contributions", f'{facts["public_commits"]:,}'),
        ("Public PRs opened", f'{facts["public_prs"]:,}'),
        ("Public issues opened", f'{facts["public_issues"]:,}'),
        ("Public PR reviews", f'{facts["public_reviews"]:,}'),
        (
            "Published restricted contributions",
            f"{private:,}" if private is not None else "Not published / none",
        ),
    ]
    elements = [
        text(20, 30, f"{username}'s GitHub stats", colors["accent"], 18),
        text(20, 52, f'{facts["year"]} YTD through {facts["as_of"]} (UTC)', colors["text"], 11),
    ]
    for index, (label, count) in enumerate(rows):
        baseline = 82 + index * 23
        elements.append(text(20, baseline, label, colors["text"], 12))
        elements.append(text(445, baseline, count, colors["accent"], 12, anchor="end"))
    elements.append(
        text(20, 211, "Restricted private activity: all types, not just commits.", colors["text"], 10)
    )
    return svg(
        467,
        229,
        f"{username}'s public contribution stats",
        "".join(elements),
        colors["background"],
        "Public commit contributions are eligible commits to public repositories, not every Git commit on every branch. "
        "Private counts are only anonymized totals published by GitHub.",
    )


def timeline_card(username: str, facts: dict | None, colors: dict) -> str:
    if not facts or not facts.get("days"):
        return pending(f"{username}'s contributions", colors, width=846, height=190)
    # JSON keys are sorted when cached; explicitly sort dates before charting.
    values = [facts["days"][day] for day in sorted(facts["days"])]
    weeks = [sum(values[start : start + 7]) for start in range(0, len(values), 7)]
    peak_total = max(weeks)
    maximum = max(peak_total, 1)
    coordinates = [
        (24 + index * 798 / max(1, len(weeks) - 1), 166 - total * 90 / maximum)
        for index, total in enumerate(weeks)
    ]
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coordinates)
    heading = [
        text(24, 31, username, colors["title"], 20, weight="bold"),
        text(
            822,
            31,
            f'{facts["calendar_total"]:,} contributions',
            colors["secondary"],
            19,
            anchor="end",
            weight="bold",
        ),
        text(
            24,
            54,
            f'365 days: {facts["calendar_start"]} – {facts["calendar_end"]}',
            colors["text"],
            11,
        ),
    ]
    grid = [
        render("svg/timeline-grid.svg", y=y, border=colors["border"])
        for y in (76, 106, 136, 166)
    ]
    caption = text(
        24,
        193,
        "Weekly totals · includes anonymized private activity only when publicly visible",
        colors["text"],
        10,
    )
    peak_x, peak_y = coordinates[weeks.index(peak_total)]
    body = render(
        "svg/timeline.svg",
        accent=colors["accent"],
        secondary=colors["secondary"],
        border=colors["border"],
        background=colors["background"],
        points=points,
        peak_x=f"{peak_x:.1f}",
        peak_y=f"{peak_y:.1f}",
        peak_total=f"{peak_total:,}",
        fragments={"heading": "".join(heading), "grid": "".join(grid), "caption": caption},
    )
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


def quote_card(entries: list[tuple[str, str]], today: date, colors: dict) -> str:
    if not entries:
        return pending(
            "No quotes configured",
            colors,
            "Add your own quotes to quotes.txt. Nothing is fetched or attributed to you.",
            width=600,
        )
    quote, author = entries[today.toordinal() % len(entries)]
    lines = textwrap.wrap(quote, 58, break_long_words=False, break_on_hyphens=False)
    last_baseline = 42 + 23 * (len(lines) - 1)
    height = max(96, last_baseline + (52 if author else 26))
    quote_lines = []
    for index, line in enumerate(lines):
        if index == len(lines) - 1:
            line += "”"
        quote_lines.append(text(62, 42 + index * 23, line, colors["title"], 15))
    attribution = text(62, last_baseline + 28, "— " + author, colors["text"], 12) if author else ""
    body = render(
        "svg/quote.svg",
        bottom=height - 20,
        accent=colors["accent"],
        fragments={
            "opening_mark": text(35, 56, "“", colors["accent"], 42),
            "lines": "".join(quote_lines),
            "author": attribution,
        },
    )
    description = f"{quote} — {author}" if author else quote
    return svg(600, height, "Quote from quotes.txt", body, colors["background"], description)


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
        animation = {
            "attributeName": "transform",
            "type": "translate",
            "values": ";".join(f"{offset:g} 0" for offset in offsets),
        }
        for key in ("calcMode", "keyTimes", "dur", "repeatCount"):
            animation[key] = reveal.attrib[key]
        ET.SubElement(line, SVG_NS + "animateTransform", animation)
    return ET.tostring(root, encoding="utf-8")


def snake_card(content: bytes, colors: dict) -> bytes:
    """Theme fresh or cached snk output without changing its animation or data."""
    ET.register_namespace("", SVG_NS[1:-1])
    root = ET.fromstring(content)
    style = root.find(SVG_NS + "style")
    if style is None or not style.text:
        raise ValueError("Snake SVG is missing its palette")
    stylesheet = style.text
    palette = {
        "cb": "1b1f230a",
        "cs": colors["snake"],
        "ce": colors["dots"][0],
        **{f"c{i}": color for i, color in enumerate(colors["dots"])},
    }
    for name, color in palette.items():
        stylesheet, count = re.subn(
            r"--" + name + r":[^;}]+", f"--{name}:#{color}", stylesheet, count=1
        )
        if count != 1:
            raise ValueError(f"Snake SVG is missing palette entry {name}")
    style.text = stylesheet
    background = root.find(f'{SVG_NS}rect[@id="snake-background"]')
    if background is None:
        background = ET.Element(SVG_NS + "rect", {"id": "snake-background"})
        root.insert(0, background)
    x, y, width, height = root.attrib["viewBox"].split()
    background.attrib.update(
        x=x, y=y, width=width, height=height, rx="8", fill="#" + colors["background"]
    )
    return ET.tostring(root, encoding="utf-8")
