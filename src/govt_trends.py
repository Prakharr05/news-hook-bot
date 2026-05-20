"""
Government / political trending-news detector.

Separate from the tech pipeline. Scrapes general Indian news sources, then detects
what's TRENDING via cross-source volume: a topic covered by many outlets in a short
window is hot; a topic in one outlet is not.

Top 8 = trending (ranked by how many distinct sources cover the topic cluster).
/govtmore pool = the rest, ranked by recency.

Flow:
  fetch_govt_stories()  -> raw list from all GOVT_SOURCES
  cluster_by_entities() -> group stories sharing key entities (Modi, Congress, etc.)
  rank_trending()       -> score clusters by source-diversity, return top 8 + more pool
"""
from __future__ import annotations
import asyncio
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import feedparser
import httpx

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "news-hook-bot/1.0 (personal content research)"}
TIMEOUT = httpx.Timeout(15.0, connect=10.0)
MAX_AGE_HOURS = 36   # govt news moves fast; only consider last 36h for trending

# ─── GENERAL INDIAN NEWS SOURCES ───
# Mix of national dailies + wires. Politics/governance/policy/state news.
# Some will 403 or break; the pipeline tolerates dead feeds.
GOVT_SOURCES = [
    {"name": "NDTV India",        "url": "https://feeds.feedburner.com/ndtvnews-india-news"},
    {"name": "NDTV Top",          "url": "https://feeds.feedburner.com/ndtvnews-top-stories"},
    {"name": "Indian Express",    "url": "https://indianexpress.com/feed/"},
    {"name": "IE India",          "url": "https://indianexpress.com/section/india/feed/"},
    {"name": "IE Politics",       "url": "https://indianexpress.com/section/political-pulse/feed/"},
    {"name": "Hindustan Times",   "url": "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml"},
    {"name": "The Hindu Nat'l",   "url": "https://www.thehindu.com/news/national/feeder/default.rss"},
    {"name": "News18 India",      "url": "https://www.news18.com/rss/india.xml"},
    {"name": "News18 Politics",   "url": "https://www.news18.com/rss/politics.xml"},
    {"name": "Scroll.in",         "url": "https://scroll.in/feeds/all.rss"},
    {"name": "The Wire",          "url": "https://thewire.in/rss"},
    {"name": "The Quint",         "url": "https://www.thequint.com/stories.rss"},
    {"name": "Firstpost India",   "url": "https://www.firstpost.com/rss/india.xml"},
    {"name": "Free Press Jrnl",   "url": "https://www.freepressjournal.in/stories.rss"},
    {"name": "Live Law",          "url": "https://www.livelaw.in/rss/top-stories"},
    {"name": "The News Minute",   "url": "https://www.thenewsminute.com/feeds/rss"},
    {"name": "Deccan Herald",     "url": "https://www.deccanherald.com/rss/national.rss"},
    {"name": "Outlook India",     "url": "https://www.outlookindia.com/rss/main/magazine"},
]

# Stopwords for entity extraction — common capitalized words that aren't entities
_STOPWORDS = {
    "The", "A", "An", "In", "On", "At", "Of", "For", "To", "And", "But", "Or",
    "India", "Indian", "News", "Latest", "Breaking", "Update", "Updates", "Report",
    "Says", "Said", "After", "Before", "During", "Over", "Under", "How", "Why",
    "What", "When", "Where", "Who", "New", "Big", "Top", "Live", "Watch", "Video",
    "Day", "Year", "Today", "Week", "Month", "Government", "Minister", "Govt",
    "Here", "This", "That", "These", "Those", "Will", "Can", "May", "Must",
}


def _parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except (TypeError, ValueError):
        pass
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except (TypeError, ValueError):
        return None


def _is_recent(raw: str, max_hours: int = MAX_AGE_HOURS) -> bool:
    dt = _parse_date(raw)
    if dt is None:
        return True   # benefit of the doubt
    return dt >= datetime.now(timezone.utc) - timedelta(hours=max_hours)


def _extract_entities(title: str) -> set[str]:
    """Pull proper-noun entities from a headline.

    Simple heuristic: capitalized words/phrases not in stopwords. Good enough for
    clustering — we mainly need to know two headlines are about the same thing.
    """
    # Find sequences of Capitalized Words (e.g., "Narendra Modi", "Supreme Court")
    phrases = re.findall(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\b", title)
    entities = set()
    for phrase in phrases:
        words = [w for w in phrase.split() if w not in _STOPWORDS and len(w) > 2]
        # Add the full multi-word phrase (e.g. "Narendra Modi")
        if len(words) >= 2:
            entities.add(" ".join(words).lower())
        # Also add individual significant words (e.g. "Modi", "Norway")
        for w in words:
            entities.add(w.lower())
    return entities


async def _fetch_one(client: httpx.AsyncClient, src: dict) -> list[dict]:
    try:
        r = await client.get(src["url"], headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        parsed = feedparser.parse(r.text)
        out = []
        for entry in parsed.entries[:25]:
            pub = entry.get("published", "") or entry.get("updated", "")
            if not _is_recent(pub):
                continue
            title = (entry.get("title", "") or "").strip()
            if not title:
                continue
            out.append({
                "title": title,
                "url": entry.get("link", ""),
                "source": src["name"],
                "published": pub,
                "summary": (entry.get("summary", "") or entry.get("description", ""))[:400],
                "entities": _extract_entities(title),
            })
        logger.info("GOVT %s: %d recent items", src["name"], len(out))
        return out
    except Exception as e:
        logger.warning("GOVT %s failed: %s", src["name"], e)
        return []


async def fetch_govt_stories() -> list[dict]:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = [_fetch_one(client, s) for s in GOVT_SOURCES]
        results = await asyncio.gather(*tasks)
    stories = [s for batch in results for s in batch]
    logger.info("GOVT total fetched: %d stories", len(stories))
    return stories


def cluster_by_entities(stories: list[dict]) -> list[dict]:
    """Group stories that share significant entities into trending clusters.

    Returns a list of clusters, each: {
      headline, entities, sources (set), source_count, stories (list), latest_pub
    }
    A story joins an existing cluster if it shares >=2 entities (or 1 strong multi-word
    entity) with that cluster. Otherwise it starts a new cluster.
    """
    clusters: list[dict] = []

    # Sort by number of entities desc so richer headlines seed clusters first
    stories_sorted = sorted(stories, key=lambda s: len(s["entities"]), reverse=True)

    for s in stories_sorted:
        ents = s["entities"]
        if not ents:
            continue
        best_cluster = None
        best_overlap = 0
        for c in clusters:
            overlap = ents & c["entities"]
            # Multi-word entity match (e.g. "narendra modi") counts double
            strong = any(" " in e for e in overlap)
            score = len(overlap) + (2 if strong else 0)
            if score > best_overlap and (len(overlap) >= 2 or strong):
                best_overlap = score
                best_cluster = c
        if best_cluster:
            best_cluster["stories"].append(s)
            best_cluster["entities"] |= ents
            best_cluster["sources"].add(s["source"])
        else:
            clusters.append({
                "headline": s["title"],   # representative headline = first/richest
                "entities": set(ents),
                "sources": {s["source"]},
                "stories": [s],
            })

    # Finalize: compute source_count + latest publish time + best URL
    for c in clusters:
        c["source_count"] = len(c["sources"])
        # Representative story = the one from the most "national" source, else first
        c["story_count"] = len(c["stories"])
        # Pick the most recent story's URL as the canonical link
        def pub_key(st):
            d = _parse_date(st.get("published", ""))
            return d or datetime.min.replace(tzinfo=timezone.utc)
        rep = max(c["stories"], key=pub_key)
        c["url"] = rep["url"]
        c["headline"] = rep["title"]
        c["summary"] = rep.get("summary", "")
        c["latest_pub"] = rep.get("published", "")
    return clusters


def rank_trending(stories: list[dict], top_n: int = 8, more_n: int = 50) -> tuple[list[dict], list[dict]]:
    """Return (trending_top, more_pool).

    trending_top: clusters ranked by source_count (cross-source volume = trending),
                  tie-broken by story_count then recency. These are the genuinely hot topics.
    more_pool:    individual stories NOT in the top clusters, ranked by recency.
    """
    clusters = cluster_by_entities(stories)

    # Trending = covered by multiple sources. Sort by source diversity primarily.
    def cluster_rank(c):
        d = _parse_date(c.get("latest_pub", ""))
        recency = d.timestamp() if d else 0
        return (c["source_count"], c["story_count"], recency)

    clusters.sort(key=cluster_rank, reverse=True)

    # Top trending clusters become the digest
    trending_top = clusters[:top_n]

    # More pool: all stories whose URL isn't already represented in the top clusters,
    # ranked by recency.
    top_urls = {c["url"] for c in trending_top}
    leftover = [s for s in stories if s["url"] not in top_urls]

    def story_recency(s):
        d = _parse_date(s.get("published", ""))
        return d.timestamp() if d else 0

    leftover.sort(key=story_recency, reverse=True)
    more_pool = [
        {
            "title": s["title"],
            "url": s["url"],
            "source": s["source"],
            "published": s.get("published", ""),
        }
        for s in leftover[:more_n]
    ]

    return trending_top, more_pool