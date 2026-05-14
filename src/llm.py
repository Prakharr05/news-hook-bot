"""
Uses OpenAI's gpt-4o-mini (cheap, fast) to generate:
  - A 1-line hook (the first 3-4 second grab)
  - A tech-content angle (the bridge from news -> tech explainer)

Costs ~$0.0002 per story at gpt-4o-mini pricing — even cheaper than Haiku.
"""
from __future__ import annotations
import json
import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)

# Cheap + fast. Swap to "gpt-4o" or "gpt-4.1" for better angles at ~30x cost.
MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = (
    "You're a writing assistant for a tech content creator who makes short-form "
    "videos in the style of EZ Snippet (Neeraj Walia). The creator opens videos "
    "with a sharp news hook, then pivots into a tech explainer. You output only "
    "valid JSON, no markdown fences, no preamble."
)

USER_PROMPT_TEMPLATE = """Given this news, produce:
1. A 4-6 second spoken HOOK that grabs attention. Punchy. Conversational Hinglish-friendly English. No clickbait words like "you won't believe". State the surprising fact directly.
2. A TECH ANGLE — what technical topic the creator can explain after the hook. Be specific (e.g., not "AI", but "how transformer attention mechanisms work" or "how Instagram's bot detection uses graph neural networks").
3. A confidence score (1-10) for how strong this story is for hook-based content.

News:
Title: {title}
Source: {source}
Summary: {summary}

Respond ONLY in valid JSON with this exact shape:
{{"hook": "...", "tech_angle": "...", "confidence": 7}}"""


def _build_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY env var not set")
    return OpenAI(api_key=api_key)


def generate_hook(story: dict, client: OpenAI | None = None) -> dict:
    """Add 'hook', 'tech_angle', and 'llm_confidence' fields to a story."""
    client = client or _build_client()
    user_prompt = USER_PROMPT_TEMPLATE.format(
        title=story["title"],
        source=story["source"],
        summary=story["summary"][:500],
    )
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            max_tokens=400,
            temperature=0.7,
            # Force JSON output — OpenAI guarantees parseable JSON with this flag
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = resp.choices[0].message.content.strip()
        data = json.loads(text)
        story["hook"] = data.get("hook", "")
        story["tech_angle"] = data.get("tech_angle", "")
        story["llm_confidence"] = int(data.get("confidence", 5))
    except Exception as e:
        logger.warning("LLM hook gen failed for '%s': %s", story["title"][:60], e)
        story["hook"] = ""
        story["tech_angle"] = ""
        story["llm_confidence"] = 0
    return story


def generate_hooks(stories: list[dict]) -> list[dict]:
    """Generate hooks for every story. Sequential — usually <10 stories so no need for async."""
    client = _build_client()
    for s in stories:
        generate_hook(s, client)
    return stories