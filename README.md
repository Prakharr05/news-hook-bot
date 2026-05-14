# News Hook Bot

Daily Telegram digest of tech news ranked by **hook potential** — stories that grab attention in 3-4 seconds and have a clear bridge to tech-explainer content (EZ Snippet style).

## What it does

1. Pulls news from 10+ RSS feeds, Hacker News, and 3 subreddits in parallel.
2. Dedupes near-identical stories across outlets.
3. Scores each on hook potential — drama, scale, bots/AI/leaks, big-tech names, Indian context.
4. Top 8 stories go to Claude Haiku 4.5, which generates:
   - A 4–6 second spoken **hook**
   - A specific **tech angle** to bridge into your explainer
   - A confidence score
5. Sends the digest to your Telegram.

## Cost

- Anthropic API: ~₹0.50–2/day at Haiku 4.5 pricing
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
2. Add three secrets: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
3. The `.github/workflows/daily.yml` workflow runs at **08:30 IST every day**. Change the cron in that file to whatever time you want.
4. Trigger it manually first: **Actions → Daily News Digest → Run workflow** to confirm it works.

## Tuning

- **Add sources**: edit `src/sources.py`. Any RSS feed or Reddit `top.json` URL works.
- **Adjust hook keywords**: edit `HOOK_KEYWORDS` in `src/scorer.py`. Higher weight = more likely to make the cut.
- **More/fewer stories**: `python run.py --top 12 --min-score 4`
- **Different LLM model**: edit `MODEL` in `src/llm.py`. Sonnet 4.6 gives better hooks but ~10x cost.

## How the scoring works

Two signals combine: a keyword score (drama, scale, bot/AI terms, big-tech entities, Indian context) and a pattern score (numbers in headline, question titles, "how/why" openers). Title text is weighted 2x summary text because the headline IS the hook. Promos/listicles get negative weight. Diversity rule: max 2 stories per source in the final cut, so the digest doesn't turn into "TechCrunch x8".

## Project layout

```
news-hook-bot/
├── run.py                 # CLI entry point
├── requirements.txt
├── .env.example
├── .github/workflows/daily.yml
└── src/
    ├── sources.py         # RSS / HN / Reddit config
    ├── fetcher.py         # parallel async fetching
    ├── scorer.py          # dedupe + hook scoring
    ├── llm.py             # Claude Haiku hook generation
    └── telegram.py        # MarkdownV2 digest sender
```
