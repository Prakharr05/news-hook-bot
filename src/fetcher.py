"""
Fetches news from RSS feeds, Hacker News, and Reddit in parallel.
Returns a normalized list of stories: {title, url, source, category, published, summary}
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx

from .sources import RSS_FEEDS, HN_TOP_STORIES, REDDIT_FEEDS

logger = logging.getLogger(__name__)

# Reddit blocks default user-agents; identify properly.
HEADERS = {"User-Agent": "news-hook-bot/1.0 (personal content research)"}
TIMEOUT = httpx.Timeout(15.0, connect=10.0)


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
        for entry in parsed.entries[:20]:
            out.append(_normalize(
                title=entry.get("title", ""),
                url=entry.get("link", ""),
                source=feed["name"],
                category=feed["category"],
                published=entry.get("published", ""),
                summary=entry.get("summary", "") or entry.get("description", ""),
            ))
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
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            out.append(_normalize(
                title=hit.get("title", ""),
                url=url,
                source="Hacker News",
                category="deep_tech",
                published=hit.get("created_at", ""),
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
