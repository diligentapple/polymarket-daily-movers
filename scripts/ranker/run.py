"""
Ranker subagent v7.
Scores markets by mover formula, applies diversity constraints.

INPUT: {DATA_DIR}/briefs/{date}/scan_output.json
OUTPUT: {DATA_DIR}/briefs/{date}/ranked.json
EXIT: 0 on success, 1 on failure
"""

import os
import sys
import json
import math
import re
from pathlib import Path
from collections import Counter

DATA_DIR = Path(os.environ.get("DATA_DIR", "/home/diligentapple/.openclaw/workspace/polymarket"))
DATE = os.environ.get("RUN_DATE")
INPUT_FILE = DATA_DIR / "briefs" / DATE / "scan_output.json"
OUTPUT_FILE = DATA_DIR / "briefs" / DATE / "ranked.json"
TMP_FILE = DATA_DIR / "briefs" / DATE / "ranked.tmp.json"

TOP_N = int(os.environ.get("TOP_N_MOVERS", 8))
MAX_PER_CATEGORY = int(os.environ.get("MAX_PER_CATEGORY", 2))
MAX_SPORTS = int(os.environ.get("MAX_SPORTS", 2))

# ── Repetitive intra-day market dedup ──────────────────────────────────────────
REPETITIVE_PATTERNS = [
    (re.compile(r"(?i)(bitcoin|btc).*(?:up|down)"),        "bitcoin"),
    (re.compile(r"(?i)(ethereum|eth).*(?:up|down)"),       "ethereum"),
    (re.compile(r"(?i)(sol|solana).*(?:up|down)"),          "solana"),
    (re.compile(r"(?i)up.or.down.*(?:bitcoin|btc|ethereum|eth|sol)"), "crypto"),
]

# ── Named entity patterns (v7: added award races + token markets) ───────────────
ENTITY_PATTERNS = [
    # People
    (re.compile(r"(?i)\b(mrbeast|mr\.?\s*beast)\b"), "mrbeast"),
    (re.compile(r"(?i)\b(trump)\b"), "trump"),
    (re.compile(r"(?i)\b(biden)\b"), "biden"),
    (re.compile(r"(?i)\b(harris)\b"), "harris"),
    (re.compile(r"(?i)\b(elon\s*musk|musk)\b"), "musk"),
    (re.compile(r"(?i)\b(zelensky)\b"), "zelensky"),
    (re.compile(r"(?i)\b(netanyahu)\b"), "netanyahu"),
    (re.compile(r"(?i)\b(putin)\b"), "putin"),
    (re.compile(r"(?i)\b(macron)\b"), "macron"),
    (re.compile(r"(?i)\b(modi)\b"), "modi"),
    (re.compile(r"(?i)\b(openai|open\s+ai)\b"), "openai"),
    (re.compile(r"(?i)\b(tesla)\b"), "tesla"),
    (re.compile(r"(?i)\b(nvidia)\b"), "nvidia"),
    (re.compile(r"(?i)\b(spacex)\b"), "spacex"),
    # Crypto
    (re.compile(r"(?i)\b(bitcoin|btc)\b"), "bitcoin"),
    (re.compile(r"(?i)\b(ethereum|eth)\b"), "ethereum"),
    (re.compile(r"(?i)\b(solana|sol)\b"), "solana"),
    # Sports leagues (one entity per championship race)
    (re.compile(r"(?i)\b(la\s*liga)\b"), "la-liga"),
    (re.compile(r"(?i)\b(real\s*madrid)\b"), "la-liga"),
    (re.compile(r"(?i)\b(barcelona|barca|barça)\b"), "la-liga"),
    (re.compile(r"(?i)\b(atletico\s*madrid|atlético)\b"), "la-liga"),
    (re.compile(r"(?i)\b(premier\s*league)\b"), "premier-league"),
    (re.compile(r"(?i)\b(serie\s*a)\b"), "serie-a"),
    (re.compile(r"(?i)\b(bundesliga)\b"), "bundesliga"),
    (re.compile(r"(?i)\b(champions\s*league|ucl)\b"), "champions-league"),
    # v7: Award races — all players competing for same award → same entity
    (re.compile(r"(?i)\bart\s*ross\b"), "nhl-art-ross"),
    (re.compile(r"(?i)\bhart\s*(memorial\s*)?trophy\b"), "nhl-hart"),
    (re.compile(r"(?i)\bnorris\s*trophy\b"), "nhl-norris"),
    (re.compile(r"(?i)\bvezina\s*trophy\b"), "nhl-vezina"),
    (re.compile(r"(?i)\bcalder\s*(memorial\s*)?trophy\b"), "nhl-calder"),
    (re.compile(r"(?i)\bselke\s*trophy\b"), "nhl-selke"),
    (re.compile(r"(?i)\bmvp\b.*\b(nba|nfl|mlb|nhl)\b"), "mvp-award"),
    (re.compile(r"(?i)\b(nba|nfl|mlb|nhl)\b.*\bmvp\b"), "mvp-award"),
    (re.compile(r"(?i)\bheisman\b"), "heisman"),
    (re.compile(r"(?i)\bcy\s*young\b"), "cy-young"),
    (re.compile(r"(?i)\bballon\s*d.or\b"), "ballon-dor"),
    (re.compile(r"(?i)\bgolden\s*boot\b"), "golden-boot"),
    (re.compile(r"(?i)\bgolden\s*glove\b"), "golden-glove"),
    # v7: NBA Rookie of the Year
    (re.compile(r"(?i)\brookie\s*of\s*the\s*year\b"), "rookie-of-the-year"),
    # v7: NCAA tournament winners — same championship, same entity
    (re.compile(r"(?i)ncaa.*tournament.*winner"), "ncaa-tournament"),
    (re.compile(r"(?i)women.*ncaa.*tournament"), "ncaa-women-tournament"),
    (re.compile(r"(?i)win.*ncaa.*tournament"), "ncaa-tournament"),
    (re.compile(r"(?i)\bncaa\s*tournament\b"), "ncaa-tournament"),
    # v7: Token launch markets
    (re.compile(r"(?i)\b(axiom)\b.*\btoken\b"), "axiom"),
    (re.compile(r"(?i)\btoken\b.*\b(axiom)\b"), "axiom"),
    (re.compile(r"(?i)\blauch\s+a\s+token\b"), "token-launch"),
    (re.compile(r"(?i)\btoken\s+launch\b"), "token-launch"),
    (re.compile(r"(?i)\bairdrop\b"), "airdrop"),
]

MAX_PER_PERSON = 1
MAX_PER_CRYPTO_COIN = 1
MAX_CRYPTO = 1  # v8: cap crypto markets in top N (excl. from lead, max 1 in thread)

def is_crypto_market(market: dict) -> bool:
    """Check if a market is crypto-related (coin price, token launch, DeFi, etc.)."""
    question = market.get("question", "").lower()
    tag_slugs = [s.lower() for s in market.get("tag_slugs", [])]
    crypto_kw = {
        "bitcoin", "btc", "ethereum", "eth", "solana", "sol",
        "crypto", "token", "airdrop", "defi", "nft",
        "cardano", "dogecoin", "xrp", "ripple", "polygon", "matic",
        "avalanche", "avax", "chainlink", "uniswap",
    }
    crypto_tags = {"crypto", "bitcoin", "ethereum", "defi", "nft", "token", "airdrop", "web3", "blockchain"}
    if crypto_tags.intersection(tag_slugs):
        return True
    for kw in crypto_kw:
        if kw in question:
            return True
    return False

def extract_primary_entity(question: str) -> str | None:
    for pattern, entity_key in ENTITY_PATTERNS:
        if pattern.search(question):
            return entity_key
    return None

def get_entity_cap(entity: str) -> int:
    """Return the max allowed markets for a given entity."""
    people = {"mrbeast", "trump", "biden", "harris", "musk", "zelensky",
              "netanyahu", "putin", "macron", "modi"}
    crypto = {"bitcoin", "ethereum", "solana"}
    leagues = {"la-liga", "premier-league", "serie-a", "bundesliga", "champions-league"}
    # v7: award races capped at 1 — correlated inverse markets
    awards = {"nhl-art-ross", "nhl-hart", "nhl-norris", "nhl-vezina",
              "nhl-calder", "nhl-selke", "mvp-award", "heisman",
              "cy-young", "ballon-dor", "golden-boot", "golden-glove",
              "ncaa-tournament", "ncaa-women-tournament",
              "rookie-of-the-year"}
    tokens = {"axiom", "token-launch", "airdrop"}

    if entity in people:
        return MAX_PER_PERSON
    elif entity in crypto:
        return MAX_PER_CRYPTO_COIN
    elif entity in leagues:
        return 1
    elif entity in awards:
        return 1
    elif entity in tokens:
        return 1
    else:
        return MAX_PER_CATEGORY  # default cap

# ── Editorial weight ────────────────────────────────────────────────────────────

# v12: Load editorial weights from config if available
_WEIGHTS_CONFIG = DATA_DIR / "config" / "editorial_weights.json"
if _WEIGHTS_CONFIG.exists():
    try:
        _wc = json.loads(_WEIGHTS_CONFIG.read_text())
        EDITORIAL_WEIGHT = _wc.get("weights", {})
        CRYPTO_UPDOWN_WEIGHT = _wc.get("crypto_updown_weight", 0.4)
        print(f"[RANK] Loaded {len(EDITORIAL_WEIGHT)} editorial weights from config")
    except Exception as e:
        print(f"[RANK] WARN: Config load failed: {e}. Using hardcoded weights.", file=sys.stderr)
        EDITORIAL_WEIGHT = None

if not globals().get('EDITORIAL_WEIGHT'):
        EDITORIAL_WEIGHT = {
    "geopolitics": 1.8, "politics": 1.6, "us-politics": 1.6,
    "elections": 1.5, "trade": 1.5, "tariffs": 1.5,
    "economy": 1.5, "fed": 1.5, "inflation": 1.4,
    "ai": 1.4, "tech": 1.3, "legal": 1.3,
    "ukraine": 1.6, "russia": 1.5, "israel": 1.6,
    "china": 1.5, "iran": 1.5, "taiwan": 1.5,
    "middle-east": 1.5, "climate": 1.3, "energy": 1.3, "space": 1.3,
    "crypto": 1.0, "culture": 1.0, "entertainment": 1.0,
    "sports": 0.6, "mls": 0.6, "nba": 0.7, "nfl": 0.7,
    "ufc": 0.7, "mma": 0.7, "nbl": 0.6,
}

CRYPTO_UPDOWN_WEIGHT = 0.4

def is_crypto_updown(question: str) -> bool:
    return bool(re.search(r"(?i)(bitcoin|btc|ethereum|eth|solana|sol).*(up|down)", question))

def apply_editorial_weight(market: dict) -> float:
    question = market.get("question", "")
    tag_slugs = market.get("tag_slugs", [])
    if is_crypto_updown(question):
        return CRYPTO_UPDOWN_WEIGHT
    best_weight = 1.0
    for slug in tag_slugs:
        slug_lower = slug.lower()
        if slug_lower in EDITORIAL_WEIGHT:
            best_weight = max(best_weight, EDITORIAL_WEIGHT[slug_lower])
        for key, weight in EDITORIAL_WEIGHT.items():
            if key in slug_lower:
                best_weight = max(best_weight, weight)
                break
    return best_weight

def volume_confidence(vol: float) -> float:
    """v7: Penalize thin markets. Noise, not signal."""
    if vol < 5000:
        return 0.3
    elif vol < 20000:
        return 0.6
    return 1.0

def repetitive_group(market: dict) -> str | None:
    q = market.get("question", "").lower()
    slug = market.get("market_slug", "").lower()
    for pattern, subject in REPETITIVE_PATTERNS:
        if pattern.search(q) or pattern.search(slug):
            return subject
    return None

def deduplicate_repetitive(scored: list) -> list:
    best_per_group: dict[str, tuple] = {}
    dropped = 0
    for m in scored:
        grp = repetitive_group(m)
        score = m.get("mover_score", 0)
        key = grp if grp is not None else f"__normal__{m.get('condition_id', id(m))}"
        existing_score, _ = best_per_group.get(key, (None, None))
        if existing_score is None or score > existing_score:
            best_per_group[key] = (score, m)
        if grp is not None:
            dropped += 1
    result = [m for _, m in sorted(best_per_group.values(), key=lambda x: x[0], reverse=True)]
    print(f"[RANK] Deduped {dropped} repetitive markets. Remaining: {len(result)}")
    return result

def compute_mover_score(market: dict) -> float | None:
    price_now = market.get("price_now")
    price_24h_ago = market.get("price_24h_ago")
    volume_24h = market.get("volume_24h", 0)
    spread = market.get("spread", 1.0)
    if price_now is None or price_24h_ago is None:
        return None
    delta = abs(price_now - price_24h_ago)
    if delta < 0.01:
        return None
    score = delta * math.log(1 + volume_24h) / (1 + spread)
    return score

def primary_category(market: dict) -> str:
    tag_slugs = market.get("tag_slugs", [])
    generic = {"general", "other", "trending", "popular", "polymarket"}
    for slug in tag_slugs:
        if slug.lower() not in generic:
            return slug.lower()
    return (market.get("market_slug") or "unknown").lower()

def select_diverse_top_n(scored: list, top_n: int) -> list:
    selected = []
    entity_counts = Counter()
    category_counts = Counter()
    event_slugs_seen = set()  # v9: no two markets from same event
    sports_count = 0
    crypto_count = 0
    for m in scored:
        if len(selected) >= top_n:
            break
        question = m.get("question", "")
        entity = extract_primary_entity(question)
        cat = primary_category(m)
        is_sport = m.get("is_sports", False)
        is_crypto = is_crypto_market(m)
        event_slug = m.get("event_slug", "")

        # v9: Layer 0 - event slug dedup (no two markets from same event)
        if event_slug and event_slug in event_slugs_seen:
            continue

        if entity:
            cap = get_entity_cap(entity)
            if entity_counts[entity] >= cap:
                continue
        if category_counts[cat] >= MAX_PER_CATEGORY:
            continue
        if is_sport and sports_count >= MAX_SPORTS:
            continue
        if is_crypto and crypto_count >= MAX_CRYPTO:
            continue
        selected.append(m)
        m["is_crypto"] = is_crypto
        if event_slug:
            event_slugs_seen.add(event_slug)
        if entity:
            entity_counts[entity] += 1
        category_counts[cat] += 1
        if is_sport:
            sports_count += 1
        if is_crypto:
            crypto_count += 1
    return selected

def main():
    if not INPUT_FILE.exists():
        print(f"[RANK] ERROR: {INPUT_FILE} not found", file=sys.stderr)
        sys.exit(1)

    with open(INPUT_FILE) as f:
        scan_data = json.load(f)

    markets = scan_data.get("markets", [])

    scored = []
    for m in markets:
        score = compute_mover_score(m)
        if score is None:
            continue
        vol = m.get("volume_24h", 0)
        editorial_mult = apply_editorial_weight(m)
        vol_conf = volume_confidence(vol)
        raw_score = score
        final_score = raw_score * editorial_mult * vol_conf

        m["mover_score_raw"] = round(raw_score, 6)
        m["mover_score"] = round(final_score, 6)
        m["editorial_weight"] = editorial_mult
        m["volume_confidence"] = vol_conf
        m["delta_pp"] = round((m["price_now"] - m["price_24h_ago"]) * 100, 1)
        m["direction"] = "▲" if m["delta_pp"] > 0 else "▼"
        m["abs_delta_pp"] = abs(m["delta_pp"])
        m["price_now_pct"] = round(m["price_now"] * 100, 0)
        m["price_24h_ago_pct"] = round(m["price_24h_ago"] * 100, 0)
        scored.append(m)

    scored.sort(key=lambda x: x["mover_score"], reverse=True)
    scored = deduplicate_repetitive(scored)
    top = select_diverse_top_n(scored, TOP_N)

    for i, m in enumerate(top):
        m["rank"] = i + 1

    output = {
        "date": DATE,
        "top_n": TOP_N,
        "total_scored": len(scored),
        "sports_cap": MAX_SPORTS,
        "category_cap": MAX_PER_CATEGORY,
        "movers": top,
    }

    with open(TMP_FILE, "w") as f:
        json.dump(output, f, indent=2)
    TMP_FILE.rename(OUTPUT_FILE)

    print(f"[RANK] Selected {len(top)} diverse movers from {len(scored)} scored markets.")

    # v7: detailed scoring breakdown
    final_entity_counts = Counter()
    for m in top:
        ent = extract_primary_entity(m.get("question", ""))
        if ent:
            final_entity_counts[ent] += 1
    if final_entity_counts:
        print(f"[RANK] Entity counts: {dict(final_entity_counts)}")

    for m in top:
        cat = primary_category(m)
        sport_tag = " [SPORT]" if m.get("is_sports") else ""
        print(f" {m['rank']}. [{cat}]{sport_tag} {m['question'][:50]}...")
        print(f"    {m['direction']}{m['abs_delta_pp']}pp | "
              f"score={m['mover_score']:.4f} "
              f"(raw={m['mover_score_raw']:.4f} × ed={m['editorial_weight']} × vol_conf={m['volume_confidence']}) "
              f"| vol=${m['volume_24h']:,.0f}")

    # v7: score distribution
    vols = [m['volume_24h'] for m in scored[:20]]
    print(f"\n[RANK] Top-20 volume range: ${min(vols):,.0f} – ${max(vols):,.0f}")
    low_vol = sum(1 for m in top if m['volume_confidence'] < 1.0)
    print(f"[RANK] Movers with vol penalty: {low_vol}/{len(top)}")
    sys.exit(0)

if __name__ == "__main__":
    main()
