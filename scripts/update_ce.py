#!/usr/bin/env python3
"""Daily discovery of Cisco CE / Rev Up posts from official Cisco sources."""
import datetime as dt
import json
import re
import sys
import urllib.parse
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE = "https://learningnetwork.cisco.com/s/topic/0TO6e000002e4QmGAI/rev-up-to-recert-community"

# Cisco Learning Network topic is Salesforce/JS-rendered and cannot be reliably
# scraped without a browser session. Cisco Blogs RSS feeds are the primary
# machine-readable source; Google News is only a fallback/discovery supplement.
CISCO_BLOG_FEEDS = [
    "https://blogs.cisco.com/tag/cisco-u/feed",
    "https://blogs.cisco.com/tag/cisco-certifications/feed",
    "https://blogs.cisco.com/tag/cisco-learning-network/feed",
]
QUERIES = [
    'site:learningnetwork.cisco.com/s/question/ "Rev Up to Recert"',
    'site:learningnetwork.cisco.com/s/blogs/ "Rev Up to Recert"',
    'site:blogs.cisco.com/learning/ "Rev Up to Recert"',
    'site:blogs.cisco.com/learning/ "Continuing Education" "CE credits"',
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CiscoCEWatch/2.0; +https://github.com/etech-symantec/ce)"
}
TIMEOUT = 18

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def canonical(url):
    u = urllib.parse.urlsplit(url)
    scheme = u.scheme.lower() or "https"
    return urllib.parse.urlunsplit((scheme, u.netloc.lower(), u.path.rstrip("/"), "", ""))

def host_allowed(url):
    h = urllib.parse.urlsplit(url).hostname or ""
    return h in ("learningnetwork.cisco.com", "blogs.cisco.com")

def date_from_entry(e):
    for prop in ("published_parsed", "updated_parsed", "created_parsed"):
        v = e.get(prop)
        if v:
            return dt.date(v.tm_year, v.tm_mon, v.tm_mday)
    return None

def clean_text(value):
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)

def is_relevant(title, body):
    text = f"{title} {body}"
    has_revup = bool(re.search(r"\brev\s*up\b|rev\s*up\s*to\s*recert", text, re.I))
    has_ce = bool(re.search(
        r"continuing\s+education|\bCE\s+(?:credits?|credit)\b|\b\d+\s*CE\b",
        text,
        re.I,
    ))
    # Strong signal: Rev Up + CE in title/body. Also accept titles explicitly
    # announcing Rev Up even when the feed excerpt omits the credit wording.
    return (has_revup and has_ce) or bool(re.search(r"rev\s*up\s*to\s*recert", title, re.I))

def article_text(session, url):
    try:
        res = session.get(url, timeout=TIMEOUT)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        article = soup.find("article") or soup.find("main") or soup
        return article.get_text(" ", strip=True)[:120000]
    except requests.RequestException:
        return ""

def cisco_blog_candidates(session, cutoff):
    posts = {}
    succeeded = 0
    failures = []
    seen_urls = set()

    for feed_url in CISCO_BLOG_FEEDS:
        try:
            res = session.get(feed_url, timeout=TIMEOUT)
            res.raise_for_status()
            feed = feedparser.parse(res.content)
            if feed.bozo and not feed.entries:
                raise ValueError(str(feed.bozo_exception))
            succeeded += 1

            for e in feed.entries:
                url = canonical(e.get("link", ""))
                if not url or url in seen_urls or not host_allowed(url):
                    continue
                seen_urls.add(url)

                published = date_from_entry(e)
                if published is None or published < cutoff:
                    continue

                title = clean_text(e.get("title", ""))[:240]
                excerpt = clean_text(e.get("summary", "") or e.get("description", ""))
                body = excerpt
                if not is_relevant(title, body):
                    body = article_text(session, url)
                if not is_relevant(title, body):
                    continue

                posts[url] = {
                    "title": title,
                    "url": url,
                    "published": published.isoformat(),
                    "source": "Cisco Blogs RSS (공식)",
                    "verification": "Cisco 공식 글 · CE/Rev Up 관련",
                }
        except (requests.RequestException, ValueError) as exc:
            failures.append(f"Cisco Blogs RSS failed ({feed_url}): {type(exc).__name__}: {exc}")

    return posts, succeeded, failures

def google_news_candidates(session, cutoff):
    posts = {}
    succeeded = 0
    failures = []
    for query in QUERIES:
        rss = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
            "q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"
        })
        try:
            res = session.get(rss, timeout=TIMEOUT)
            res.raise_for_status()
            feed = feedparser.parse(res.content)
            if feed.bozo and not feed.entries:
                raise ValueError(str(feed.bozo_exception))
            succeeded += 1
            for e in feed.entries:
                published = date_from_entry(e)
                if published is None or published < cutoff:
                    continue
                title = clean_text(e.get("title", ""))
                if not re.search(r"rev\s*up|continuing education|\bCE credits?\b", title, re.I):
                    continue
                snippet = BeautifulSoup(e.get("summary", ""), "html.parser")
                links = [a.get("href", "") for a in snippet.find_all("a", href=True)]
                direct = next((x for x in links if host_allowed(x)), "")
                if not direct:
                    continue
                u = canonical(direct)
                posts[u] = {
                    "title": title[:240],
                    "url": u,
                    "published": published.isoformat(),
                    "source": "Google News 검색 (Cisco 링크)",
                    "verification": "검색 발견 · 상세 확인 필요",
                }
        except (requests.RequestException, ValueError) as exc:
            failures.append(f"Google News RSS query failed: {type(exc).__name__}: {exc}")
    return posts, succeeded, failures

def topic_check(session):
    try:
        res = session.get(SOURCE, timeout=TIMEOUT)
        res.raise_for_status()
        txt = BeautifulSoup(res.text, "html.parser").get_text(" ", strip=True)
        if len(txt) < 150 or ("Loading" in txt[:100] and len(txt) < 500):
            return "동적 로딩/접근 제한 (Cisco Blogs 공식 피드로 보완)"
        return "페이지 응답 확인 (전체 게시글 수집 여부 별도 검증 필요)"
    except requests.RequestException as exc:
        return f"접속 실패 ({type(exc).__name__})"

def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    cutoff = today - dt.timedelta(days=183)
    session = requests.Session()
    session.headers.update(HEADERS)

    older = load(DATA / "posts.json", [])
    saved = {
        canonical(p["url"]): p
        for p in older
        if isinstance(p, dict)
        and host_allowed(p.get("url", ""))
        and p.get("published", "") >= cutoff.isoformat()
    }

    official, official_ok, official_errors = cisco_blog_candidates(session, cutoff)
    fallback, google_ok, google_errors = google_news_candidates(session, cutoff)

    # Official Cisco Blogs data wins when the same URL appears in both sources.
    discovered = dict(fallback)
    discovered.update(official)

    old_urls = {
        canonical(p["url"])
        for p in older
        if isinstance(p, dict) and p.get("url")
    }
    saved.update(discovered)
    posts = sorted(saved.values(), key=lambda x: (x["published"], x["title"]), reverse=True)

    status = {
        "checked_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "window_start": cutoff.isoformat(),
        "window_end": today.isoformat(),
        "topic_url": SOURCE,
        "topic_access": topic_check(session),
        "discovery": "Cisco Blogs 공식 RSS 직접 수집 + Google News RSS 보조 발견.",
        "official_feeds_succeeded": official_ok,
        "official_feeds_total": len(CISCO_BLOG_FEEDS),
        "rss_queries_succeeded": google_ok,
        "rss_queries_total": len(QUERIES),
        "new_candidates": len(set(discovered) - old_urls),
        "candidate_count": len(posts),
        "errors": official_errors + google_errors,
        "course_update": "검증된 무료 CE 과정은 data/courses.json에 별도 관리",
    }

    DATA.mkdir(exist_ok=True)
    (DATA / "posts.json").write_text(
        json.dumps(posts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (DATA / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
