"""
News Hook Bot — entry point with two subcommands.

USAGE
=====

# Daily digest (the original flow — fetch, score, hook, send to Telegram)
python run.py                       # full pipeline
python run.py digest                # same as above (explicit)
python run.py digest --dry-run      # skip Telegram, print to stdout
python run.py digest --no-llm       # skip LLM (cheap test)
python run.py digest --save out.json

# On-demand script generation (NEW)
python run.py script                # generate script for top story of today's digest
python run.py script --index 2      # pick 2nd-ranked story instead
python run.py script --send         # also send the generated script to Telegram
python run.py script --all          # generate scripts for ALL stories in today's digest

The script command reads from the last saved digest at ./data/last_digest.json,
which is auto-saved every time the digest runs. So your workflow is:
  morning: digest runs (auto via cron) -> you read on Telegram -> pick a story
  later:   python run.py script --index 3 --send -> script arrives on Telegram
"""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Auto-load .env file if present (no-op in GitHub Actions, which uses real env vars)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src import fetcher, scorer, llm, script_gen, telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("news-hook-bot")

# Where the latest digest gets cached so `script` can read it back
DATA_DIR = Path("data")
LAST_DIGEST = DATA_DIR / "last_digest.json"


# ─────────────────────────────────────────────────────────────────────────────
# DIGEST subcommand
# ─────────────────────────────────────────────────────────────────────────────
def cmd_digest(args) -> int:
    log.info("Fetching news from all sources…")
    raw = asyncio.run(fetcher.fetch_all())
    log.info("Fetched %d raw stories", len(raw))

    log.info("Deduping and ranking…")
    top = scorer.rank(raw, top_n=args.top, min_score=args.min_score)
    log.info("Selected %d top stories", len(top))

    if not args.no_llm and top:
        log.info("Generating hooks with %s…", llm.MODEL)
        # Use the bot owner's key for hooks (your key, since you're paying for the digest)
        top = llm.generate_hooks(top)
        top.sort(key=lambda s: s["hook_score"] + s.get("llm_confidence", 0) * 2, reverse=True)

    # Local file cache (used by `python run.py script` CLI fallback)
    DATA_DIR.mkdir(exist_ok=True)
    LAST_DIGEST.write_text(json.dumps(top, indent=2, default=str))
    log.info("Cached digest locally to %s", LAST_DIGEST)

    # Persist to Upstash so the webhook can read it
    try:
        from src import storage
        storage.save_digest(top)
    except Exception as e:
        log.warning("Could not save digest to Upstash (webhook won't work): %s", e)

    if args.save:
        Path(args.save).write_text(json.dumps(top, indent=2, default=str))
        log.info("Also saved to %s", args.save)

    if args.dry_run:
        print(json.dumps(top, indent=2, default=str))
        return 0

    # Broadcast to all configured users (you + senior). Falls back to env if none.
    from src import users as users_mod
    user_list = users_mod.load_users()
    if user_list:
        log.info("Broadcasting digest to %d user(s)…", len(user_list))
        telegram.broadcast(top, user_list)
    else:
        log.info("Sending digest to single user via env vars…")
        telegram.send(top)
    log.info("Done.")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# SCRIPT subcommand — generate full reel script(s) on-demand
# ─────────────────────────────────────────────────────────────────────────────
def cmd_script(args) -> int:
    if not LAST_DIGEST.exists():
        log.error("No cached digest found at %s. Run `python run.py digest` first.", LAST_DIGEST)
        return 1

    stories = json.loads(LAST_DIGEST.read_text())
    if not stories:
        log.error("Cached digest is empty.")
        return 1

    if args.all:
        selected = stories
        log.info("Generating scripts for ALL %d stories in today's digest…", len(selected))
    else:
        idx = args.index - 1
        if idx < 0 or idx >= len(stories):
            log.error("Index %d out of range (digest has %d stories)", args.index, len(stories))
            return 1
        selected = [stories[idx]]
        log.info("Generating script for story #%d: %s", args.index, selected[0]["title"][:80])

    selected = script_gen.generate_scripts(
        selected,
        template_override=args.template.upper() if args.template else None,
    )

    for i, s in enumerate(selected, 1):
        scr = s.get("script", {}) or {}
        story_num = args.index if not args.all else i

        # Error case
        if "error" in scr:
            print(f"\n⚠️ Script gen failed for #{story_num}: {scr['error']}")
            continue

        print("\n" + "=" * 78)
        print(f"STORY #{story_num}: {s['title']}")
        print("─" * 78)

        # Show the brainstorm in all cases (rejected or not)
        angles = scr.get("angles_considered", {})
        if angles:
            print("Angles considered:")
            chosen = scr.get("chosen_template", "").upper()
            for k in ("opportunity", "insight", "tutorial"):
                a = angles.get(k, {})
                if a:
                    marker = "✅" if k.upper() == chosen else "  "
                    print(f"  {marker} {k.upper():<12} [{a.get('score', '?')}/10] {a.get('summary', '')}")
            print()

        # Rejection case
        if scr.get("script_worth_making") is False:
            print(f"⏭️  REJECTED — {scr.get('rejection_reason', '—')}")
            print(f"💡 Suggested next: {scr.get('alternative_angle', '—')}")
            print("=" * 78)
            continue

        # Success case
        template = scr.get("chosen_template", scr.get("template", "?"))
        print(f"Template: {template}  |  Source: {s['source']}  |  "
              f"~{scr.get('estimated_seconds', '?')}s  |  {scr.get('word_count', '?')} words")
        if scr.get("why_chosen"):
            print(f"Why this angle: {scr['why_chosen']}")
        print("─" * 78)
        print(scr.get("script", "(no script)"))
        print(f"\nCTA word: {scr.get('cta_word', '?')}")
        print(f"Filming notes: {scr.get('notes_for_filming', '—')}")
        print("=" * 78)

    if args.send:
        log.info("Sending generated script(s) to Telegram…")
        telegram.send_scripts(selected)

    return 0


# ─────────────────────────────────────────────────────────────────────────────
# CLI plumbing
# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(
        description="News hook bot — daily digest + on-demand script generation")
    sub = ap.add_subparsers(dest="cmd")

    d = sub.add_parser("digest", help="fetch news, rank, generate hooks, send to Telegram")
    d.add_argument("--dry-run",  action="store_true")
    d.add_argument("--no-llm",   action="store_true")
    d.add_argument("--top",      type=int, default=8)
    d.add_argument("--min-score", type=int, default=6)
    d.add_argument("--save",     type=str)

    s = sub.add_parser("script", help="generate full reel script from today's digest")
    s.add_argument("--index", type=int, default=1,
                   help="which story to script (1 = top, default)")
    s.add_argument("--all",   action="store_true",
                   help="generate scripts for every story in digest")
    s.add_argument("--send",  action="store_true",
                   help="also send generated script(s) to Telegram")
    s.add_argument("--template", type=str, default=None,
                   choices=["opportunity", "insight", "tutorial", "twist",
                            "OPPORTUNITY", "INSIGHT", "TUTORIAL", "TWIST"],
                   help="force a specific template instead of letting LLM pick")

    args = ap.parse_args()
    if args.cmd is None:
        args = ap.parse_args(["digest"] + sys.argv[1:])

    if args.cmd == "digest":
        return cmd_digest(args)
    elif args.cmd == "script":
        return cmd_script(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())