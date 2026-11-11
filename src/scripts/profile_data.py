"""Public-only profile data. No third-party APIs, PATs, or Python dependencies."""

from __future__ import annotations

import json
import re
import time as clock
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from operator import itemgetter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_RESPONSE = 4 * 1024 * 1024


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise ValueError("Refusing a non-HTTPS redirect")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and urlsplit(newurl).netloc != urlsplit(req.full_url).netloc:
            redirected.remove_header("Authorization")
        return redirected


def fetch(url: str, *, token: str = "", payload: dict | None = None) -> bytes:
    target = urlsplit(url)
    if target.scheme != "https":
        raise ValueError("Only HTTPS data sources are allowed")
    headers = {
        "User-Agent": "Cosipa-profile",
        "Accept": "application/json" if target.netloc == "api.github.com" else "*/*",
    }
    if target.netloc == "api.github.com":
        headers["X-GitHub-Api-Version"] = "2022-11-28"
        if token:
            headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload).encode() if payload is not None else None
    if body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(3):
        try:
            with build_opener(SafeRedirect()).open(
                Request(url, data=body, headers=headers), timeout=30
            ) as response:
                data = response.read(MAX_RESPONSE + 1)
                if len(data) > MAX_RESPONSE:
                    raise ValueError("Data source exceeded the response size limit")
                return data
        except HTTPError as exc:
            if attempt == 2 or exc.code not in (429, 500, 502, 503, 504):
                raise ValueError(f"HTTP {exc.code} from {target.netloc}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt == 2:
                raise ValueError(f"Network failure contacting {target.netloc}") from exc
        clock.sleep(2**attempt)
    raise RuntimeError("Unreachable retry state")


def api(path: str, token: str = "") -> dict:
    document = json.loads(fetch("https://api.github.com" + path, token=token))
    if not isinstance(document, dict):
        raise ValueError("GitHub API returned a non-object response")
    return document


QUERY = (Path(__file__).resolve().parents[1] / "queries/profile.graphql").read_text(
    encoding="utf-8"
)


def contribution_variables(username: str, now: datetime) -> dict:
    now = now.astimezone(UTC).replace(microsecond=0)
    return {
        "login": username,
        "yearFrom": datetime(now.year, 1, 1, tzinfo=UTC).isoformat(),
        "to": now.isoformat(),
    }


def nonnegative(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Invalid contribution count")
    return value


def public_count(year: dict, connection: str, repository_count: str) -> int:
    repositories = year[connection]
    reported = nonnegative(year[repository_count])
    if reported > len(repositories) and len(repositories) >= 100:
        raise ValueError(
            "GitHub truncated a contribution breakdown; refusing an incomplete total"
        )
    return sum(
        nonnegative(repository["contributions"]["totalCount"])
        for repository in repositories
        if repository["repository"]["isPrivate"] is False
    )


def normalize_contributions(document: dict, now: datetime) -> dict:
    if document.get("errors"):
        raise ValueError("GitHub GraphQL rejected the public contribution query")
    user = (document.get("data") or {}).get("user")
    if not user:
        raise ValueError("GitHub returned no contribution data")
    year = user["year"]

    today = now.astimezone(UTC).date()
    private = nonnegative(year["restrictedContributionsCount"])
    return {
        "as_of": today.isoformat(),
        "year": today.year,
        "public_commits": public_count(
            year, "commitContributionsByRepository", "totalRepositoriesWithContributedCommits"
        ),
        "public_prs": public_count(
            year, "pullRequestContributionsByRepository", "totalRepositoriesWithContributedPullRequests"
        ),
        "public_issues": public_count(
            year, "issueContributionsByRepository", "totalRepositoriesWithContributedIssues"
        ),
        "public_reviews": public_count(
            year, "pullRequestReviewContributionsByRepository",
            "totalRepositoriesWithContributedPullRequestReviews",
        ),
        # Restricted means inaccessible to this token, not necessarily every private contribution.
        "published_private": private if private else None,
    }


def contributions(username: str, now: datetime, token: str) -> dict:
    if not token:
        raise ValueError(
            "Contribution stats await the workflow's built-in GITHUB_TOKEN; no guessed totals"
        )
    document = json.loads(
        fetch(
            "https://api.github.com/graphql",
            token=token,
            payload={"query": QUERY, "variables": contribution_variables(username, now)},
        )
    )
    return normalize_contributions(document, now)


class CalendarHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cells = {}
        self.counts = {}
        self.target = None
        self.label = []
        self.all = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-date" in attrs and "id" in attrs:
            self.cells[attrs["id"]] = attrs["data-date"]
        if tag == "tool-tip":
            self.target = attrs.get("for")
            self.label = []

    def handle_data(self, data: str) -> None:
        self.all.append(data)
        if self.target:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == "tool-tip" and self.target:
            label = " ".join("".join(self.label).split())
            if re.match(r"No contributions? on ", label, re.IGNORECASE):
                self.counts[self.target] = 0
            else:
                match = re.match(r"([\d,]+) contributions? on ", label, re.IGNORECASE)
                if match:
                    self.counts[self.target] = int(match[1].replace(",", ""))
            self.target = None


def normalize_calendar(content: bytes, today: date) -> dict:
    parser = CalendarHTML()
    parser.feed(content.decode())
    start = today - timedelta(days=364)
    days = {}
    for cell_id, value in parser.cells.items():
        day = date.fromisoformat(value)
        if start <= day <= today and cell_id in parser.counts:
            days[value] = nonnegative(parser.counts[cell_id])
    expected = {(start + timedelta(days=i)).isoformat() for i in range(365)}
    if set(days) != expected:
        raise ValueError(
            "Incomplete public contribution calendar; refusing to fill missing days with zero"
        )
    heading = re.search(
        r"([\d,]+) contributions? in ", " ".join(" ".join(parser.all).split()), re.IGNORECASE
    )
    if not heading:
        raise ValueError("Public contribution calendar has no recognizable total")
    source_total = int(heading[1].replace(",", ""))
    if (
        set(parser.cells) - set(parser.counts)
        or sum(parser.counts[cell_id] for cell_id in parser.cells) != source_total
    ):
        raise ValueError("Public calendar total disagrees with its daily counts")
    # GitHub rounds its visible grid to weeks. Our clearly labeled 365-day card
    # excludes any extra leading dates instead of borrowing the grid's headline.
    return {
        "as_of": today.isoformat(),
        "calendar_start": start.isoformat(),
        "calendar_end": today.isoformat(),
        "calendar_total": sum(days.values()),
        "source_calendar_total": source_total,
        "days": dict(sorted(days.items())),
    }


def public_calendar(username: str, today: date) -> dict:
    # No token: respect public privacy settings, even in a private preview repo.
    # GitHub's from/to URL parameters select calendar years, not arbitrary windows;
    # fetch the rolling grid and select the exact dates locally instead.
    return normalize_calendar(
        fetch(f"https://github.com/users/{quote(username, safe='')}/contributions"), today
    )


def activity(username: str, today: date, token: str = "") -> dict:
    result = []
    for kind in ("pr", "issue"):
        # Explicit public filter even if someone later supplies a more privileged token.
        query = urlencode({
            "q": f"author:{username} is:{kind} is:open is:public",
            "sort": "updated",
            "order": "desc",
            "per_page": 100,
        })
        page = api("/search/issues?" + query, token)
        if page.get("incomplete_results"):
            raise ValueError("GitHub returned incomplete activity search results")
        for item in page["items"]:
            if item["state"] != "open":
                continue
            path = urlsplit(item["html_url"])
            if path.scheme != "https" or path.netloc != "github.com":
                raise ValueError("Unexpected GitHub activity URL")
            parts = path.path.strip("/").split("/")
            result.append({
                "kind": kind,
                "title": item["title"],
                "url": item["html_url"],
                "repository": "/".join(parts[:2]),
                "number": item["number"],
                "updated_at": item["updated_at"],
            })
    result.sort(key=itemgetter("updated_at"), reverse=True)
    return {"as_of": today.isoformat(), "items": result[:12]}


def recently_merged(username: str, today: date, token: str = "") -> dict:
    # Search cannot sort by merge time. Read every result (up to GitHub's 1,000
    # result limit), then sort actual merged_at timestamps, not update/close dates.
    items = []
    for page_number in range(1, 11):
        query = urlencode({
            "q": f"author:{username} is:pr is:merged is:public",
            "sort": "updated",
            "order": "desc",
            "per_page": 100,
            "page": page_number,
        })
        page = api("/search/issues?" + query, token)
        total = nonnegative(page["total_count"])
        if page.get("incomplete_results") or total > 1000:
            raise ValueError("GitHub truncated merged PR search; refusing an incomplete list")
        batch = page["items"]
        items.extend(batch)
        if len(items) >= total:
            break
        if not batch:
            raise ValueError("GitHub returned an incomplete merged PR search page")
    else:
        raise ValueError("GitHub truncated merged PR search pagination")
    merged = {}
    for item in items:
        timestamp = (item.get("pull_request") or {}).get("merged_at")
        if item["state"] != "closed" or not timestamp:
            continue  # Never equate closed with merged.
        url = urlsplit(item["html_url"])
        parts = url.path.strip("/").split("/")
        if (
            url.scheme != "https"
            or url.netloc != "github.com"
            or len(parts) != 4
            or parts[2] != "pull"
            or not parts[3].isdigit()
        ):
            raise ValueError("Unexpected merged pull request URL")
        when = datetime.fromisoformat(timestamp)
        if when.tzinfo is None:
            raise ValueError("Merged pull request timestamp is missing its timezone")
        merged[item["html_url"]] = {
            "kind": "pr",
            "title": item["title"],
            "url": item["html_url"],
            "repository": "/".join(parts[:2]),
            "number": item["number"],
            "merged_at": when.astimezone(UTC).isoformat(),
        }
    result = sorted(merged.values(), key=itemgetter("merged_at"), reverse=True)
    return {"as_of": today.isoformat(), "items": result[:6]}


class FeedText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self.all: list[str] = []
        self.current: list[str] | None = None
        self.ignore = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.ignore += 1
        if self.ignore:
            return
        if tag == "p":
            self.current = []
        if tag == "br":
            self.handle_data(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.ignore:
            self.ignore -= 1
            return
        if tag == "p" and self.current is not None:
            text = " ".join("".join(self.current).split())
            if text:
                self.paragraphs.append(text)
            self.current = None

    def handle_data(self, data: str) -> None:
        if not self.ignore:
            self.all.append(data)
            if self.current is not None:
                self.current.append(data)


def parse_posts(content: bytes, feed_url: str) -> list[dict]:
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ValueError("RSS declarations/entities are not allowed")
    root = ET.fromstring(content)
    result = []
    for item in root.findall("./channel/item"):
        title = " ".join((item.findtext("title") or "").split())
        raw_link = (item.findtext("link") or "").strip()
        if not raw_link:
            raise ValueError("RSS item has no article URL")
        link = urljoin(feed_url, raw_link)
        url = urlsplit(link)
        if not title or url.scheme != "https" or url.netloc != urlsplit(feed_url).netloc:
            raise ValueError("RSS item has an invalid title or article URL")
        published = parsedate_to_datetime(item.findtext("pubDate") or "")
        if published.tzinfo is None:
            raise ValueError("RSS item date has no timezone")
        parser = FeedText()
        parser.feed(
            item.findtext("description")
            or item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
            or ""
        )
        paragraph = next(iter(parser.paragraphs), " ".join("".join(parser.all).split()))
        # A contiguous first-sentence excerpt, never a paraphrase or generated summary.
        sentence = re.match(r"^(.+?[.!?])(?=\s|$)", paragraph, re.DOTALL)
        excerpt = sentence.group(1) if sentence else paragraph
        if not excerpt:
            raise ValueError("RSS item has no usable excerpt")
        result.append({
            "title": title,
            "url": link,
            "published": published.isoformat(),
            "excerpt": excerpt,
        })
    if not result:
        raise ValueError("RSS feed is empty; refusing to erase the previous posts")
    result.sort(key=publication_time, reverse=True)
    return result


def publication_time(post: dict) -> datetime:
    return datetime.fromisoformat(post["published"])


def posts(feed_url: str, today: date) -> dict:
    return {"as_of": today.isoformat(), "items": parse_posts(fetch(feed_url), feed_url)}
