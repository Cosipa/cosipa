"""Regression coverage for parsing boundaries and the refactored workflow helpers."""

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, call, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src/scripts"))

import profile_cards as cards
import profile_data as data
import profile_markup as markup
import profile_svg as svg
import profile_text as text
import update_profile as profile


class TextParsingTests(unittest.TestCase):
    def test_contribution_labels_distinguish_zero_from_unknown(self):
        labels = {
            "No contributions on November 12.": 0,
            "no contribution on November 12.": 0,
            "1 contribution on November 12.": 1,
            "1,234 CONTRIBUTIONS ON November 12.": 1234,
            "Hidden contributions": None,
        }
        for label, expected in labels.items():
            with self.subTest(label=label):
                self.assertEqual(text.daily_contribution_count(label), expected)

    def test_calendar_total_handles_whitespace_and_thousands(self):
        self.assertEqual(
            text.calendar_total("\n1,234 contributions\n in the last year"), 1234
        )
        with self.assertRaisesRegex(ValueError, "no recognizable total"):
            text.calendar_total("Private calendar")

    def test_first_sentence_preserves_contiguous_source_text(self):
        paragraphs = {
            "Exact sentence! Another sentence.": "Exact sentence!",
            "No sentence terminator": "No sentence terminator",
            "A dotted.name stays intact. Next.": "A dotted.name stays intact.",
            "Across\nlines? Next.": "Across\nlines?",
            "": "",
        }
        for paragraph, expected in paragraphs.items():
            with self.subTest(paragraph=paragraph):
                self.assertEqual(text.first_sentence(paragraph), expected)

    def test_prose_wrapping_does_not_split_long_words_or_hyphens(self):
        self.assertEqual(
            text.wrap_prose("A long-hyphenated-word ends", 10),
            [
                "A",
                "long-hyphenated-word",
                "ends",
            ],
        )


class SvgBoundaryTests(unittest.TestCase):
    def test_generated_names_require_the_exact_digest_length(self):
        self.assertTrue(svg.is_generated_asset("stats-dark.012345abcdef.svg"))
        for name in (
            "handmade.svg",
            "badge.abc.svg",
            "badge.012345abcdef0.svg",
            "../a.svg",
        ):
            with self.subTest(name=name):
                self.assertFalse(svg.is_generated_asset(name))
        for name in ("../escape", "Uppercase", "has.dot", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                svg.validate_asset_name(name)

    def test_key_id_is_validated_before_shortening(self):
        fingerprint = "a" * 24 + "0123456789abcdef"
        self.assertEqual(svg.pgp_key_id(fingerprint), "0x0123456789ABCDEF")
        for invalid in ("a" * 39, "a" * 65, "g" * 40):
            with self.subTest(fingerprint=invalid), self.assertRaises(ValueError):
                svg.pgp_key_id(invalid)

    def test_svg_validation_rejects_active_elements_and_references(self):
        unsafe_bodies = (
            "<script/>",
            "<g><foreignObject/></g>",
            '<path onclick="run()"/>',
            '<use href="https://example.com/a.svg"/>',
            '<use xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="external.svg"/>',
        )
        for body in unsafe_bodies:
            payload = f'<svg xmlns="http://www.w3.org/2000/svg">{body}</svg>'.encode()
            with self.subTest(body=body), self.assertRaises(ValueError):
                svg.validate_svg(payload)
        svg.validate_svg(
            b'<svg xmlns="http://www.w3.org/2000/svg"><use href="#local"/></svg>'
        )
        with self.assertRaisesRegex(ValueError, "not an SVG"):
            svg.validate_svg(b"<html/>")

    def test_palette_changes_only_the_first_declaration_and_keeps_animation(self):
        stylesheet = (
            ":root{--c0:#000;--cs:#111} .other{--c0:#222}@keyframes x{to{opacity:0}}"
        )
        expected = (
            ":root{--c0:#abc;--cs:#def} .other{--c0:#222}@keyframes x{to{opacity:0}}"
        )
        self.assertEqual(
            svg.replace_palette(stylesheet, {"c0": "abc", "cs": "def"}), expected
        )
        with self.assertRaisesRegex(ValueError, "missing palette entry ce"):
            svg.replace_palette(stylesheet, {"ce": "000"})


class FetchTests(unittest.TestCase):
    URL = "https://api.github.com/example"

    def test_retryable_http_failures_back_off_before_success(self):
        failure = HTTPError(self.URL, 503, "Unavailable", {}, None)
        self.addCleanup(failure.close)
        with (
            patch.object(
                data, "read_response", side_effect=[failure, failure, b"ok"]
            ) as read,
            patch.object(data.clock, "sleep") as sleep,
        ):
            self.assertEqual(data.fetch(self.URL), b"ok")
        self.assertEqual(read.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(1), call(2)])

    def test_non_retryable_http_failure_stops_immediately(self):
        failure = HTTPError(self.URL, 403, "Forbidden", {}, None)
        self.addCleanup(failure.close)
        with (
            patch.object(data, "read_response", side_effect=failure) as read,
            patch.object(data.clock, "sleep") as sleep,
            self.assertRaisesRegex(ValueError, "HTTP 403 from api.github.com"),
        ):
            data.fetch(self.URL)
        read.assert_called_once()
        sleep.assert_not_called()

    def test_network_failure_stops_after_the_last_attempt(self):
        with (
            patch.object(
                data, "read_response", side_effect=URLError("offline")
            ) as read,
            patch.object(data.clock, "sleep") as sleep,
            self.assertRaisesRegex(
                ValueError, "Network failure contacting api.github.com"
            ),
        ):
            data.fetch(self.URL)
        self.assertEqual(read.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(1), call(2)])

    def test_response_size_and_timeout_are_enforced(self):
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        request = Request(self.URL)
        with (
            patch.object(data, "build_opener", return_value=opener),
            patch.object(data, "MAX_RESPONSE", 4),
        ):
            response.read.return_value = b"1234"
            self.assertEqual(data.read_response(request), b"1234")
            response.read.assert_called_once_with(5)
            opener.open.assert_called_once_with(request, timeout=30)
            response.read.return_value = b"12345"
            with self.assertRaisesRegex(ValueError, "response size limit"):
                data.read_response(request)

    def test_headers_only_authenticate_the_github_api(self):
        headers = data.build_request_headers(self.URL, "secret", has_payload=True)
        self.assertEqual(headers["Authorization"], "Bearer secret")
        self.assertEqual(headers["Content-Type"], "application/json")
        public = data.build_request_headers(
            "https://github.com/users/example", "secret", has_payload=False
        )
        self.assertNotIn("Authorization", public)
        self.assertNotIn("X-GitHub-Api-Version", public)
        with self.assertRaisesRegex(ValueError, "Only HTTPS"):
            data.build_request_headers(
                "http://example.com", "secret", has_payload=False
            )

    def test_redirects_strip_auth_on_host_changes_and_reject_http(self):
        request = Request(self.URL, headers={"Authorization": "Bearer secret"})
        handler = data.SafeRedirect()
        redirected = handler.redirect_request(
            request, None, 302, "Found", {}, "https://other.example/path"
        )
        self.assertIsNone(redirected.get_header("Authorization"))
        with self.assertRaisesRegex(ValueError, "non-HTTPS"):
            handler.redirect_request(
                request, None, 302, "Found", {}, "http://example.com/path"
            )


class WorkflowHelperTests(unittest.TestCase):
    def test_cache_validation_does_not_overwrite_unsupported_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            self.assertEqual(profile.load_cache(path), {"schema": 1, "sources": {}})
            self.assertFalse(path.exists())
            for invalid in ({"schema": 2, "sources": {}}, {"schema": 1, "sources": []}):
                original = json.dumps(invalid)
                path.write_text(original)
                with (
                    self.subTest(state=invalid),
                    self.assertRaisesRegex(ValueError, "Unsupported"),
                ):
                    profile.load_cache(path)
                self.assertEqual(path.read_text(), original)

    def test_unchanged_files_are_not_written_again(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested/result.txt"
            profile.write_if_changed(path, "first")
            with patch.object(Path, "write_text") as write:
                profile.write_if_changed(path, "first")
                write.assert_not_called()
            profile.write_if_changed(path, "second")
            self.assertEqual(path.read_text(), "second")

    def test_snake_prefers_fresh_then_cached_but_never_a_cached_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cached = root / "snake-dark.012345abcdef.svg"
            cached.write_bytes(b"cached")
            fresh_dir = root / "fresh"
            fresh_dir.mkdir()
            fresh = fresh_dir / "snake-dark.svg"
            fresh.write_bytes(b"fresh")
            self.assertEqual(
                profile.read_snake_source(root, "dark", cached.name, fresh_dir),
                b"fresh",
            )
            self.assertEqual(
                profile.read_snake_source(root, "dark", cached.name, None), b"cached"
            )
            pending = root / "snake-dark-pending.012345abcdef.svg"
            pending.write_bytes(b"placeholder")
            self.assertIsNone(
                profile.read_snake_source(root, "dark", "./" + pending.name, None)
            )
            self.assertIsNone(
                profile.read_snake_source(root, "dark", "missing.svg", None)
            )

    def test_weekly_totals_sort_dates_and_keep_the_partial_final_week(self):
        days = {f"2026-01-{day:02}": day for day in reversed(range(1, 10))}
        self.assertEqual(cards.weekly_totals(days), [28, 17])

    def test_zero_and_single_week_charts_do_not_divide_by_zero(self):
        self.assertEqual(cards.calculate_weekly_chart_points([0]), [(24.0, 166.0)])
        self.assertEqual(cards.calculate_weekly_chart_points([5]), [(24.0, 76.0)])
        self.assertEqual(
            cards.calculate_weekly_chart_points([0, 0]), [(24.0, 166.0), (822.0, 166.0)]
        )

    def test_timeline_templates_use_the_same_layout_as_the_chart(self):
        layout = replace(
            cards.TIMELINE,
            width=930,
            height=220,
            left=30,
            right=900,
            chart_bottom=175,
            grid_baselines=(175,),
        )
        palette = dict.fromkeys(
            ("title", "secondary", "text", "border", "accent", "background"), "abc"
        )
        facts = {
            "days": {"2026-01-01": 0},
            "calendar_total": 0,
            "calendar_start": "2026-01-01",
            "calendar_end": "2026-01-01",
        }
        with patch.object(cards, "TIMELINE", layout):
            document = cards.render_timeline_card("Example", facts, palette)
        self.assertIn('width="930" height="220"', document)
        self.assertIn('width="929" height="219"', document)
        self.assertIn('d="M30 175H900"', document)
        self.assertIn('points="30,175 30.0,175.0 900,175"', document)

    def test_document_policy_retains_hosted_widget_and_details_checks(self):
        for content in (
            "![Stats](https://img.shields.io/badge/example?color=blue)",
            "<details>Collapsed</details>",
        ):
            with self.subTest(content=content), self.assertRaises(ValueError):
                markup.validate_document_content(content)
        markup.validate_document_content("[Ordinary link](https://example.com)")


if __name__ == "__main__":
    unittest.main()
