"""
Emoji Picker subagent v9.
Uses an LLM to assign the single best emoji per market.
Falls back to static map if LLM unavailable.

INPUT: {DATA_DIR}/briefs/{date}/ranked.json (or enriched.json)
OUTPUT: Adds "emoji" field to each mover in the input file (in-place)
EXIT: 0 always (non-critical — failures are non-blocking)
"""

import os, sys, json, requests
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR  = Path(os.environ.get("DATA_DIR", "/home/diligentapple/.openclaw/workspace/polymarket"))
DATE      = os.environ.get("RUN_DATE")
RANKED    = DATA_DIR / "briefs" / DATE / "ranked.json"
ENRICHED  = DATA_DIR / "briefs" / DATE / "enriched.json"
INPUT_FILE = ENRICHED if ENRICHED.exists() else RANKED
TMP_FILE  = INPUT_FILE.parent / f"{INPUT_FILE.stem}.emoji_tmp.json"

ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY")
OPENAI_KEY    = os.environ.get("OPENAI_API_KEY")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

FALLBACK = {
    "bitcoin": "₿", "btc": "₿", "ethereum": "⟠", "eth": "⟠",
    "crypto": "🪙", "token": "🪙", "defi": "🪙", "airdrop": "🪙",
    "politics": "🇺🇸", "election": "🗳️", "trump": "🇺🇸",
    "ukraine": "🇺🇦", "russia": "🇷🇺", "israel": "🇮🇱", "iran": "🇮🇷",
    "china": "🇨🇳", "taiwan": "🇹🇼",
    "nba": "🏀", "nfl": "🏈", "mlb": "⚾", "nhl": "🏒", "mls": "⚽",
    "ufc": "🥊", "mma": "🥊", "esports": "🎮", "lol": "🎮", "cs2": "🎮",
    "fokus": "🎮", "wildcard": "🎮", "handicap": "🎮", "map-handicap": "🎮", "pistol-round": "🎮",
    "cba": "🏀", "bkcba": "🏀", "kirin": "🏀", "tigers": "🏀", "chinese-basketball": "🏀",
    "ai": "🤖", "tech": "💻", "spx": "📈", "s&p": "📈", "sp500": "📈", "s&p-500": "📈",
 "dow": "📈", "nasdaq": "📈",
 "atp": "🎾", "wta": "🎾", "tennis": "🎾",
 "wimbledon": "🎾", "golf": "⛳", "pga": "⛳", "space": "🚀", "musk": "🚀",
    "fed": "🏦", "economy": "📊", "ipo": "📈", "stocks": "📈",
    "movie": "🎬", "film": "🎬", "entertainment": "🎬",
    "climate": "🌡️", "oil": "🛢️", "energy": "⚡",
    "war": "⚔️", "military": "⚔️",
    "f1": "🏎️", "tennis": "🎾", "golf": "⛳",
}
DEFAULT = "📌"

# v12: Load from config if available
_EMOJI_CONFIG = DATA_DIR / "config" / "emoji_map.json"
if _EMOJI_CONFIG.exists():
    try:
        _ec = json.loads(_EMOJI_CONFIG.read_text())
        FALLBACK = _ec.get("map", FALLBACK)
        DEFAULT = _ec.get("default", DEFAULT)
        print(f"[EMOJI] Loaded {len(FALLBACK)} mappings from config/emoji_map.json")
    except Exception as e:
        print(f"[EMOJI] WARN: Config load failed: {e}", file=sys.stderr)

def pick_batch_llm(movers: list) -> dict:
    market_list = "\n".join(f"{m['rank']}. {m['question']}" for m in movers)
    prompt = (
        "Assign ONE emoji to each prediction market question below.\n\n"
        "Rules:\n"
        "- ONE emoji per market\n"
        "- Be specific: movie→🎬, basketball→🏀, a country→its flag\n"
        "- Crypto: Bitcoin→₿, Ethereum→⟠, other tokens→🪙\n"
        "- Games/esports→🎮, Finance/IPO/stocks→📈\n"
        "- War/military→⚔️, Politics→🇺🇸 (or relevant country flag)\n"
        "- Never use 📌\n\n"
        "Markets:\n" + market_list + "\n\n"
        "Respond with ONLY valid JSON: {\"1\":\"🎬\",\"2\":\"🏀\",...}\n"
        "No markdown, no explanation."
    )
    if ANTHROPIC_KEY:
        resp = requests.post(
            f"{os.environ.get('ANTHROPIC_BASE_URL','https://api.anthropic.com/v1')}/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"), "max_tokens": 8000 if os.environ.get("LLM_MAX_TOKENS") is None else int(os.environ.get("LLM_MAX_TOKENS")),
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip()
    elif OPENAI_KEY:
        resp = requests.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={"model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), "max_tokens": 8000 if os.environ.get("LLM_MAX_TOKENS") is None else int(os.environ.get("LLM_MAX_TOKENS")),
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        raw = msg.get("content") or ""
        if not raw:
            raise ValueError("LLM returned empty response")
        raw = raw.strip()
    else:
        return {}
    raw = raw.strip("`")
    if raw.startswith("json"):
        raw = raw[4:].strip()
    try:
        return {int(k): v for k, v in json.loads(raw).items()}
    except Exception as e:
        print(f" [WARN] Parse failed: {e} | raw: {raw[:100]}", file=sys.stderr)
        return {}

def fallback_emoji(question: str, tag_slugs: list) -> str:
    combined = (question + " " + " ".join(s for s in tag_slugs)).lower()
    for kw, emo in FALLBACK.items():
        if kw in combined:
            return emo
    return DEFAULT

def main():
    if not INPUT_FILE.exists():
        print(f"[EMOJI] ERROR: {INPUT_FILE} not found", file=sys.stderr)
        sys.exit(1)
    with open(INPUT_FILE) as f:
        data = json.load(f)
    movers = data.get("movers", [])
    if not movers:
        print("[EMOJI] No movers — skipping.", file=sys.stderr)
        sys.exit(0)

    print(f"[EMOJI] Picking emojis for {len(movers)} movers...")
    llm_map = {}
    try:
        llm_map = pick_batch_llm(movers)
        print(f"[EMOJI] LLM returned {len(llm_map)} emojis.")
    except Exception as e:
        print(f"[EMOJI] LLM failed: {e}. Using static fallback.", file=sys.stderr)

    for m in movers:
        r = m.get("rank", 0)
        if r in llm_map and llm_map[r] != DEFAULT:
            m["emoji"] = llm_map[r]
            print(f"  {r}. {llm_map[r]} (llm) — {m['question'][:50]}...")
        else:
            m["emoji"] = fallback_emoji(m.get("question",""), m.get("tag_slugs",[]))
            print(f"  {r}. {m['emoji']} (fb) — {m['question'][:50]}...")

    data["emoji_picked_at"] = datetime.now(timezone.utc).isoformat()
    with open(TMP_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    TMP_FILE.rename(INPUT_FILE)
    print("[EMOJI] Done.")
    sys.exit(0)

if __name__ == "__main__":
    main()
