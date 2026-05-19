"""
Sends the daily digest to Telegram via Bot API.

Setup:
  1. Open Telegram, search @BotFather, run /newbot, copy the token
  2. Message your new bot once (any text) so it can DM you
  3. Visit https://api.telegram.org/bot<TOKEN>/getUpdates to find your chat_id
  4. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars
"""
from __future__ import annotations
import logging
import os
import time
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_MSG_LIMIT = 4000   # 4096 is the hard limit; leave headroom


def _escape_md(text: str) -> str:
    """Escape MarkdownV2 special chars. Backslash first to avoid double-escaping."""
    text = text.replace("\\", "\\\\")
    for ch in "_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, "\\" + ch)
    return text


def _format_story(idx: int, s: dict) -> str:
    title = _escape_md(s["title"])
    source = _escape_md(s["source"])
    hook = _escape_md(s.get("hook", "") or "(no hook generated)")
    pivot = _escape_md(s.get("pivot", "") or "")
    angle = _escape_md(s.get("tech_angle", "") or "(no angle generated)")
    payoff = _escape_md((s.get("payoff_structure", "") or "").upper())
    lean = _escape_md(s.get("template_lean", "") or "")
    score = s.get("hook_score", 0)
    conf = s.get("llm_confidence", 0)
    url = s["url"]   # URLs go inside () in MD links, not escaped

    # Emoji per template lean for quick scanning
    lean_emoji = {
        "OPPORTUNITY": "💼",
        "INSIGHT": "🧠",
        "TUTORIAL": "🛠️",
        "TWIST": "🌀",
    }.get(s.get("template_lean", ""), "📰")

    parts = [
        f"*{idx}\\. {lean_emoji} {title}*",
        f"_{source} · {lean} · score {score} · conf {conf}/10_",
        "",
        f"🎬 *Hook:* {hook}",
    ]
    if pivot:
        parts.append(f"➡️ *Pivot:* {pivot}")
    if payoff:
        parts.append(f"🧩 *Structure:* {payoff}")
    parts.append(f"💡 *Payoff:* {angle}")
    parts.append(f"[Read]({url})")
    return "\n".join(parts)


def format_digest(stories: list[dict]) -> list[str]:
    """Returns a list of message chunks under Telegram's size limit."""
    date_str = datetime.now().strftime("%a, %d %b %Y")
    header = f"📰 *News Hook Digest* — _{_escape_md(date_str)}_\n_{len(stories)} stories ranked_\n"

    chunks: list[str] = []
    current = header
    for i, s in enumerate(stories, 1):
        block = "\n\n" + _format_story(i, s)
        if len(current) + len(block) > TELEGRAM_MSG_LIMIT:
            chunks.append(current)
            current = block.lstrip()
        else:
            current += block
    if current.strip():
        chunks.append(current)
    return chunks


def _send_chunks(chunks: list[str], chat_id: str | None = None, bot_token: str | None = None) -> None:
    """Shared helper used by both send() and send_scripts().

    chat_id and bot_token can be overridden per call (for multi-user broadcasts).
    Falls back to env vars otherwise.
    """
    token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    cid = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not cid:
        raise RuntimeError("Telegram bot token and chat_id required")

    url = API_BASE.format(token=token)
    with httpx.Client(timeout=20.0) as client:
        for chunk in chunks:
            payload = {
                "chat_id": cid,
                "text": chunk,
                "parse_mode": "MarkdownV2",
                "disable_web_page_preview": True,
            }
            r = client.post(url, json=payload)
            if r.status_code != 200:
                logger.error("Telegram send failed (chat %s): %s %s", cid, r.status_code, r.text)
                payload.pop("parse_mode", None)
                payload["text"] = chunk.replace("\\", "")
                client.post(url, json=payload)
            time.sleep(0.5)
    logger.info("Sent %d chunks to Telegram chat %s", len(chunks), cid)


def send(stories: list[dict], chat_id: str | None = None) -> None:
    """Send digest. If chat_id given, sends only there; otherwise uses env var."""
    if not stories:
        chunks = [_escape_md("No high-score news today — try lowering min_score.")]
    else:
        chunks = format_digest(stories)
    _send_chunks(chunks, chat_id=chat_id)


def broadcast(stories: list[dict], users: list[dict]) -> None:
    """Send digest to multiple users. Each user has their own chat_id + optional feed_filter.

    If a user has feed_filter set, only stories from those categories are sent.
    Otherwise the user sees all stories.
    """
    if not users:
        logger.warning("broadcast: no users configured, falling back to env TELEGRAM_CHAT_ID")
        send(stories)
        return
    from src import users as users_mod
    for u in users:
        try:
            user_stories = users_mod.filter_stories_for_user(stories, u)
            if not user_stories and u.get("feed_filter"):
                logger.info("User %s has feed_filter %s but no matching stories today",
                            u.get("name", "?"), u.get("feed_filter"))
            send(user_stories, chat_id=u["chat_id"])
            logger.info("Sent %d stories to %s (chat %s)",
                        len(user_stories), u.get("name", "?"), u["chat_id"])
        except Exception as e:
            logger.error("Failed to send digest to %s: %s", u.get("name", "?"), e)


def send_more_headlines(headlines: list[dict], chat_id: str | None = None) -> None:
    """Send a compact list of additional headlines (title + source + link).

    No hooks, no payoffs — just enough to scan for stories worth pursuing.
    Chunks into multiple messages if needed to stay under Telegram's 4000-char limit.
    """
    if not headlines:
        _send_chunks([_escape_md("No additional headlines today. Try again tomorrow.")], chat_id=chat_id)
        return

    lean_emoji = {"OPPORTUNITY": "💼", "INSIGHT": "🧠", "TUTORIAL": "🛠️", "TWIST": "🌀"}

    date_str = datetime.now().strftime("%a, %d %b %Y")
    header = f"📋 *More headlines* — _{_escape_md(date_str)}_\n_{len(headlines)} additional stories beyond today's digest_\n"

    chunks: list[str] = [header]
    current = ""

    for i, h in enumerate(headlines, 1):
        emoji = lean_emoji.get(h.get("template_lean", ""), "📰")
        title = _escape_md(h["title"][:140])
        source = _escape_md(h.get("source", ""))
        score = h.get("hook_score", 0)
        url = h["url"]

        line = f"\n{i}\\. {emoji} [{title}]({url})\n   _{source} · score {score}_"

        # Telegram limit is 4096; leave headroom
        if len(chunks[-1]) + len(line) > 3800:
            chunks.append(line.lstrip())
        else:
            chunks[-1] += line

    _send_chunks(chunks, chat_id=chat_id)
    """Send full reel scripts. Optionally to a specific chat (used by the webhook)."""
    if not stories:
        _send_chunks([_escape_md("No scripts to send.")], chat_id=chat_id)
        return

    chunks: list[str] = []
    for s in stories:
        scr = s.get("script", {}) or {}
        if "error" in scr:
            chunks.append(_escape_md(f"⚠️ Script gen failed for: {s['title']}\n{scr['error']}"))
            continue

        # Rejection — show the brainstorm so user sees why
        if scr.get("script_worth_making") is False:
            title = _escape_md(s["title"])
            reason = _escape_md(scr.get("rejection_reason", "no reason given"))
            alt = _escape_md(scr.get("alternative_angle", "—"))
            angles = scr.get("angles_considered", {})
            angles_text = ""
            for k in ("opportunity", "insight", "tutorial", "twist"):
                a = angles.get(k, {})
                if a:
                    angles_text += f"\n• *{k.upper()}* \\({a.get('score', '?')}/10\\): {_escape_md(a.get('summary', ''))}"
            chunks.append(
                f"⏭️ *No strong angle found*\n"
                f"*Story:* {title}\n"
                f"{angles_text}\n\n"
                f"*Why rejected:* {reason}\n"
                f"💡 *Next:* {alt}"
            )
            continue

        title = _escape_md(s["title"])
        source = _escape_md(s["source"])
        template = _escape_md(scr.get("chosen_template", scr.get("template", "?")))
        secs = scr.get("estimated_seconds", "?")
        words = scr.get("word_count", "?")
        notes = _escape_md(scr.get("notes_for_filming", "—"))
        url = s["url"]

        # Show the brainstorm so you see the rejected angles too
        angles = scr.get("angles_considered", {})
        angles_text = ""
        for k in ("opportunity", "insight", "tutorial", "twist"):
            a = angles.get(k, {})
            if a:
                marker = "✅" if k.upper() == scr.get("chosen_template", "") else "  "
                angles_text += f"\n{marker} *{k.upper()}* \\({a.get('score', '?')}/10\\): {_escape_md(a.get('summary', ''))}"

        block = (
            f"🎬 *REEL SCRIPT*\n"
            f"*Story:* {title}\n"
            f"_{source} · {template} · ~{secs}s · {words} words_\n"
            f"{angles_text}\n\n"
            f"```\n{scr.get('script', '')}\n```\n\n"
        )

        # Show what specifics the LLM claims to have preserved (quality signal)
        specifics = scr.get("specifics_preserved") or []
        if specifics:
            specs_text = ", ".join(_escape_md(str(x)) for x in specifics[:6])
            block += f"📌 *Specifics kept:* {specs_text}\n"

        # Show structural choices — helps you spot if the LLM is defaulting
        opener = scr.get("hook_opener_used")
        body = scr.get("body_structure_used")
        if opener or body:
            structure_bits = []
            if opener:
                structure_bits.append(f"opener: {_escape_md(opener)}")
            if body:
                structure_bits.append(f"body: {_escape_md(body)}")
            block += f"🏗️ *Structure:* {' · '.join(structure_bits)}\n"

        block += (
            f"🔁 *CTA word:* `{scr.get('cta_word', '?')}`\n"
            f"🎥 *Filming:* {notes}\n"
            f"[Read source]({url})"
        )
        chunks.append(block)

    _send_chunks(chunks, chat_id=chat_id)