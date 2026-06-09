"""
AI-creator-profile scraper.

Pipeline:
  1. fetch_ai_stories() - parallel async fetch from AI-focused sources
  2. score_with_profile() - score against the creator's taste profile JSON
  3. rank_for_creator() - return top N + more pool

The profile is loaded from profiles/ai_creator_profile.json. To re-tune:
edit the JSON, no code change needed.

Outputs are kept SEPARATE from the existing tech bot (different Upstash keys)
so the agency creator's daily digest is unaffected.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import httpx

from .ai_sources import AI_RSS_FEEDS, HN_AI_API

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "news-hook-bot/1.0 (AI-creator-profile scraper)"}
TIMEOUT = httpx.Timeout(15.0, connect=10.0)
MAX_AGE_HOURS = 30   # AI news moves fast; only consider last 30h

PROFILE_PATH = Path(__file__).parent.parent / "profiles" / "ai_creator_profile.json"


def load_profile() -> dict:
    """Load the AI creator's taste profile."""
    return json.loads(PROFILE_PATH.read_text())


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
        return True
    return dt >= datetime.now(timezone.utc) - timedelta(hours=max_hours)


async def _fetch_rss(client: httpx.AsyncClient, feed: dict) -> list[dict]:
    try:
        r = await client.get(feed["url"], headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        parsed = feedparser.parse(r.text)
        out = []
        dropped = 0
        for entry in parsed.entries[:30]:
            pub = entry.get("published", "") or entry.get("updated", "")
            if not _is_recent(pub):
                dropped += 1
                continue
            title = (entry.get("title", "") or "").strip()
            if not title:
                continue
            out.append({
                "title": title,
                "url": entry.get("link", ""),
                "source": feed["name"],
                "category": feed["category"],
                "published": pub,
                "summary": (entry.get("summary", "") or entry.get("description", ""))[:500],
            })
        if dropped:
            logger.info("AI %s: %d items (%d stale)", feed["name"], len(out), dropped)
        else:
            logger.info("AI %s: %d items", feed["name"], len(out))
        return out
    except Exception as e:
        logger.warning("AI %s failed: %s", feed["name"], e)
        return []


async def _fetch_hn(client: httpx.AsyncClient) -> list[dict]:
    try:
        r = await client.get(HN_AI_API, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        out = []
        for hit in r.json().get("hits", []):
            pub = hit.get("created_at", "")
            if not _is_recent(pub):
                continue
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            out.append({
                "title": hit.get("title", ""),
                "url": url,
                "source": "Hacker News (AI)",
                "category": "ai_news",
                "published": pub,
                "summary": f"HN points: {hit.get('points', 0)}, comments: {hit.get('num_comments', 0)}",
            })
        logger.info("HN AI: %d items", len(out))
        return out
    except Exception as e:
        logger.warning("HN AI failed: %s", e)
        return []


async def fetch_ai_stories() -> list[dict]:
    """Fetch from all AI-focused sources in parallel."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = [_fetch_rss(client, s) for s in AI_RSS_FEEDS]
        tasks.append(_fetch_hn(client))
        results = await asyncio.gather(*tasks)
    stories = [s for batch in results for s in batch]
    # Dedupe by URL
    seen = set()
    unique = []
    for s in stories:
        if s["url"] and s["url"] not in seen:
            seen.add(s["url"])
            unique.append(s)
    logger.info("AI total fetched: %d unique stories", len(unique))
    return unique


# ─── PROFILE-BASED SCORING ──────────────────────────────────────────────────

def _has(text: str, phrases: list[str]) -> bool:
    """Word-boundary aware substring check.

    Multi-word phrases match as substring. Single short words ('repo', 'agent') match
    with word boundaries so 'report' doesn't trigger 'repo'.
    """
    for p in phrases:
        if " " in p or "-" in p:
            if p in text:
                return True
        else:
            # word-boundary regex for single words
            if re.search(r"\b" + re.escape(p) + r"\b", text):
                return True
    return False


def _detect_topic(text_lower: str) -> str | None:
    """Categorize a story into one of the creator's topic buckets.

    Returns the topic key (matches ai_categories_boost in the profile) or None.
    Word-boundary matching prevents 'report' from triggering 'repo'.
    """
    # Order matters: more specific patterns first.

    # Business move: partnerships, acquisitions, layoffs, leadership shifts among
    # AI companies. This is the "Apple Siri × Gemini" shape — concrete corporate news.
    if _has(text_lower, [
        "partners with", "partnership with", "partnering with", "partnering up",
        "teams up with", "team up with", "joins forces", "deal with",
        "integrates with", "integration with",
        "acquires", "acquired", "to acquire", "acquisition",
        "layoffs", "laid off", "fires", "fired", "cuts jobs", "job cuts",
        "ipo", "files for ipo", "going public", "stock market",
        "ceo steps down", "ceo resigns", "ceo joins", "hired as ceo",
        "valuation hits", "valued at", "deal worth",
        "files antitrust", "settles with", "merger",
    ]):
        return "business_move"

    if _has(text_lower, [
        "repo", "github stars", "open-source", "open source",
        "now open source", "released on github", "stars on github",
    ]):
        return "dev_tool_repo"

    if _has(text_lower, [
        "benchmark", "benchmarks", "outperforms", "beats gpt", "beats claude",
        "swe bench", "leaderboard", "state of the art", "sota",
    ]):
        return "benchmark_comparison"

    if _has(text_lower, [
        "launches", "launched", "unveiled", "announces", "releases", "released",
        "introduces", "introducing", "drops new", "new model", "ships",
        "available now", "rolling out",
    ]):
        return "model_launch"

    if _has(text_lower, [
        "how to use", "tutorial", "step-by-step", "step by step",
        "guide to", "build with", "workflow", "how i built",
    ]):
        return "tutorial_workflow"

    if _has(text_lower, [
        "agent", "agentic", "agents", "multi-agent", "autonomous",
    ]):
        return "agentic_application"

    if _has(text_lower, ["consumer", "device", "gadget"]):
        if _has(text_lower, ["ai", "llm", "artificial intelligence"]):
            return "consumer_ai_product"

    if _has(text_lower, [
        "raised", "funding round", "series a", "series b", "series c", "valuation",
    ]):
        return "funding_with_product"

    return None


# Headline shapes we want to PENALIZE (newsletter analyses, vague upcoming things)
_ANALYSIS_PATTERNS = [
    r"^frontier radar",
    r"#\d+\b",                          # newsletter issue numbers
    r"\b(matters more|more than scale)\b",
    r"\bproves (that|how|why)\b",
    r"\bhow .* is (turning|changing|reshaping|disrupting)\b",
    r"\bpreps (overhaul|launch|update)\b",
    r"\bcould (change|disrupt|transform)\b.*\bif\b",
    r"\b(uncanny valley|the curve|the moment)\b",
    r"\b(deep dive|weekly digest|monthly roundup)\b",
    r"\bwhy .* matters\b",
]


def _is_analysis_shape(text_lower: str) -> bool:
    """Detect newsletter / analysis / vague-future headlines that Prakhar skipped."""
    for p in _ANALYSIS_PATTERNS:
        if re.search(p, text_lower):
            return True
    return False



def score_with_profile(stories: list[dict], profile: dict | None = None) -> list[dict]:
    """Score each story against the creator's taste profile.

    Adds: hook_score, topic, profile_signals (debug), is_excluded
    """
    profile = profile or load_profile()
    cats = profile["ai_categories_boost"]
    companies = profile["ai_companies_he_covers"]
    vocab = profile["vocabulary_signals_positive"]
    exclusions = set(profile["hard_exclusions"])
    soft_neg = profile["soft_negative_signals"]

    for s in stories:
        text = (s["title"] + " " + s["summary"]).lower()
        signals: dict[str, int] = {}

        # 1. Hard exclusion check
        is_excluded = any(excl in text for excl in exclusions)
        if is_excluded:
            s["hook_score"] = -100
            s["is_excluded"] = True
            s["excluded_by"] = next((excl for excl in exclusions if excl in text), "?")
            s["topic"] = None
            continue

        # 2. Topic detection + boost
        topic = _detect_topic(text)
        s["topic"] = topic
        topic_boost = cats.get(topic, 0) if topic else 0
        if topic_boost:
            signals[f"topic:{topic}"] = topic_boost

        # 3. Company-name matches (any company name = creator covers this org)
        company_boost = 0
        company_hits: list[str] = []
        for kw, w in companies.items():
            if kw in text:
                company_boost += w
                company_hits.append(kw)
        # Cap to prevent runaway scoring on multi-company stories
        company_boost = min(company_boost, 15)
        if company_hits:
            signals["companies"] = company_boost

        # 4. Vocabulary signals (open-source, benchmark, agentic, etc.)
        vocab_boost = 0
        vocab_hits: list[str] = []
        for kw, w in vocab.items():
            if kw in text:
                vocab_boost += w
                vocab_hits.append(kw)
        vocab_boost = min(vocab_boost, 18)
        if vocab_hits:
            signals["vocab"] = vocab_boost

        # 5. Soft negative penalties
        neg_penalty = 0
        for kw, w in soft_neg.items():
            if kw in text:
                neg_penalty += w   # already negative

        # 5b. Newsletter/analysis-shape penalty — headlines like "Frontier Radar #3",
        # "How X is reshaping Y", "X proves more than scale" — Prakhar consistently
        # skips these because they're analyses, not concrete product news.
        if _is_analysis_shape(text):
            neg_penalty -= 12

        # 6. Title-vs-summary weighting: title hits matter 2x more than summary hits
        # (we already combined them, so re-check the title alone for an extra boost)
        title_lower = s["title"].lower()
        title_extra = sum(w for kw, w in companies.items() if kw in title_lower) // 2
        title_extra += sum(w for kw, w in vocab.items() if kw in title_lower) // 2
        title_extra = min(title_extra, 10)

        # 6b. Multi-company-in-title boost — the "Apple × Gemini" or "OpenAI × Microsoft"
        # shape is high-signal (concrete deal/conflict between named players). Counts
        # how many distinct companies appear in the title alone.
        company_words_in_title = sum(1 for kw in companies if kw in title_lower)
        if company_words_in_title >= 2:
            title_extra += 8

        # 7. Source-tier boost
        # ai_lab sources (Anthropic blog, OpenAI blog) get priority — they're "primary news"
        source_boost = {"ai_lab": 5, "ai_repo": 3, "ai_research": 3, "ai_news": 0}.get(
            s.get("category", ""), 0)

        s["hook_score"] = (
            topic_boost + company_boost + vocab_boost + title_extra
            + source_boost + neg_penalty
        )
        s["is_excluded"] = False
        s["profile_signals"] = signals
        s["company_hits"] = company_hits[:5]
        s["vocab_hits"] = vocab_hits[:5]

    return stories


def rank_for_creator(stories: list[dict], top_n: int = 8, more_n: int = 50,
                     min_score: int = 8) -> tuple[list[dict], list[dict]]:
    """Return (top_n, more_pool).

    top_n: highest-scoring non-excluded stories
    more_pool: next more_n highest-scoring stories
    """
    scored = score_with_profile(stories)
    eligible = [s for s in scored if not s.get("is_excluded") and s["hook_score"] >= min_score]
    eligible.sort(key=lambda s: s["hook_score"], reverse=True)

    # Soft cap per source so digest isn't all from one outlet
    source_cap = max(2, top_n // 4)
    per_source: dict[str, int] = {}
    top: list[dict] = []
    leftover: list[dict] = []
    for s in eligible:
        if per_source.get(s["source"], 0) < source_cap and len(top) < top_n:
            top.append(s)
            per_source[s["source"]] = per_source.get(s["source"], 0) + 1
        else:
            leftover.append(s)

    # More pool = next 50 highest-scoring (lightweight format)
    more = [
        {
            "title": s["title"],
            "url": s["url"],
            "source": s["source"],
            "hook_score": s["hook_score"],
            "topic": s.get("topic", ""),
        }
        for s in leftover[:more_n]
    ]

    return top, more