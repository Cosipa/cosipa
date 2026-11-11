"""Public-only profile data. No third-party APIs, PATs, or Python dependencies."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import json
import re
import time as clock
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET

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
    if urlsplit(url).scheme != "https":
        raise ValueError("Only HTTPS data sources are allowed")
    headers = {"User-Agent": "Cosipa-profile-showcase", "Accept": "application/json" if urlsplit(url).netloc == "api.github.com" else "*/*"}
    if urlsplit(url).netloc == "api.github.com":
        headers["X-GitHub-Api-Version"] = "2022-11-28"
        if token:
            headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload).encode() if payload is not None else None
    if body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(3):
        try:
            with build_opener(SafeRedirect()).open(Request(url, data=body, headers=headers), timeout=30) as response:
                data = response.read(MAX_RESPONSE + 1)
                if len(data) > MAX_RESPONSE:
                    raise ValueError("Data source exceeded the response size limit")
                return data
        except HTTPError as exc:
            if attempt == 2 or exc.code not in (429, 500, 502, 503, 504):
                raise ValueError(f"HTTP {exc.code} from {urlsplit(url).netloc}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt == 2:
                raise ValueError(f"Network failure contacting {urlsplit(url).netloc}") from exc
        clock.sleep(2 ** attempt)
    raise RuntimeError("Unreachable retry state")


def api(path: str, token: str = "") -> dict | list:
    return json.loads(fetch("https://api.github.com" + path, token=token))


def public_profile(username: str, repository: str, today: date, token: str = "") -> dict:
    user = api(f"/users/{quote(username, safe='')}", token)
    try:
        repo = api(f"/repos/{repository}", token)
    except ValueError as exc:
        if "HTTP 404" not in str(exc):
            raise
        repo = {}
    # A private preview repository is not public data, even if this workflow can read it.
    if repo.get("private"):
        repo = {}
    return {
        "as_of": today.isoformat(),
        "login": user["login"],
        "created_at": user["created_at"],
        "followers": user["followers"],
        "public_repos": user["public_repos"],
        "repository_stars": repo.get("stargazers_count"),
        "repository_updated": repo["pushed_at"][:10] if repo.get("pushed_at") else None,
    }


QUERY = """
query Profile($login: String!, $yearFrom: DateTime!, $to: DateTime!) {
  user(login: $login) {
    year: contributionsCollection(from: $yearFrom, to: $to) {
      totalRepositoriesWithContributedCommits
      totalRepositoriesWithContributedIssues
      totalRepositoriesWithContributedPullRequests
      totalRepositoriesWithContributedPullRequestReviews
      restrictedContributionsCount
      commitContributionsByRepository(maxRepositories: 100) {
        repository { isPrivate }
        contributions { totalCount }
      }
      issueContributionsByRepository(maxRepositories: 100) {
        repository { isPrivate }
        contributions { totalCount }
      }
      pullRequestContributionsByRepository(maxRepositories: 100) {
        repository { isPrivate }
        contributions { totalCount }
      }
      pullRequestReviewContributionsByRepository(maxRepositories: 100) {
        repository { isPrivate }
        contributions { totalCount }
      }
    }
  }
}
"""


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


def normalize_contributions(document: dict, now: datetime) -> dict:
    if document.get("errors"):
        raise ValueError("GitHub GraphQL rejected the public contribution query")
    user = (document.get("data") or {}).get("user")
    if not user:
        raise ValueError("GitHub returned no contribution data")
    year = user["year"]
    def public_count(connection, repository_count):
        repositories = year[connection]
        reported = nonnegative(year[repository_count])
        if reported > len(repositories) and len(repositories) >= 100:
            raise ValueError("GitHub truncated a contribution breakdown; refusing an incomplete total")
        return sum(nonnegative(r["contributions"]["totalCount"])
                   for r in repositories if r["repository"]["isPrivate"] is False)

    today = now.astimezone(UTC).date()
    private = nonnegative(year["restrictedContributionsCount"])
    return {
        "as_of": today.isoformat(), "year": today.year,
        "public_commits": public_count("commitContributionsByRepository", "totalRepositoriesWithContributedCommits"),
        "public_prs": public_count("pullRequestContributionsByRepository", "totalRepositoriesWithContributedPullRequests"),
        "public_issues": public_count("issueContributionsByRepository", "totalRepositoriesWithContributedIssues"),
        "public_reviews": public_count("pullRequestReviewContributionsByRepository", "totalRepositoriesWithContributedPullRequestReviews"),
        # Restricted means inaccessible to this token, not necessarily every private contribution.
        "published_private": private if private else None,
    }


def contributions(username: str, now: datetime, token: str) -> dict:
    if not token:
        raise ValueError("Contribution stats await the workflow's built-in GITHUB_TOKEN; no guessed totals")
    document = json.loads(fetch("https://api.github.com/graphql", token=token,
                                payload={"query": QUERY, "variables": contribution_variables(username, now)}))
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

    def handle_data(self, text):
        self.all.append(text)
        if self.target:
            self.label.append(text)

    def handle_endtag(self, tag):
        if tag == "tool-tip" and self.target:
            label = " ".join("".join(self.label).split())
            if re.match(r"No contributions? on ", label, re.I):
                self.counts[self.target] = 0
            else:
                match = re.match(r"([\d,]+) contributions? on ", label, re.I)
                if match:
                    self.counts[self.target] = int(match[1].replace(",", ""))
            self.target = None


def normalize_calendar(content: bytes, today: date) -> dict:
    parser = CalendarHTML()
    parser.feed(content.decode())
    start = today - timedelta(days=364)
    days = {}
    for cell_id, value in parser.cells.items():
        d = date.fromisoformat(value)
        if start <= d <= today and cell_id in parser.counts:
            days[value] = nonnegative(parser.counts[cell_id])
    expected = {(start + timedelta(days=i)).isoformat() for i in range(365)}
    if set(days) != expected:
        raise ValueError("Incomplete public contribution calendar; refusing to fill missing days with zero")
    heading = re.search(r"([\d,]+) contributions? in ", " ".join(" ".join(parser.all).split()), re.I)
    if not heading:
        raise ValueError("Public contribution calendar has no recognizable total")
    source_total = int(heading[1].replace(",", ""))
    if set(parser.cells) - set(parser.counts) or sum(parser.counts[i] for i in parser.cells) != source_total:
        raise ValueError("Public calendar total disagrees with its daily counts")
    # GitHub rounds its visible grid to weeks. Our clearly labeled 365-day card
    # excludes any extra leading dates instead of borrowing the grid's headline.
    return {"as_of": today.isoformat(), "calendar_start": start.isoformat(),
            "calendar_end": today.isoformat(), "calendar_total": sum(days.values()),
            "source_calendar_total": source_total, "days": dict(sorted(days.items()))}


def public_calendar(username: str, today: date) -> dict:
    # No token: respect public privacy settings, even in a private preview repo.
    # GitHub's from/to URL parameters select calendar years, not arbitrary windows;
    # fetch the rolling grid and select the exact dates locally instead.
    return normalize_calendar(fetch(f"https://github.com/users/{quote(username, safe='')}/contributions"), today)


def activity(username: str, today: date, token: str = "") -> dict:
    result = []
    for kind in ("pr", "issue"):
        # Explicit public filter even if someone later supplies a more privileged token.
        query = urlencode({"q": f"author:{username} is:{kind} is:open is:public", "sort": "updated", "order": "desc", "per_page": 100})
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
            result.append({"kind": kind, "title": item["title"], "url": item["html_url"],
                           "repository": "/".join(parts[:2]), "number": item["number"],
                           "updated_at": item["updated_at"]})
    result.sort(key=lambda item: item["updated_at"], reverse=True)
    return {"as_of": today.isoformat(), "items": result[:12]}


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

    def handle_data(self, text):
        if not self.ignore:
            self.all.append(text)
            if self.current is not None:
                self.current.append(text)


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
        parser.feed(item.findtext("description") or item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or "")
        paragraph = next(iter(parser.paragraphs), " ".join("".join(parser.all).split()))
        # A contiguous first-sentence excerpt, never a paraphrase or generated summary.
        sentence = re.match(r"^(.+?[.!?])(?=\s|$)", paragraph, re.S)
        excerpt = sentence.group(1) if sentence else paragraph
        if not excerpt:
            raise ValueError("RSS item has no usable excerpt")
        result.append({"title": title, "url": link, "published": published.isoformat(), "excerpt": excerpt})
    if not result:
        raise ValueError("RSS feed is empty; refusing to erase the previous posts")
    result.sort(key=lambda post: datetime.fromisoformat(post["published"]), reverse=True)
    return result


def posts(feed_url: str, today: date) -> dict:
    return {"as_of": today.isoformat(), "items": parse_posts(fetch(feed_url), feed_url)}
