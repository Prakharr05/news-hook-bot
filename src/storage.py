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
RATE_LIMIT_KEY_PREFIX = "news_hook_bot:ratelimit"


def _client() -> tuple[str, dict]:
    url = os.environ.get("UPSTASH_REDIS_REST_URL")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        raise RuntimeError("UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN must be set")
    return url.rstrip("/"), {"Authorization": f"Bearer {token}"}


def save_digest(stories: list[dict]) -> None:
    """Persist today's digest to Redis with a 36-hour TTL (auto-expires next day)."""
    url, headers = _client()
    payload = json.dumps(stories, default=str)
    # SETEX = set with expiry. 36 hours = enough overlap for next-day script generation.
    r = httpx.post(
        f"{url}/setex/{DIGEST_KEY}/129600",
        headers=headers,
        content=payload,
        timeout=10.0,
    )
    r.raise_for_status()
    logger.info("Saved digest to Upstash (%d stories, TTL 36h)", len(stories))


def load_digest() -> list[dict]:
    """Fetch today's digest. Returns empty list if nothing cached."""
    url, headers = _client()
    r = httpx.get(f"{url}/get/{DIGEST_KEY}", headers=headers, timeout=10.0)
    r.raise_for_status()
    result = r.json().get("result")
    if not result:
        return []
    return json.loads(result)


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
