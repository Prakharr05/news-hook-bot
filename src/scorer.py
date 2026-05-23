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
    # Funding language — kept at near-zero so a press release alone doesn't dominate.
    # Big rounds will surface via the crore/lakh/billion weights above.
    # Series-letter keywords completely removed — too noisy.
    "unicorn": 3,
}

# ─── STUDENT-AUDIENCE BOOST KEYWORDS ───
# Lighter weights than my first pass. Student-relevant stories get a small bump but
# don't dominate the digest with niche AI framework news.
STUDENT_AUDIENCE_KEYWORDS = {
    "career": 3, "careers": 3, "salary": 3, "salaries": 3,
    "intern": 2, "internship": 3, "internships": 3,
    "fresher": 3, "freshers": 3, "graduate": 2, "graduates": 2,
    "college": 2, "campus": 2, "university": 2,
    "engineer": 2, "engineers": 2, "developer": 2, "developers": 2,
    "skill": 3, "skills": 3, "stack": 2, "tech stack": 3,
    "github": 3, "leetcode": 3, "open source": 3,
    "agent": 3, "agents": 3, "agentic": 4,
    "rag": 3, "langgraph": 3, "crewai": 3, "langchain": 3,
    "vector database": 3, "vector db": 3,
    "llm": 3, "fine tuning": 3, "fine-tuning": 3,
    "30 lpa": 4, "lpa": 3, "package": 2,
    "deepfake": 4, "deepfakes": 4,
}

# ─── VIRAL/TRENDING-INDIA BOOST KEYWORDS ───
# These signal stories that engage Indian audiences regardless of topic.
# Heavy weight because virality > niche relevance for top-of-funnel growth.
# ─── EVENT / LAUNCH BOOST KEYWORDS ───
# Major tech events, product launches, and high-engagement model releases.
# These help global tech news compete with your Indian-trending focus without
# dominating it. Designed so a typical I/O/keynote preview scores ~50-70 range.
# ─── NAMED POWER PLAYERS ───
# Big tech names + power figures. On their own these are mild; combined with a
# CONFLICT keyword they signal a high-engagement "clash" story (the kind Prakhar picks).
POWER_PLAYER_KEYWORDS = {
    "openai": 4, "anthropic": 4, "google": 3, "meta": 3, "apple": 3,
    "microsoft": 3, "amazon": 3, "nvidia": 4, "tesla": 3, "spacex": 3,
    "deepseek": 4, "claude": 4, "chatgpt": 4, "gemini": 4, "grok": 3,
    "ambani": 5, "adani": 5, "mukesh ambani": 5, "jio": 4, "reliance": 4,
    "tata": 3, "airtel": 3, "swiggy": 4, "zomato": 4, "paytm": 3,
    "elon musk": 4, "jensen huang": 4, "sam altman": 4, "sundar pichai": 4,
    "nvidia": 4, "linkedin": 3, "tiktok": 3, "youtube": 3, "rbi": 4,
    "npci": 4, "sebi": 4, "cci": 4, "supreme court": 4, "delhi hc": 4,
    "parliament": 3, "centre": 3, "it ministry": 4, "meity": 4,
}

# ─── CONFLICT / TENSION MARKERS ───
# Words that signal a fight, stakes, or structural shift. The "story" in a story.
CONFLICT_KEYWORDS = {
    "vs": 4, "versus": 4, "lead over": 5, "beats": 4, "overtakes": 5,
    "banned": 5, "bans": 5, "ban": 4, "block": 4, "blocked": 4, "blocks": 4,
    "antitrust": 5, "lawsuit": 5, "sued": 5, "sues": 5, "probe": 4, "fir": 4,
    "roadblock": 5, "stalls": 4, "stalled": 4, "fails": 4, "failed": 4,
    "war": 4, "battle": 4, "fight": 3, "clash": 4, "clashes": 4,
    "crisis": 4, "lost control": 5, "war on": 5, "crackdown": 4,
    "scrutiny": 4, "flags": 3, "high risk": 4, "threat": 4, "threats": 4,
    "restrict": 4, "restricts": 4, "default": 3, "scam": 4, "scams": 4,
    "profitable": 4, "first profitable": 6, "revenue lead": 6,
    "structural trap": 5, "plateau": 4, "admission": 4,
    "takes on": 4, "challenge": 3, "challenges": 3, "disrupt": 4,
}

# ─── GADGET-LAUNCH NOISE PENALTY ───
# Phone/earbud/wearable spec leaks and launches — low value for Prakhar's content.
GADGET_KEYWORDS = {
    "tipped to": -6, "specifications leaked": -6, "specs leaked": -6,
    "colour options": -6, "color options": -6, "launch timeline": -5,
    "price range leaked": -6, "spotted on": -5, "gsma database": -6,
    "launched in india with": -5, "launch date revealed": -5,
    "key specifications": -5, "expected specifications": -5,
    "tipster": -6, "leaks key": -5, "reportedly spotted": -5,
    "earbuds": -4, "smartwatch launch": -4, "music playback": -4,
    "drivers": -3, "mah battery": -4, "display refresh": -4,
    "redmi note": -4, "vivo s": -4, "oppo enco": -5, "honor win": -4,
    "realme": -3, "iqoo": -3, "poco": -3,
}

EVENT_KEYWORDS = {
    # Annual tech events
    "keynote": 5, "i/o": 6, "io 2026": 5, "wwdc": 5, "re:invent": 4,
    "ignite": 3, "build conference": 3, "dev day": 4, "devday": 4,
    "openai devday": 5, "google i/o": 6, "apple wwdc": 5, "ces 2026": 3,

    # Launch / announcement verbs
    "unveils": 4, "unveiled": 4, "launches": 3, "launched": 3,
    "announces": 3, "announced": 3, "reveals": 3, "revealed": 3,
    "rolls out": 3, "rolled out": 3, "debuts": 3,

    # Major AI models and products (current and likely-imminent)
    "gemini": 5, "gemini 3": 5, "gemini 4": 6, "gemini intelligence": 5,
    "gpt-5": 6, "gpt 5": 6, "gpt-4.5": 4, "o1": 3, "o3": 4, "o4": 5,
    "claude opus": 4, "claude sonnet": 3, "claude 5": 6,
    "llama 4": 4, "llama 5": 5, "mistral": 3,
    "grok": 3, "deepseek": 4, "qwen": 3,
    "veo": 4, "sora": 5, "imagen": 3, "midjourney": 3,
    "android 17": 4, "android xr": 4, "ios 27": 4,
    "pixel 11": 3, "iphone 17": 4, "iphone 18": 5,

    # Hot-topic releases that engage students
    "vibe coding": 5, "ai studio": 4, "antigravity": 4,
    "codex": 4, "copilot": 3, "cursor": 4, "windsurf": 4,
    "agent mode": 4, "browser agent": 5, "computer use": 4,
    "rag pipeline": 3, "fine-tune": 3, "open weights": 3, "open-source model": 4,
}


# ─── ENTERTAINMENT / GOSSIP PENALTY ───
# These words signal celebrity/Bollywood/sports content that doesn't fit Prakhar's
# tech-behind-trending format. Heavy negative weight to filter them out.
GOSSIP_KEYWORDS = {
    "bollywood": -8, "tollywood": -6, "kollywood": -6,
    "celebrity": -5, "celeb": -5, "actress": -6, "actor": -3,
    "wedding": -5, "marriage": -3, "divorce": -3, "dating": -5,
    "fashion": -4, "outfit": -5, "outfits": -5, "saree": -5,
    "kapoor": -5, "khan": -3, "bachchan": -5, "deepika": -5, "ranbir": -5,
    "trailer": -4, "teaser": -4, "release date": -3, "box office": -5,
    "ipl": -4, "cricket": -3, "csk": -5, "rcb": -5, "mumbai indians": -5,
    "fifa": -4, "football match": -4,
    "horoscope": -8, "zodiac": -8, "astrology": -8,
    "recipe": -6, "viral video": -3, "memes": -4,
}

VIRAL_KEYWORDS = {
    # Public figures — names that make Indians click
    "modi": 5, "narendra modi": 5, "pm modi": 5,
    "rahul gandhi": 5, "raghav chadha": 5, "kejriwal": 4,
    "adani": 5, "ambani": 5, "mukesh ambani": 5, "gautam adani": 5,
    "sundar pichai": 4, "satya nadella": 4, "elon musk": 5,
    "yogi": 4, "shah": 3, "mamata": 3,

    # Geopolitics that lands in India
    "china": 4, "pakistan": 4, "us tariff": 4, "tariffs": 3,
    "norway": 3, "netherlands": 3, "russia": 3, "iran": 3,
    "border": 3, "diplomatic": 3, "ambassador": 3,

    # Controversy markers — these turn news into story
    "demands": 3, "demand": 2, "responds": 3, "fires back": 4,
    "exposes": 4, "exposed": 4, "leaks": 4, "leaked": 4,
    "denies": 3, "admits": 3, "confesses": 4,
    "vs ": 3, "clashes with": 3, "slams": 3,

    # Rule/policy/ruling words for the China-rule type stories
    "new rule": 5, "new rules": 5, "rules out": 3,
    "verdict": 4, "supreme court": 4, "high court": 3,
    "passed bill": 4, "ordinance": 3,
    "fired": 3, "resigned": 3, "ousted": 4,
    "scam": 5, "fraud": 4, "raid": 4, "arrested": 4,

    # India-context engagement signals
    "indian": 2, "india": 2, "bharat": 2,
    "lok sabha": 3, "rajya sabha": 3, "parliament": 3,
    "election": 3, "voter": 3, "elections": 3,
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

        # Category weighting — Prakhar's content focuses on TRENDING Indian news with
        # a tech/data angle (60% target) + pure tech news (40% target).
        # india_trending gets the HIGHEST baseline because that's the primary content category.
        category_bonus = {
            "india_trending":     12,   # primary content category
            "india_tech_policy":  8,
            "india_ai_policy":    8,
            "india_tech":         6,
            "ai_research":        4,
            "platform":           2,
        }.get(s.get("category", ""), 0)

        text_lower = (s["title"] + " " + s["summary"]).lower()

        # Viral boost: public figures, geopolitics, controversy markers, policy rulings.
        # These signal engagement potential regardless of tech angle.
        viral_boost = 0
        viral_matches: list[str] = []
        for kw, w in VIRAL_KEYWORDS.items():
            if kw in text_lower:
                viral_boost += w
                viral_matches.append(kw)

        # Student boost: smaller now (max ~10 across all matches typically)
        student_boost = 0
        student_matches: list[str] = []
        for kw, w in STUDENT_AUDIENCE_KEYWORDS.items():
            if kw in text_lower:
                student_boost += w
                student_matches.append(kw)

        # Gossip / entertainment penalty — Bollywood, sports gossip, fashion, etc.
        # These dominate trending feeds but don't fit Prakhar's content style.
        gossip_penalty = 0
        for kw, w in GOSSIP_KEYWORDS.items():
            if kw in text_lower:
                gossip_penalty += w   # already negative

        # Event/launch boost — major tech events (I/O, WWDC), model launches (Gemini, GPT-5),
        # and product reveals. Helps global tech news compete with Indian-trending focus.
        event_boost = 0
        event_matches: list[str] = []
        for kw, w in EVENT_KEYWORDS.items():
            if kw in text_lower:
                event_boost += w
                event_matches.append(kw)
        # Cap to prevent runaway scoring on long articles mentioning many models
        event_boost = min(event_boost, 25)

        # Named-player-conflict boost — Prakhar's favorite story shape is a big-name
        # clash (OpenAI vs Anthropic, China bans Nvidia, Ambani IPO hits roadblock).
        # Power player alone = mild. Power player + conflict word = high signal.
        player_hits = sum(1 for kw in POWER_PLAYER_KEYWORDS if kw in text_lower)
        conflict_hits = sum(1 for kw in CONFLICT_KEYWORDS if kw in text_lower)
        player_score = sum(w for kw, w in POWER_PLAYER_KEYWORDS.items() if kw in text_lower)
        conflict_score = sum(w for kw, w in CONFLICT_KEYWORDS.items() if kw in text_lower)
        conflict_boost = min(player_score + conflict_score, 22)
        if player_hits >= 1 and conflict_hits >= 1:
            conflict_boost += 8   # combo bonus: named player IN a conflict

        # Gadget-launch penalty — phone/earbud spec leaks are noise for this audience.
        gadget_penalty = 0
        gadget_hits = 0
        for kw, w in GADGET_KEYWORDS.items():
            if kw in text_lower:
                gadget_penalty += w   # already negative
                gadget_hits += 1
        # If a story is clearly a gadget-launch (2+ gadget signals OR a phone brand +
        # launch/spec word), nuke its score regardless of other boosts. These are the
        # Vivo/Honor/Redmi/Oppo stories Prakhar never wants.
        phone_brands = ("vivo", "honor", "redmi", "oppo", "realme", "iqoo", "poco",
                        "oneplus", "samsung galaxy", "moto ", "infinix", "tecno")
        launch_words = ("launch", "specifications", "specs", "tipped", "leaked",
                        "colour", "color option", "price in india", "spotted")
        has_phone = any(b in text_lower for b in phone_brands)
        has_launch = any(l in text_lower for l in launch_words)
        if gadget_hits >= 2 or (has_phone and has_launch):
            gadget_penalty -= 40   # hard suppression

        # Small-deal penalty — funding rounds under $20M or 100 crore are press-release
        # noise (no narrative). Big rounds keep their natural score from crore/billion
        # keywords; this only suppresses the small ones.
        small_deal_penalty = 0
        is_funding_story = any(kw in text_lower for kw in
                               ("raised", "funding", "series a", "series b", "series c"))
        if is_funding_story:
            # Extract any numeric amount in $M or crore
            m = re.search(r"\$?\s*(\d+(?:\.\d+)?)\s*(million|m\b|crore|cr\b|billion|b\b)", text_lower)
            if m:
                amount = float(m.group(1))
                unit = m.group(2)
                # Normalize to USD millions: 1 billion = 1000M, 1 crore ≈ 0.12M
                if unit.startswith("b"):
                    usd_millions = amount * 1000
                elif unit.startswith("cr") or unit == "crore":
                    usd_millions = amount * 0.12
                else:
                    usd_millions = amount
                # Threshold: under $20M = small deal, suppress heavily
                if usd_millions < 20:
                    small_deal_penalty = -12
                elif usd_millions < 50:
                    small_deal_penalty = -4
                # 50M+ rounds keep natural score (they're genuinely interesting)
            else:
                # Funding story without a clear amount → probably small/vague, suppress
                small_deal_penalty = -6

        # Earnings-report penalty — quarterly results are boring number-reporting
        # (Prakhar skipped both Ixigo Q4 and Lenskart Q4). Light penalty unless there's
        # a conflict/drama angle.
        earnings_penalty = 0
        earnings_markers = ("q1 revenue", "q2 revenue", "q3 revenue", "q4 revenue",
                            "q1 profit", "q2 profit", "q3 profit", "q4 profit",
                            "quarterly results", "posts profit", "posts loss",
                            "clocks profit", "revenue climbs", "profit dips",
                            "profit rises", "net profit", "ebitda")
        if any(m in text_lower for m in earnings_markers):
            earnings_penalty = -10
        # Trending stories need EITHER a viral signal (they're naturally high-engagement)
        # OR a tech keyword (so we can find an angle to teach). Pure entertainment/gossip
        # without either gets penalized.
        if s.get("category") == "india_trending":
            has_viral = viral_boost >= 3
            has_tech = student_boost >= 2 or title_score >= 4
            if not (has_viral or has_tech):
                category_bonus -= 15   # downweight pure entertainment

        s["hook_score"] = (
            title_score * 2 + summary_score + category_bonus
            + viral_boost + student_boost + event_boost + conflict_boost
            + gossip_penalty + small_deal_penalty + gadget_penalty + earnings_penalty
        )
        s["matched_keywords"] = title_kws[:5]
        if student_matches:
            s["student_keywords"] = student_matches[:5]
        if viral_matches:
            s["viral_keywords"] = viral_matches[:5]
        if event_matches:
            s["event_keywords"] = event_matches[:5]

        # Template prediction — combines title + summary, title weighted more
        combined = (s["title"] + " ") * 2 + s["summary"]
        lean, lean_scores = _template_lean(combined)
        s["template_lean"] = lean
        s["template_scores"] = lean_scores
    return stories


def rank(stories: list[dict], top_n: int = 8, min_score: int = 6) -> list[dict]:
    """
    Rank with THREE diversity guarantees:
    1. Max N stories per source (so the digest isn't 'TechCrunch x8')
    2. Content-type quota: 60% trending/govt + 40% pure tech (for top_n=8: 5 govt + 3 tech)
    3. Template diversity within each bucket

    Govt-bucket categories: india_trending, india_tech_policy, india_ai_policy
    Tech-bucket categories: everything else (bigtech, ai_research, india_tech, platform, deep_tech)
    """
    scored = score(dedupe(stories))
    scored.sort(key=lambda s: s["hook_score"], reverse=True)

    source_cap = max(2, top_n // 10)

    # Content-type quota: 60% govt-ish, 40% tech.
    govt_categories = {"india_trending", "india_tech_policy", "india_ai_policy"}
    govt_target = max(1, round(top_n * 0.6))   # 5 of 8
    tech_target = top_n - govt_target           # 3 of 8
    govt_count = 0
    tech_count = 0

    # Cap funding-press-release stories to prevent them from dominating
    # (a 4-keyword "raised Series A funding at $50M valuation" can score high)
    funding_cap = max(1, top_n // 4)  # for top_n=8: max 2 funding stories
    funding_count = 0
    def is_funding(s: dict) -> bool:
        t = (s.get("title", "") + " " + s.get("summary", "")).lower()
        return any(k in t for k in ("raised", "funding round", "series a", "series b", "series c"))

    # Template quota inside each bucket (looser, will overflow if needed)
    target_per_template = {
        "OPPORTUNITY": max(1, top_n * 3 // 8),
        "INSIGHT":     max(1, top_n * 2 // 8),
        "TUTORIAL":    max(1, top_n * 2 // 8),
        "TWIST":       max(1, top_n * 1 // 8),
    }
    while sum(target_per_template.values()) < top_n:
        target_per_template["OPPORTUNITY"] += 1
    template_count: dict[str, int] = {k: 0 for k in target_per_template}
    per_source_count: dict[str, int] = {}
    out: list[dict] = []

    # Phase 1: Fill govt + tech quotas with template diversity preference.
    for s in scored:
        if s["hook_score"] < min_score:
            continue
        if per_source_count.get(s["source"], 0) >= source_cap:
            continue
        if is_funding(s) and funding_count >= funding_cap:
            continue
        is_govt = s.get("category") in govt_categories
        if is_govt and govt_count >= govt_target:
            continue
        if not is_govt and tech_count >= tech_target:
            continue
        lean = s.get("template_lean", "OPPORTUNITY")
        # Soft template diversity — only enforce if we have headroom
        if template_count[lean] >= target_per_template[lean] and len(out) < top_n - 2:
            continue
        out.append(s)
        template_count[lean] += 1
        per_source_count[s["source"]] = per_source_count.get(s["source"], 0) + 1
        if is_funding(s):
            funding_count += 1
        if is_govt:
            govt_count += 1
        else:
            tech_count += 1
        if len(out) >= top_n:
            break

    # Phase 2: If govt bucket couldn't be filled (slow news day), let tech overflow.
    # If tech bucket couldn't be filled, let govt overflow.
    if len(out) < top_n:
        seen_urls = {s["url"] for s in out}
        for s in scored:
            if s["url"] in seen_urls:
                continue
            if s["hook_score"] < min_score:
                continue
            if per_source_count.get(s["source"], 0) >= source_cap:
                continue
            out.append(s)
            per_source_count[s["source"]] = per_source_count.get(s["source"], 0) + 1
            if len(out) >= top_n:
                break

    # Final sort by score so the highest-impact story is #1
    out.sort(key=lambda s: s["hook_score"], reverse=True)
    return out