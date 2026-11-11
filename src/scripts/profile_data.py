"""Public-only profile data. No third-party APIs, PATs, or Python dependencies."""

from __future__ import annotations

import json
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

if __package__:
    from .profile_text import (
        calendar_total,
        daily_contribution_count,
        first_sentence,
        normalized_whitespace,
    )
else:
    from profile_text import (
        calendar_total,
        daily_contribution_count,
        first_sentence,
        normalized_whitespace,
    )

MAX_RESPONSE = 4 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
FETCH_ATTEMPTS = 3
RETRY_BACKOFF_BASE_SECONDS = 2
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
GITHUB_API_URL = "https://api.github.com"
GITHUB_API_HOST = "api.github.com"
GITHUB_API_VERSION = "2022-11-28"
GITHUB_PAGE_SIZE = 100
GITHUB_SEARCH_LIMIT = 1000
GITHUB_SEARCH_PAGES = GITHUB_SEARCH_LIMIT // GITHUB_PAGE_SIZE
CONTRIBUTION_REPOSITORY_LIMIT = 100  # Matches maxRepositories in profile.graphql.
CALENDAR_DAYS = 365
ACTIVITY_DISPLAY_LIMIT = 12
MERGED_DISPLAY_LIMIT = 6
RSS_CONTENT_TAG = "{http://purl.org/rss/1.0/modules/content/}encoded"
CONTRIBUTION_BREAKDOWNS = (
    (
        "public_commits",
        "commitContributionsByRepository",
        "totalRepositoriesWithContributedCommits",
    ),
    (
        "public_prs",
        "pullRequestContributionsByRepository",
        "totalRepositoriesWithContributedPullRequests",
    ),
    (
        "public_issues",
        "issueContributionsByRepository",
        "totalRepositoriesWithContributedIssues",
    ),
    (
        "public_reviews",
        "pullRequestReviewContributionsByRepository",
        "totalRepositoriesWithContributedPullRequestReviews",
    ),
)


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise ValueError("Refusing a non-HTTPS redirect")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and urlsplit(newurl).netloc != urlsplit(req.full_url).netloc:
            redirected.remove_header("Authorization")
        return redirected


def build_request_headers(url: str, token: str, *, has_payload: bool) -> dict[str, str]:
    target = urlsplit(url)
    if target.scheme != "https":
        raise ValueError("Only HTTPS data sources are allowed")
    headers = {
        "User-Agent": "Cosipa-profile",
        "Accept": "application/json" if target.netloc == GITHUB_API_HOST else "*/*",
    }
    if target.netloc == GITHUB_API_HOST:
        headers["X-GitHub-Api-Version"] = GITHUB_API_VERSION
        if token:
            headers["Authorization"] = f"Bearer {token}"
    if has_payload:
        headers["Content-Type"] = "application/json"
    return headers


def read_response(request: Request) -> bytes:
    with build_opener(SafeRedirect()).open(
        request, timeout=REQUEST_TIMEOUT_SECONDS
    ) as response:
        content = response.read(MAX_RESPONSE + 1)
    if len(content) > MAX_RESPONSE:
        raise ValueError("Data source exceeded the response size limit")
    return content


def fetch(url: str, *, token: str = "", payload: dict | None = None) -> bytes:
    headers = build_request_headers(url, token, has_payload=payload is not None)
    body = json.dumps(payload).encode() if payload is not None else None
    host = urlsplit(url).netloc
    for attempt in range(FETCH_ATTEMPTS):
        last_attempt = attempt == FETCH_ATTEMPTS - 1
        try:
            return read_response(Request(url, data=body, headers=headers))
        except HTTPError as exc:
            if last_attempt or exc.code not in RETRYABLE_HTTP_STATUSES:
                raise ValueError(f"HTTP {exc.code} from {host}") from exc
        except (URLError, TimeoutError) as exc:
            if last_attempt:
                raise ValueError(f"Network failure contacting {host}") from exc
        clock.sleep(RETRY_BACKOFF_BASE_SECONDS**attempt)
    raise RuntimeError("Unreachable retry state")


def fetch_github_api(path: str, token: str = "") -> dict:
    document = json.loads(fetch(GITHUB_API_URL + path, token=token))
    if not isinstance(document, dict):
        raise ValueError("GitHub API returned a non-object response")
    return document


QUERY = (Path(__file__).resolve().parents[1] / "queries/profile.graphql").read_text(
    encoding="utf-8"
)


def build_contribution_variables(username: str, now: datetime) -> dict:
    now = now.astimezone(UTC).replace(microsecond=0)
    return {
        "login": username,
        "yearFrom": datetime(now.year, 1, 1, tzinfo=UTC).isoformat(),
        "to": now.isoformat(),
    }


def require_nonnegative_integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Invalid contribution count")
    return value


def count_public_contributions(
    year: dict, connection: str, repository_count: str
) -> int:
    repositories = year[connection]
    reported = require_nonnegative_integer(year[repository_count])
    if (
        reported > len(repositories)
        and len(repositories) >= CONTRIBUTION_REPOSITORY_LIMIT
    ):
        raise ValueError(
            "GitHub truncated a contribution breakdown; refusing an incomplete total"
        )
    return sum(
        require_nonnegative_integer(repository["contributions"]["totalCount"])
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
    private = require_nonnegative_integer(year["restrictedContributionsCount"])
    public_counts = {
        name: count_public_contributions(year, connection, repository_count)
        for name, connection, repository_count in CONTRIBUTION_BREAKDOWNS
    }
    return {
        "as_of": today.isoformat(),
        "year": today.year,
        **public_counts,
        # Restricted means inaccessible to this token, not necessarily every private contribution.
        "published_private": private if private else None,
    }


def fetch_contributions(username: str, now: datetime, token: str) -> dict:
    if not token:
        raise ValueError(
            "Contribution stats await the workflow's built-in GITHUB_TOKEN; no guessed totals"
        )
    document = json.loads(
        fetch(
            GITHUB_API_URL + "/graphql",
            token=token,
            payload={
                "query": QUERY,
                "variables": build_contribution_variables(username, now),
            },
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
        if tag != "tool-tip" or not self.target:
            return
        count = daily_contribution_count(normalized_whitespace("".join(self.label)))
        if count is not None:
            self.counts[self.target] = count
        self.target = None


def extract_calendar_days(
    parser: CalendarHTML, start: date, today: date
) -> dict[str, int]:
    """Require a count for every date in the rolling window, including zero days."""
    days = {}
    for cell_id, value in parser.cells.items():
        day = date.fromisoformat(value)
        if start <= day <= today and cell_id in parser.counts:
            days[value] = require_nonnegative_integer(parser.counts[cell_id])
    expected = {(start + timedelta(days=i)).isoformat() for i in range(CALENDAR_DAYS)}
    if set(days) != expected:
        raise ValueError(
            "Incomplete public contribution calendar; refusing to fill missing days with zero"
        )
    return dict(sorted(days.items()))


def normalize_calendar(content: bytes, today: date) -> dict:
    parser = CalendarHTML()
    parser.feed(content.decode())
    start = today - timedelta(days=CALENDAR_DAYS - 1)
    days = extract_calendar_days(parser, start, today)
    source_total = calendar_total(" ".join(parser.all))
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
        "days": days,
    }


def fetch_public_calendar(username: str, today: date) -> dict:
    # No token: respect public privacy settings, even in a private preview repo.
    # GitHub's from/to URL parameters select calendar years, not arbitrary windows;
    # fetch the rolling grid and select the exact dates locally instead.
    return normalize_calendar(
        fetch(f"https://github.com/users/{quote(username, safe='')}/contributions"),
        today,
    )


def search_issues(filters: str, token: str, *, page: int | None = None) -> dict:
    # Always request public results, even with a more privileged token.
    parameters = {
        "q": filters + " is:public",
        "sort": "updated",
        "order": "desc",
        "per_page": GITHUB_PAGE_SIZE,
    }
    if page is not None:
        parameters["page"] = page
    return fetch_github_api("/search/issues?" + urlencode(parameters), token)


def normalize_activity_fields(item: dict, kind: str, *, merged: bool = False) -> dict:
    """Normalize the common fields after validating the source GitHub URL."""
    url = urlsplit(item["html_url"])
    parts = url.path.strip("/").split("/")
    valid_host = url.scheme == "https" and url.netloc == "github.com"
    if not merged and not valid_host:
        raise ValueError("Unexpected GitHub activity URL")
    if merged and (
        not valid_host
        or len(parts) != 4
        or parts[2] != "pull"
        or not parts[3].isdigit()
    ):
        raise ValueError("Unexpected merged pull request URL")
    return {
        "kind": kind,
        "title": item["title"],
        "url": item["html_url"],
        "repository": "/".join(parts[:2]),
        "number": item["number"],
    }


def fetch_open_activity(username: str, today: date, token: str = "") -> dict:
    result = []
    for kind in ("pr", "issue"):
        page = search_issues(f"author:{username} is:{kind} is:open", token)
        if page.get("incomplete_results"):
            raise ValueError("GitHub returned incomplete activity search results")
        for item in page["items"]:
            if item["state"] != "open":
                continue
            result.append(
                {
                    **normalize_activity_fields(item, kind),
                    "updated_at": item["updated_at"],
                }
            )
    result.sort(key=itemgetter("updated_at"), reverse=True)
    return {"as_of": today.isoformat(), "items": result[:ACTIVITY_DISPLAY_LIMIT]}


def fetch_merged_search_items(username: str, token: str) -> list[dict]:
    """Read all search pages; a partial list cannot establish the latest merges."""
    items = []
    for page_number in range(1, GITHUB_SEARCH_PAGES + 1):
        page = search_issues(
            f"author:{username} is:pr is:merged", token, page=page_number
        )
        total = require_nonnegative_integer(page["total_count"])
        if page.get("incomplete_results") or total > GITHUB_SEARCH_LIMIT:
            raise ValueError(
                "GitHub truncated merged PR search; refusing an incomplete list"
            )
        batch = page["items"]
        items.extend(batch)
        if len(items) >= total:
            return items
        if not batch:
            raise ValueError("GitHub returned an incomplete merged PR search page")
    raise ValueError("GitHub truncated merged PR search pagination")


def fetch_recently_merged_prs(username: str, today: date, token: str = "") -> dict:
    # Search cannot sort by merge time. Sort actual merged_at timestamps after
    # reading every result, not update/close dates from the first search page.
    merged = {}
    for item in fetch_merged_search_items(username, token):
        timestamp = (item.get("pull_request") or {}).get("merged_at")
        if item["state"] != "closed" or not timestamp:
            continue  # Never equate closed with merged.
        fields = normalize_activity_fields(item, "pr", merged=True)
        when = datetime.fromisoformat(timestamp)
        if when.tzinfo is None:
            raise ValueError("Merged pull request timestamp is missing its timezone")
        merged[item["html_url"]] = {
            **fields,
            "merged_at": when.astimezone(UTC).isoformat(),
        }
    result = sorted(merged.values(), key=itemgetter("merged_at"), reverse=True)
    return {"as_of": today.isoformat(), "items": result[:MERGED_DISPLAY_LIMIT]}


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
            text = normalized_whitespace("".join(self.current))
            if text:
                self.paragraphs.append(text)
            self.current = None

    def handle_data(self, data: str) -> None:
        if self.ignore:
            return
        self.all.append(data)
        if self.current is not None:
            self.current.append(data)


def extract_post_excerpt(item: ET.Element) -> str:
    parser = FeedText()
    parser.feed(item.findtext("description") or item.findtext(RSS_CONTENT_TAG) or "")
    paragraph = next(
        iter(parser.paragraphs), normalized_whitespace("".join(parser.all))
    )
    excerpt = first_sentence(paragraph)
    if not excerpt:
        raise ValueError("RSS item has no usable excerpt")
    return excerpt


def parse_post(item: ET.Element, feed_url: str) -> dict:
    title = normalized_whitespace(item.findtext("title") or "")
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
    return {
        "title": title,
        "url": link,
        "published": published.isoformat(),
        "excerpt": extract_post_excerpt(item),
    }


def parse_posts(content: bytes, feed_url: str) -> list[dict]:
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ValueError("RSS declarations/entities are not allowed")
    root = ET.fromstring(content)
    result = [parse_post(item, feed_url) for item in root.findall("./channel/item")]
    if not result:
        raise ValueError("RSS feed is empty; refusing to erase the previous posts")
    result.sort(key=publication_time, reverse=True)
    return result


def publication_time(post: dict) -> datetime:
    return datetime.fromisoformat(post["published"])


def fetch_posts(feed_url: str, today: date) -> dict:
    return {"as_of": today.isoformat(), "items": parse_posts(fetch(feed_url), feed_url)}
