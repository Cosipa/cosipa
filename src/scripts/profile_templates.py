"""Render local SVG/HTML templates, escaping values but preserving trusted fragments."""

from functools import cache
from html import escape
from pathlib import Path
from string import Template

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"


@cache
def load_template(name: str) -> Template:
    return Template((TEMPLATE_DIR / name).read_text(encoding="utf-8"))


def render(
    name: str, *, fragments: dict[str, str] | None = None, **values: object
) -> str:
    substitutions = {
        key: escape(str(value), quote=True) for key, value in values.items()
    }
    if fragments:
        substitutions.update(fragments)
    return load_template(name).substitute(substitutions)
