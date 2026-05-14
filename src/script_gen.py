"""
Script generator — turns a single news story into a full EZ Snippet style script.

Output structure (every script):
  1. Hook   — user-state framed, starts with "Bhai", direct pain/aspiration callout
  2. Bridge — promise of solution/reveal + "batata hu kaise" energy
  3. Body   — either step-by-step (tutorial) OR numbered insights (mechanism/insight)
  4. Payoff — specific concrete benefits the viewer gets
  5. CTA    — "Comment karo [TOPIC_WORD] aur mai dm kardunga"

Called on-demand for top stories (NOT every story in the daily digest, since each
script generation costs ~5x a hook generation).

Usage:
    python run.py script --story-id 3
    python run.py script --title "Instagram bot purge"
"""
from __future__ import annotations
import json
import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)

# For scripts, default to gpt-4o (better voice mimicry).
# Override with SCRIPT_MODEL env var if you want to test gpt-4o-mini.
MODEL = os.environ.get("SCRIPT_MODEL", "gpt-4o")

SYSTEM_PROMPT = """You write Instagram Reel scripts for Prakhar in the EXACT voice of EZ Snippet (Neeraj Walia) — Indian audience, Hinglish, conversational, warm.

You output only valid JSON, no markdown fences, no preamble.

# THE VOICE — non-negotiable rules

1. EVERY script opens with "Bhai" as the first word. This is the signature.
2. NO clickbait words: "shocking", "you won't believe", "mind-blowing", "insane", "crazy".
3. NO English-only sentences. Hinglish throughout, Hindi connectors like "ke lie", "ki help se", "ke baad", "karo", "rahe ho", "jao", "dalo".
4. Direct address — always "aap", "aapko", "tum", "tumhe". Never third-person.
5. Frame the hook around the VIEWER'S pain or aspiration, not the news event.
   ❌ "Instagram has banned 10 million bot accounts."
   ✅ "Bhai agar aapke bhi fake followers hain toh chinta mat karo, batata hu kaise asli vs nakli detect hota hai."
6. The first sentence is conversational and warm — "chinta mat karo", "agar aap bhi...", "khush karna chahte ho".

# SCRIPT STRUCTURE — pick the right template

## Template A: TUTORIAL
Use when the news is about a tool, trick, hack, or process the viewer can follow.

Beats:
- Hook: "Bhai agar aap [aspiration]... toh [solution teaser]..."
- Bridge: "Aur yeh karna bohot asan hai." / "Aao batata hu kaise."
- Body: Step-by-step using "Sabse pehle... fir uske baad... wahan par... aur bas..."
- Payoff: "Aapki [thing] ready hojayegi" + 2-3 specifics
- CTA: "Comment karo [TRIGGER_WORD] aur mai [thing] tumhe dm kardunga."

## Template B: INSIGHT
Use when the news is about *how something works*, *why something is broken*, or *what 3-5 things matter*.

Beats:
- Hook: "Bhai agar aapki bhi [problem]... toh chinta mat karo / solution aa gaya hai."
- Bridge: "Toh bhai dekho [problem] [reason], kyunki tum [N] cheezein miss kar rahe ho."
- Body: Numbered insights — "Pehli baat... doosri baat... teesri baat... chauthi baat... aakhri baat..." Each insight is one specific actionable point.
- Payoff: Implicit — the insights themselves are the payoff.
- CTA: "Comment karo [TRIGGER_WORD] aur mai iski puri detail tumhe dm kardunga."

## Template C: OPPORTUNITY
Use when the news reveals a business/build opportunity (broken industry, hidden cost, new market).

Beats:
- Hook: "Bhai [shock fact about an industry]." (declarative)
- Bridge: "Ye ek problem hai aur tum isse [tech/AI] se solve karke paise kama sakte ho."
- Body: Market numbers (crore/lakh) + the gap + what kind of solution would work.
- Payoff: "Agar koi yeh structure banaye toh [outcome]."
- CTA: "Comment karo [TRIGGER_WORD] aur mai iska blueprint dm kardunga."

# CTA TRIGGER WORD RULES
- Single English word, ALL CAPS.
- Topic-relevant: MOM (mother's day), PROMPT (prompt tool), WORK (realism), CLAUDE (Claude skill), BOT (bot detection), MONEY (income opportunity), HACK (trick).
- Never random — must connect to the topic so the viewer remembers it.

# LENGTH
Vary by topic. Tutorial = ~80-110 words. Insight = ~120-150 words (more body). Opportunity = ~90-120 words. Don't pad. If story is thin, keep it short.

# FORMAT — Hindi/English written in Roman script (Hinglish), exactly like the examples Prakhar gave you. Never Devanagari. Never pure English."""

USER_PROMPT_TEMPLATE = """News:
Title: {title}
Source: {source}
Summary: {summary}

Existing hook/angle for reference (you can improve on it):
Hook: {hook}
Tech angle: {tech_angle}
Payoff structure suggestion: {payoff_structure}

Generate a complete Instagram Reel script in EZ Snippet voice. Pick the right template (TUTORIAL, INSIGHT, or OPPORTUNITY) for this specific news. Output ONLY this JSON:

{{
  "template": "TUTORIAL | INSIGHT | OPPORTUNITY",
  "title": "Short script title for reference",
  "script": "Full script as one block of Hinglish text, starting with 'Bhai'. Should read like a person talking, no stage directions, no [pause] markers.",
  "cta_word": "Single ALL-CAPS English word",
  "estimated_seconds": 45,
  "word_count": 95,
  "notes_for_filming": "1-2 line note on visual b-roll suggestion or screen recording cues"
}}"""


def _build_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY env var not set")
    return OpenAI(api_key=api_key)


def generate_script(story: dict, client: OpenAI | None = None) -> dict:
    """Generate a full reel script for one story. Adds 'script' subdict to the story."""
    client = client or _build_client()
    user_prompt = USER_PROMPT_TEMPLATE.format(
        title=story.get("title", ""),
        source=story.get("source", ""),
        summary=(story.get("summary", "") or "")[:600],
        hook=story.get("hook", ""),
        tech_angle=story.get("tech_angle", ""),
        payoff_structure=story.get("payoff_structure", ""),
    )
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            max_tokens=1200,
            temperature=0.8,   # higher temp = more voice variation
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        data = json.loads(resp.choices[0].message.content.strip())
        story["script"] = data
        logger.info("Generated %s script (%d words) for: %s",
                    data.get("template"), data.get("word_count", 0), story["title"][:60])
    except Exception as e:
        logger.error("Script generation failed for '%s': %s", story["title"][:60], e)
        story["script"] = {"error": str(e)}
    return story


def generate_scripts(stories: list[dict]) -> list[dict]:
    """Generate scripts for multiple stories (used when you want top-N at once)."""
    client = _build_client()
    for s in stories:
        generate_script(s, client)
    return stories