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

SYSTEM_PROMPT = """You're a writing assistant for Prakhar, a tech content creator who makes short-form videos in the style of EZ Snippet (Neeraj Walia) — Indian audience, Hinglish, no hype words, sharp factual hooks, payoff-driven explainers.

You output only valid JSON, no markdown fences, no preamble.

# THE EZ SNIPPET FORMULA

## Hook (first 4 seconds)
A flat, declarative shock fact. NO clickbait words ("you won't believe", "shocking"). NO questions. NO "did you know". The fact itself does the work.

Good hook examples:
- "Zomato 1 order pe 27% commission kaat ta hai."
- "Instagram ne sabke bot followers hata diye."
- "China ek aisa rule laya hai jo agar India aaya, toh 90% influencers gayab ho jayenge."

## Pivot (seconds 5-8)
Casual Hinglish bridge that promises something specific. Sounds like a friend, not a teacher. Always promises a reveal — solution, mechanism, or twist.

Good pivot examples:
- "Ye detect kaise karta hai, aaja batata hu."
- "Ye ek problem hai, aur tum isse AI se solve karke paise kama sakte ho."
- "Lekin iska ek interesting loophole hai."

## Payoff Structures (pick ONE that fits the story)

1. **MECHANISM** — break down HOW something technical works in 3-5 named signals/layers/steps. Use real technical terms (graph neural networks, device fingerprinting, behavioral biometrics, etc.).
   Use when: story is about detection, security, algorithms, ranking, moderation, infra.

2. **OPPORTUNITY** — turn the news into a business/build idea with real INR numbers (market size, commission rates, user counts) and a "you can build this" angle.
   Use when: story is about a platform problem, broken industry, or new tech opening a market.

3. **TWIST** — state a rule/event/fact, then reveal a clever exception, loophole, or hidden implication for a specific audience (devs, students, Indians).
   Use when: story is regulation, policy, geopolitical, or has counterintuitive consequences.

# RULES

- ALWAYS use Indian context: INR not USD, lakh/crore not million/billion, mention Indian companies/regulators if relevant.
- Numbers make abstract things visceral. Include real numbers in the payoff whenever possible.
- The "tech_angle" output should be the FULL payoff content — 3-5 specific technical points, NOT a generic topic.
- Hinglish in hook/pivot, more English in tech_angle (since it covers real terms).
- If the news doesn't fit any of the 3 payoff structures well, lower the confidence score.
"""

USER_PROMPT_TEMPLATE = """News:
Title: {title}
Source: {source}
Summary: {summary}

Produce:
1. HOOK — flat declarative Hinglish shock fact, max 12 words
2. PIVOT — casual Hinglish bridge sentence promising the reveal, max 15 words
3. PAYOFF_STRUCTURE — one of: "mechanism", "opportunity", or "twist"
4. TECH_ANGLE — the actual payoff content (3-5 specific technical points or numbered breakdown, with real terms and numbers). This is the meat of the video.
5. CONFIDENCE — 1-10, how well this story fits the EZ Snippet formula

Respond ONLY in valid JSON with this exact shape:
{{"hook": "...", "pivot": "...", "payoff_structure": "mechanism", "tech_angle": "...", "confidence": 7}}"""


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
            max_tokens=700,
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
        story["pivot"] = data.get("pivot", "")
        story["payoff_structure"] = data.get("payoff_structure", "")
        story["tech_angle"] = data.get("tech_angle", "")
        story["llm_confidence"] = int(data.get("confidence", 5))
    except Exception as e:
        logger.warning("LLM hook gen failed for '%s': %s", story["title"][:60], e)
        story["hook"] = ""
        story["pivot"] = ""
        story["payoff_structure"] = ""
        story["tech_angle"] = ""
        story["llm_confidence"] = 0
    return story


def generate_hooks(stories: list[dict]) -> list[dict]:
    """Generate hooks for every story. Sequential — usually <10 stories so no need for async."""
    client = _build_client()
    for s in stories:
        generate_hook(s, client)
    return stories