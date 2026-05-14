"""
News Hook Bot — daily entry point.

Usage:
    python run.py               # full pipeline: fetch -> rank -> hook -> Telegram
    python run.py --dry-run     # skip Telegram, dump JSON to stdout
    python run.py --no-llm      # skip the LLM hook generation (cheap test)
"""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Auto-load .env file if present (no-op in GitHub Actions, which uses real env vars)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src import fetcher, scorer, llm, telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("news-hook-bot")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run",  action="store_true", help="skip Telegram, print to stdout")
    ap.add_argument("--no-llm",   action="store_true", help="skip Claude hook generation")
    ap.add_argument("--top",      type=int, default=8, help="number of stories to include")
    ap.add_argument("--min-score",type=int, default=6, help="minimum hook score threshold")
    ap.add_argument("--save",     type=str, help="also save the digest JSON to this path")
    args = ap.parse_args()

    log.info("Fetching news from all sources…")
    raw = asyncio.run(fetcher.fetch_all())
    log.info("Fetched %d raw stories", len(raw))

    log.info("Deduping and ranking…")
    top = scorer.rank(raw, top_n=args.top, min_score=args.min_score)
    log.info("Selected %d top stories", len(top))

    if not args.no_llm and top:
        log.info("Generating hooks with Claude Haiku 4.5…")
        top = llm.generate_hooks(top)
        # re-sort: blend hook_score with LLM confidence
        top.sort(key=lambda s: s["hook_score"] + s.get("llm_confidence", 0) * 2, reverse=True)

    if args.save:
        Path(args.save).write_text(json.dumps(top, indent=2, default=str))
        log.info("Saved digest JSON to %s", args.save)

    if args.dry_run:
        print(json.dumps(top, indent=2, default=str))
        return 0

    log.info("Sending digest to Telegram…")
    telegram.send(top)
    log.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())