"""
Upstash Redis storage via REST API.

Why REST and not redis-py: Upstash's REST API works from anywhere (Vercel serverless,
GitHub Actions, your laptop) with zero connection-pooling concerns. Standard Redis
client doesn't play well with serverless cold starts.

Setup (5 min):
  1. https://console.upstash.com → sign up with GitHub
  2. Create Redis Database (any region, free tier)
  3. Copy "UPSTASH_REDIS_REST_URL" and "UPSTASH_REDIS_REST_TOKEN" from the dashboard
  4. Set both as env vars in Vercel + GitHub Actions
"""
from __future__ import annotations
import json
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DIGEST_KEY = "news_hook_bot:last_digest"
MORE_POOL_KEY = "news_hook_bot:more_pool"
GOVT_DIGEST_KEY = "news_hook_bot:govt_digest"
GOVT_MORE_KEY = "news_hook_bot:govt_more"
RATE_LIMIT_KEY_PREFIX = "news_hook_bot:ratelimit"


def _client() -> tuple[str, dict]:
    url = os.environ.get("UPSTASH_REDIS_REST_URL")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        raise RuntimeError("UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN must be set")
    return url.rstrip("/"), {"Authorization": f"Bearer {token}"}


def save_digest(stories_or_dict) -> None:
    """Persist today's digest to Redis with a 36-hour TTL (auto-expires next day).

    Accepts either:
      - list[dict]: single-user mode, all users get same digest
      - dict[chat_id, list[dict]]: multi-user mode, each user has their own digest
    """
    url, headers = _client()
    payload = json.dumps(stories_or_dict, default=str)
    r = httpx.post(
        f"{url}/setex/{DIGEST_KEY}/129600",
        headers=headers,
        content=payload,
        timeout=10.0,
    )
    r.raise_for_status()
    if isinstance(stories_or_dict, dict):
        total = sum(len(v) for v in stories_or_dict.values())
        logger.info("Saved per-user digests to Upstash (%d users, %d total stories, TTL 36h)",
                    len(stories_or_dict), total)
    else:
        logger.info("Saved digest to Upstash (%d stories, TTL 36h)", len(stories_or_dict))


def load_digest(chat_id: str | None = None) -> list[dict]:
    """Fetch today's digest. Returns empty list if nothing cached.

    If the cached digest is in per-user format and chat_id is given, returns that user's
    stories. If chat_id not given or not found, falls back to first user's digest.
    """
    url, headers = _client()
    r = httpx.get(f"{url}/get/{DIGEST_KEY}", headers=headers, timeout=10.0)
    r.raise_for_status()
    result = r.json().get("result")
    if not result:
        return []
    data = json.loads(result)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if chat_id and str(chat_id) in data:
            return data[str(chat_id)]
        return next(iter(data.values()), [])
    return []


def save_more_pool(per_user_more: dict) -> None:
    """Save the 'more headlines' pool — stories beyond top_n that /more will show.

    Format: dict[chat_id, list[dict]] — each user has their own filtered list.
    Stories should be lightweight (no hook/payoff content — just title/source/url).
    """
    url, headers = _client()
    payload = json.dumps(per_user_more, default=str)
    r = httpx.post(
        f"{url}/setex/{MORE_POOL_KEY}/129600",
        headers=headers,
        content=payload,
        timeout=10.0,
    )
    r.raise_for_status()
    total = sum(len(v) for v in per_user_more.values())
    logger.info("Saved /more pool to Upstash (%d users, %d total headlines)",
                len(per_user_more), total)


def load_more_pool(chat_id: str) -> list[dict]:
    """Fetch the user's /more headlines list."""
    url, headers = _client()
    r = httpx.get(f"{url}/get/{MORE_POOL_KEY}", headers=headers, timeout=10.0)
    r.raise_for_status()
    result = r.json().get("result")
    if not result:
        return []
    data = json.loads(result)
    if isinstance(data, dict):
        return data.get(str(chat_id), [])
    return []


def _save_key(key: str, value, ttl: int = 129600) -> None:
    """Generic SETEX helper."""
    url, headers = _client()
    r = httpx.post(f"{url}/setex/{key}/{ttl}", headers=headers,
                   content=json.dumps(value, default=str), timeout=10.0)
    r.raise_for_status()


def _load_key(key: str):
    url, headers = _client()
    r = httpx.get(f"{url}/get/{key}", headers=headers, timeout=10.0)
    r.raise_for_status()
    result = r.json().get("result")
    return json.loads(result) if result else None


def save_govt_digest(clusters: list[dict]) -> None:
    """Save the trending govt clusters (top 8). Stored as a flat list."""
    # Strip non-serializable sets before saving
    clean = []
    for c in clusters:
        clean.append({
            "headline": c.get("headline", ""),
            "url": c.get("url", ""),
            "summary": c.get("summary", ""),
            "source_count": c.get("source_count", 0),
            "story_count": c.get("story_count", 0),
            "sources": sorted(c.get("sources", [])) if isinstance(c.get("sources"), (set, list)) else [],
            "latest_pub": c.get("latest_pub", ""),
        })
    _save_key(GOVT_DIGEST_KEY, clean)
    logger.info("Saved govt digest to Upstash (%d trending clusters)", len(clean))


def load_govt_digest() -> list[dict]:
    data = _load_key(GOVT_DIGEST_KEY)
    return data if isinstance(data, list) else []


def save_govt_more(headlines: list[dict]) -> None:
    _save_key(GOVT_MORE_KEY, headlines)
    logger.info("Saved govt /more pool to Upstash (%d headlines)", len(headlines))


def load_govt_more() -> list[dict]:
    data = _load_key(GOVT_MORE_KEY)
    return data if isinstance(data, list) else []


def check_rate_limit(user_chat_id: str, max_per_hour: int = 5) -> tuple[bool, int]:
    """
    Returns (allowed, count_in_last_hour).
    Increments the counter on success — so calling this counts as "one use."
    Uses a simple sliding 1-hour window via a per-user key with 1h TTL.
    """
    url, headers = _client()
    key = f"{RATE_LIMIT_KEY_PREFIX}:{user_chat_id}:{int(time.time()) // 3600}"

    # Atomic increment with INCR; returns new value
    r = httpx.post(f"{url}/incr/{key}", headers=headers, timeout=10.0)
    r.raise_for_status()
    count = int(r.json().get("result", 0))

    # First time this hour? Set TTL so the key auto-expires.
    if count == 1:
        httpx.post(f"{url}/expire/{key}/3700", headers=headers, timeout=10.0)

    return (count <= max_per_hour, count)