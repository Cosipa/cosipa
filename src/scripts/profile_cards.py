"""Prepare card layouts from fetched data and render local SVG templates."""

from __future__ import annotations

import json
import math
import textwrap
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from pathlib import Path

if __package__:
    from .profile_svg import SVG_NAMESPACE, SVG_NS, replace_palette, required_element
    from .profile_templates import render
    from .profile_text import wrap_prose
else:
    from profile_svg import SVG_NAMESPACE, SVG_NS, replace_palette, required_element
    from profile_templates import render
    from profile_text import wrap_prose

DEFAULT_TEXT_SIZE = 13
DAYS_PER_WEEK = 7
FONT_METRIC_PRECISION = 2
TYPING_CELL_EM_RATIO = 0.5  # Iosevka Term glyphs occupy half of the font size.
ANIMATION_TIMING_ATTRIBUTES = ("calcMode", "keyTimes", "dur", "repeatCount")
SNAKE_BORDER_COLOR = "1b1f230a"
SNAKE_CORNER_RADIUS = 8


@dataclass(frozen=True)
class BadgeLayout:
    segment_padding: int = 6
    fallback_glyph_width: int = 7


@dataclass(frozen=True)
class PendingLayout:
    width: int = 467
    height: int = 145
    left: int = 20
    title_baseline: int = 35
    title_size: int = 18
    detail_baseline: int = 70
    detail_size: int = 12
    line_height: int = 21
    minimum_wrap_columns: int = 30
    estimated_glyph_width: int = 7


@dataclass(frozen=True)
class StatsLayout:
    width: int = 467
    height: int = 229
    left: int = 20
    count_x: int = 445
    title_baseline: int = 30
    title_size: int = 18
    subtitle_baseline: int = 52
    subtitle_size: int = 11
    first_row_baseline: int = 82
    row_height: int = 23
    row_size: int = 12
    footnote_baseline: int = 211
    footnote_size: int = 10


@dataclass(frozen=True)
class TimelineLayout:
    width: int = 846
    height: int = 208
    pending_height: int = 190
    left: int = 24
    right: int = 822
    chart_bottom: int = 166
    chart_height: int = 90
    title_baseline: int = 31
    title_size: int = 20
    total_size: int = 19
    subtitle_baseline: int = 54
    subtitle_size: int = 11
    grid_baselines: tuple[int, ...] = (76, 106, 136, 166)
    caption_baseline: int = 193
    caption_size: int = 10

    @property
    def chart_width(self) -> int:
        return self.right - self.left


@dataclass(frozen=True)
class QuoteLayout:
    width: int = 600
    minimum_height: int = 96
    wrap_columns: int = 58
    left: int = 62
    first_baseline: int = 42
    line_height: int = 23
    text_size: int = 15
    author_offset: int = 28
    author_size: int = 12
    bottom_space_with_author: int = 52
    bottom_space_without_author: int = 26
    border_bottom_margin: int = 20
    opening_mark_x: int = 35
    opening_mark_baseline: int = 56
    opening_mark_size: int = 42


BADGE = BadgeLayout()
PENDING = PendingLayout()
STATS = StatsLayout()
TIMELINE = TimelineLayout()
QUOTE = QuoteLayout()


def render_text(
    x: float,
    y: float,
    value: str,
    color: str,
    size: int = DEFAULT_TEXT_SIZE,
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


def render_svg(
    width: int,
    height: int,
    title: str,
    body: str,
    background: str,
    description: str = "",
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
    (Path(__file__).resolve().parents[1] / "data/badge-font.json").read_text(
        encoding="utf-8"
    )
)


def badge_text_width(value: str) -> float:
    advances = BADGE_FONT["advances"]
    first_codepoint = BADGE_FONT["first_codepoint"]
    width = 0.0
    for character in value:
        index = ord(character) - first_codepoint
        width += (
            advances[index]
            if 0 <= index < len(advances)
            else BADGE.fallback_glyph_width
        )
    return round(width, FONT_METRIC_PRECISION)


def render_badge(
    label: str, value: str, label_color: str = "555555", color: str = "313131"
) -> str:
    left = math.ceil(badge_text_width(label)) + 2 * BADGE.segment_padding
    right = math.ceil(badge_text_width(value)) + 2 * BADGE.segment_padding
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


def render_placeholder(
    title: str,
    colors: dict,
    detail: str = "Awaiting the first successful GitHub Actions run.",
    width: int = PENDING.width,
    height: int = PENDING.height,
) -> str:
    wrap_columns = max(
        PENDING.minimum_wrap_columns,
        (width - 2 * PENDING.left) // PENDING.estimated_glyph_width,
    )
    lines = textwrap.wrap(detail, wrap_columns)
    elements = [
        render_text(
            PENDING.left,
            PENDING.title_baseline,
            title,
            colors["title"],
            PENDING.title_size,
        )
    ]
    for index, line in enumerate(lines):
        baseline = PENDING.detail_baseline + index * PENDING.line_height
        elements.append(
            render_text(
                PENDING.left, baseline, line, colors["text"], PENDING.detail_size
            )
        )
    return render_svg(
        width, height, title, "".join(elements), colors["background"], detail
    )


def render_stats_card(
    username: str, facts: dict | None, today: date, colors: dict
) -> str:
    if not facts or facts.get("year") != today.year:
        return render_placeholder(
            f"{username}'s GitHub stats",
            colors,
            "Accurate calendar-year counts await the workflow's GitHub token. No estimated totals are shown.",
        )
    private = facts["published_private"]
    rows = [
        ("Public commit contributions", f"{facts['public_commits']:,}"),
        ("Public PRs opened", f"{facts['public_prs']:,}"),
        ("Public issues opened", f"{facts['public_issues']:,}"),
        ("Public PR reviews", f"{facts['public_reviews']:,}"),
        (
            "Published restricted contributions",
            f"{private:,}" if private is not None else "Not published / none",
        ),
    ]
    elements = [
        render_text(
            STATS.left,
            STATS.title_baseline,
            f"{username}'s GitHub stats",
            colors["accent"],
            STATS.title_size,
        ),
        render_text(
            STATS.left,
            STATS.subtitle_baseline,
            f"{facts['year']} YTD through {facts['as_of']} (UTC)",
            colors["text"],
            STATS.subtitle_size,
        ),
    ]
    for index, (label, count) in enumerate(rows):
        baseline = STATS.first_row_baseline + index * STATS.row_height
        elements.append(
            render_text(STATS.left, baseline, label, colors["text"], STATS.row_size)
        )
        elements.append(
            render_text(
                STATS.count_x,
                baseline,
                count,
                colors["accent"],
                STATS.row_size,
                anchor="end",
            )
        )
    elements.append(
        render_text(
            STATS.left,
            STATS.footnote_baseline,
            "Restricted private activity: all types, not just commits.",
            colors["text"],
            STATS.footnote_size,
        )
    )
    return render_svg(
        STATS.width,
        STATS.height,
        f"{username}'s public contribution stats",
        "".join(elements),
        colors["background"],
        "Public commit contributions are eligible commits to public repositories, not every Git commit on every branch. "
        "Private counts are only anonymized totals published by GitHub.",
    )


def weekly_totals(days: dict[str, int]) -> list[int]:
    # JSON keys are sorted when cached; explicitly sort dates before charting.
    values = [days[day] for day in sorted(days)]
    return [
        sum(values[start : start + DAYS_PER_WEEK])
        for start in range(0, len(values), DAYS_PER_WEEK)
    ]


def calculate_weekly_chart_points(weeks: list[int]) -> list[tuple[float, float]]:
    maximum = max(max(weeks), 1)
    intervals = max(1, len(weeks) - 1)
    return [
        (
            TIMELINE.left + index * TIMELINE.chart_width / intervals,
            TIMELINE.chart_bottom - total * TIMELINE.chart_height / maximum,
        )
        for index, total in enumerate(weeks)
    ]


def render_timeline_card(username: str, facts: dict | None, colors: dict) -> str:
    if not facts or not facts.get("days"):
        return render_placeholder(
            f"{username}'s contributions",
            colors,
            width=TIMELINE.width,
            height=TIMELINE.pending_height,
        )
    weeks = weekly_totals(facts["days"])
    peak_total = max(weeks)
    coordinates = calculate_weekly_chart_points(weeks)
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coordinates)
    heading = [
        render_text(
            TIMELINE.left,
            TIMELINE.title_baseline,
            username,
            colors["title"],
            TIMELINE.title_size,
            weight="bold",
        ),
        render_text(
            TIMELINE.right,
            TIMELINE.title_baseline,
            f"{facts['calendar_total']:,} contributions",
            colors["secondary"],
            TIMELINE.total_size,
            anchor="end",
            weight="bold",
        ),
        render_text(
            TIMELINE.left,
            TIMELINE.subtitle_baseline,
            f"365 days: {facts['calendar_start']} – {facts['calendar_end']}",
            colors["text"],
            TIMELINE.subtitle_size,
        ),
    ]
    grid = [
        render(
            "svg/timeline-grid.svg",
            left=TIMELINE.left,
            right=TIMELINE.right,
            y=y,
            border=colors["border"],
        )
        for y in TIMELINE.grid_baselines
    ]
    caption = render_text(
        TIMELINE.left,
        TIMELINE.caption_baseline,
        "Weekly totals · includes anonymized private activity only when publicly visible",
        colors["text"],
        TIMELINE.caption_size,
    )
    peak_x, peak_y = coordinates[weeks.index(peak_total)]
    body = render(
        "svg/timeline.svg",
        accent=colors["accent"],
        secondary=colors["secondary"],
        border=colors["border"],
        background=colors["background"],
        # The border uses a one-pixel stroke, inset halfway at each edge.
        border_width=TIMELINE.width - 1,
        border_height=TIMELINE.height - 1,
        chart_left=TIMELINE.left,
        chart_right=TIMELINE.right,
        chart_bottom=TIMELINE.chart_bottom,
        points=points,
        peak_x=f"{peak_x:.1f}",
        peak_y=f"{peak_y:.1f}",
        peak_total=f"{peak_total:,}",
        fragments={
            "heading": "".join(heading),
            "grid": "".join(grid),
            "caption": caption,
        },
    )
    return render_svg(
        TIMELINE.width,
        TIMELINE.height,
        f"{username}'s 365-day contribution timeline",
        body,
        colors["background"],
    )


def parse_quote_entries(source: str) -> list[tuple[str, str]]:
    result = []
    for line in source.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        quote, _, author = line.partition("\t")
        if quote.strip():
            result.append((quote.strip(), author.strip()))
    return result


def render_quote_card(entries: list[tuple[str, str]], today: date, colors: dict) -> str:
    if not entries:
        return render_placeholder(
            "No quotes configured",
            colors,
            "Add your own quotes to quotes.txt. Nothing is fetched or attributed to you.",
            width=QUOTE.width,
        )
    quote, author = entries[today.toordinal() % len(entries)]
    lines = wrap_prose(quote, QUOTE.wrap_columns)
    last_baseline = QUOTE.first_baseline + QUOTE.line_height * (len(lines) - 1)
    bottom_space = (
        QUOTE.bottom_space_with_author if author else QUOTE.bottom_space_without_author
    )
    height = max(QUOTE.minimum_height, last_baseline + bottom_space)
    if lines:
        lines[-1] += "”"
    quote_lines = [
        render_text(
            QUOTE.left,
            QUOTE.first_baseline + index * QUOTE.line_height,
            line,
            colors["title"],
            QUOTE.text_size,
        )
        for index, line in enumerate(lines)
    ]
    attribution = (
        render_text(
            QUOTE.left,
            last_baseline + QUOTE.author_offset,
            "— " + author,
            colors["text"],
            QUOTE.author_size,
        )
        if author
        else ""
    )
    body = render(
        "svg/quote.svg",
        bottom=height - QUOTE.border_bottom_margin,
        accent=colors["accent"],
        fragments={
            "opening_mark": render_text(
                QUOTE.opening_mark_x,
                QUOTE.opening_mark_baseline,
                "“",
                colors["accent"],
                QUOTE.opening_mark_size,
            ),
            "lines": "".join(quote_lines),
            "author": attribution,
        },
    )
    description = f"{quote} — {author}" if author else quote
    return render_svg(
        QUOTE.width,
        height,
        "Quote from quotes.txt",
        body,
        colors["background"],
        description,
    )


def center_typing_line(
    line: ET.Element,
    reveal: ET.Element,
    *,
    canvas_width: float,
    cell_width: float,
    revealed_widths: list[float],
    clip: str,
) -> None:
    """Move a line and its clip together at every step of the reveal animation."""
    glyphs = required_element(
        line, ".//*[@aria-label]", "Outlined typing line is missing its accessible text"
    )
    line_width = len(glyphs.attrib["aria-label"]) * cell_width
    offsets = [
        (canvas_width - min(visible, line_width)) / 2 for visible in revealed_widths
    ]
    line.set("clip-path", clip)
    line.set("transform", f"translate({offsets[0]:g} 0)")
    animation = {
        "attributeName": "transform",
        "type": "translate",
        "values": ";".join(f"{offset:g} 0" for offset in offsets),
        **{key: reveal.attrib[key] for key in ANIMATION_TIMING_ATTRIBUTES},
    }
    ET.SubElement(line, SVG_NS + "animateTransform", animation)


def render_typing_card(content: bytes, colors: dict) -> bytes:
    """Theme and center visible glyph cells without changing typing/line timing."""
    ET.register_namespace("", SVG_NAMESPACE)
    root = ET.fromstring(content)
    lettering = required_element(
        root,
        './/*[@id="typing-text"]',
        "Outlined typing SVG is missing its lettering group",
    )
    lettering.set("fill", "#" + colors["typing"])
    reveal = required_element(
        root,
        f'.//{SVG_NS}animate[@attributeName="width"]',
        "Outlined typing SVG is missing its reveal animation",
    )
    _, _, width, _ = map(float, root.attrib["viewBox"].split())
    cell_width = float(lettering.attrib["font-size"]) * TYPING_CELL_EM_RATIO
    revealed_widths = [float(value) for value in reveal.attrib["values"].split(";")]
    # Move each line and its local clip together, keeping the currently visible
    # text centered during typing, pauses and erasing (not just the SVG box).
    clip = lettering.attrib.pop("clip-path")
    for line in lettering.findall(SVG_NS + "g"):
        center_typing_line(
            line,
            reveal,
            canvas_width=width,
            cell_width=cell_width,
            revealed_widths=revealed_widths,
            clip=clip,
        )
    return ET.tostring(root, encoding="utf-8")


def render_snake_card(content: bytes, colors: dict) -> bytes:
    """Theme fresh or cached snk output without changing its animation or data."""
    ET.register_namespace("", SVG_NAMESPACE)
    root = ET.fromstring(content)
    style = required_element(root, SVG_NS + "style", "Snake SVG is missing its palette")
    if not style.text:
        raise ValueError("Snake SVG is missing its palette")
    palette = {
        "cb": SNAKE_BORDER_COLOR,
        "cs": colors["snake"],
        "ce": colors["dots"][0],
        **{f"c{i}": color for i, color in enumerate(colors["dots"])},
    }
    style.text = replace_palette(style.text, palette)
    background = root.find(f'{SVG_NS}rect[@id="snake-background"]')
    if background is None:
        background = ET.Element(SVG_NS + "rect", {"id": "snake-background"})
        root.insert(0, background)
    x, y, width, height = root.attrib["viewBox"].split()
    background.attrib.update(
        x=x,
        y=y,
        width=width,
        height=height,
        rx=str(SNAKE_CORNER_RADIUS),
        fill="#" + colors["background"],
    )
    return ET.tostring(root, encoding="utf-8")
