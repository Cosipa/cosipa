from datetime import UTC, date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
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


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.config = tomllib.loads((ROOT / "profile.toml").read_text())
        self.palette = self.config["colors"]["dark"]

    def test_quotes_are_user_supplied_only_and_deterministic(self):
        entries = profile.quote_entries("# ignored\n\nAn exact quote\tIts author\nAnother exact quote\n")
        self.assertEqual(entries, [("An exact quote", "Its author"), ("Another exact quote", "")])
        first = profile.quote_card(entries, NOW.date(), self.palette)
        self.assertEqual(first, profile.quote_card(entries, NOW.date(), self.palette))
        self.assertNotIn("Cosipa", first)
        empty = profile.quote_card([], NOW.date(), self.palette)
        self.assertIn("No quotes configured", empty)
        self.assertNotIn("Your chosen author", empty)

    def test_svg_and_markdown_text_are_escaped(self):
        document = profile.quote_card([('<script>&"', '<author>')], NOW.date(), self.palette)
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
        document = profile.stats_card("Cosipa", facts, NOW.date(), self.palette)
        self.assertIn("Public commit contributions", document)
        self.assertIn("Published restricted contributions", document)
        self.assertNotIn("Private commits", document)
        self.assertIn("2026 YTD", document)
        stale = profile.stats_card("Cosipa", facts, date(2027, 1, 1), self.palette)
        self.assertIn("await", stale)
        self.assertNotIn("2026 YTD", stale)

    def test_article_urls_cannot_break_markdown_links(self):
        link = profile.post_link({"title": "Exact title", "url": "https://cosipa.dev/posts/a)b(|c/"})
        self.assertIn("a%29b%28%7Cc/", link)
        self.assertEqual(link.count(")"), 1)

    def test_posts_keep_the_selected_layouts(self):
        posts = data.parse_posts(rss(), "https://cosipa.dev/rss")
        cards = profile.post_cards(posts)
        self.assertIn('width="50%" valign="top"', cards)
        self.assertIn("### [Exact title &amp; spelling]", cards)
        self.assertEqual(cards.count("https://cosipa.dev/posts/test/"), 1)
        rows = profile.post_rows(posts)
        self.assertIn('width="20%" valign="top">October 18, 2026', rows)
        self.assertIn("> Exact first sentence.", rows)
        self.assertNotIn("<img", rows)
        self.assertNotIn("[!", profile.post_excerpts(posts, "quote"))
        self.assertIn("[!TIP]", profile.post_excerpts(posts, "tip"))

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
            first = assets.put("badge", profile.badge("PR", "open"))
            same = assets.put("badge", profile.badge("PR", "open"))
            self.assertEqual(first, same)
            second = assets.put("badge", profile.badge("PR", "closed"))
            unrelated = assets.directory / "handmade.svg"
            unrelated.write_text("do not delete")
            assets.prune(first)
            self.assertTrue((root / first).exists())
            self.assertFalse((root / second).exists())
            self.assertTrue(unrelated.exists())
            with self.assertRaises(ValueError):
                assets.put("bad", '<svg xmlns="http://www.w3.org/2000/svg"><script>oops</script></svg>')
            with self.assertRaises(ValueError):
                assets.put("../escape", profile.badge("PR", "open"))

    def test_render_preserves_everything_outside_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "quotes.txt").write_text("")
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
    def test_source_failure_keeps_last_good_data(self):
        config = tomllib.loads((ROOT / "profile.toml").read_text())
        state = {"schema": 1, "sources": {"posts": {"as_of": "2026-10-18", "items": [{"title": "Existing post"}]}}}
        original = json.loads(json.dumps(state))
        with patch.object(data, "public_profile", side_effect=ValueError("offline")), \
             patch.object(data, "contributions", side_effect=ValueError("offline")), \
             patch.object(data, "public_calendar", side_effect=ValueError("offline")), \
             patch.object(data, "activity", side_effect=ValueError("offline")), \
             patch.object(data, "posts", side_effect=ValueError("offline")):
            warnings = profile.refresh(config, state, NOW)
        self.assertEqual(len(warnings), 5)
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
        directory = ROOT / "profile-showcase/static"
        manifest = json.loads((directory / "provenance.json").read_text())
        for name, metadata in manifest.items():
            self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), metadata["sha256"])
            ET.parse(directory / name)

    def test_layout_and_terminal_are_not_redesigned(self):
        markdown = (ROOT / "test.md").read_text()
        self.assertEqual([int(n) for n in re.findall(r"^## (\d+) ·", markdown, re.M)],
                         [1, 3, 4, 5, 7, 18, 9, 12, 14, 17, 19, 21, 22, 24, 37, 42, 47, 48])
        self.assertIn("### 48A · Ordinary blockquotes", markdown)
        self.assertIn("### 48B · Unframed excerpts", markdown)
        self.assertIn("### 48C · Green TIP callouts, for comparison", markdown)
        self.assertNotIn("<details", markdown)
        self.assertEqual(tomllib.loads((ROOT / "profile.toml").read_text())["markdown"], "test.md")
        self.assertTrue((ROOT / "profile-showcase/terminal-rose-pine.svg").is_file())


if __name__ == "__main__":
    unittest.main()
