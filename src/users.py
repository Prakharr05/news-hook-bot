"""
Multi-user config.

Users are loaded from JSON in the USERS env var. Format:
  [
    {"name": "Prakhar", "chat_id": "987654321", "openai_key": "sk-..."},
    {"name": "Senior",  "chat_id": "123456789", "openai_key": "sk-...",
     "feed_filter": ["india_tech_policy", "india_ai_policy"]}
  ]

`feed_filter` is OPTIONAL. If present, the user only receives stories whose source
category matches one of the filter values. If omitted, user sees all stories.

This keeps user info OUT of source control. In Vercel/GitHub Actions, paste the JSON
as a single-line env var.

For local dev, you can also drop a users.json file in the project root and it'll be
loaded automatically (gitignored).
"""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def load_users() -> list[dict]:
    """Load users from USERS env var, falling back to local users.json."""
    raw = os.environ.get("USERS")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("USERS env var is not valid JSON: %s", e)
            return []

    local = Path("users.json")
    if local.exists():
        return json.loads(local.read_text())

    logger.warning("No users configured. Set USERS env var or create users.json")
    return []


def get_user_by_chat_id(chat_id: int | str) -> Optional[dict]:
    """Look up a user by their Telegram chat ID. Used by the webhook."""
    chat_id = str(chat_id)
    for u in load_users():
        if str(u.get("chat_id")) == chat_id:
            return u
    return None


def filter_stories_for_user(stories: list[dict], user: dict) -> list[dict]:
    """
    Return only the stories matching the user's feed_filter.

    If user has no feed_filter, returns all stories unchanged.
    If user has feed_filter=["india_tech_policy"], returns only those.
    """
    feed_filter = user.get("feed_filter")
    if not feed_filter:
        return stories
    allowed = set(feed_filter)
    return [s for s in stories if s.get("category") in allowed]