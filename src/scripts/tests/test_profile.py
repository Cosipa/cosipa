from datetime import UTC, date, datetime, timedelta
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src/scripts"))
import profile_cards as cards
import profile_data as data
import update_profile as profile

NOW = datetime(2026, 11, 12, 15, 30, tzinfo=UTC)


def contribution_document():
    year = {"restrictedContributionsCount": 24}
    for kind, suffix, count in [("commit", "Commits", 4), ("issue", "Issues", 2),
                                ("pullRequest", "PullRequests", 4), ("pullRequestReview", "PullRequestReviews", 5)]:
        year["totalRepositoriesWithContributed" + suffix] = 2
        year[kind + "ContributionsByRepository"] = [
            {"repository": {"isPrivate": False}, "contributions": {"totalCount": count}},
            {"repository": {"isPrivate": True}, "contributions": {"totalCount": 99}}]
    return {"data": {"user": {"year": year}}}


def calendar_html():
    start = NOW.date() - timedelta(days=364)
    cells = ['<h2>3 contributions in the last year</h2>']
    for i in range(365):
        day = (start + timedelta(days=i)).isoformat()
        label = "3 contributions on example." if i == 0 else "No contributions on example."
        cells.append(f'<td data-date="{day}" id="day-{i}"></td><tool-tip for="day-{i}">{label}</tool-tip>')
    return "".join(cells).encode()


def rss(title="Exact title &amp; spelling", link="https://cosipa.dev/posts/test/", body="<p>Exact first sentence. Another sentence.</p>"):
    return f'<rss><channel><item><title>{title}</title><link>{link}</link><pubDate>Sun, 18 Oct 2026 00:00:00 +0000</pubDate><description><![CDATA[{body}]]></description></item></channel></rss>'.encode()


class ContributionTests(unittest.TestCase):
    def test_explicit_year_and_365_day_bounds(self):
        variables = data.contribution_variables("Cosipa", NOW)
        self.assertEqual(variables["yearFrom"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(variables["to"], "2026-11-12T15:30:00+00:00")
        self.assertIn("from: $yearFrom, to: $to", data.QUERY)

    def test_public_commits_do_not_include_private_repository(self):
        facts = data.normalize_contributions(contribution_document(), NOW)
        self.assertEqual(facts["public_commits"], 4)
        self.assertEqual(facts["published_private"], 24)
        self.assertNotIn("private_commits", facts)
        self.assertEqual(facts["public_prs"], 4)
        self.assertEqual(facts["public_issues"], 2)
        self.assertEqual(facts["public_reviews"], 5)
        calendar = data.normalize_calendar(calendar_html(), NOW.date())
        self.assertEqual(calendar["calendar_total"], sum(calendar["days"].values()))
        self.assertEqual(len(calendar["days"]), 365)

    def test_truncated_commit_count_is_not_reported(self):
        doc = contribution_document()
        year = doc["data"]["user"]["year"]
        year["commitContributionsByRepository"] *= 50
        year["totalRepositoriesWithContributedCommits"] = 101
        with self.assertRaisesRegex(ValueError, "truncated"):
            data.normalize_contributions(doc, NOW)

    def test_missing_calendar_days_are_not_zero_filled(self):
        content = calendar_html().replace(b'for="day-364"', b'for="missing-day"')
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            data.normalize_calendar(content, NOW.date())

    def test_calendar_total_is_checked(self):
        content = calendar_html().replace(b'<h2>3 contributions', b'<h2>1390 contributions')
        with self.assertRaisesRegex(ValueError, "disagrees"):
            data.normalize_calendar(content, NOW.date())

    def test_calendar_is_fetched_without_an_auth_token(self):
        with patch.object(data, "fetch", return_value=calendar_html()) as fetch:
            result = data.public_calendar("Cosipa", NOW.date())
        fetch.assert_called_once_with("https://github.com/users/Cosipa/contributions")
        self.assertEqual(result["calendar_total"], 3)

    def test_week_rounded_headline_is_not_reused_for_365_day_total(self):
        content = calendar_html().replace(b'<h2>3 contributions', b'<h2>22 contributions')
        extra = b'<td data-date="2025-11-12" id="extra"></td><tool-tip for="extra">19 contributions on example.</tool-tip>'
        result = data.normalize_calendar(content + extra, NOW.date())
        self.assertEqual(result["calendar_total"], 3)
        self.assertEqual(result["source_calendar_total"], 22)
        self.assertEqual(len(result["days"]), 365)

    def test_hidden_private_activity_is_not_invented(self):
        doc = contribution_document()
        doc["data"]["user"]["year"]["restrictedContributionsCount"] = 0
        self.assertIsNone(data.normalize_contributions(doc, NOW)["published_private"])

    def test_missing_token_and_graphql_errors_do_not_produce_zero(self):
        with self.assertRaisesRegex(ValueError, "(?i)token"):
            data.contributions("Cosipa", NOW, "")
        with self.assertRaises(ValueError):
            data.normalize_contributions({"errors": [{"message": "denied"}]}, NOW)

    def test_bad_counts_are_rejected(self):
        for count in [-1, True, "62", None]:
            with self.subTest(count=count), self.assertRaises(ValueError):
                data.nonnegative(count)


class FeedTests(unittest.TestCase):
    def test_exact_title_link_and_contiguous_excerpt(self):
        post = data.parse_posts(rss(), "https://cosipa.dev/rss")[0]
        self.assertEqual(post["title"], "Exact title & spelling")
        self.assertEqual(post["excerpt"], "Exact first sentence.")
        self.assertEqual(post["url"], "https://cosipa.dev/posts/test/")

    def test_inline_code_and_unicode_are_not_paraphrased(self):
        post = data.parse_posts(rss(body='<p>Device-Mapper’s <code>crypt</code> is useful. <a href="/">Link</a></p>'), "https://cosipa.dev/rss")[0]
        self.assertEqual(post["excerpt"], "Device-Mapper’s crypt is useful.")

    def test_scripts_are_never_executed_or_displayed(self):
        post = data.parse_posts(rss(body='<script>danger()</script><p>Real text.</p>'), "https://cosipa.dev/rss")[0]
        self.assertEqual(post["excerpt"], "Real text.")

    def test_empty_feed_invalid_dates_and_unsafe_links_fail_closed(self):
        bad = [b'<rss><channel/></rss>', rss(link="javascript:alert(1)"),
               rss(link="https://other.example/post"), rss().replace(b"Sun, 18 Oct 2026 00:00:00 +0000", b"not a date"),
               b'<!DOCTYPE rss [<!ENTITY x "oops">]><rss/>']
        for content in bad:
            with self.subTest(content=content), self.assertRaises(ValueError):
                data.parse_posts(content, "https://cosipa.dev/rss")

    def test_feed_is_sorted_by_publication_date(self):
        first = rss().decode().split("<channel>")[1].split("</channel>")[0]
        second = first.replace("18 Oct 2026", "18 Oct 2025").replace("Exact title", "Older title")
        posts = data.parse_posts(f'<rss><channel>{second}{first}</channel></rss>'.encode(), "https://cosipa.dev/rss")
        self.assertEqual(posts[0]["title"], "Exact title & spelling")


class MergedActivityTests(unittest.TestCase):
    def item(self, number, merged_at, **extra):
        return {"state": "closed", "title": f"Actual PR {number}", "number": number,
                "html_url": f"https://github.com/owner/repo/pull/{number}",
                "updated_at": "2026-11-12T00:00:00Z", "pull_request": {"merged_at": merged_at}, **extra}

    def test_merged_list_uses_merge_time_and_excludes_unmerged_or_open_prs(self):
        calls = []
        items = [self.item(1, "2026-11-01T12:00:00Z"), self.item(2, "2026-11-11T12:00:00Z"),
                 self.item(3, None), self.item(4, "2026-11-12T00:00:00Z", state="open")]
        def api(path, token):
            calls.append(path)
            return {"incomplete_results": False, "total_count": 4, "items": items}
        with patch.object(data, "api", side_effect=api):
            result = data.recently_merged("Cosipa", NOW.date(), "token")
        self.assertEqual([i["number"] for i in result["items"]], [2, 1])
        self.assertIn("is%3Amerged", calls[0])
        self.assertIn("is%3Apublic", calls[0])
        self.assertEqual(result["items"][0]["merged_at"], "2026-11-11T12:00:00+00:00")

    def test_merge_search_paginates_before_selecting_six_latest(self):
        old = [self.item(i, f"2026-11-{i:02}T00:00:00Z") for i in range(1, 7)]
        pages = [{"incomplete_results": False, "total_count": 7, "items": old},
                 {"incomplete_results": False, "total_count": 7,
                  "items": [self.item(7, "2026-11-07T00:00:00Z")]}]
        with patch.object(data, "api", side_effect=pages) as api:
            result = data.recently_merged("Cosipa", NOW.date())
        self.assertEqual([i["number"] for i in result["items"]], [7, 6, 5, 4, 3, 2])
        self.assertIn("page=2", api.call_args_list[1].args[0])

    def test_truncated_merge_search_fails_instead_of_publishing_partial_data(self):
        for page in [{"incomplete_results": True, "total_count": 0, "items": []},
                     {"incomplete_results": False, "total_count": 1001, "items": []},
                     {"incomplete_results": False, "total_count": 1, "items": []}]:
            with self.subTest(page=page), patch.object(data, "api", return_value=page), self.assertRaises(ValueError):
                data.recently_merged("Cosipa", NOW.date())

    def test_merged_urls_and_timestamps_are_validated(self):
        for item in [self.item(1, "2026-11-11T00:00:00Z", html_url="https://example.com/a/b/pull/1"),
                     self.item(1, "2026-11-11T00:00:00Z", html_url="https://github.com/a/b/issues/1"),
                     self.item(1, "2026-11-11T00:00:00")]:
            page = {"incomplete_results": False, "total_count": 1, "items": [item]}
            with self.subTest(item=item), patch.object(data, "api", return_value=page), self.assertRaises(ValueError):
                data.recently_merged("Cosipa", NOW.date())

    def test_no_merged_prs_produces_an_honest_empty_list(self):
        with patch.object(data, "api", return_value={"total_count": 0, "incomplete_results": False, "items": []}):
            self.assertEqual(data.recently_merged("Cosipa", NOW.date())["items"], [])


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.config = tomllib.loads((ROOT / "src/data/profile.toml").read_text())
        self.palette = self.config["colors"]["dark"]
        source = ET.parse(ROOT / "src/assets/source/typing-iosevka.svg")
        self.typing_lines = [node.text for node in source.iter("{http://www.w3.org/2000/svg}text")]

    def test_quotes_preserve_supplied_text_and_choose_deterministically(self):
        entries = cards.quote_entries("# ignored\n\nAn exact quote\tIts author\nAnother exact quote\n")
        self.assertEqual(entries, [("An exact quote", "Its author"), ("Another exact quote", "")])
        first = cards.quote_card(entries, NOW.date(), self.palette)
        self.assertEqual(first, cards.quote_card(entries, NOW.date(), self.palette))
        supplied = cards.quote_card([("An exact quote", "Its author")], NOW.date(), self.palette)
        self.assertIn("An exact quote", supplied)
        self.assertIn("— Its author", supplied)
        empty = cards.quote_card([], NOW.date(), self.palette)
        self.assertIn("No quotes configured", empty)

    def test_theme_selection_uses_github_anchor_markers_not_os_media(self):
        class Images(HTMLParser):
            def __init__(self):
                super().__init__()
                self.anchors, self.images = [], []

            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    self.anchors.append(dict(attrs))
                elif tag == "img":
                    self.images.append(dict(attrs))

        paths = {"dark": "./dark.svg", "light": "./light.svg"}
        alt = 'A "quote" & <card>'
        for link in (None, "./quotes.txt"):
            markup = profile.themed_images(paths, alt, width=467, link=link)
            parsed = Images()
            parsed.feed(markup)
            self.assertEqual(len(parsed.anchors), 2)
            self.assertEqual(len(parsed.images), 2)
            self.assertNotIn("prefers-color-scheme", markup)
            self.assertNotIn("<picture", markup)
            for i, theme in enumerate(("dark", "light")):
                self.assertEqual(parsed.anchors[i]["href"], (link or paths[theme]) + f"#gh-{theme}-mode-only")
                self.assertEqual(parsed.images[i], {"src": paths[theme], "alt": alt, "width": "467"})

    def test_svg_and_markdown_text_are_escaped(self):
        document = cards.quote_card([('<script>&"', '<author>')], NOW.date(), self.palette)
        ET.fromstring(document)
        self.assertNotIn("<script>", document)
        self.assertIn("&lt;script&gt;", document)
        self.assertEqual(profile.md("[x] | <b>"), r"\[x\] \| &lt;b&gt;")
        self.assertEqual(profile.md("# heading"), r"\# heading")
        self.assertEqual(profile.md("1. item"), r"1\. item")
        self.assertEqual(profile.md("- item"), r"\- item")
        self.assertEqual(profile.md("pull-through"), "pull-through")

    def test_public_stats_have_no_grade_or_private_commit_guess(self):
        facts = data.normalize_contributions(contribution_document(), NOW)
        document = cards.stats_card("Cosipa", facts, NOW.date(), self.palette)
        self.assertIn("Public commit contributions", document)
        self.assertIn("Published restricted contributions", document)
        self.assertNotIn("Private commits", document)
        self.assertIn("2026 YTD", document)
        stale = cards.stats_card("Cosipa", facts, date(2027, 1, 1), self.palette)
        self.assertIn("await", stale)
        self.assertNotIn("2026 YTD", stale)

    def test_article_urls_cannot_break_markdown_links(self):
        link = profile.post_link({"title": "Exact title", "url": "https://cosipa.dev/posts/a)b(|c/"})
        self.assertIn("a%29b%28%7Cc/", link)
        self.assertEqual(link.count(")"), 1)

    def test_posts_keep_the_selected_layouts(self):
        posts = data.parse_posts(rss(), "https://cosipa.dev/rss")
        rows = profile.post_rows(posts)
        self.assertIn('width="20%" valign="top">October 18, 2026', rows)
        self.assertIn("> Exact first sentence.", rows)
        self.assertNotIn("<img", rows)
        self.assertNotIn("[!", profile.post_excerpts(posts, "quote"))
        self.assertIn("Exact first sentence.", profile.post_excerpts(posts, "plain"))
        with self.assertRaises(ValueError):
            profile.post_excerpts(posts, "tip")

    def test_badges_have_consistent_six_pixel_segment_padding(self):
        ns = {"s": "http://www.w3.org/2000/svg"}
        for label, value in [("followers", "5"), ("stars", "12"), ("updated", "2026-11-11"), ("pgp", "0xA8523AE122FE6E85")]:
            with self.subTest(label=label):
                root = ET.fromstring(cards.badge(label, value))
                segments = root.findall('.//s:g[@clip-path="url(#badge)"]/s:rect', ns)[:2]
                foreground = root.findall(".//s:text", ns)[1::2]
                for segment, node in zip(segments, foreground):
                    padding = (float(segment.attrib["width"]) - float(node.attrib["textLength"])) / 2
                    self.assertGreaterEqual(padding, 6)
                    self.assertLess(padding, 6.5)
                    self.assertEqual(node.attrib["lengthAdjust"], "spacingAndGlyphs")
        self.assertLess(cards.badge_text_width("iiii"), cards.badge_text_width("WWWW"))

    def test_typing_export_preserves_source_text_and_shows_one_line_at_a_time(self):
        ns = {"s": "http://www.w3.org/2000/svg"}
        self.assertTrue(self.typing_lines)
        exported = ET.parse(ROOT / "src/assets/static/typing-iosevka.svg").getroot()
        groups = exported.find('.//*[@id="typing-text"]').findall("s:g", ns)
        self.assertEqual([group.find('.//*[@aria-label]').attrib["aria-label"] for group in groups], self.typing_lines)
        animations = [group.find('s:animate[@attributeName="opacity"]', ns) for group in groups]
        reveal = exported.find('.//s:animate[@attributeName="width"]', ns)
        cycle_seconds = float(reveal.attrib["dur"].removesuffix("s")) * len(self.typing_lines)
        for animation in animations:
            self.assertEqual(float(animation.attrib["dur"].removesuffix("s")), cycle_seconds)
            self.assertEqual(animation.attrib["repeatCount"], "indefinite")
        # Each slot shows exactly its own line, not overlapping text.
        for slot in range(len(self.typing_lines)):
            for fraction in (.01, .5, .99):
                phase = (slot + fraction) / len(self.typing_lines)
                active = []
                for i, animation in enumerate(animations):
                    times = [float(t) for t in animation.attrib["keyTimes"].split(";")]
                    values = animation.attrib["values"].split(";")
                    step = max(j for j, time in enumerate(times) if time <= phase)
                    if values[step] == "1":
                        active.append(i)
                self.assertEqual(active, [slot])

    def test_typing_has_outlined_iosevka_and_preserved_animation(self):
        root = ET.parse(ROOT / "src/assets/static/typing-iosevka.svg").getroot()
        ns = {"s": "http://www.w3.org/2000/svg"}
        self.assertEqual(root.findall(".//s:text", ns), [])
        self.assertTrue(root.findall(".//s:path", ns))
        self.assertIn("IosevkaTerm Nerd Font", "".join(root.itertext()))
        for path in root.findall(".//s:path", ns):
            self.assertNotIn("opacity:0", path.attrib.get("style", ""))
            self.assertNotEqual(path.attrib.get("opacity"), "0")
        reveal = root.find('.//s:animate[@attributeName="width"]', ns)
        self.assertEqual(reveal.attrib["calcMode"], "discrete")
        widths = [float(v) for v in reveal.attrib["values"].split(";")]
        cell_width = float(root.find('.//*[@id="typing-text"]').attrib["font-size"]) / 2
        self.assertGreaterEqual(max(widths), max(map(len, self.typing_lines)) * cell_width)
        self.assertLessEqual(max(widths), float(root.attrib["width"]))
        self.assertTrue(all(abs(b - a) in (0, cell_width) for a, b in zip(widths, widths[1:])))
        self.assertTrue(any(b < a for a, b in zip(widths, widths[1:])))
        for node in root.findall(".//s:animate", ns):
            times = [float(t) for t in node.attrib["keyTimes"].split(";")]
            self.assertEqual(len(times), len(node.attrib["values"].split(";")))
            self.assertTrue(all(a < b for a, b in zip(times, times[1:])))

    def test_typing_stays_centered_at_every_character_step_in_both_themes(self):
        source = (ROOT / "src/assets/static/typing-iosevka.svg").read_bytes()
        ns = {"s": "http://www.w3.org/2000/svg"}
        for colors in self.config["colors"].values():
            root = ET.fromstring(cards.typing_card(source, colors))
            lettering = root.find('.//*[@id="typing-text"]')
            canvas_width = float(root.attrib["viewBox"].split()[2])
            cell_width = float(lettering.attrib["font-size"]) / 2
            self.assertNotIn("clip-path", lettering.attrib)
            reveal = root.find('.//s:animate[@attributeName="width"]', ns)
            widths = [float(value) for value in reveal.attrib["values"].split(";")]
            lines = lettering.findall("s:g", ns)
            self.assertEqual(len(lines), len(self.typing_lines))
            self.assertEqual([line.find('.//*[@aria-label]').attrib["aria-label"] for line in lines], self.typing_lines)
            for line in lines:
                self.assertEqual(line.attrib["clip-path"], "url(#typing-line)")
                glyphs = line.find('.//*[@aria-label]')
                line_width = len(glyphs.attrib["aria-label"]) * cell_width
                movement = line.find("s:animateTransform", ns)
                self.assertEqual(movement.attrib["attributeName"], "transform")
                self.assertEqual(movement.attrib["type"], "translate")
                for key in ("calcMode", "keyTimes", "dur", "repeatCount"):
                    self.assertEqual(movement.attrib[key], reveal.attrib[key])
                offsets = [list(map(float, value.split())) for value in movement.attrib["values"].split(";")]
                self.assertEqual(len(offsets), len(widths))
                for (x, y), visible in zip(offsets, widths):
                    self.assertEqual(y, 0)
                    self.assertAlmostEqual(x + min(visible, line_width) / 2, canvas_width / 2)

    def test_typing_variants_preserve_glyphs_timing_and_readable_contrast(self):
        source = (ROOT / "src/assets/static/typing-iosevka.svg").read_bytes()
        ns = {"s": "http://www.w3.org/2000/svg"}
        original = ET.fromstring(source)

        def luminance(hex_color):
            channels = [int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            channels = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
            return sum(v * w for v, w in zip(channels, (.2126, .7152, .0722)))

        for colors in self.config["colors"].values():
            result = ET.fromstring(cards.typing_card(source, colors))
            self.assertEqual(result.find('.//*[@id="typing-text"]').attrib["fill"], "#" + colors["typing"])
            self.assertEqual([p.attrib["d"] for p in original.findall(".//s:path", ns)],
                             [p.attrib["d"] for p in result.findall(".//s:path", ns)])
            self.assertEqual([a.attrib for a in original.findall(".//s:animate", ns)],
                             [a.attrib for a in result.findall(".//s:animate", ns)])
            a, b = sorted([luminance(colors["typing"]), luminance(colors["background"])])
            self.assertGreaterEqual((b + .05) / (a + .05), 4.5)

    def test_snake_themes_cached_or_fresh_animation_without_changing_data(self):
        content = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-16 -32 880 192">'
                   b'<style>:root{--cb:#000;--cs:#fff;--ce:#000;--c0:#000;--c1:#111;--c2:#222;--c3:#333;--c4:#444}'
                   b'@keyframes travel{100%{transform:translate(10px,0)}}</style>'
                   b'<rect class="snake" width="12" height="12"/></svg>')
        for theme, colors in self.config["colors"].items():
            with self.subTest(theme=theme):
                result = cards.snake_card(content, colors)
                self.assertEqual(cards.snake_card(result, colors), result)
                root = ET.fromstring(result)
                background = root[0]
                self.assertEqual(background.attrib["fill"], "#" + colors["background"])
                self.assertEqual(background.attrib["x"], "-16")
                self.assertIn(("--cs:#" + colors["snake"]).encode(), result)
                self.assertIn(("--c4:#" + colors["dots"][4]).encode(), result)
                self.assertIn(b"@keyframes travel{100%{transform:translate(10px,0)}}", result)
                self.assertEqual(len(root.findall('.//*[@id="snake-background"]')), 1)
                self.assertEqual(root[-1].attrib["class"], "snake")

    def test_timeline_has_coloured_area_and_real_peak(self):
        facts = {"days": {f"2026-01-{i:02}": i for i in range(1, 15)},
                 "calendar_total": 105, "calendar_start": "2025-01-15", "calendar_end": "2026-01-14"}
        for colors in self.config["colors"].values():
            document = cards.timeline_card("Cosipa", facts, colors)
            ET.fromstring(document)
            self.assertIn('fill="url(#area)"', document)
            self.assertIn('stroke="url(#line)"', document)
            self.assertIn("Peak week: 77 contributions", document)
            self.assertIn("105 contributions", document)
            self.assertIn("#" + colors["secondary"], document)

    def test_activity_tables_show_status_dates_and_escaped_titles(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = profile.Assets(Path(directory), "generated")
            item = {"kind": "pr", "title": "Actual | title", "repository": "owner/repo", "number": 1,
                    "url": "https://github.com/owner/repo/pull/1", "merged_at": "2026-11-11T12:00:00+00:00"}
            opened = profile.activity_table({"items": [item, {**item, "kind": "issue"}]}, assets)
            merged = profile.activity_table({"items": [item]}, assets, merged=True)
            self.assertEqual(opened.splitlines()[1], "| :---: | :-- | :-- |")
            self.assertEqual(merged.splitlines()[1], "| :---: | :-- | :-- | :-- |")
            self.assertEqual(opened.count('align="top"'), 2)
            self.assertEqual(merged.count('align="top"'), 1)
            self.assertIn('alt="PR open"', opened)
            self.assertIn('alt="Issue open"', opened)
            self.assertIn('alt="PR merged"', merged)
            self.assertIn("status-pr-open.", opened)
            self.assertIn("status-issue-open.", opened)
            self.assertIn("status-pr-merged.", merged)
            self.assertIn("Merged (UTC)", merged)
            self.assertIn("2026-11-11", merged)
            self.assertIn(r"Actual \| title", merged)
            self.assertNotIn("Status style preview", merged)
            self.assertNotIn("static/badge-", opened)

    def test_empty_merged_table_has_no_style_preview_or_fake_prs(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = profile.Assets(Path(directory), "generated")
            rendered = profile.activity_table({"items": []}, assets, merged=True)
            self.assertTrue(rendered.startswith("| Status | Repository | Title | Merged (UTC) |"))
            self.assertNotIn("Status style preview", rendered)
            self.assertNotIn("status-pr-merged", rendered)
            self.assertIn("No merged public pull requests found.", rendered)
            self.assertNotIn("https://github.com/", rendered)
            pending = profile.activity_table({"items": [], "pending": True}, assets, merged=True)
            self.assertIn("Awaiting a successful", pending)
            self.assertNotIn("No merged public", pending)
            self.assertNotIn("Status style preview", pending)
            self.assertEqual(list(assets.directory.glob("*.svg")), [])

    def test_local_links_resolve_from_the_containing_document(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = ('![Card](./src/assets/static/card.svg)\n'
                        '<a href="./src/data/quotes.txt#section"><img src="./src/assets/static/card.svg"></a>\n'
                        '[External](https://example.com/card.svg)\n'
                        'Prose: "./not-a-link" and href="./not-an-attribute"\n'
                        r'Escaped: \[not a link\](./not-a-link)')
            expected = {root / "src/assets/static/card.svg", root / "src/data/quotes.txt"}
            for name in ("README.md", "src/showcase.md", "src/nested/showcase.md"):
                document = root / name
                with self.subTest(document=name):
                    converted = profile.document_links(original, root, document)
                    self.assertEqual(profile.linked_files(root, converted, document), expected)
                    self.assertIn("#section", converted)
                    self.assertIn("https://example.com/card.svg", converted)
                    self.assertIn('Prose: "./not-a-link" and href="./not-an-attribute"', converted)
                    self.assertIn(r'\[not a link\](./not-a-link)', converted)

    def test_nested_document_validation_rejects_missing_or_escaping_svgs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "src/showcase.md"
            for target in ("./assets/missing.svg", "../../outside.svg", "../.git/config.svg"):
                markdown = f'<!-- profile:stats:start -->\n![Card]({target})\n<!-- profile:stats:end -->'
                with self.subTest(target=target), self.assertRaises(ValueError):
                    profile.validate(root, self.config, markdown, regions=["stats"], document=document)

    def test_only_marked_content_is_changed(self):
        original = "before\n<!-- profile:stats:start -->\nold\n<!-- profile:stats:end -->\nafter\n"
        changed = profile.replace_region(original, "stats", "new\\not a regex replacement")
        self.assertEqual(changed, original.replace("\nold\n", "\nnew\\not a regex replacement\n"))
        with self.assertRaises(ValueError):
            profile.replace_region(original + original, "stats", "new")

    def test_output_paths_cannot_escape_repository_or_git(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in ["../outside.svg", ".git/config"]:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    profile.inside(root, path)

    def test_hashed_assets_are_deterministic_and_pruned_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = profile.Assets(root, "generated")
            first = assets.put("badge", cards.badge("PR", "open"))
            same = assets.put("badge", cards.badge("PR", "open"))
            self.assertEqual(first, same)
            second = assets.put("badge", cards.badge("PR", "closed"))
            unrelated = assets.directory / "handmade.svg"
            unrelated.write_text("do not delete")
            assets.prune([(root / "README.md", f"![Badge]({first})")])
            self.assertTrue((root / first).exists())
            self.assertFalse((root / second).exists())
            self.assertTrue(unrelated.exists())
            with self.assertRaises(ValueError):
                assets.put("bad", '<svg xmlns="http://www.w3.org/2000/svg"><script>oops</script></svg>')
            with self.assertRaises(ValueError):
                assets.put("../escape", cards.badge("PR", "open"))

    def test_selected_regions_render_without_unselected_widgets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            quotes = root / self.config["quotes"]
            quotes.parent.mkdir(parents=True)
            quotes.write_text("")
            assets = profile.Assets(root, "generated")
            regions = self.config["regions"]
            original = "# Keep this intro\n" + "\n".join(
                f'<!-- profile:{name}:start -->\nold {name}\n<!-- profile:{name}:end -->'
                for name in regions) + "\nKeep this ending.\n"
            state = {"schema": 1, "sources": {"posts": {"items": data.parse_posts(rss(), "https://cosipa.dev/rss")}}}
            rendered = profile.render(original, self.config, state, assets, NOW.date(), None, regions=regions)
            profile.validate(root, self.config, rendered, regions=regions)
            self.assertEqual(set(re.findall(r"profile:([\w-]+):start", rendered)), set(regions))
            for name in regions:
                self.assertNotIn(f"old {name}", rendered)
            self.assertTrue(rendered.startswith("# Keep this intro\n"))
            self.assertTrue(rendered.endswith("\nKeep this ending.\n"))
            self.assertNotIn("footer-wave", rendered)
            self.assertNotIn("Repository preview placeholder", rendered)

    def test_region_validation_rejects_missing_duplicate_and_unexpected_markers(self):
        valid = "<!-- profile:typing:start -->\nbody\n<!-- profile:typing:end -->"
        profile.validate_regions(valid, ["typing"])
        for markdown, regions in [
            (valid, ["typing", "pgp"]),
            (valid + "\n" + valid, ["typing"]),
            (valid + "\n<!-- profile:typing:end -->", ["typing"]),
            (valid + "\n<!-- profile:footer:start -->", ["typing"]),
            (valid, ["typing", "typing"]),
            (valid, ["unknown"]),
            (valid, []),
        ]:
            with self.subTest(markdown=markdown, regions=regions), self.assertRaises(ValueError):
                profile.validate_regions(markdown, regions)

    def test_render_preserves_everything_outside_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            quotes = root / self.config["quotes"]
            quotes.parent.mkdir(parents=True)
            quotes.write_text("")
            assets = profile.Assets(root, "generated")
            original = "# Keep this layout\n" + "\n".join(
                f'<!-- profile:{name}:start -->\nold {name}\n<!-- profile:{name}:end -->'
                for name in profile.REGIONS) + "\nfooter prose\n"
            state = {"schema": 1, "sources": {"posts": {"items": data.parse_posts(rss(), "https://cosipa.dev/rss")}}}
            rendered = profile.render(original, self.config, state, assets, NOW.date(), None)
            def outside(markdown):
                for name in profile.REGIONS:
                    markdown = profile.replace_region(markdown, name, "UNCHANGED REGION")
                return markdown
            self.assertEqual(outside(original), outside(rendered))
            self.assertNotIn("Platane/snk/output", rendered)
            self.assertIn("Repository preview placeholder", rendered)


class WorkflowAndCacheTests(unittest.TestCase):
    def copy_profile_inputs(self, root):
        paths = ["src/data/profile.toml", "README.md", "src/showcase.md", "src/data/quotes.txt", "src/data/public.json"]
        paths += [str(path.relative_to(ROOT)) for path in (ROOT / "src/assets/static").glob("*.svg")]
        for relative in paths:
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / relative).read_bytes())

    def test_offline_refresh_updates_both_documents_and_retains_their_assets(self):
        config = tomllib.loads((ROOT / "src/data/profile.toml").read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_profile_inputs(root)
            before = {name: (root / name).read_text() for name in (config["markdown"], config["showcase_markdown"])}
            with patch.object(profile, "ROOT", root), patch.object(sys, "argv", ["update_profile.py", "--offline"]), \
                 patch.object(profile, "refresh", side_effect=AssertionError("offline must not fetch")):
                profile.main()
                for name, regions in [(config["markdown"], config["regions"]), (config["showcase_markdown"], config["showcase_regions"])]:
                    updated = (root / name).read_text()
                    profile.validate(root, config, updated, regions=regions, document=root / name)
                    original = before[name]
                    for region in regions:
                        original = profile.replace_region(original, region, "REGION")
                        updated = profile.replace_region(updated, region, "REGION")
                    self.assertEqual(updated, original)
                catalogue_path = root / config["showcase_markdown"]
                catalogue = catalogue_path.read_text()
                readme_path = root / config["markdown"]
                readme = readme_path.read_text()
                catalogue_only = profile.region_pattern("repository-placeholder").search(catalogue)[2]
                catalogue_assets = profile.linked_files(root, catalogue_only, catalogue_path)
                self.assertTrue(catalogue_assets)
                for path in catalogue_assets:
                    self.assertNotIn(path, profile.linked_files(root, readme, readme_path))
                    self.assertTrue(path.is_file())
                cache = json.loads((root / config["cache"]).read_text())
                for path in cache["snake"].values():
                    self.assertTrue(path.startswith("./src/assets/generated/"))
                    self.assertTrue((root / path).is_file())
                snapshot = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
                profile.main()
                self.assertEqual(snapshot, {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()})
            with patch.object(profile, "ROOT", root), patch.object(sys, "argv", ["update_profile.py", "--check"]):
                profile.main()

    def test_broken_catalogue_aborts_before_fetching_or_writing_readme(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_profile_inputs(root)
            before = (root / "README.md").read_bytes()
            catalogue = root / "src/showcase.md"
            catalogue.write_text(catalogue.read_text().replace("<!-- profile:footer:end -->", ""))
            with patch.object(profile, "ROOT", root), patch.object(sys, "argv", ["update_profile.py"]), \
                 patch.object(profile, "refresh") as refresh, self.assertRaises(ValueError):
                profile.main()
            refresh.assert_not_called()
            self.assertEqual((root / "README.md").read_bytes(), before)
            self.assertFalse((root / "src/assets/generated").exists())

    def test_configured_documents_partition_the_known_regions(self):
        config = tomllib.loads((ROOT / "src/data/profile.toml").read_text())
        primary = set(config["regions"])
        showcase = set(config["showcase_regions"])
        self.assertTrue(primary.isdisjoint(showcase))
        self.assertEqual(primary | showcase, set(profile.REGIONS))
        for path, regions in [(config["markdown"], config["regions"]),
                              (config["showcase_markdown"], config["showcase_regions"])]:
            with self.subTest(document=path):
                profile.validate(ROOT, config, (ROOT / path).read_text(), regions=regions, document=ROOT / path)

    def test_source_failure_keeps_last_good_data(self):
        config = tomllib.loads((ROOT / "src/data/profile.toml").read_text())
        state = {"schema": 1, "sources": {"posts": {"as_of": "2026-10-18", "items": [{"title": "Existing post"}]}}}
        original = json.loads(json.dumps(state))
        with patch.object(data, "public_profile", side_effect=ValueError("offline")), \
             patch.object(data, "contributions", side_effect=ValueError("offline")), \
             patch.object(data, "public_calendar", side_effect=ValueError("offline")), \
             patch.object(data, "activity", side_effect=ValueError("offline")), \
             patch.object(data, "recently_merged", side_effect=ValueError("offline")), \
             patch.object(data, "posts", side_effect=ValueError("offline")):
            warnings = profile.refresh(config, state, NOW)
        self.assertEqual(len(warnings), 6)
        self.assertEqual(state, original)

    def test_closed_and_private_activity_is_not_published(self):
        calls = []
        def api(path, token):
            calls.append(path)
            return {"incomplete_results": False, "items": [
                {"state": "open", "html_url": "https://github.com/owner/repo/pull/1", "title": "Actual title", "number": 1, "updated_at": "2026-11-12T00:00:00Z"},
                {"state": "closed", "html_url": "https://github.com/owner/repo/pull/2", "title": "Closed", "number": 2, "updated_at": "2026-11-12T00:00:00Z"}]}
        with patch.object(data, "api", side_effect=api):
            activity = data.activity("Cosipa", NOW.date(), "token")
        self.assertTrue(all("is%3Aopen" in c and "is%3Apublic" in c for c in calls))
        self.assertTrue(all(item["number"] == 1 for item in activity["items"]))

    def test_private_preview_metadata_is_not_published(self):
        user = {"login": "Cosipa", "created_at": "2025-01-01T00:00:00Z", "followers": 2, "public_repos": 4}
        private = {"private": True, "stargazers_count": 99, "pushed_at": "2026-11-12T00:00:00Z"}
        with patch.object(data, "api", side_effect=[user, private]):
            result = data.public_profile("Cosipa", "Cosipa/cosipa", NOW.date(), "token")
        self.assertIsNone(result["repository_stars"])
        self.assertIsNone(result["repository_updated"])
        self.assertEqual(result["followers"], 2)

    def test_action_refs_and_python_are_pinned(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            content = path.read_text()
            for action in re.findall(r"uses:\s+(\S+)", content):
                self.assertRegex(action, r"^[\w./-]+@[a-f0-9]{40}$")
            self.assertNotIn("pull_request_target", content)
            self.assertNotIn("METRICS_TOKEN", content)
        self.assertRegex((ROOT / ".python-version").read_text().strip(), r"^3\.\d+\.\d+$")
        self.assertIn("github-actions", json.loads((ROOT / "renovate.json").read_text())["enabledManagers"])

    def test_static_snapshots_match_recorded_provenance(self):
        directory = ROOT / "src/assets/static"
        manifest = json.loads((directory / "provenance.json").read_text())
        for name, metadata in manifest.items():
            self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), metadata["sha256"])
            ET.parse(directory / name)


if __name__ == "__main__":
    unittest.main()
