# Configuration Reference

## secrets.env

Place this file at `{DATA_DIR}/config/secrets.env`.

> **Env var naming:** This skill uses `TWITTER_CONSUMER_KEY` / `TWITTER_CONSUMER_SECRET`
> (x-compose compatible). Do NOT use `TWITTER_API_KEY` / `TWITTER_API_SECRET`.

```bash
# Polymarket
POLYMARKET_REFERRAL_ID=your_real_id_from_polymarket.com/refer

# X/Twitter — OAuth 1.0a + Bearer (from developer.x.com)
# NOTE: use TWITTER_CONSUMER_* (not TWITTER_API_*)
TWITTER_CONSUMER_KEY=your_consumer_key
TWITTER_CONSUMER_SECRET=your_consumer_secret
TWITTER_ACCESS_TOKEN=your_access_token
TWITTER_ACCESS_TOKEN_SECRET=your_access_token_secret
TWITTER_BEARER_TOKEN=your_bearer_token

# LLM (optional — enables LLM emoji, lead title, interest ranking)
COMPOSE_MODE=llm   # "template" or "llm"

# LLM via OpenRouter (recommended — uses your current model)
OPENAI_API_KEY=sk-or-v1-...
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=minimax/minimax-m2.7
LLM_MAX_TOKENS=8000   # increase for reasoning models (MiniMax needs high output tokens)

# Or use Anthropic directly
# ANTHROPIC_API_KEY=sk-ant-api03-...
# ANTHROPIC_BASE_URL=https://api.anthropic.com/v1
# ANTHROPIC_MODEL=claude-sonnet-4-20250514

# Pipeline settings
TOP_N_MOVERS=8
MIN_VOLUME_24H=2000
PUBLISH_HOUR_UTC=13
MAX_RETRIES=3

# Resolved market filter
PRICE_FLOOR=0.03
PRICE_CEILING=0.97

# Tag exclusions (comma-separated, case-insensitive)
SKIP_TAGS=temperature,weather,highest-temperature,lowest-temperature

# Diversity caps
MAX_PER_CATEGORY=2
MAX_SPORTS=2
MAX_CRYPTO=1

# Timeouts (seconds)
SCAN_TIMEOUT_SECONDS=1200
NEWS_ENRICH_TIMEOUT=300
COMPOSE_TIMEOUT_SECONDS=300
PUBLISH_TIMEOUT_SECONDS=180
URL_CHECK_TIMEOUT=8
NEWS_SEARCH_TIMEOUT=10

# Data directories
DATA_DIR=/path/to/polymarket-daily-movers
BRIEFS_DIR=/path/to/polymarket-daily-movers/briefs
```

## Directory layout

```
{DATA_DIR}/
├── config/
│   └── secrets.env           ← all credentials (fill in before running)
├── briefs/
│   └── {YYYY-MM-DD}/
│       ├── scan_output.json      ← Stage 1 output
│       ├── ranked.json           ← Stage 2 output
│       ├── enriched.json         ← Stages 3–5 output (modified in-place)
│       ├── tweets.json           ← Stage 6 output
│       ├── url_verification.json ← Stage 7 output
│       ├── publish_x.json       ← Stage 8 output (tweet IDs + status)
│       └── checkpoint.json       ← orchestrator state (idempotency/resume)
├── logs/
│   └── {YYYY-MM-DD}/
│       └── {stage}.out.log / .err.log
├── alerts/
│   └── latest.json              ← written on pipeline failure
└── scripts/
    ├── run_pipeline.py          ← one-shot orchestrator entry point
    ├── scanner/run.py
    ├── ranker/run.py
    ├── news_enricher/run.py
    ├── emoji_picker/run.py
    ├── interest_ranker/run.py
    ├── composer/run.py
    ├── url_verifier/run.py
    ├── publisher_x/run.py        ← posts via tweepy (uses TWITTER_CONSUMER_*)
    ├── post_tweet.js            ← posts via raw Twitter API v2 (uses TWITTER_CONSUMER_*)
    └── read_nitter.js           ← reads X posts for free via Nitter RSS
```

## First-time setup

1. Copy and fill in `config/secrets.env`
2. Set `DATA_DIR` to the skill's root directory
3. Install dependencies: `pip install requests httpx tweepy python-dotenv`
4. Run: `RUN_DATE=YYYY-MM-DD python3 scripts/run_pipeline.py`
5. Or post manually: `node scripts/post_tweet.js --thread "Tweet 1" "Tweet 2"`

## Environment variables consumed by each script

| Script | Env vars used |
|--------|-------------|
| `scanner/run.py` | `RUN_DATE`, `DATA_DIR`, `MIN_VOLUME_24H`, `PRICE_FLOOR`, `PRICE_CEILING`, `SKIP_TAGS` |
| `ranker/run.py` | `RUN_DATE`, `DATA_DIR`, `TOP_N_MOVERS`, `MAX_SPORTS`, `MAX_CRYPTO`, `MAX_PER_CATEGORY` |
| `news_enricher/run.py` | `RUN_DATE`, `DATA_DIR`, `NEWS_SEARCH_TIMEOUT`, `NEWS_ENRICH_TIMEOUT` |
| `emoji_picker/run.py` | `RUN_DATE`, `DATA_DIR`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` |
| `interest_ranker/run.py` | `RUN_DATE`, `DATA_DIR`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` |
| `composer/run.py` | `RUN_DATE`, `DATA_DIR`, `COMPOSE_MODE`, `POLYMARKET_REFERRAL_ID`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` |
| `url_verifier/run.py` | `RUN_DATE`, `DATA_DIR`, `POLYMARKET_REFERRAL_ID`, `URL_CHECK_TIMEOUT` |
| `publisher_x/run.py` | `RUN_DATE`, `DATA_DIR`, `TWITTER_BEARER_TOKEN`, `TWITTER_CONSUMER_KEY`, `TWITTER_CONSUMER_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_TOKEN_SECRET` |
| `post_tweet.js` | `TWITTER_CONSUMER_KEY`, `TWITTER_CONSUMER_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_TOKEN_SECRET` |
| `read_nitter.js` | (no credentials needed) |
