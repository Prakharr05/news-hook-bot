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


# Weighted keywords. Tuned for EZ Snippet-style editorial picks:
#   1. Hidden cost / hidden mechanism  (commission, detection, algorithm)
#   2. Indian-relevance through implication  (regulation, rules, bans)
#   3. Platform vs user power dynamics  (purges, fees, lockouts)
# AVOIDED: product launches, funding rounds, earnings — these score LOW now.
HOOK_KEYWORDS: dict[str, int] = {
    # ── TIER 1: Hidden mechanism / "how this actually works" ──
    # These are gold — they unlock MECHANISM payoffs (Neeraj's #1 structure).
    "detect": 9, "detection": 9, "detects": 8,
    "algorithm": 8, "algorithms": 8, "ranking": 7, "moderation": 8,
    "shadow ban": 10, "shadowban": 10, "shadow-ban": 10,
    "throttle": 9, "throttled": 9, "rate limit": 8,
    "fingerprint": 9, "fingerprinting": 9,
    "behind the scenes": 8, "how it works": 7, "internally": 7,
    "uncovered": 8, "investigation": 7, "exposed": 9, "exposes": 9,
    "reverse engineer": 9, "reverse engineered": 9,

    # ── TIER 1: Hidden cost / platform economics ──
    # The Zomato 27% energy. Reveals what platforms take from users/SMBs.
    "commission": 9, "commissions": 9, "takes a cut": 10,
    "fees": 7, "fee": 6, "charges": 6, "hidden cost": 10,
    "monetiz": 7, "paywall": 7, "subscription": 5,
    "ad revenue": 7, "revenue share": 8, "creator payout": 8,
    "deplatform": 9, "demonetiz": 9, "blocked from": 7,
    "lockout": 8, "kicked off": 8, "locked out": 8,

    # ── TIER 1: Regulation / rule / policy (twist payoffs) ──
    # Especially when from China, EU, or India — implications travel.
    "new rule": 8, "new law": 8, "new regulation": 8,
    "mandate": 7, "mandated": 7, "mandatory": 7,
    "must register": 9, "required to": 6, "crackdown": 9,
    "ruling": 7, "ruled": 6, "court": 6,
    "regulation": 7, "regulator": 7, "regulators": 7,
    "ftc": 7, "eu ": 6, "doj": 7, "sebi": 8, "rbi": 8, "trai": 8, "meity": 8,
    "antitrust": 8, "compliance": 6,

    # ── TIER 1: Bot / fake / spam (your example domain) ──
    "bots": 9, "bot": 7, "fake account": 9, "fake accounts": 9,
    "deepfake": 9, "ai-generated": 7, "synthetic": 6,
    "purge": 9, "purged": 9, "removes": 5, "removed": 5, "deleted": 6,
    "spam": 6, "scam": 8, "fraud": 8,

    # ── TIER 2: Drama / conflict ──
    "lawsuit": 8, "sued": 8, "ban": 8, "banned": 8, "blocked": 7,
    "leaked": 9, "leak": 8, "hacked": 9, "breach": 9,
    "fined": 8, "fine": 7, "penalty": 7,
    "shutdown": 7, "shuts down": 7, "outage": 6, "down": 3,
    "recall": 7, "recalls": 7, "recalled": 6,
    "warning": 4, "warns": 5, "controversy": 6, "backlash": 6,
    "scandal": 8, "accused": 6, "arrested": 7,

    # ── TIER 2: Scale (numbers create instant hooks) ──
    "billion": 6, "million": 4, "trillion": 7,
    "crore": 7, "lakh": 6,    # Indian unit bonus
    "record": 5, "biggest": 5, "largest": 5, "first ever": 6,
    "millions of": 7, "thousands of": 5,
    "percent": 4, "% of": 4,

    # ── TIER 3: Indian context (your audience) ──
    # Heavier weight than before — local matters more than global to him.
    "india": 7, "indian": 7, "indians": 7,
    "upi": 8, "ola": 6, "uber": 5, "zomato": 8, "swiggy": 8,
    "reliance": 6, "jio": 7, "paytm": 7, "phonepe": 7, "google pay": 6,
    "byju": 7, "byjus": 7, "ed ": 5, "income tax": 6,
    "nasscom": 6, "startup india": 6, "drhp": 6, "ipo": 5,
    "mumbai": 4, "bengaluru": 4, "delhi": 4, "gurgaon": 4,
    "rupee": 5, "rupees": 5, "inr": 4,

    # ── TIER 3: China (implication-source for India angle) ──
    "china": 6, "chinese": 6, "beijing": 6, "tencent": 6, "bytedance": 7,
    "shenzhen": 5, "wechat": 6,

    # ── TIER 3: Platforms users actually live on ──
    "instagram": 8, "whatsapp": 8, "youtube": 7, "tiktok": 7,
    "twitter": 5, "x ": 3, " x.": 3, "facebook": 5,
    "linkedin": 6, "snapchat": 5, "telegram": 6, "discord": 5,
    "reddit": 5, "spotify": 6,

    # ── TIER 4: AI / tech (lower weight than before — too saturated) ──
    # We don't want every "OpenAI launches X" to dominate the digest.
    "gpt": 5, "openai": 5, "anthropic": 5, "claude": 4, "gemini": 5,
    "llm": 4, "agent": 4, "agentic": 5,
    "breakthrough": 6,   # only when ACTUAL breakthrough
    "first": 3,

    # ── TIER 4: Big Tech (low — too common) ──
    "google": 3, "meta": 4, "apple": 3, "microsoft": 3,
    "nvidia": 5, "amazon": 3, "tesla": 4, "spacex": 4,

    # ── Curiosity triggers ──
    "secret": 8, "hidden": 8, "actually": 4, "turns out": 6, "revealed": 6,
    "surprising": 5, "loophole": 9, "workaround": 7, "trick": 5,
    "why": 3, "how": 2,
}

# Phrases that pattern-match — checked separately
HOOK_PATTERNS = [
    (r"\b(\d+)\s*(million|billion|trillion|lakh|crore)\b", 5),   # "27% commission", "10 million users"
    (r"\b(\d{1,3})\s*%\b", 5),                                    # "27%", "90 percent"
    (r"\b₹\s*\d", 5),                                             # "₹38 lakh"
    (r"\brs\.?\s*\d", 4),                                         # "Rs 38 lakh"
    (r"\$\s*\d", 3),
    (r"\?$", 2),                                                  # title is a question
    (r"^how\b", 2),                                               # "How X does Y"
    (r"^why\b", 3),                                               # "Why X happened"
    (r"^inside\b", 5),                                            # "Inside Instagram's..."
]

NEGATIVE_PATTERNS = [
    # Filter out the stuff Neeraj never covers
    (r"\bdeal\b|\bsale\b|\bcoupon\b|\bdiscount\b|\boffer\b", -10),
    (r"\bbest \d+\b|\btop \d+\b|\b\d+ best\b", -6),
    (r"\bguide\b|\btutorial\b|\bhow to install\b|\bhow to use\b", -5),
    (r"\bsponsored\b|\bgiveaway\b|\bpromotion\b", -10),
    (r"\breview\b|\bunboxing\b|\bhands\-on\b", -5),     # he doesn't do reviews
    (r"\bvaluation\b|\braised \$|\bseries [a-d]\b|\bfunding round\b", -4),   # funding news = boring
    (r"\bearnings\b|\bquarterly results\b|\bq[1-4] 20\d\d\b", -4),           # earnings = boring
    (r"\brumor\b|\brumors\b|\bleaked specs\b|\bcould launch\b", -3),         # speculation
    (r"\bopinion\b|\beditorial\b|\bcolumn\b", -3),
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


# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATE LEANING — predicts which EZ Snippet template a story fits best.
# This is SEPARATE from hook_score; it just predicts the script shape.
# Used to enforce digest diversity (roughly equal TUTORIAL/INSIGHT/OPPORTUNITY).
# ─────────────────────────────────────────────────────────────────────────────

TUTORIAL_KEYWORDS = {
    # New tool / feature releases the viewer can use TODAY
    "launches": 3, "launched": 3, "released": 3, "release": 2,
    "available now": 4, "rolling out": 3, "rolled out": 3,
    "new feature": 4, "new tool": 4, "hidden feature": 5,
    "free tier": 4, "free version": 4, "no signup": 5,
    "open source": 3, "open-source": 3, "github": 2,
    "extension": 3, "plugin": 3, "chrome extension": 4,
    "api": 2, "sdk": 2, "library": 2,
    "tutorial": 3, "step-by-step": 3, "how to": 2,
    "trick": 4, "hack": 4, "workaround": 4,
    "shortcut": 3, "automation": 3,
    "skill": 3, "prompt": 3, "claude code": 3, "agent": 2,
}

INSIGHT_KEYWORDS = {
    # Mechanism / algorithm / "how it works" stories
    "algorithm": 5, "algorithms": 5, "model": 2, "neural": 4, "ml model": 4,
    "detection": 5, "detect": 4, "detects": 4,
    "ranking": 4, "recommendation": 4, "recommends": 3,
    "fingerprint": 5, "fingerprinting": 5,
    "behavioral": 4, "biometric": 5, "biometrics": 5,
    "graph neural": 6, "transformer": 4, "attention": 3,
    "exploit": 5, "vulnerability": 5, "zero day": 6, "zero-day": 6,
    "reverse engineer": 5, "reverse-engineered": 5,
    "moderation": 4, "shadow ban": 5, "shadowban": 5,
    "internally": 3, "behind the scenes": 4, "how it works": 4,
    "investigation reveals": 5, "researchers found": 4,
    "inside ": 4, "deep dive": 4,
    "encryption": 4, "obfuscation": 4, "watermark": 4,
}

TWIST_KEYWORDS = {
    # Trends, comparisons, regulations with counterintuitive consequences
    "rule": 4, "rules": 3, "new policy": 4, "policy": 2,
    "mandate": 4, "mandates": 4, "mandated": 4,
    "ruling": 4, "verdict": 4, "court": 3, "supreme court": 5,
    "loophole": 6, "exception": 4, "exempt": 4, "exempted": 4,
    "implication": 4, "consequence": 4, "side effect": 5,
    "ironic": 5, "ironically": 5, "contrary": 4, "counterintuitive": 6,
    "actually": 3, "turns out": 4, "but wait": 5,
    "compared to": 3, "vs ": 3, "overtakes": 5, "overtook": 5,
    "first time": 4, "fell behind": 5, "lost lead": 5, "lost ground": 4,
    "slumps": 4, "slumping": 4, "behind": 2,
    "shift": 3, "trend": 3, "reverses": 4, "reversal": 4,
    "however": 2, "but ": 1, "though": 2,
    "china": 3, "beijing": 3,   # boost TWIST for China-rule type stories
}

OPPORTUNITY_KEYWORDS = {
    # Already covered well in HOOK_KEYWORDS — listed here for tagging
    "commission": 6, "commissions": 6, "takes a cut": 6, "fees": 4, "fee": 4,
    "hidden cost": 6, "market": 3, "industry": 3, "broken": 3,
    "crore": 4, "lakh": 4, "billion": 3, "trillion": 4,
    "gap": 4, "opportunity": 5, "untapped": 5,
    "regulation": 4, "regulator": 4, "mandate": 4, "mandated": 4,
    "crackdown": 4, "ban": 3, "banned": 3,
    "strike": 4, "protest": 3, "boycott": 4,
    "lawsuit": 4, "sued": 4, "antitrust": 4, "fine": 3, "fined": 3,
    "monopoly": 5, "monopol": 5, "exploit": 3,
    "raised": -3,   # funding news is OPPORTUNITY-looking but actually boring
}


def _template_lean(text: str) -> tuple[str, dict[str, int]]:
    """Return the template this story leans toward + per-template scores."""
    text_lower = text.lower()
    scores = {"TUTORIAL": 0, "INSIGHT": 0, "OPPORTUNITY": 0, "TWIST": 0}
    for kw, w in TUTORIAL_KEYWORDS.items():
        if kw in text_lower:
            scores["TUTORIAL"] += w
    for kw, w in INSIGHT_KEYWORDS.items():
        if kw in text_lower:
            scores["INSIGHT"] += w
    for kw, w in OPPORTUNITY_KEYWORDS.items():
        if kw in text_lower:
            scores["OPPORTUNITY"] += w
    for kw, w in TWIST_KEYWORDS.items():
        if kw in text_lower:
            scores["TWIST"] += w
    # Default lean if nothing strong matches
    winner = max(scores, key=scores.get)
    if scores[winner] < 3:
        winner = "OPPORTUNITY"   # safe default per system prompt rules
    return winner, scores


def score(stories: list[dict]) -> list[dict]:
    """Add 'hook_score', 'template_lean', 'template_scores' to each story."""
    for s in stories:
        title_score, title_kws = _score_text(s["title"])
        summary_score, _ = _score_text(s["summary"])

        category_bonus = {
            "india_tech":   8,
            "india_policy": 10,
            "platform":     3,
        }.get(s.get("category", ""), 0)

        s["hook_score"] = title_score * 2 + summary_score + category_bonus
        s["matched_keywords"] = title_kws[:5]

        # Template prediction — combines title + summary, title weighted more
        combined = (s["title"] + " ") * 2 + s["summary"]
        lean, lean_scores = _template_lean(combined)
        s["template_lean"] = lean
        s["template_scores"] = lean_scores
    return stories


def rank(stories: list[dict], top_n: int = 8, min_score: int = 6) -> list[dict]:
    """
    Rank with two diversity guarantees:
    1. Max 2 stories per source (so the digest isn't 'TechCrunch x8')
    2. Template diversity — try to fill a quota of each template

    Target distribution for top_n=8: 3 OPPORTUNITY + 3 INSIGHT + 2 TUTORIAL
    (slight bias to opportunity since it's the default fallback). If not enough
    of one template exists, the remaining slots overflow to the highest-scoring
    stories of any template.
    """
    scored = score(dedupe(stories))
    scored.sort(key=lambda s: s["hook_score"], reverse=True)

    # Target counts per template — scaled to top_n
    # For top_n=8: 3 OPPORTUNITY + 2 INSIGHT + 2 TUTORIAL + 1 TWIST
    target_per_template = {
        "OPPORTUNITY": max(1, top_n * 3 // 8),
        "INSIGHT":     max(1, top_n * 2 // 8),
        "TUTORIAL":    max(1, top_n * 2 // 8),
        "TWIST":       max(1, top_n * 1 // 8),
    }
    # Make sure the targets sum to top_n (rounding can leave slots empty)
    while sum(target_per_template.values()) < top_n:
        target_per_template["OPPORTUNITY"] += 1
    template_count: dict[str, int] = {k: 0 for k in target_per_template}
    per_source_count: dict[str, int] = {}
    out: list[dict] = []

    # Phase 1: Fill template quotas. Pick the top-scoring story for each template.
    for s in scored:
        if s["hook_score"] < min_score:
            continue
        if per_source_count.get(s["source"], 0) >= 2:
            continue
        lean = s.get("template_lean", "OPPORTUNITY")
        if template_count[lean] >= target_per_template[lean]:
            continue
        out.append(s)
        template_count[lean] += 1
        per_source_count[s["source"]] = per_source_count.get(s["source"], 0) + 1
        if len(out) >= top_n:
            break

    # Phase 2: Overflow — if any template didn't have enough stories,
    # fill remaining slots with the next-highest-scoring stories regardless of template
    if len(out) < top_n:
        seen_urls = {s["url"] for s in out}
        for s in scored:
            if s["url"] in seen_urls:
                continue
            if s["hook_score"] < min_score:
                continue
            if per_source_count.get(s["source"], 0) >= 2:
                continue
            out.append(s)
            per_source_count[s["source"]] = per_source_count.get(s["source"], 0) + 1
            if len(out) >= top_n:
                break

    # Final sort by score so the highest-impact story is #1 regardless of template
    out.sort(key=lambda s: s["hook_score"], reverse=True)
    return out