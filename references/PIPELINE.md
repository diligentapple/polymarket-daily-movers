# Pipeline Reference

## Stage overview

| # | Stage | Script | Output file | Timeout | Critical? |
|---|-------|--------|-------------|---------|-----------|
| 1 | Scanner | `scanner/run.py` | `scan_output.json` | 1200s | ✅ |
| 2 | Ranker | `ranker/run.py` | `ranked.json` | 120s | ✅ |
| 3 | News Enricher | `news_enricher/run.py` | `enriched.json` | 300s | ❌ |
| 4 | Emoji Picker | `emoji_picker/run.py` | `enriched.json` | 60s | ❌ |
| 5 | Interest Ranker | `interest_ranker/run.py` | `enriched.json` | 60s | ❌ |
| 6 | Composer | `composer/run.py` | `tweets.json` | 300s | ✅ |
| 7 | URL Verifier | `url_verifier/run.py` | `url_verification.json` | 120s | ❌ |
| 8 | X Publisher | `publisher_x/run.py` | `publish_x.json` | 180s | ✅ |

**Critical stages:** halt pipeline on failure.
**Non-critical stages:** produce a fallback output and continue if they fail.

---

## Stage details

### Stage 1: Scanner

Fetches all active, unresolved Polymarket markets via Gamma API. Filters out low-volume, expired, and resolved markets. Enriches each market with 24h price history and order book data.

**Filters applied:**
1. `volume_24h < $2,000` → skip
2. Market end date passed → skip
3. Tags match `SKIP_TAGS` (temperature, weather) → skip
4. `price_now >= 0.97` or `<= 0.03` (resolved) → skip
5. Post-enrichment resolved re-check → skip

**Output fields per market:** `condition_id`, `market_slug`, `event_slug`, `question`, `primary_token_id`, `price_now`, `price_24h_ago`, `volume_24h`, `liquidity`, `best_bid`, `best_ask`, `spread`, `market_url`, `primary_outcome`, `all_outcomes`, `tag_slugs`, `is_sports`, `end_date`

---

### Stage 2: Ranker

Scores and selects the top N movers with diversity constraints.

**Score formula:**
```
raw_score = |price_now - price_24h_ago| × log(1 + volume_24h) / (1 + spread)
mover_score = raw_score × editorial_weight × volume_confidence
```

**Editorial weights:**
- Geopolitics, Ukraine, Israel: 1.5–1.8×
- Politics, elections, trade, fed: 1.4–1.6×
- AI, tech: 1.3–1.4×
- Crypto (general): 1.0×
- Crypto up/down intraday: 0.4×
- Sports: 0.6–0.7×

**Volume confidence:**
- `$0–$5K`: 0.3×
- `$5K–$20K`: 0.6×
- `$20K+`: 1.0×

**Diversity constraints (applied in order):**
1. No two markets from the same `event_slug`
2. Max 1 per person (MrBeast, Trump), max 1 per crypto coin, max 1 per award race, max 2 per general entity
3. Max 2 per tag/category
4. Max 2 total sports markets
5. Max 1 total crypto market

---

### Stage 3: News Enricher

Searches the web for recent news explaining WHY each market moved. Uses DuckDuckGo HTML search with Google News RSS fallback.

**Failure:** non-critical. Copies `ranked.json` → `enriched.json` and continues.

---

### Stage 4: Emoji Picker

Assigns the best emoji to each mover via LLM batch call. Falls back to static keyword map.

**Fallback emoji map (partial):**
- `bitcoin`→₿ `ethereum`→⟠ `crypto`→🪙
- `nba`→🏀 `nfl`→🏈 `mlb`→⚾ `esports`/`lol`/`cs2`→🎮
- `ai`→🤖 `tech`→💻 `spx`/`stocks`→📈
- `politics`/`trump`→🇺🇸 `ukraine`→🇺🇦 `china`→🇨🇳
- 40+ team names (MLB, NBA, NFL) mapped to sport emojis
- Last-resort heuristics: vs/match→⚽, price/$→📈, election→🗳️, war→⚔️, tweet→🐦
- Default: 📌 (should rarely appear now)

**Failure:** non-critical. Uses static fallback map.

---

### Stage 5: Interest Ranker

Reorders movers from most to least engaging/shareable via LLM. Forces crypto to the end regardless of LLM ranking.

**Failure:** non-critical. Keeps mover-score order.

---

### Stage 6: Composer

Generates a tweet thread (1 lead + N replies) from the ranked, enriched movers.

**Lead tweet:** branded `📊 𝗣𝗼𝗹𝘆𝗺𝗮𝗿𝗸𝗲𝘁 𝗡𝗲𝘄𝘀` header + 3 diverse NON-crypto movers with emoji, 📈/📉 direction indicators, short question, old%→new%. Ends with `Show more`.

**Reply structure (v13+):**
```
{emoji} {Unicode bold theme}

{shortened question}
{outcome}: {pct}% {📈/📉} ({old}→{new}%, {±vol} vol)

{context line — news-aware or analytical}

➜  {polymarket URL}
```

**Context line:** news headline woven naturally (if news exists) or analytical template explaining repricing. Volume is NOT mentioned in context (already in pct_line). Headlines trimmed to 55 chars max.

**Length enforcement:** `_trim_to_limit()` progressively shortens replies (context line → question → blank lines → hard truncate). Safety net in `main()` catches any remaining overruns.

**Validation:** every reply must have context ≥15 chars; no placeholders; all ≤280 effective chars (BMP-aware counting: Unicode bold chars = 2 chars each).

---

### Stage 7: URL Verifier

HEAD-requests every `polymarket.com/event/` URL in composed tweets. Fixes 404s by replacing with generic `polymarket.com` fallback.

**Failure:** non-critical. Even with generic fallbacks the thread publishes.

---

### Stage 8: X Publisher

Posts the thread to X via Twitter API v2 OAuth 1.0a.

**Preflight blockers (blocks posting entirely):**
- Any `{{`, `}}`, `__FILL_IN__`, `SUBSTACK_URL` placeholder
- Any tweet >280 effective chars
- Any reply missing a `polymarket.com/event/` URL

**Post sequence:** lead → reply 1 → reply 2... with 1.5s delay between tweets.

**Env vars:** `TWITTER_CONSUMER_KEY`, `TWITTER_CONSUMER_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_TOKEN_SECRET`, `TWITTER_BEARER_TOKEN`

---

## Orchestrator (run_pipeline.py)

The `run_pipeline.py` script at the root of `scripts/` is the entry point. It:

1. Reads `config/secrets.env` for credentials
2. Loads or creates a checkpoint for the given date
3. Runs each stage in order, spawning subagents as subprocesses
4. Validates output after each critical stage
5. On non-critical stage failure: creates fallback output and advances
6. On critical stage failure: writes alert, stops
7. Writes checkpoint state after each stage

**Resume behavior:** if a checkpoint exists with a partial state, the orchestrator skips completed stages and resumes from the current one.

**Idempotency:** if an output file already exists and is valid, the stage is skipped.
