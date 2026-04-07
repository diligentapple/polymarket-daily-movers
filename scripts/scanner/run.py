"""
Scanner subagent v2.
Fetches active, UNRESOLVED markets from Polymarket Gamma API.
Enriches with 24h price history and order book data from CLOB API.
Filters out resolved markets, expired markets, and excluded tags.

INPUT: Environment variables (RUN_DATE, MIN_VOLUME_24H, PRICE_FLOOR, PRICE_CEILING, SKIP_TAGS)
OUTPUT: {DATA_DIR}/briefs/{date}/scan_output.json (atomic write)
EXIT: 0 on success, 1 on failure
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

DATA_DIR = Path(os.environ.get("DATA_DIR", "/home/diligentapple/.openclaw/workspace/polymarket"))
DATE = os.environ.get("RUN_DATE", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
OUTPUT_DIR = DATA_DIR / "briefs" / DATE
OUTPUT_FILE = OUTPUT_DIR / "scan_output.json"
TMP_FILE = OUTPUT_DIR / "scan_output.tmp.json"

MIN_VOLUME = float(os.environ.get("MIN_VOLUME_24H", 2000))
PRICE_FLOOR = float(os.environ.get("PRICE_FLOOR", 0.03))
PRICE_CEILING = float(os.environ.get("PRICE_CEILING", 0.97))
SKIP_TAGS_RAW = os.environ.get("SKIP_TAGS", "temperature,weather,highest-temperature,lowest-temperature")
SKIP_TAGS = set(t.strip().lower() for t in SKIP_TAGS_RAW.split(",") if t.strip())

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"

NOW = datetime.now(timezone.utc)

# ── Sports keyword set ─────────────────────────────────────────────────────────
_SPORTS_KEYWORDS = {
    "mls", "nfl", "nba", "nhl", "mlb", "ufc", "epl", "la-liga",
    "serie-a", "bundesliga", "ligue-1", "champions-league", "mma",
    "fight-night", "premier-league", "soccer", "football", "basketball",
    "baseball", "hockey", "boxing", "cricket", "tennis", "f1",
    "sports", "ncaa", "ncaab", "ncaaw", "ncaafb", "ncaamb", "ncaawb",
    "college-basketball", "college-football",
    "nbl", "a-league", "afl", "rugby", "super-rugby", "six-nations",
    "copa-america", "copa-libertadores", "liga-mx",
    "esports", "e-sports", "counter-strike", "cs2", "csgo",
    "dota", "dota2", "league-of-legends", "valorant",
    "overwatch", "call-of-duty", "faze", "navi",
    # v7 additions
    "march-madness", "final-four", "sweet-sixteen", "elite-eight",
    "art-ross", "hart-trophy", "norris-trophy", "vezina", "calder",
    "selke", "stanley-cup", "nhl-awards", "wnba",
    "euroleague", "uefa",
    "cba", "bkcba", "chinese-basketball",
}

_AWARD_KEYWORDS = [
    "trophy", "art ross", "hart memorial", "mvp", "norris",
    "vezina", "calder", "selke", "golden boot", "ballon d'or",
    "heisman", "cy young",
]

def fetch_active_markets():
    """Paginate through all active, non-closed markets from Gamma."""
    markets = []
    offset = 0
    limit = 100
    while True:
        resp = requests.get(
            f"{GAMMA_BASE}/markets",
            params={
                "limit": limit,
                "offset": offset,
                "closed": "false",
                "active": "true",
                "order": "volume24hr",
                "ascending": "false",
            },
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        markets.extend(batch)
        offset += limit
        time.sleep(0.3)
    return markets

def parse_json_field(raw, fallback=None):
    """Safely parse a JSON-encoded string field, or return the value if already parsed."""
    if fallback is None:
        fallback = []
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return fallback
    return raw if raw is not None else fallback

def extract_tag_slugs(market: dict) -> list:
    """Pull normalized tag slugs from a market object."""
    tags = parse_json_field(market.get("tags"), [])
    slugs = []
    for t in tags:
        if isinstance(t, dict):
            slug = t.get("slug", t.get("label", "")).lower().strip()
        elif isinstance(t, str):
            slug = t.lower().strip()
        else:
            continue
        if slug:
            slugs.append(slug)
    return slugs

def is_sports_market(tag_slugs: list, question: str) -> bool:
    """Heuristic: does this market look like a sports event?"""
    q_lower = question.lower()

    # Check tags first
    for slug in tag_slugs:
        if slug in _SPORTS_KEYWORDS:
            return True

    # Award keyword heuristic
    for kw in _AWARD_KEYWORDS:
        if kw in q_lower:
            return True

    # NCAA tournament heuristic
    if "ncaa" in q_lower or "march madness" in q_lower or "tournament winner" in q_lower:
        return True

    # Common sports patterns: "Team A vs Team B on [date]"
    if (" vs " in q_lower or " vs. " in q_lower) and any(
        s in q_lower for s in ["win", "championship", "final", "playoffs", "season"]
    ):
        return True

    return False

def market_is_expired(market: dict) -> bool:
    """Check if the market's end date has already passed."""
    end_date_str = market.get("endDate") or market.get("end_date_iso")
    if not end_date_str:
        return False
    try:
        end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        return end_dt < NOW
    except (ValueError, TypeError):
        return False

def fetch_price_history(token_id: str) -> list:
    """Fetch 24h hourly price history from CLOB."""
    try:
        resp = requests.get(
            f"{CLOB_BASE}/prices-history",
            params={"market": token_id, "interval": "1d", "fidelity": 60},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("history", [])
    except Exception as e:
        print(f" [WARN] price-history failed for {token_id}: {e}", file=sys.stderr)
        return []

def fetch_book_summary(token_id: str) -> dict:
    """Fetch best bid/ask from CLOB order book."""
    try:
        resp = requests.get(
            f"{CLOB_BASE}/book",
            params={"token_id": token_id},
            timeout=10,
        )
        resp.raise_for_status()
        book = resp.json()
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        best_bid = float(bids[0]["price"]) if bids else 0.0
        best_ask = float(asks[0]["price"]) if asks else 1.0
        return {"best_bid": best_bid, "best_ask": best_ask, "spread": best_ask - best_bid}
    except Exception:
        return {"best_bid": 0.0, "best_ask": 1.0, "spread": 1.0}

def _get_event_slug(market: dict) -> str:
    """Extract event slug from Gamma market object.
    
    Gamma API returns events as a list: {"events": [{"slug": "...", "id": "..."}]}
    Use events[0].slug as the canonical event identifier — this always resolves
    to a valid Polymarket page. The market-level 'slug' field often 404s.
    """
    events = market.get("events") or []
    if events and isinstance(events, list):
        first = events[0]
        if isinstance(first, dict) and first.get("slug"):
            return first["slug"]
    return ""

def _build_market_url(event_slug: str, market_slug: str = "", condition_id: str = "") -> str:
    """Build Polymarket URL. Use event-level slug — always valid."""
    if event_slug:
        return f"https://polymarket.com/event/{event_slug}"
    elif market_slug:
        return f"https://polymarket.com/event/{market_slug}"
    elif condition_id:
        return f"https://polymarket.com/event/{condition_id}"
    return "https://polymarket.com"

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[SCAN] Fetching active markets from Gamma...")
    all_markets = fetch_active_markets()
    print(f"[SCAN] Found {len(all_markets)} active markets total.")

    candidates = []
    skipped_reasons = {"low_volume": 0, "resolved": 0, "expired": 0, "excluded_tag": 0}

    for m in all_markets:
        question = m.get("question", "")
        vol_24h = float(m.get("volume24hr", 0) or 0)

        # FILTER 1: Minimum volume (now 2000)
        if vol_24h < MIN_VOLUME:
            skipped_reasons["low_volume"] += 1
            continue

        # FILTER 2: Expired end date
        if market_is_expired(m):
            skipped_reasons["expired"] += 1
            continue

        # FILTER 3: Excluded tags
        market_slug_lower = (m.get("market_slug") or m.get("slug") or "").lower()
        tag_slugs = extract_tag_slugs(m)
        slug_set = set(tag_slugs) | {market_slug_lower}
        if any(skip_tag in slug for slug in slug_set for skip_tag in SKIP_TAGS):
            skipped_reasons["excluded_tag"] += 1
            continue

        # FILTER 4: Resolved markets (price at 0% or 100%)
        outcome_prices = parse_json_field(m.get("outcomePrices"), [])
        if outcome_prices:
            price_yes = float(outcome_prices[0])
            if price_yes >= PRICE_CEILING or price_yes <= PRICE_FLOOR:
                skipped_reasons["resolved"] += 1
                continue

        m["_tag_slugs"] = tag_slugs
        m["_is_sports"] = is_sports_market(tag_slugs, question)
        candidates.append(m)

    print(f"[SCAN] After filtering: {len(candidates)} candidates.")
    print(f" Skipped: {json.dumps(skipped_reasons)}")

    # ── Parallel enrichment ────────────────────────────────────────────────────
    seen_tokens = set()
    enriched = []
    total = len(candidates)
    done = 0

    def enrich_one(m):
        clob_token_ids = parse_json_field(m.get("clobTokenIds"), [])
        if not clob_token_ids:
            return None

        primary_token = clob_token_ids[0]
        history = fetch_price_history(primary_token)
        book = fetch_book_summary(primary_token)

        outcome_prices = parse_json_field(m.get("outcomePrices"), [])
        price_now = float(outcome_prices[0]) if outcome_prices else None

        # Post-enrichment resolved check
        if price_now is not None and (price_now >= PRICE_CEILING or price_now <= PRICE_FLOOR):
            return {"type": "skip_resolved", "token": primary_token}

        price_24h_ago = None
        if history:
            p = history[0].get("p")
            if p is not None:
                price_24h_ago = float(p)

        event_slug = _get_event_slug(m)
        market_slug = m.get("marketSlug") or m.get("slug") or ""
        condition_id = m.get("conditionId") or ""

        # Extract primary outcome label
        outcomes_raw = m.get("outcomes", "[]")
        if isinstance(outcomes_raw, str):
            try:
                outcomes_list = json.loads(outcomes_raw)
            except json.JSONDecodeError:
                outcomes_list = []
        else:
            outcomes_list = outcomes_raw or []
        primary_outcome = outcomes_list[0] if outcomes_list else "Yes"

        return {
            "type": "enriched",
            "market": {
                "condition_id": condition_id,
                "market_slug": market_slug,
                "question": m.get("question"),
                "event_slug": event_slug,
                "primary_token_id": primary_token,
                "price_now": price_now,
                "price_24h_ago": price_24h_ago,
                "volume_24h": float(m.get("volume24hr", 0) or 0),
                "liquidity": float(m.get("liquidityNum", 0) or 0),
                "best_bid": book["best_bid"],
                "best_ask": book["best_ask"],
                "spread": book["spread"],
                "outcomes": m.get("outcomes"),
                "primary_outcome": primary_outcome,
                "end_date": m.get("endDate"),
                "tag_slugs": m["_tag_slugs"],
                "is_sports": m["_is_sports"],
                "image": m.get("image"),
                # v7: canonical URL built from slugs
                "market_url": _build_market_url(event_slug, condition_id=condition_id),
            }
        }

    print(f"[SCAN] Enriching {total} candidates with 20 concurrent workers...")
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(enrich_one, m): i for i, m in enumerate(candidates)}
        for future in as_completed(futures):
            done += 1
            if done % 50 == 0 or done == total:
                print(f" [Enriching {done}/{total}]")
            result = future.result()
            if result is None:
                continue
            if result["type"] == "skip_resolved":
                skipped_reasons["resolved"] += 1
                continue
            mkt = result["market"]
            token = mkt["primary_token_id"]
            if token in seen_tokens:
                skipped_reasons["duplicate_token"] = skipped_reasons.get("duplicate_token", 0) + 1
                continue
            seen_tokens.add(token)
            enriched.append(mkt)

    print(f"[SCAN] Enriched {len(enriched)} markets (skipped: {skipped_reasons})")

    # v7: URL debug sample
    print("\n[SCAN] URL debug sample:")
    for e in enriched[:5]:
        print(f"  Q: {e['question'][:50]}")
        print(f"    market_slug: {e.get('market_slug','NONE')}")
        print(f"    event_slug: {e.get('event_slug','NONE')}")
        print(f"    market_url: {e.get('market_url','NONE')}")

    # Atomic write
    with open(TMP_FILE, "w") as f:
        json.dump({
            "date": DATE,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "total_active": len(all_markets),
            "enriched_count": len(enriched),
            "skip_summary": skipped_reasons,
            "markets": enriched,
        }, f, indent=2)
    TMP_FILE.rename(OUTPUT_FILE)

    print(f"\n[SCAN] Done. {len(enriched)} unresolved, enriched markets written.")
    sys.exit(0)

if __name__ == "__main__":
    main()
