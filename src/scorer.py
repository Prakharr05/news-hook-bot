"""
Scoring + deduplication.

Two phases:
  1. Dedupe near-identical stories (same headline across outlets)
  2. Score each story on "hook potential" — how likely it grabs attention
     in 3-4 seconds AND has a clear tech-content angle.
"""
from __future__ import annotations
import re
from difflib import SequenceMatcher
from typing import Any


# Weighted keywords. The vibe: short, punchy, conflict/scale/secrecy.
# These map to EZ-snippet-style hooks: scandal, scale, breakthrough, surprise.
HOOK_KEYWORDS: dict[str, int] = {
    # Drama / conflict (highest hook value)
    "lawsuit": 9, "sued": 9, "ban": 9, "banned": 9, "blocked": 8,
    "leaked": 10, "leak": 9, "hacked": 10, "breach": 9, "scam": 9, "fraud": 9,
    "arrested": 9, "fired": 8, "fires": 7, "layoff": 8, "layoffs": 8,
    "outage": 8, "down": 5, "crashed": 7, "exposed": 8,
    "scandal": 9, "controversy": 7, "backlash": 7, "accused": 7,
    "recall": 8, "recalls": 8, "recalled": 7, "shutdown": 7, "shuts down": 7,
    "warns": 5, "warning": 4, "killed": 7, "dies": 6, "crash": 6,

    # Scale (numbers = instant hook)
    "billion": 7, "million": 5, "trillion": 8,
    "record": 6, "biggest": 6, "largest": 6, "first ever": 7,
    "millions of": 8,

    # Bot / fake / spam (your example domain — keep high)
    "bots": 9, "bot": 7, "fake account": 9, "fake accounts": 9,
    "deepfake": 9, "ai-generated": 6, "synthetic": 5,
    "purge": 8, "purged": 8, "removes": 4, "deleted": 5,

    # AI / GenAI (highly relevant to your content style)
    "gpt": 7, "openai": 7, "anthropic": 8, "claude": 7, "gemini": 7,
    "llm": 6, "agent": 5, "agentic": 6, "open source": 5, "open-source": 5,
    "release": 4, "launches": 4, "launched": 4, "unveils": 5,
    "breakthrough": 8, "first": 5,

    # Big Tech entities (modest weight — common terms)
    "google": 4, "meta": 5, "apple": 4, "instagram": 6, "whatsapp": 6,
    "youtube": 5, "tiktok": 7, "twitter": 6, "x ": 4, "facebook": 5,
    "microsoft": 4, "nvidia": 6, "amazon": 4, "tesla": 5, "spacex": 5,

    # Policy / regulation
    "regulation": 5, "regulator": 5, "ftc": 6, "eu ": 5, "doj": 6,
    "antitrust": 7, "fine": 6, "fined": 6, "investigation": 6,

    # Surprise / curiosity
    "surprising": 6, "shocking": 7, "secret": 7, "hidden": 6,
    "actually": 4, "turns out": 5, "revealed": 6,

    # Indian context bonus (your audience)
    "india": 5, "indian": 5, "upi": 6, "ola": 4, "zomato": 4, "swiggy": 4,
    "reliance": 4, "jio": 5, "paytm": 5,
}

# Phrases that pattern-match — checked separately
HOOK_PATTERNS = [
    (r"\b(\d+)\s*(million|billion|trillion)\b", 4),   # "5 million users"
    (r"\b(\d{2,3})%\b", 3),                            # "70% of users"
    (r"\?$", 3),                                       # title is a question
    (r"^how\b", 2),                                    # "How X does Y"
    (r"^why\b", 3),                                    # "Why X happened"
]

NEGATIVE_PATTERNS = [
    # filter out obvious clickbait/listicles/promos
    (r"\bdeal\b|\bsale\b|\bcoupon\b|\bdiscount\b", -8),
    (r"\bbest \d+\b|\btop \d+\b", -4),
    (r"\bguide\b|\btutorial\b|\bhow to install\b", -3),
    (r"\bsponsored\b|\bgiveaway\b", -10),
]


def _norm_title(t: str) -> str:
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm_title(a), _norm_title(b)).ratio()


def dedupe(stories: list[dict]) -> list[dict]:
    """Group near-duplicates (same story, different outlets). Keep first."""
    kept: list[dict] = []
    for s in stories:
        if any(_similar(s["title"], k["title"]) > 0.55 for k in kept):
            continue
        kept.append(s)
    return kept


def _score_text(text: str) -> tuple[int, list[str]]:
    text_lower = text.lower()
    score = 0
    matched: list[str] = []
    for kw, weight in HOOK_KEYWORDS.items():
        if kw in text_lower:
            score += weight
            matched.append(kw)
    for pattern, weight in HOOK_PATTERNS:
        if re.search(pattern, text_lower):
            score += weight
    for pattern, weight in NEGATIVE_PATTERNS:
        if re.search(pattern, text_lower):
            score += weight
    return score, matched


def score(stories: list[dict]) -> list[dict]:
    """Add a 'hook_score' field to each story."""
    for s in stories:
        # Title weighted more than summary — headline = the actual hook
        title_score, title_kws = _score_text(s["title"])
        summary_score, _ = _score_text(s["summary"])
        s["hook_score"] = title_score * 2 + summary_score
        s["matched_keywords"] = title_kws[:5]
    return stories


def rank(stories: list[dict], top_n: int = 8, min_score: int = 6) -> list[dict]:
    """Sort by score desc, keep top N above min_score, ensure source diversity."""
    scored = score(dedupe(stories))
    scored.sort(key=lambda s: s["hook_score"], reverse=True)

    # diversity: cap 2 per source in the final cut, so the digest doesn't
    # become "TechCrunch x8".
    per_source_count: dict[str, int] = {}
    out: list[dict] = []
    for s in scored:
        if s["hook_score"] < min_score:
            break
        if per_source_count.get(s["source"], 0) >= 2:
            continue
        out.append(s)
        per_source_count[s["source"]] = per_source_count.get(s["source"], 0) + 1
        if len(out) >= top_n:
            break
    return out
