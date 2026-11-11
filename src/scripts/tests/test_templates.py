"""Regression tests for template escaping and card layout edge cases."""

import sys
import tomllib
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src/scripts"))

import profile_cards as cards
import profile_data as data
from profile_templates import render


class TemplateTests(unittest.TestCase):
    def test_text_and_attribute_values_cannot_insert_markup(self):
        value = '<script>alert("$value & test")</script>'
        color = 'fff" onclick="alert(1)'
        document = cards.render_text(10, 20, value, color)
        element = ET.fromstring(document)
        self.assertEqual(element.text, value)
        self.assertEqual(element.attrib["fill"], "#" + color)
        self.assertNotIn("onclick", element.attrib)
        self.assertEqual(list(element), [])

    def test_missing_template_values_raise(self):
        with self.assertRaises(KeyError):
            render("svg/text.svg", value="Missing the layout values")

    def test_badge_preserves_special_characters_as_text(self):
        label = 'Label <&> "$label"'
        value = 'Value <&> "$value"'
        root = ET.fromstring(cards.render_badge(label, value))
        self.assertEqual(root.find(cards.SVG_NS + "title").text, f"{label}: {value}")
        self.assertEqual(
            [node.text for node in root.iter(cards.SVG_NS + "text")],
            [label, label, value, value],
        )

    def test_badge_font_metrics_cover_printable_ascii(self):
        self.assertEqual(cards.BADGE_FONT["first_codepoint"], 32)
        self.assertEqual(len(cards.BADGE_FONT["advances"]), 95)
        self.assertEqual(cards.badge_text_width(""), 0)
        self.assertEqual(cards.badge_text_width("\N{SNOWMAN}"), 7)

    def test_empty_calendar_renders_a_placeholder(self):
        config = tomllib.loads((ROOT / "src/data/profile.toml").read_text())
        for palette in config["colors"].values():
            with self.subTest(background=palette["background"]):
                document = cards.render_timeline_card("Cosipa", {"days": {}}, palette)
                ET.fromstring(document)
                self.assertIn("Awaiting the first successful", document)
                self.assertNotIn("Peak week", document)

    def test_quote_without_author_has_no_attribution(self):
        config = tomllib.loads((ROOT / "src/data/profile.toml").read_text())
        document = cards.render_quote_card(
            [("Exact text", "")], date(2026, 11, 12), config["colors"]["dark"]
        )
        root = ET.fromstring(document)
        self.assertEqual(root.attrib["height"], "96")
        self.assertNotIn("—", "".join(root.itertext()))
        self.assertIn("Exact text”", "".join(root.itertext()))

    def test_api_rejects_non_object_responses(self):
        for content in (b"[]", b"null", b"42"):
            with (
                self.subTest(content=content),
                patch.object(data, "fetch", return_value=content),
                self.assertRaisesRegex(ValueError, "non-object"),
            ):
                data.fetch_github_api("/users/Cosipa")


if __name__ == "__main__":
    unittest.main()
