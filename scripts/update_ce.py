#!/usr/bin/env python3
"""Daily discovery of Cisco CE posts. Candidate posts are NOT verified CE courses."""
import datetime as dt
import json
import os
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
QUERIES = [
    'site:learningnetwork.cisco.com/s/question/ "Rev Up to Recert"',
    'site:learningnetwork.cisco.com/s/blogs/ "Rev Up to Recert"',
    'site:blogs.cisco.com/learning/ "Rev Up to Recert"',
]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CiscoCEWatch/1.0; +https://github.com/)"}
TIMEOUT = 18

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def canonical(url):
    u = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((u.scheme, u.netloc.lower(), u.path.rstrip('/'), '', ''))

def host_allowed(url):
    h = urllib.parse.urlsplit(url).hostname or ''
    return h in ('learningnetwork.cisco.com', 'blogs.cisco.com')

def date_from_entry(e):
    for prop in ('published_parsed', 'updated_parsed'):
        v = e.get(prop)
        if v:
            return dt.date(v.tm_year, v.tm_mon, v.tm_mday)
    return None

def google_news_candidates(session, cutoff):
    posts = {}
    succeeded = 0
    failures = []
    for query in QUERIES:
        rss = 'https://news.google.com/rss/search?' + urllib.parse.urlencode({'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})
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
                title = BeautifulSoup(e.get('title', ''), 'html.parser').get_text(' ', strip=True)
                if not re.search(r'rev\s*up\s*to\s*recert|continuing education|\bCE credits\b', title, re.I):
                    continue
                # Google News RSS links are Google redirects and not direct Cisco permalinks.
                # Never publish the redirect as if it were a verified Cisco post.
                snippet = BeautifulSoup(e.get('summary', ''), 'html.parser')
                links = [a.get('href', '') for a in snippet.find_all('a', href=True)]
                direct = next((x for x in links if host_allowed(x)), '')
                if not direct:
                    continue
                u = canonical(direct)
                posts[u] = {'title': title[:240], 'url': u, 'published': published.isoformat(), 'source': 'Google News 검색 (Cisco 링크)', 'verification': '검색 발견 · 상세 확인 필요'}
        except (requests.RequestException, ValueError) as exc:
            failures.append(f'RSS query failed: {type(exc).__name__}: {exc}')
    return posts, succeeded, failures

def topic_check(session):
    try:
        res = session.get(SOURCE, timeout=TIMEOUT)
        res.raise_for_status()
        txt = BeautifulSoup(res.text, 'html.parser').get_text(' ', strip=True)
        if len(txt) < 150 or ('Loading' in txt[:100] and len(txt) < 500):
            return '동적 로딩/접근 제한 (전체 게시글 목록 미확인)'
        return '페이지 응답 확인 (전체 게시글 수집 여부 별도 검증 필요)'
    except requests.RequestException as exc:
        return f'접속 실패 ({type(exc).__name__})'

def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    cutoff = today - dt.timedelta(days=183)
    session = requests.Session()
    session.headers.update(HEADERS)
    older = load(DATA / 'posts.json', [])
    saved = {canonical(p['url']): p for p in older if isinstance(p, dict) and host_allowed(p.get('url','')) and p.get('published','') >= cutoff.isoformat()}
    discovered, succeeded, failures = google_news_candidates(session, cutoff)
    saved.update(discovered)
    posts = sorted(saved.values(), key=lambda x: (x['published'], x['title']), reverse=True)
    status = {
        'checked_at': dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        'window_start': cutoff.isoformat(), 'window_end': today.isoformat(),
        'topic_url': SOURCE, 'topic_access': topic_check(session),
        'discovery': 'Google News RSS를 통한 보조 발견. 전체 글 목록 보장 안 됨.',
        'rss_queries_succeeded': succeeded, 'rss_queries_total': len(QUERIES),
        'new_candidates': len(set(discovered)-set(canonical(p['url']) for p in older if isinstance(p,dict) and p.get('url'))),
        'candidate_count': len(posts), 'errors': failures,
        'course_update': 'CE 과정은 별도 검증된 data/courses.json만 표시하며 자동으로 확정하지 않음'
    }
    DATA.mkdir(exist_ok=True)
    (DATA / 'posts.json').write_text(json.dumps(posts, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (DATA / 'status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(status, ensure_ascii=False, indent=2))
    # Do not let a transient search failure delete previously discovered posts.
    # Workflow succeeds but leaves an explicit health warning when all RSS sources fail.
    return 0

if __name__ == '__main__':
    sys.exit(main())
