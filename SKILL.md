---
name: polymarket-daily-movers
description: >-
    Run the Polymarket Daily Mover pipeline end-to-end: scan Polymarket markets,
    rank movers, enrich with news, compose and publish a Twitter/X thread.
    Also read and monitor X posts via the bundled x-compose scripts.
    Triggers on requests to: (1) run the daily pipeline, (2) generate a Polymarket
    brief or movers thread, (3) post to X about prediction market moves, (4) check
    or resume the pipeline for a specific date, (5) update Polymarket pipeline config
    or emoji maps, (6) troubleshoot a failed pipeline stage, (7) read someone's
    tweets or monitor X activity.
    Does NOT trigger on general questions about Polymarket markets or prices without
    a pipeline or workflow request.
---

# Polymarket Daily Mover Pipeline

Runs daily at 13:00 UTC (configurable). Produces a Twitter/X thread of the top prediction market movers with news context, emoji tags, and Polymarket referral links.

## Quick start

```bash
# Run full pipeline
RUN_DATE=2026-04-06 python3 scripts/run_pipeline.py

# Post the composed thread to X
node scripts/post_tweet.js --thread "Tweet 1" "Tweet 2" "Tweet 3"

# Read a user's recent tweets (free, no credentials)
node scripts/read_nitter.js elonmusk 10
```

## Pipeline overview (8 stages)

| # | Stage | Script | Critical |
|---|-------|--------|----------|
| 1 | Scanner | `scanner/run.py` | ✅ |
| 2 | Ranker | `ranker/run.py` | ✅ |
| 3 | News Enricher | `news_enricher/run.py` | ❌ |
| 4 | Emoji Picker | `emoji_picker/run.py` | ❌ |
| 5 | Interest Ranker | `interest_ranker/run.py` | ❌ |
| 6 | Composer | `composer/run.py` | ✅ |
| 7 | URL Verifier | `url_verifier/run.py` | ❌ |
| 8 | X Publisher | `publisher_x/run.py` | ✅ |

## Running the pipeline stage-by-stage

Set `DATA_DIR` and `RUN_DATE` first, then run each stage:

```bash
export DATA_DIR="$(dirname $PWD)"
export RUN_DATE="2026-04-06"

python3 scripts/scanner/run.py         # → scan_output.json
python3 scripts/ranker/run.py          # → ranked.json
python3 scripts/news_enricher/run.py   # → enriched.json
python3 scripts/emoji_picker/run.py    # adds emoji to enriched.json
python3 scripts/interest_ranker/run.py # reorders enriched.json
python3 scripts/composer/run.py        # → tweets.json
python3 scripts/url_verifier/run.py    # validates URLs in tweets.json
python3 scripts/publisher_x/run.py     # posts tweets.json to X
```

Or run everything in one shot:
```bash
RUN_DATE=2026-04-06 python3 scripts/run_pipeline.py
```

## Posting to X — two methods

### Method A: publisher_x/run.py (pipeline integration)

Reads `tweets.json`, validates, and posts the full thread. Configure credentials in `config/secrets.env` first.

```bash
python3 scripts/publisher_x/run.py
```

### Method B: post_tweet.js (direct, flexible)

Single tweets, threads, replies, and quote tweets. Uses Twitter API v2 OAuth 1.0a.

```bash
# Single tweet
node scripts/post_tweet.js "Hello world!"

# Thread (chains via reply-to automatically)
node scripts/post_tweet.js --thread "First tweet" "Second tweet" "Third tweet"

# Reply to an existing tweet
node scripts/post_tweet.js --reply-to 2041067159141634377 "Great thread!"

# Quote tweet
node scripts/post_tweet.js --quote 2041067159141634377 "My commentary on this"
```

## Reading X posts (free — no credentials needed)

Uses Nitter RSS instances. No Twitter API required.

```bash
# Latest 10 tweets from a user
node scripts/read_nitter.js elonmusk

# Last 5 tweets
node scripts/read_nitter.js elonmusk 5

# Tweets from a specific date
node scripts/read_nitter.js elonmusk 20 "2026-04-03"

# Get a specific user's timeline (full URL)
node scripts/read_nitter.js https://nitter.net/elonmusk
```

## Checkpoint and resume

After each stage, a checkpoint is saved at `{DATA_DIR}/briefs/{RUN_DATE}/checkpoint.json`. Re-running with the same date skips completed stages automatically.

```bash
# Resume from where it left off
RUN_DATE=2026-04-06 python3 scripts/run_pipeline.py
```

## Credentials (in `config/secrets.env`)

```
# Polymarket
POLYMARKET_REFERRAL_ID=your_id_from_polymarket.com/refer

# X/Twitter — use TWITTER_CONSUMER_* (matches x-compose skill)
TWITTER_CONSUMER_KEY=your_consumer_key
TWITTER_CONSUMER_SECRET=your_consumer_secret
TWITTER_ACCESS_TOKEN=your_access_token
TWITTER_ACCESS_TOKEN_SECRET=your_access_token_secret
TWITTER_BEARER_TOKEN=your_bearer_token

# LLM (optional — enables LLM emoji, lead title, interest ranking)
COMPOSE_MODE=template   # or "llm"
ANTHROPIC_API_KEY=sk-ant-api03-...
# or
OPENAI_API_KEY=sk-...
```

> **Note:** `post_tweet.js` uses `TWITTER_CONSUMER_KEY`/`TWITTER_CONSUMER_SECRET`. `publisher_x/run.py` uses the same names. Do not use `TWITTER_API_KEY`/`TWITTER_API_SECRET` — those are a different naming convention.

## Key pipeline settings

| Variable | Default | Description |
|----------|---------|-------------|
| `MIN_VOLUME_24H` | 2000 | Minimum 24h volume in dollars |
| `TOP_N_MOVERS` | 8 | Number of movers to rank |
| `MAX_SPORTS` | 2 | Max sports markets in top N |
| `MAX_CRYPTO` | 1 | Max crypto markets in top N |
| `MAX_PER_CATEGORY` | 2 | Max per tag/category |

## Emoji maps

To fix a market that got 📌, edit **one file**:
- `config/emoji_map.json` — both emoji_picker and composer load from here

For new sports leagues, also add the slug to `scripts/scanner/run.py` → `_SPORTS_KEYWORDS`.

The `emoji_map.json` has three sections:
- `"map"`: keyword → emoji mappings
- `"priority"`: order in which keywords are checked (specific before generic)
- `"default"`: fallback emoji when nothing matches (📌)

## Dependencies

```bash
pip install requests httpx tweepy python-dotenv
node (v14+)
npm install -g nitter-rss  # optional, for read_nitter.js (uses hardcoded instances)
```

## Reference files

- **`references/CONFIG.md`** — full secrets.env template and env var reference
- **`references/PIPELINE.md`** — stage-by-stage breakdown, score formulas, diversity rules
- **`references/CHECKLIST.md`** — 14-item pre-launch checklist before daily production
- **`assets/sample_thread.txt`** — what the final thread looks like
