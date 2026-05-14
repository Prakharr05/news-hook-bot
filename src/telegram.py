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
    score = s.get("hook_score", 0)
    conf = s.get("llm_confidence", 0)
    url = s["url"]   # URLs go inside () in MD links, not escaped

    parts = [
        f"*{idx}\\. {title}*",
        f"_{source} · score {score} · conf {conf}/10_",
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


def _send_chunks(chunks: list[str]) -> None:
    """Shared helper used by both send() and send_scripts()."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

    url = API_BASE.format(token=token)
    with httpx.Client(timeout=20.0) as client:
        for chunk in chunks:
            payload = {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "MarkdownV2",
                "disable_web_page_preview": True,
            }
            r = client.post(url, json=payload)
            if r.status_code != 200:
                logger.error("Telegram send failed: %s %s", r.status_code, r.text)
                # Retry once without markdown if it's a parse error
                payload.pop("parse_mode", None)
                payload["text"] = chunk.replace("\\", "")
                client.post(url, json=payload)
            time.sleep(0.5)   # be nice to the Telegram rate limit
    logger.info("Sent %d message chunks to Telegram", len(chunks))


def send(stories: list[dict]) -> None:
    """Send the daily digest (hooks + payoffs, not full scripts)."""
    if not stories:
        chunks = [_escape_md("No high-score news today — try lowering min_score.")]
    else:
        chunks = format_digest(stories)
    _send_chunks(chunks)


def send_scripts(stories: list[dict]) -> None:
    """Send full reel scripts. One Telegram message per script for easy copy-paste."""
    if not stories:
        _send_chunks([_escape_md("No scripts to send.")])
        return

    chunks: list[str] = []
    for s in stories:
        scr = s.get("script", {}) or {}
        if "error" in scr:
            chunks.append(_escape_md(f"⚠️ Script gen failed for: {s['title']}\n{scr['error']}"))
            continue

        title = _escape_md(s["title"])
        source = _escape_md(s["source"])
        template = _escape_md(scr.get("template", "?"))
        secs = scr.get("estimated_seconds", "?")
        words = scr.get("word_count", "?")
        cta = _escape_md(scr.get("cta_word", "?"))
        notes = _escape_md(scr.get("notes_for_filming", "—"))
        script_text = _escape_md(scr.get("script", "(no script)"))
        url = s["url"]

        # Use ``` code block for the script body so copy-paste preserves whitespace
        # and Telegram renders it monospace (easy to read for filming).
        block = (
            f"🎬 *REEL SCRIPT*\n"
            f"*Story:* {title}\n"
            f"_{source} · {template} · ~{secs}s · {words} words_\n\n"
            f"```\n{scr.get('script', '')}\n```\n\n"
            f"🔁 *CTA word:* `{scr.get('cta_word', '?')}`\n"
            f"🎥 *Filming:* {notes}\n"
            f"[Read source]({url})"
        )
        chunks.append(block)

    _send_chunks(chunks)