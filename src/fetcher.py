"""
Fetches news from RSS feeds, Hacker News, and Reddit in parallel.
Returns a normalized list of stories: {title, url, source, category, published, summary}

Freshness: discards items older than MAX_AGE_DAYS. Some feeds (especially full-site
RSS from The Wire, Scroll, etc.) include older items that we want to filter out.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx

from .sources import RSS_FEEDS, HN_TOP_STORIES, REDDIT_FEEDS

logger = logging.getLogger(__name__)

# Reddit blocks default user-agents; identify properly.
HEADERS = {"User-Agent": "news-hook-bot/1.0 (personal content research)"}
TIMEOUT = httpx.Timeout(15.0, connect=10.0)

# Discard items older than this. 4 days handles weekend gaps + late-published items
# while filtering out archive content from full-site RSS feeds.
MAX_AGE_DAYS = 4


def _parse_pub_date(raw: str) -> datetime | None:
    """Parse a published-date string from any reasonable RSS/Atom format.

    Returns timezone-aware datetime, or None if unparseable.
    Common formats handled:
      - 'Mon, 19 May 2025 12:30:00 +0000'  (RFC 822, most RSS)
      - '2025-05-19T12:30:00Z'             (ISO 8601, Atom)
      - '2025-05-19T12:30:00+00:00'
    """
    if not raw:
        return None
    raw = raw.strip()
    # Try RFC 822 first (most RSS feeds)
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        pass
    # Try ISO 8601
    try:
        # Python <3.11 doesn't handle 'Z' suffix in fromisoformat
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        pass
    return None


def _is_fresh(published_raw: str, max_age_days: int = MAX_AGE_DAYS) -> bool:
    """Return True if the item is recent enough OR if we can't parse the date.

    Falls back to True for unparseable dates so we don't accidentally filter
    out feeds that use weird date formats — better to over-include than to
    silently drop a whole source.
    """
    dt = _parse_pub_date(published_raw)
    if dt is None:
        return True   # benefit of the doubt
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    return dt >= cutoff


def _normalize(title: str, url: str, source: str, category: str,
               published: str | None = None, summary: str = "") -> dict[str, Any]:
    return {
        "title": (title or "").strip(),
        "url": url,
        "source": source,
        "category": category,
        "published": published or datetime.now(timezone.utc).isoformat(),
        "summary": (summary or "").strip()[:600],   # cap summary size
    }


async def _fetch_rss(client: httpx.AsyncClient, feed: dict) -> list[dict]:
    try:
        r = await client.get(feed["url"], headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        parsed = feedparser.parse(r.text)
        out = []
        dropped_stale = 0
        for entry in parsed.entries[:30]:   # widened from 20 to compensate for stale-filtering
            pub_raw = entry.get("published", "") or entry.get("updated", "")
            if not _is_fresh(pub_raw):
                dropped_stale += 1
                continue
            out.append(_normalize(
                title=entry.get("title", ""),
                url=entry.get("link", ""),
                source=feed["name"],
                category=feed["category"],
                published=pub_raw,
                summary=entry.get("summary", "") or entry.get("description", ""),
            ))
        if dropped_stale:
            logger.info("RSS %s: %d items (dropped %d stale, >%dd old)",
                        feed["name"], len(out), dropped_stale, MAX_AGE_DAYS)
        else:
            logger.info("RSS %s: %d items", feed["name"], len(out))
        return out
    except Exception as e:
        logger.warning("RSS %s failed: %s", feed["name"], e)
        return []


async def _fetch_hn(client: httpx.AsyncClient) -> list[dict]:
    try:
        r = await client.get(HN_TOP_STORIES, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        out = []
        for hit in data.get("hits", []):
            pub_raw = hit.get("created_at", "")
            if not _is_fresh(pub_raw):
                continue
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            out.append(_normalize(
                title=hit.get("title", ""),
                url=url,
                source="Hacker News",
                category="deep_tech",
                published=pub_raw,
                summary=f"HN points: {hit.get('points', 0)}, comments: {hit.get('num_comments', 0)}",
            ))
        logger.info("HN: %d items", len(out))
        return out
    except Exception as e:
        logger.warning("HN failed: %s", e)
        return []


async def _fetch_reddit(client: httpx.AsyncClient, feed: dict) -> list[dict]:
    try:
        r = await client.get(feed["url"], headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        out = []
        for post in data.get("data", {}).get("children", []):
            p = post.get("data", {})
            if p.get("stickied"):    # skip pinned mod posts
                continue
            url = p.get("url_overridden_by_dest") or f"https://reddit.com{p.get('permalink', '')}"
            out.append(_normalize(
                title=p.get("title", ""),
                url=url,
                source=feed["name"],
                category="platform",
                summary=f"Reddit score: {p.get('score', 0)}, comments: {p.get('num_comments', 0)}. {p.get('selftext', '')[:300]}",
            ))
        logger.info("Reddit %s: %d items", feed["name"], len(out))
        return out
    except Exception as e:
        logger.warning("Reddit %s failed: %s", feed["name"], e)
        return []


async def fetch_all() -> list[dict]:
    """Fetch from every configured source concurrently."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = []
        tasks.extend(_fetch_rss(client, f) for f in RSS_FEEDS)
        tasks.append(_fetch_hn(client))
        tasks.extend(_fetch_reddit(client, f) for f in REDDIT_FEEDS)

        results = await asyncio.gather(*tasks, return_exceptions=True)

    stories: list[dict] = []
    for r in results:
        if isinstance(r, list):
            stories.extend(r)
    # drop empties
    stories = [s for s in stories if s["title"] and s["url"]]
    logger.info("Total stories fetched: %d", len(stories))
    return stories