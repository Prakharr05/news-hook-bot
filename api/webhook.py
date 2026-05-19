"""
Vercel serverless webhook for Telegram.

Routes:
  POST /api/webhook  — Telegram sends incoming messages here

Commands the bot understands:
  /help           — show available commands
  /digest         — re-send today's cached digest
  /script N       — generate full reel script for story #N

Each user uses their own OpenAI API key for /script. The key is looked up
by their Telegram chat ID via src/users.py.

Setup once (after deploy):
  curl -F "url=https://your-app.vercel.app/api/webhook" \\
       "https://api.telegram.org/bot<TOKEN>/setWebhook"
"""
from __future__ import annotations
import json
import logging
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# Vercel deploys this file with the repo root as the working dir,
# so `from src import ...` works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import script_gen, storage, telegram, users

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("webhook")


HELP_TEXT = (
    "🤖 *News Hook Bot commands:*\n\n"
    "`/digest` — Re\\-send today's top 8 digest\n"
    "`/more` — Show up to 50 additional headlines \\(no hooks, just titles\\)\n"
    "`/script N` — Generate reel script for story \\#N \\(auto template\\)\n"
    "`/script N opportunity` — Force OPPORTUNITY framing\n"
    "`/script N insight` — Force INSIGHT framing\n"
    "`/script N tutorial` — Force TUTORIAL framing\n"
    "`/script N twist` — Force TWIST framing\n"
    "`/help` — Show this message\n\n"
    "_Daily digest arrives automatically at 8:30 AM IST\\._"
)


def _send_text(chat_id: str, text: str) -> None:
    """Quick helper to send a plain text reply via Telegram. No markdown escaping concerns."""
    import os
    import httpx
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "MarkdownV2"},
        timeout=10.0,
    )


def handle_command(text: str, user: dict) -> None:
    """Route a slash-command. Sends reply via Telegram directly."""
    chat_id = user["chat_id"]
    api_key = user.get("openai_key")
    text = text.strip()

    if text in ("/start", "/help"):
        _send_text(chat_id, HELP_TEXT)
        return

    if text == "/digest":
        stories = storage.load_digest(chat_id=chat_id)
        if not stories:
            _send_text(chat_id, "No digest cached yet\\. Wait for the next 8:30 AM run\\.")
            return
        telegram.send(stories, chat_id=chat_id)
        return

    if text == "/more":
        headlines = storage.load_more_pool(chat_id=chat_id)
        if not headlines:
            _send_text(chat_id, "No additional headlines cached yet\\. Wait for the next 8:30 AM run\\.")
            return
        telegram.send_more_headlines(headlines, chat_id=chat_id)
        return

    if text.startswith("/script"):
        # Validate format: /script N  OR  /script N template
        parts = text.split()
        if len(parts) < 2 or len(parts) > 3 or not parts[1].isdigit():
            _send_text(chat_id,
                "Usage:\n"
                "`/script N` \\(auto\\-pick template\\)\n"
                "`/script N opportunity` \\(force OPPORTUNITY\\)\n"
                "`/script N insight` \\(force INSIGHT\\)\n"
                "`/script N tutorial` \\(force TUTORIAL\\)\n"
                "`/script N twist` \\(force TWIST\\)")
            return

        idx = int(parts[1]) - 1
        template_override = None
        if len(parts) == 3:
            t = parts[2].lower()
            if t not in {"opportunity", "insight", "tutorial", "twist"}:
                _send_text(chat_id, f"Unknown template `{parts[2]}`\\. Use opportunity, insight, tutorial, or twist\\.")
                return
            template_override = t.upper()

        # Rate limit
        allowed, count = storage.check_rate_limit(chat_id, max_per_hour=5)
        if not allowed:
            _send_text(
                chat_id,
                f"⚠️ Rate limit hit \\({count} scripts this hour, cap is 5\\)\\. "
                f"Try again in a bit\\.",
            )
            return

        stories = storage.load_digest(chat_id=chat_id)
        if not stories:
            _send_text(chat_id, "No digest cached\\. Wait for the next daily run\\.")
            return
        if idx < 0 or idx >= len(stories):
            _send_text(chat_id, f"Story \\#{idx + 1} out of range \\(digest has {len(stories)} stories\\)\\.")
            return

        # Acknowledge fast
        ack_msg = f"🎬 Generating script for story \\#{idx + 1}"
        if template_override:
            ack_msg += f" \\(forcing {template_override}\\)"
        ack_msg += "\\.\\.\\. \\(takes 10\\-20 sec\\)"
        _send_text(chat_id, ack_msg)

        if not api_key:
            _send_text(chat_id, "⚠️ No OpenAI key configured for your account\\. Contact admin\\.")
            return

        try:
            story = stories[idx]
            script_gen.generate_script(story, api_key=api_key, template_override=template_override)
            telegram.send_scripts([story], chat_id=chat_id)
        except Exception as e:
            log.exception("Script generation failed for chat %s", chat_id)
            _send_text(chat_id, f"⚠️ Script generation failed: `{str(e)[:200]}`")
        return

    _send_text(chat_id, "Unknown command\\. Try /help\\.")


class handler(BaseHTTPRequestHandler):
    """Vercel-required class name. Vercel routes POST requests here."""

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            update = json.loads(body)
            log.info("Incoming update: %s", update.get("update_id"))

            message = update.get("message") or update.get("edited_message")
            if not message:
                self._reply_ok()
                return

            from_user = message.get("from", {})
            chat_id = str(message.get("chat", {}).get("id", from_user.get("id")))
            text = message.get("text", "")

            user = users.get_user_by_chat_id(chat_id)
            if not user:
                log.warning("Unknown user %s tried to message the bot", chat_id)
                _send_text(chat_id, "Sorry, this bot is private\\. Ask the admin to add you\\.")
                self._reply_ok()
                return

            if text.startswith("/"):
                handle_command(text, user)
            else:
                _send_text(chat_id, "I only respond to commands\\. Try /help\\.")
        except Exception:
            log.error("Webhook handler crashed:\n%s", traceback.format_exc())
        finally:
            # ALWAYS return 200 to Telegram. Otherwise it retries indefinitely.
            self._reply_ok()

    def _reply_ok(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def do_GET(self):
        # Useful for verifying the deployment is alive
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"News hook bot webhook is alive.")