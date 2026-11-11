"""Small, named parsers for text published by GitHub and RSS feeds."""

import re
import textwrap

NO_CONTRIBUTIONS = re.compile(r"No contributions? on ", re.IGNORECASE)
DAILY_CONTRIBUTIONS = re.compile(r"(?P<count>[\d,]+) contributions? on ", re.IGNORECASE)
CALENDAR_TOTAL = re.compile(r"(?P<count>[\d,]+) contributions? in ", re.IGNORECASE)
FIRST_SENTENCE = re.compile(r"^(?P<sentence>.+?[.!?])(?=\s|$)", re.DOTALL)


def normalized_whitespace(value: str) -> str:
    return " ".join(value.split())


def wrap_prose(value: str, columns: int) -> list[str]:
    """Wrap human text without splitting words, hyphenated names, or URLs."""
    return textwrap.wrap(value, columns, break_long_words=False, break_on_hyphens=False)


def daily_contribution_count(label: str) -> int | None:
    """Return None for unrecognized labels, rather than inventing a zero."""
    if NO_CONTRIBUTIONS.match(label):
        return 0
    match = DAILY_CONTRIBUTIONS.match(label)
    return int(match["count"].replace(",", "")) if match else None


def calendar_total(text: str) -> int:
    match = CALENDAR_TOTAL.search(normalized_whitespace(text))
    if not match:
        raise ValueError("Public contribution calendar has no recognizable total")
    return int(match["count"].replace(",", ""))


def first_sentence(paragraph: str) -> str:
    """Take a contiguous excerpt; never paraphrase or summarize feed text."""
    match = FIRST_SENTENCE.match(paragraph)
    return match["sentence"] if match else paragraph
