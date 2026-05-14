# News Hook Bot

Daily Telegram digest of tech news ranked by **hook potential** — stories that grab attention in 3-4 seconds and have a clear bridge to tech-explainer content (EZ Snippet style).

## What it does

1. Pulls news from 10+ RSS feeds, Hacker News, and 3 subreddits in parallel.
2. Dedupes near-identical stories across outlets.
3. Scores each on hook potential — drama, scale, bots/AI/leaks, big-tech names, Indian context.
4. Top 8 stories go to OpenAI's gpt-4o-mini, which generates:
   - A 4–6 second spoken **hook**
   - A specific **tech angle** to bridge into your explainer
   - A confidence score
5. Sends the digest to your Telegram.

## Cost

- OpenAI API: ~₹0.20–1/day at gpt-4o-mini pricing
- Everything else (RSS, HN, Reddit, Telegram, GitHub Actions): free

## Quick start

```bash
git clone <this repo>
cd news-hook-bot
pip install -r requirements.txt
cp .env.example .env       # then fill in keys

# Test without sending to Telegram or calling LLM
python run.py --dry-run --no-llm

# Test with LLM, dump JSON locally
python run.py --dry-run --save out.json

# Full run
python run.py
```

## Telegram setup (5 minutes)

1. Open Telegram → search **@BotFather** → `/newbot` → name it → copy the **token**.
2. Search for your new bot, send it any message (this opens the chat so it can DM you).
3. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser. Find the `"chat":{"id":...}` value — that's your **chat_id**.
4. Set the env vars and you're done.

## Daily automation (free, no server needed)

Push this repo to GitHub, then:
1. Repo → **Settings → Secrets and variables → Actions → New repository secret**
2. Add three secrets: `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
3. The `.github/workflows/daily.yml` workflow runs at **08:30 IST every day**. Change the cron in that file to whatever time you want.
4. Trigger it manually first: **Actions → Daily News Digest → Run workflow** to confirm it works.

## Tuning

- **Add sources**: edit `src/sources.py`. Any RSS feed or Reddit `top.json` URL works.
- **Adjust hook keywords**: edit `HOOK_KEYWORDS` in `src/scorer.py`. Higher weight = more likely to make the cut.
- **More/fewer stories**: `python run.py --top 12 --min-score 4`
- **Different LLM model**: edit `MODEL` in `src/llm.py`. `gpt-4o` gives better hooks but ~30x cost — still under ₹30/day for ~8 stories.

## How the scoring works

Two signals combine: a keyword score (drama, scale, bot/AI terms, big-tech entities, Indian context) and a pattern score (numbers in headline, question titles, "how/why" openers). Title text is weighted 2x summary text because the headline IS the hook. Promos/listicles get negative weight. Diversity rule: max 2 stories per source in the final cut, so the digest doesn't turn into "TechCrunch x8".

## Project layout

```
news-hook-bot/
├── run.py                 # CLI: `digest` (daily) and `script` (on-demand)
├── requirements.txt
├── .env.example
├── .github/workflows/daily.yml
├── data/                  # Auto-generated. Caches today's digest for `script` cmd.
└── src/
    ├── sources.py         # RSS / HN / Reddit config
    ├── fetcher.py         # parallel async fetching
    ├── scorer.py          # dedupe + hook scoring (tuned for EZ Snippet picks)
    ├── llm.py             # OpenAI hook + payoff generation (gpt-4o-mini)
    ├── script_gen.py      # OpenAI full reel script generation (gpt-4o)
    └── telegram.py        # MarkdownV2 digest + script sender
```

## The two-stage workflow

The bot has **two commands** because they serve different needs:

**1. `python run.py digest` (or just `python run.py`)** — the daily skim
Cheap to run, fetches news, ranks stories, generates a short hook + payoff for each, sends to Telegram. Runs automatically every day at 8:30 IST via GitHub Actions. You read the digest in 60 seconds and pick stories worth filming.

**2. `python run.py script --index N --send`** — full reel script on demand
Takes story #N from this morning's digest and generates a complete EZ Snippet-style script (Hook → Bridge → Body → CTA), ready to record. Costs ~₹3-5 per script on gpt-4o, but you only run it for stories you actually want to film. Use `--all` if you want scripts for every story in the digest (most days you'd run this only for the top 1-2).

Typical day:
- 8:30 AM — digest arrives on Telegram, you sip chai and pick story #3
- 8:45 AM — `python run.py script --index 3 --send`
- 9:00 AM — script arrives on Telegram, formatted as a code block for easy copy
- 9:15 AM — you film the reel using the script