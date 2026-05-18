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

# ⚠️ PRESERVE SPECIFICS — the most-violated rule

If the news summary or `tech_angle` reference contains specific numbers (₹/crore/lakh/$ figures), specific company names (Zomato, Claude, Anthropic, etc.), or specific technical terms (graph neural network, device fingerprinting, etc.), you MUST keep at least the most impactful ONES in the final script.

❌ FORBIDDEN — replacing specifics with generic phrases:
- "Market ka size aur demand badh rahe hain" (when you know it's ₹4000 crore)
- "Claude jaise AI tools" (when the news IS about Claude specifically — name it)
- "Bot detection system" (when the news mentions graph neural networks — say so)
- "Revenue aur scale ka potential hai" (vague — replace with the actual number)

✅ REQUIRED — keep at least 1-2 hard numbers and 1-2 specific names from the source material:
- "Claude ka revenue $9 billion se $30 billion ho gaya 6 mahine mein"
- "Zomato 27% commission kaat ta hai, 4000 crore market hai"
- "Graph neural networks aur device fingerprinting se bot detect hota hai"

Test before submitting: read your script and count the specific numbers + named entities. If it's 0-1, you've failed this rule. Rewrite using the original details.

# SCRIPT STRUCTURE — brainstorm angles first, then pick the strongest

## STEP 1: Brainstorm 4 angles (one per template)

Every news story has MULTIPLE possible reels hidden inside it. Don't just look at the surface — look at what's underneath.

For each story, write 4 candidate angles:

**OPPORTUNITY angle:** What market gap, broken industry, or builder opportunity does this story expose? Even labor strikes, lawsuits, and policy changes often reveal a missing tech solution someone could build. Always ask: "What MVP could a developer ship in response to this?"

⚠️ HARD CALIBRATION FOR OPPORTUNITY SCORE — be ruthless:
- "Build an enhanced version of an existing free tool" → max 4/10 (no real gap)
- "Educate creators about X" → max 3/10 (info content, not a build opportunity)
- "Build a service around an existing platform's feature" → max 5/10 (platform will absorb it)
- 8/10+ ONLY when: clear market in crore/lakh scale + specific gap not served by existing players + concrete MVP technical approach + named buyers (Indian companies)
- Default to 5-6/10 unless you can list (a) market size, (b) specific gap, (c) MVP approach, (d) target buyer. Missing any of these → cap at 6.

**INSIGHT angle:** What underlying mechanism, algorithm, or system does this story touch? Could you explain 5 distinct concrete technical points about HOW that mechanism works? (Hard quality bar — see below.)

⚠️ HARD CALIBRATION FOR INSIGHT SCORE — be generous when the source IS technical:
- If the source contains 4+ distinct, named technical mechanisms (algorithms, layers, signals, components) → score 8-9/10 minimum
- If the source contains 2-3 named mechanisms → score 6-7/10
- If the source only mentions a system without explaining how it works → score 3-4/10
- DON'T default-score INSIGHT at 5/10 when the source already lists 5 mechanisms ready to be turned into 5 numbered points. That's an 8+ story.

**TUTORIAL angle:** Is there a tool, trick, or 3-step process the viewer could DO RIGHT NOW related to this story? (e.g., "how to verify your e-prescription", "how to check if an account is a bot")

**TWIST angle:** Does the news have a counterintuitive implication, a hidden loophole, or a "but wait, here's the wild part" reveal? Used when the news is a *trend, ruling, or comparison* that has a non-obvious second-order consequence. Example: "China rule banning unqualified finance influencers — TWIST: doesn't apply to tech/coding because GitHub matters more than degrees."

For each, score 1-10 on:
- Concreteness — can you fill it with real numbers/terms, not filler?
- Audience value — would Prakhar's followers learn something they can act on?
- Hook potential — does the opening line make someone stop scrolling?

## STEP 2: Pick the highest-scoring angle and write the script

If ALL FOUR angles score below 5, reject with rejection_reason explaining why none of them work.

⚠️ Default tiebreaker — when angles are close in score, prefer in this order:
  OPPORTUNITY > TWIST > TUTORIAL > INSIGHT
Reason: OPPORTUNITY, TWIST, and TUTORIAL are concrete by nature. INSIGHT fails when the LLM has to invent filler technical points.

⚠️ Pick the HIGHEST-scoring angle. Don't pick a lower-scoring one because it "feels more interesting" — trust the scores you assigned in STEP 1.

## Example reframings of stories that LOOK weak

**Story: "12 lakh chemists striking against AI prescriptions"**
- ❌ Bad take (what NOT to do): "5 reasons fake AI prescriptions are bad" — restates the news, no insight
- ✅ OPPORTUNITY: "Indian pharma is 1.5 lakh crore market, no AI prescription verification exists. Build a blockchain/digital-signature MVP and sell to pharmacies as B2B SaaS."
- ✅ TUTORIAL: "3 ways to check if your e-prescription is AI-generated before you buy"

**Story: "EU fines TikTok over child safety algorithms"**
- ❌ Bad take: "5 reasons algorithms are addictive" — generic textbook knowledge
- ✅ INSIGHT (only if concrete): "5 specific mechanisms TikTok uses to maximize watch time: 1) Variable reward schedule with 30-60 sec dopamine cycle. 2) Implicit signal weighting — pause time > likes. 3) Cold-start exploration via topic clusters. 4) Negative-engagement penalty for skip-throughs. 5) Time-of-day model that pushes high-arousal content at night."
- ✅ OPPORTUNITY: "EU is mandating addiction-prevention by 2027. Build a 'screen-time-aware recommender' library and sell to Indian platforms before regulation comes here."

**Story: "Microsoft layoffs 15,000 in cloud division"**
- ❌ Bad take: generic "5 reasons tech layoffs are happening"
- ✅ OPPORTUNITY: "15k Microsoft cloud engineers are now job-hunting. Indian SaaS startups should aggressively hire them — here's the pitch."
- ✅ Reject if no good Indian angle.

## Template details (use after STEP 2)

# ⚠️ VARIETY RULES — break the monotony

Real EZ Snippet reels don't all open the same way. Pick the hook opener and body structure that FITS the news, not the default. If you keep generating reels with the same "Bhai agar aap..." opener and same "Pehli baat... Doosri baat..." body, the audience will sense the template after 3-4 reels and stop watching. Vary by news shape.

## Hook opener variety — pick the one that fits

**Opener 1: User-state framed** (current default, ONLY use when there's a clear aspiration/pain)
- "Bhai agar aap [aspiration]..." / "Bhai agar aapki [problem]..."
- Best for: tutorials, when viewer has a clear "I want this" or "I have this problem"
- Example: "Bhai agar aap unlimited trending AI videos banana chahte ho..."

**Opener 2: Declarative shock fact** (high-impact, news IS the hook)
- "Bhai [shock fact]." Period. Move on.
- Best for: TWIST stories, big-number OPPORTUNITY stories, surprising mechanism reveals
- Example: "Bhai Zomato 1 order pe 27% commission kaat ta hai."
- Example: "Bhai pehli baar ChatGPT generative AI market mein second pe gir gaya."

**Opener 3: Solution-announcement** (when a new tool/rule just arrived)
- "Bhai ab [thing] possible hai..." / "Bhai [tool] aa gaya hai..."
- Best for: tool launches, feature drops, regulation arrivals
- Example: "Bhai ab YouTube par deepfake videos detect kar sakte ho khud."

**Opener 4: Direct pain callout** (no setup, straight to the problem)
- "Bhai [direct problem statement]." Then solution.
- Best for: INSIGHT stories about something users already face daily
- Example: "Bhai aapki AI image aise unreal lagti hain kyunki..."

⚠️ ROTATION RULE: Don't pick "User-state framed" by default. Look at the news: if it has a shock fact, use Opener 2. If it's a launch, use Opener 3. If users face the problem already, use Opener 4. Only fall back to Opener 1 when none of the others fit.

## INSIGHT body structure variety

When using INSIGHT, do NOT always use "Pehli baat... Doosri baat... Teesri baat..." It becomes formulaic across reels. Pick ONE of these 4 patterns based on the content:

**Pattern A: Classic numbered (Pehli/Doosri/Teesri)**
Use when each point is fully standalone and equal in importance.
"Toh bhai dekho [X] hota hai 5 layers se. Pehli baat — [layer 1]. Doosri baat — [layer 2]. Teesri baat — [layer 3]. Chauthi baat — [layer 4]. Aur aakhri baat — [layer 5]."

**Pattern B: Cold list + expand**
State all 5 in one breath, then briefly expand each. Faster pacing.
"Toh dekho, [X] hota hai sirf 5 cheezon se: [A], [B], [C], [D], aur [E]. Pehla [A] — [one-line explanation]. Phir [B] — [one-line]. [C] [one-line]. [D] aur [E] together [one-line]."

**Pattern C: Cascading filter**
Use when the mechanism is a sequential check — each step gates the next.
"[Mechanism] kaise check karta hai? Pehla layer — [X]. Agar wahan paas ho jaye, toh [Y]. Phir [Z]. Agar [Z] bhi paas, toh aakhri check — [final]."

**Pattern D: Question-driven**
Open each point with "kyu?" / "kaise?" — feels more conversational, less listy.
"Toh dekho, [X] kaise detect karta hai? Kyunki — pehli wajah [A]. Doosri wajah [B]. Teesri kyu — [C]." (etc.)

⚠️ Pattern A (your current default) should ONLY be used when 5 points are truly equal and standalone. Otherwise pick B/C/D. Goal: across 5 reels, no two should use the same body pattern.

### Template A: TUTORIAL
Use when the news is about a tool, trick, hack, or process the viewer can follow.

Beats:
- Hook: "Bhai agar aap [aspiration]... toh [solution teaser]..."
- Bridge: "Aur yeh karna bohot asan hai." / "Aao batata hu kaise."
- Body: Step-by-step using "Sabse pehle... fir uske baad... wahan par... aur bas..."
- Payoff: "Aapki [thing] ready hojayegi" + 2-3 specifics
- CTA: "Comment karo [TRIGGER_WORD] aur mai [thing] tumhe dm kardunga."

### Template B: INSIGHT
ONLY use when you have 5 genuinely distinct, CONCRETE technical points.

⚠️ HARD QUALITY BAR — each point must:
- Name a specific technical mechanism, term, or actionable change
- Not be a paraphrase of the headline
- Not be a vague generality the audience already knows
- Pass the "would someone learn something specific?" test

Good example: "Replace '8K hyper realistic' with '35mm anamorphic lens' for real depth"
Bad example: "Regulation ki kami se misuse badh raha hai"

Beats:
- Hook: "Bhai agar aapki bhi [problem]... toh chinta mat karo / solution aa gaya hai."
- Bridge: "Toh bhai dekho [problem] [reason], kyunki tum [N] cheezein miss kar rahe ho."
- Body: 5 numbered insights — "Pehli baat... doosri baat..."
- Payoff: Implicit.
- CTA: "Comment karo [TRIGGER_WORD] aur mai iski puri detail tumhe dm kardunga."

### Template C: OPPORTUNITY
Use when the news reveals a market gap or builder opportunity. STRONG DEFAULT — pick this when in doubt.

Beats:
- Hook: "Bhai [shock fact about an industry/market]." Declarative. INR numbers if available.
- Bridge: "Ye ek problem hai aur tum isse [tech/AI/specific solution] se solve karke paise kama sakte ho."
- Body: Market size in crore/lakh + the specific gap + what kind of MVP would work + which existing players fall short
- Payoff: "Agar koi yeh structure banaye toh [specific outcome — revenue, scale, audience]."
- CTA: "Comment karo [TRIGGER_WORD] aur mai iska blueprint dm kardunga."

### Template D: TWIST
Use when the news is a trend, ruling, comparison, or policy that has a non-obvious second-order implication for the viewer. The hook teases the rule/fact; the payoff reveals the counterintuitive twist.

Real EZ Snippet example — China influencer rule:
- Hook: "Bhai China ek aisa rule lekar aaya hai jo agar India aaya, toh 90% influencers gayab ho jayenge."
- Bridge: States the rule clearly with the specific consequence (₹11.5 lakh fine + channel ban).
- Body: Names the affected categories (finance, medicine, law).
- TWIST/Payoff: "Lekin coding ya tech ke liye kuch nahi, kyunki hamare case mein degree se zyada matter karta hai GitHub."
- CTA: "Comment karo [TRIGGER_WORD] aur mai poori jaankari dm kardunga."

Beats:
- Hook: "Bhai [shock rule/fact/comparison]." Declarative, with numbers if available.
- Bridge: "Lekin iska real implication tum miss kar rahe ho." OR "Iska ek aisa side effect hai jo nobody talk kar raha."
- Body: 2-3 sentences laying out the rule/fact fully, then the *twist* — a surprising loophole, exception, or implication. The twist is the WHOLE point.
- Payoff: The twist itself is the payoff. No need for separate "you can build this" or "5 ways" — just land the reveal cleanly.
- CTA: "Comment karo [TRIGGER_WORD] aur mai iski poori detail dm kardunga."

When to pick TWIST over INSIGHT or OPPORTUNITY:
- News is a *comparison* (e.g., "Claude beat ChatGPT") with a non-obvious "why" → TWIST often beats INSIGHT
- News is a *regulation* (e.g., "China rule") with a loophole → TWIST often beats OPPORTUNITY
- News is a *trend* with a hidden cause → TWIST

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

Existing hook/angle for reference:
Hook: {hook}
Tech angle: {tech_angle}

STEP 1: Brainstorm 3 angles (one per template). Score each 1-10 on concreteness + audience value + hook potential.
STEP 2: Pick the highest-scoring angle. Tiebreak: OPPORTUNITY > TUTORIAL > INSIGHT.
STEP 3: Write the full script in EZ Snippet voice with HARD QUALITY BAR + PRESERVE SPECIFICS enforced.

Only reject (`script_worth_making: false`) if ALL FOUR angles score below 5 — i.e., the story genuinely has no concrete angle. Most stories have at least an OPPORTUNITY or TWIST angle if you look underneath the surface.

Output ONLY this JSON:

If APPROVING (the normal case):
{{
  "script_worth_making": true,
  "angles_considered": {{
    "opportunity": {{"summary": "1-line OPPORTUNITY angle", "score": 8}},
    "insight":     {{"summary": "1-line INSIGHT angle",     "score": 5}},
    "tutorial":    {{"summary": "1-line TUTORIAL angle",    "score": 6}},
    "twist":       {{"summary": "1-line TWIST angle",       "score": 7}}
  }},
  "chosen_template": "OPPORTUNITY | INSIGHT | TUTORIAL | TWIST",
  "why_chosen": "1 sentence on why this angle wins over the others",
  "hook_opener_used": "user-state | declarative | solution-announcement | direct-pain",
  "body_structure_used": "classic-numbered | cold-list | cascading-filter | question-driven | step-by-step | market-gap | twist-reveal",
  "specifics_preserved": ["list of specific numbers/names/terms you kept from the source"],
  "title": "Short script title",
  "script": "Full script as one block of Hinglish text starting with 'Bhai'. No stage directions.",
  "cta_word": "Single ALL-CAPS English word relevant to the topic",
  "estimated_seconds": 45,
  "word_count": 95,
  "notes_for_filming": "1-2 line b-roll / screen recording suggestion"
}}

If REJECTING (rare — only when all 4 score below 5):
{{
  "script_worth_making": false,
  "angles_considered": {{
    "opportunity": {{"summary": "...", "score": 3}},
    "insight":     {{"summary": "...", "score": 2}},
    "tutorial":    {{"summary": "...", "score": 4}},
    "twist":       {{"summary": "...", "score": 3}}
  }},
  "rejection_reason": "Why no angle reaches the bar",
  "alternative_angle": "What kind of follow-up news might unlock this story"
}}"""


def _build_client(api_key: str | None = None) -> OpenAI:
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY env var not set (or pass api_key arg)")
    return OpenAI(api_key=key)


VALID_TEMPLATES = {"OPPORTUNITY", "INSIGHT", "TUTORIAL", "TWIST"}


def generate_script(
    story: dict,
    client: OpenAI | None = None,
    api_key: str | None = None,
    template_override: str | None = None,
) -> dict:
    """Generate a full reel script for one story. Adds 'script' subdict to the story.

    template_override: if set to OPPORTUNITY/INSIGHT/TUTORIAL/TWIST, forces that template
    regardless of what the brainstorm would have picked.
    """
    client = client or _build_client(api_key)

    # Build optional override instruction
    override_instruction = ""
    if template_override:
        t = template_override.upper()
        if t not in VALID_TEMPLATES:
            raise ValueError(f"template_override must be one of {VALID_TEMPLATES}, got {t!r}")
        override_instruction = (
            f"\n\n⚠️ TEMPLATE OVERRIDE: The user has explicitly requested the {t} template. "
            f"Still brainstorm all 3 angles for visibility, but write the final script using "
            f"the {t} angle even if another scores higher. Set chosen_template to '{t}'."
        )

    user_prompt = USER_PROMPT_TEMPLATE.format(
        title=story.get("title", ""),
        source=story.get("source", ""),
        summary=(story.get("summary", "") or "")[:600],
        hook=story.get("hook", ""),
        tech_angle=story.get("tech_angle", ""),
    ) + override_instruction

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            max_tokens=1200,
            temperature=0.8,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        data = json.loads(resp.choices[0].message.content.strip())
        story["script"] = data
        logger.info("Generated %s script (%d words) for: %s",
                    data.get("chosen_template", data.get("template")),
                    data.get("word_count", 0),
                    story["title"][:60])
    except Exception as e:
        logger.error("Script generation failed for '%s': %s", story["title"][:60], e)
        story["script"] = {"error": str(e)}
    return story


def generate_scripts(
    stories: list[dict],
    api_key: str | None = None,
    template_override: str | None = None,
) -> list[dict]:
    """Generate scripts for multiple stories with optional template override."""
    client = _build_client(api_key)
    for s in stories:
        generate_script(s, client=client, template_override=template_override)
    return stories