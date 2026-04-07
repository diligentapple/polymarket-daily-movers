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

# v13.2: allowed theme labels — LLM must pick from this list
ALLOWED_THEMES = [
    "Geopolitics", "Politics", "Elections", "Trade",
    "Markets", "Energy", "AI", "Tech", "Science", "Space",
    "Crypto", "Sports", "Esports", "Culture", "Climate",
    "Legal", "Health",
]

def pick_batch_llm(movers: list) -> tuple[dict, dict]:
    """
    Returns (emoji_map, theme_map) where both are {rank: str}.
    Single LLM call for both emoji and theme assignment.
    """
    market_list = "\n".join(
        f"{m['rank']}. {m['question']}  [tags: {', '.join(m.get('tag_slugs', [])[:5])}]"
        for m in movers
    )
    themes_str = ", ".join(ALLOWED_THEMES)
    prompt = (
        "For each prediction market below, assign:\n"
        "1. ONE emoji that best represents it\n"
        "2. ONE theme label from this list: " + themes_str + "\n\n"
        "Emoji rules:\n"
        "- Be specific: basketball→🏀, a country→its flag, tennis→🎾\n"
        "- Crypto: Bitcoin→₿, Ethereum→⟠, other tokens→🪙\n"
        "- Games/esports→🎮, Finance/stocks→📈\n"
        "- War/military→⚔️, AI→🤖\n"
        "- Never use 📌\n\n"
        "Theme rules:\n"
        "- Pick the MOST SPECIFIC theme that fits\n"
        "- Tennis/NBA/NFL/UFC/F1 → Sports\n"
        "- CS2/Valorant/LoL/Dota → Esports\n"
        "- Bitcoin/Ethereum/tokens → Crypto\n"
        "- ChatGPT/Claude/LLMs/OpenAI → AI\n"
        "- S&P/stocks/Fed/interest rates → Markets\n"
        "- Oil/gas/OPEC → Energy\n"
        "- Wars/military/invasions → Geopolitics\n"
        "- YouTube/movies/MrBeast/awards → Culture\n"
        "- Trump/Biden/elections → Politics\n\n"
        "Markets:\n" + market_list + "\n\n"
        'Respond with ONLY valid JSON: {"1":{"emoji":"🎾","theme":"Sports"},"2":{"emoji":"⚔️","theme":"Geopolitics"},...}\n'
        "No markdown, no explanation."
    )
    if ANTHROPIC_KEY:
        resp = requests.post(
            f"{os.environ.get('ANTHROPIC_BASE_URL','https://api.anthropic.com/v1')}/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
                  "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", 8000)),
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip()
    elif OPENAI_KEY:
        resp = requests.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={"model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                  "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", 8000)),
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
        return {}, {}
    raw = raw.strip("`")
    if raw.startswith("json"):
        raw = raw[4:].strip()
    try:
        parsed = json.loads(raw)
        emoji_map = {}
        theme_map = {}
        for k, v in parsed.items():
            rank = int(k)
            if isinstance(v, dict):
                emoji_map[rank] = v.get("emoji", DEFAULT)
                theme = v.get("theme", "Markets")
                # Validate theme is in allowed list
                if theme not in ALLOWED_THEMES:
                    theme = "Markets"
                theme_map[rank] = theme
            elif isinstance(v, str):
                # Backwards compat: if LLM returns just emoji string
                emoji_map[rank] = v
        return emoji_map, theme_map
    except Exception as e:
        print(f" [WARN] Parse failed: {e} | raw: {raw[:100]}", file=sys.stderr)
        return {}, {}

def fallback_emoji(question: str, tag_slugs: list) -> str:
    combined = (question + " " + " ".join(s for s in tag_slugs)).lower()
    for kw, emo in FALLBACK.items():
        if kw in combined:
            return emo
    return DEFAULT

# v13.2: theme fallback when LLM unavailable
_THEME_FALLBACK = {
    "bitcoin": "Crypto", "btc": "Crypto", "ethereum": "Crypto", "eth": "Crypto",
    "crypto": "Crypto", "token": "Crypto", "defi": "Crypto", "solana": "Crypto",
    "nba": "Sports", "nfl": "Sports", "mlb": "Sports", "nhl": "Sports",
    "mls": "Sports", "ufc": "Sports", "mma": "Sports", "tennis": "Sports",
    "f1": "Sports", "golf": "Sports", "cricket": "Sports", "boxing": "Sports",
    "esports": "Esports", "cs2": "Esports", "valorant": "Esports",
    "dota": "Esports", "lol": "Esports", "league-of-legends": "Esports",
    "counter-strike": "Esports",
    "ai": "AI", "tech": "Tech", "science": "Science", "space": "Space",
    "politics": "Politics", "us-politics": "Politics", "election": "Elections",
    "elections": "Elections",
    "geopolitics": "Geopolitics", "ukraine": "Geopolitics", "russia": "Geopolitics",
    "israel": "Geopolitics", "iran": "Geopolitics", "china": "Geopolitics",
    "war": "Geopolitics", "military": "Geopolitics", "conflict": "Geopolitics",
    "trade": "Trade", "tariffs": "Trade",
    "economy": "Markets", "fed": "Markets", "spx": "Markets", "stocks": "Markets",
    "oil": "Energy", "opec": "Energy", "wti": "Energy", "energy": "Energy",
    "climate": "Climate", "legal": "Legal", "health": "Health",
    "entertainment": "Culture", "movie": "Culture", "mrbeast": "Culture",
    "youtube": "Culture", "awards": "Culture", "music": "Culture",
}

def fallback_theme(market: dict) -> str:
    """Assign theme from tags/question when LLM unavailable."""
    combined = " ".join(market.get("tag_slugs", [])).lower() + " " + market.get("question", "").lower()
    for kw, theme in _THEME_FALLBACK.items():
        if kw in combined:
            return theme
    if market.get("is_sports"):
        return "Sports"
    if market.get("is_crypto"):
        return "Crypto"
    return "Markets"

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
    llm_emoji_map = {}
    llm_theme_map = {}
    try:
        llm_emoji_map, llm_theme_map = pick_batch_llm(movers)
        print(f"[EMOJI] LLM returned {len(llm_emoji_map)} emojis, {len(llm_theme_map)} themes.")
    except Exception as e:
        print(f"[EMOJI] LLM failed: {e}. Using static fallback.", file=sys.stderr)

    for m in movers:
        r = m.get("rank", 0)
        # Emoji
        if r in llm_emoji_map and llm_emoji_map[r] != DEFAULT:
            m["emoji"] = llm_emoji_map[r]
            print(f"  {r}. {llm_emoji_map[r]} (llm)", end="")
        else:
            m["emoji"] = fallback_emoji(m.get("question",""), m.get("tag_slugs",[]))
            print(f"  {r}. {m['emoji']} (fb)", end="")
        # Theme
        if r in llm_theme_map:
            m["theme"] = llm_theme_map[r]
            print(f" [{m['theme']}] — {m['question'][:50]}...")
        else:
            m["theme"] = fallback_theme(m)
            print(f" [{m['theme']}] (fb) — {m['question'][:50]}...")

    data["emoji_picked_at"] = datetime.now(timezone.utc).isoformat()
    with open(TMP_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    TMP_FILE.rename(INPUT_FILE)
    print("[EMOJI] Done.")
    sys.exit(0)

if __name__ == "__main__":
    main()
