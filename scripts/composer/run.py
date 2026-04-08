"""
Composer subagent v7.
Generates tweet thread with varied language, shortened questions, and validated output.

INPUT: {DATA_DIR}/briefs/{date}/ranked.json (or enriched.json if present)
OUTPUT: {DATA_DIR}/briefs/{date}/tweets.json
EXIT: 0 on success, 1 on failure
"""

import os
import sys
import json
import re
import random
from pathlib import Path
X_URL_LENGTH = 23

# ── Unicode bold text (works on X/Twitter without markdown) ───────────────────
_BOLD_MAP = {}
for _i, _c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"):
    if _c.isupper():
        _BOLD_MAP[_c] = chr(0x1D5D4 + _i)       # 𝗔-𝗭
    elif _c.islower():
        _BOLD_MAP[_c] = chr(0x1D5EE + (_i - 26)) # 𝗮-𝘇
    else:
        _BOLD_MAP[_c] = chr(0x1D7EC + (_i - 52)) # 𝟬-𝟵
_BOLD_MAP[" "] = " "

def to_bold(text: str) -> str:
    """Convert ASCII text to Unicode Mathematical Sans-Serif Bold."""
    return "".join(_BOLD_MAP.get(c, c) for c in text)

def count_tweet_chars(text: str) -> int:
    url_pattern = re.compile(r"https?://\S+")
    urls = url_pattern.findall(text)
    char_count = 0
    for ch in text:
        # Unicode chars outside BMP (surrogate pairs) count as 2 on X
        if ord(ch) > 0xFFFF:
            char_count += 2
        else:
            char_count += 1
    for url in urls:
        url_len = sum(2 if ord(c) > 0xFFFF else 1 for c in url)
        char_count -= url_len
        char_count += X_URL_LENGTH
    return char_count


def _trim_to_limit(text: str, limit: int = 280) -> str:
    """
    Progressively shorten a reply tweet to fit within the char limit.
    Tries strategies in order from least to most aggressive.
    """
    if count_tweet_chars(text) <= limit:
        return text

    lines = text.split("\n")

    # Strategy 1: trim the context line (usually the longest part)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Skip theme header, question, pct line, URL
        if any(stripped.startswith(p) for p in ["➜", "→", "http"]):
            continue
        if "📈" in stripped or "📉" in stripped:
            continue
        if to_bold("") != "" and any(ord(c) > 0x1D400 for c in stripped[:5]):
            continue
        # This is likely the context line — shorten it
        if len(stripped) > 60:
            words = stripped.split()
            while words and count_tweet_chars("\n".join(lines)) > limit:
                words.pop()
            if words:
                lines[i] = " ".join(words)
            break

    text = "\n".join(lines)
    if count_tweet_chars(text) <= limit:
        return text

    # Strategy 2: shorten the question line
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.endswith("?") and len(stripped) > 40:
            lines[i] = stripped[:37].rsplit(" ", 1)[0] + "...?"
            break

    text = "\n".join(lines)
    if count_tweet_chars(text) <= limit:
        return text

    # Strategy 3: remove blank lines (compacts spacing)
    lines = [l for l in lines if l.strip() or lines.index(l) == len(lines) - 2]
    text = "\n".join(lines)
    if count_tweet_chars(text) <= limit:
        return text

    # Strategy 4: nuclear — hard truncate (shouldn't reach here)
    while count_tweet_chars(text) > limit and len(text) > 10:
        text = text[:len(text) - 5].rsplit(" ", 1)[0] + "..."
    return text


DATA_DIR = Path(os.environ.get("DATA_DIR", "/home/diligentapple/.openclaw/workspace/polymarket"))
DATE = os.environ.get("RUN_DATE")
ENRICHED_FILE = DATA_DIR / "briefs" / DATE / "enriched.json"
RANKED_FILE = DATA_DIR / "briefs" / DATE / "ranked.json"
INPUT_FILE = ENRICHED_FILE if ENRICHED_FILE.exists() else RANKED_FILE
TWEETS_FILE = DATA_DIR / "briefs" / DATE / "tweets.json"
COMPOSE_MODE = os.environ.get("COMPOSE_MODE", "template")
REFERRAL_ID = os.environ.get("POLYMARKET_REFERRAL_ID", "")

# ── Category emoji map (v7: added token/crypto emojis) ─────────────────────────

# v12: Load emoji map from config if available, fall back to hardcoded
_EMOJI_CONFIG_PATH = DATA_DIR / "config" / "emoji_map.json"
if _EMOJI_CONFIG_PATH.exists():
    try:
        _emoji_config = json.loads(_EMOJI_CONFIG_PATH.read_text())
        CATEGORY_EMOJI = _emoji_config.get("map", {})
        EMOJI_PRIORITY = _emoji_config.get("priority", [])
        DEFAULT_EMOJI = _emoji_config.get("default", "ð")
        print(f"[COMPOSE] Loaded {len(CATEGORY_EMOJI)} emoji mappings from config")
    except Exception as e:
        print(f"[COMPOSE] WARN: Failed to load emoji config: {e}", file=sys.stderr)
        # Fall through to hardcoded maps below
        CATEGORY_EMOJI = None

if not globals().get('CATEGORY_EMOJI'):
    CATEGORY_EMOJI = {
    "politics": "🇺🇸", "us-politics": "🇺🇸", "elections": "🗳️",
    "geopolitics": "🌍", "world": "🌍", "china": "🇨🇳",
    "europe": "🇪🇺", "middle-east": "🌍", "russia": "🇷🇺",
    "ukraine": "🇺🇦", "trade": "📦", "tariffs": "📦",
    "iran": "🇮🇷", "israel": "🇮🇱", "gaza": "🇵🇸",
    "economy": "📊", "fed": "🏦", "inflation": "📈",
    "crypto": "₿", "bitcoin": "₿", "btc": "₿", "ethereum": "⟠", "eth": "⟠", "solana": "◎",
    "markets": "📈", "stocks": "📈", "finance": "💰",
    "ai": "🤖", "tech": "💻", "science": "🔬",
    "mrbeast": "🎬", "youtube": "📺", "entertainment": "🎬",
    "culture": "🎭", "awards": "🏆", "music": "🎵", "movies": "🎬",
    "sports": "⚽", "mls": "⚽", "nba": "🏀", "nfl": "🏈",
    "ufc": "🥊", "mma": "🥊", "boxing": "🥊",
    "mlb": "⚾", "nhl": "🏒", "f1": "🏎️",
    "tennis": "🎾", "golf": "⛳", "cricket": "🏏",
    "legal": "⚖️", "health": "🏥", "energy": "⚡",
    "climate": "🌡️", "space": "🚀",
    "ukraine": "🇺🇦", "russia-ukraine": "🇺🇦",
    "peru": "🇵🇪", "ecuador": "🇪🇨", "brazil": "🇧🇷", "argentina": "🇦🇷",
    "mexico": "🇲🇽", "colombia": "🇨🇴", "chile": "🇨🇱",
    "india": "🇮🇳", "pakistan": "🇵🇰", "japan": "🇯🇵", "korea": "🇰🇷",
    "australia": "🇦🇺", "canada": "🇨🇦", "turkey": "🇹🇷",
    "nigeria": "🇳🇬", "south-africa": "🇿🇦", "egypt": "🇪🇬",
    "philippines": "🇵🇭", "indonesia": "🇮🇩", "taiwan": "🇹🇼",
    "iran": "🇮🇷", "lebanon": "🇱🇧", "syria": "🇸🇾", "yemen": "🇾🇪",
    "uk": "🇬🇧", "france": "🇫🇷", "germany": "🇩🇪",
    "italy": "🇮🇹", "spain": "🇪🇸", "poland": "🇵🇱",
    "election": "🗳️", "runoff": "🗳️", "voting": "🗳️", "referendum": "🗳️",
    "nbl": "🏀", "wnba": "🏀", "euroleague": "🏀",
    "cba": "🏀", "bkcba": "🏀", "chinese-basketball": "🏀",
    "youtube": "🎬", "twitch": "🎮", "streaming": "📺",
    "tariff": "📦", "tariffs": "📦", "trade-war": "📦",
    "nuclear": "☢️", "sanctions": "🚫",
    "fed-rate": "🏦", "interest-rate": "🏦", "rate-cut": "🏦",
    "oil": "🛢️", "opec": "🛢️", "natural-gas": "🛢️",
    "war": "⚔️", "conflict": "⚔️", "military": "⚔️",
    "musk": "🚀", "elon-musk": "🚀", "elon_musk": "🚀",
    "trump": "🇺🇸", "biden": "🇺🇸", "harris": "🇺🇸",
    "putin": "🇷🇺", "zelensky": "🇺🇦", "netanyahu": "🇮🇱",
    "macron": "🇫🇷", "modi": "🇮🇳",
    "mrbeast": "🎬", "mr-beast": "🎬",
    "esports": "🎮", "counter-strike": "🎮", "cs2": "🎮", "csgo": "🎮",
    "fokus": "🎮", "map-handicap": "🎮",
    "dota": "🎮", "dota2": "🎮", "league-of-legends": "🎮", "lol": "🎮",
    "valorant": "🎮", "overwatch": "🎮", "call-of-duty": "🎮", "cod": "🎮",
    "faze": "🎮", "navi": "🎮", "fnatic": "🎮", "g2": "🎮",
    "cybershoke": "🎮",
    "la-liga": "⚽", "la_liga": "⚽", "laliga": "⚽",
    "real-madrid": "⚽", "barcelona": "⚽", "atletico": "⚽",
    # v7: token / crypto emojis
    "token": "🪙", "airdrop": "🪙", "token-launch": "🪙",
    "axiom": "🪙", "defi": "🪙",
}
DEFAULT_EMOJI = "📌"

EMOJI_PRIORITY = [
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto",
    "nba", "nfl", "mlb", "nhl", "mls", "nbl", "wnba",
    "ufc", "mma", "boxing", "f1", "tennis", "golf", "cricket",
    "epl", "premier-league", "la-liga", "laliga", "serie-a", "bundesliga", "ligue-1",
    "champions-league",
    "esports", "e-sports", "counter-strike", "cs2", "csgo",
    "valorant", "dota", "league-of-legends", "faze", "cybershoke",
    "musk", "elon-musk", "trump", "biden", "harris",
    "putin", "zelensky", "netanyahu", "macron", "modi",
    "mrbeast", "mr-beast",
    "ukraine", "russia", "israel", "iran", "china", "taiwan",
    "peru", "ecuador", "brazil", "india", "japan", "australia",
    "uk", "france", "germany",
    "ai", "tech", "science", "space",
    "geopolitics", "politics", "us-politics", "elections", "election",
    "runoff", "voting", "referendum",
    "economy", "fed", "inflation", "trade", "tariffs",
    "climate", "energy", "oil", "nuclear",
    "legal", "war", "conflict", "military", "sanctions",
    "culture", "entertainment", "youtube", "streaming",
    "sports", "football", "soccer", "basketball", "baseball", "hockey",
    # v7: token markets
    "token", "airdrop", "token-launch", "axiom", "defi",
]

# ── Theme labels for tweet grouping ───────────────────────────────────────────
# Maps tag slugs / categories → human-readable theme label
# Each tweet gets ONE theme label displayed as "emoji 𝗧𝗵𝗲𝗺𝗲"
THEME_LABELS = {
    # Geopolitics & politics
    "geopolitics": "Geopolitics", "politics": "Politics", "us-politics": "Politics",
    "elections": "Elections", "election": "Elections",
    "ukraine": "Geopolitics", "russia": "Geopolitics", "israel": "Geopolitics",
    "iran": "Geopolitics", "china": "Geopolitics", "taiwan": "Geopolitics",
    "gaza": "Geopolitics", "middle-east": "Geopolitics",
    "trade": "Trade", "tariffs": "Trade", "tariff": "Trade",
    "war": "Geopolitics", "conflict": "Geopolitics", "military": "Geopolitics",
    "sanctions": "Geopolitics",
    # Economy & markets
    "economy": "Markets", "fed": "Markets", "inflation": "Markets",
    "fed-rate": "Markets", "interest-rate": "Markets", "rate-cut": "Markets",
    "markets": "Markets", "stocks": "Markets", "finance": "Markets",
    "spx": "Markets", "s&p": "Markets", "sp500": "Markets",
    "dow": "Markets", "nasdaq": "Markets", "ipo": "Markets",
    "oil": "Energy", "opec": "Energy", "wti": "Energy", "crude": "Energy",
    "natural-gas": "Energy", "energy": "Energy",
    # Tech & AI
    "ai": "AI", "tech": "Tech", "science": "Science",
    "space": "Space", "musk": "Tech", "elon-musk": "Tech", "spacex": "Space",
    # Crypto
    "crypto": "Crypto", "bitcoin": "Crypto", "btc": "Crypto",
    "ethereum": "Crypto", "eth": "Crypto", "solana": "Crypto", "sol": "Crypto",
    "token": "Crypto", "defi": "Crypto", "airdrop": "Crypto", "nft": "Crypto",
    # Sports — granular
    "tennis": "Tennis", "atp": "Tennis", "wta": "Tennis",
    "nba": "Basketball", "wnba": "Basketball", "nbl": "Basketball",
    "nfl": "Football", "ncaafb": "Football",
    "soccer": "Soccer", "mls": "Soccer", "epl": "Soccer",
    "la-liga": "Soccer", "premier-league": "Soccer", "serie-a": "Soccer",
    "bundesliga": "Soccer", "champions-league": "Soccer", "ligue-1": "Soccer",
    "mlb": "Baseball", "baseball": "Baseball",
    "nhl": "Hockey", "hockey": "Hockey",
    "ufc": "MMA", "mma": "MMA", "boxing": "MMA",
    "f1": "Motorsport", "nascar": "Motorsport",
    "golf": "Golf", "pga": "Golf",
    "cricket": "Cricket",
    "sports": "Sports",
    # Esports
    "esports": "Esports", "e-sports": "Esports", "cs2": "Esports", "csgo": "Esports",
    "counter-strike": "Esports", "dota": "Esports", "dota2": "Esports",
    "league-of-legends": "Esports", "lol": "Esports", "valorant": "Esports",
    "faze": "Esports", "navi": "Esports", "cybershoke": "Esports",
    # Entertainment & social
    "entertainment": "Culture", "movie": "Culture", "film": "Culture",
    "culture": "Culture", "awards": "Culture", "music": "Culture",
    "mrbeast": "Culture", "mr-beast": "Culture",
    "youtube": "Social Media", "twitter": "Social Media", "streaming": "Culture",
    # Other
    "climate": "Climate", "nuclear": "Climate",
    "legal": "Legal", "health": "Health",
    # v14.2: conflict/military + social media keywords
    "ceasefire": "Geopolitics", "invasion": "Geopolitics",
    "airstrike": "Geopolitics", "hezbollah": "Geopolitics",
    "hamas": "Geopolitics", "military action": "Geopolitics",
    "troops": "Geopolitics", "missile": "Geopolitics",
    "tweet": "Social Media", "tweets": "Social Media", "posts": "Social Media",
}

def get_theme_label(market: dict) -> str:
    """
    Return the display theme for a market.
    Prefer deterministic tag/question matching over stored LLM theme so
    obvious geopolitics markets cannot surface as Football or AI.
    """
    tag_slugs = market.get("tag_slugs", [])
    question = market.get("question", "").lower()
    for slug in tag_slugs:
        s = slug.lower()
        if s in THEME_LABELS:
            return THEME_LABELS[s]
    for kw, label in THEME_LABELS.items():
        if len(kw) >= 3 and kw in question:
            return label
    stored_theme = market.get("theme")
    if stored_theme:
        return stored_theme
    if market.get("is_sports", False):
        return "Sports"
    if market.get("is_crypto", False):
        return "Crypto"
    return "Markets"

# ── Headline cleaning ───────────────────────────────────────────────────────────
def clean_headline(raw: str) -> tuple[str, str]:
    h = raw.strip().strip('"').strip("'")
    h = re.sub(r"\s*[-–—|]\s*[A-Z][A-Za-z\s.]{2,30}$", "", h)
    h = re.sub(r"^(breaking|exclusive|update|watch|live|opinion|analysis):\s*",
               "", h, flags=re.IGNORECASE)
    if len(h) > 55:
        h = h[:52].rsplit(" ", 1)[0] + "..."
    if h:
        h = h[0].upper() + h[1:]
    return h, (h[0].lower() + h[1:]) if h else ""

# ── Emoji picking ──────────────────────────────────────────────────────────────
def get_emoji(tag_slugs: list[str], question: str = "") -> str:
    slug_set = set(s.lower() for s in tag_slugs)
    q_lower = question.lower()
    for key in EMOJI_PRIORITY:
        if key not in CATEGORY_EMOJI:
            continue
        emoji = CATEGORY_EMOJI[key]
        for slug in slug_set:
            if key == slug:
                return emoji
        for slug in slug_set:
            if len(slug) > len(key) and key in slug:
                return emoji
        if len(key) >= 4 and key in q_lower:
            return emoji
    # v7: lower threshold for sports/finance keywords in question
    sports_q_keywords = {"nba": "🏀", "nfl": "🏈", "mlb": "⚾", "nhl": "🏒",
                         "ufc": "🥊", "f1": "🏎️", "ncaaf": "🏈", "ncaab": "🏀",
                         "spx": "📈", "wti": "🛢️", "oil": "🛢️",
                         "rookie": "🏀", "award": "🏆", "trophy": "🏆",
                         "crude": "🛢️", "ether": "⟠", "btc": "₿", "eth": "⟠",
                         "atp": "🎾", "tennis": "🎾", "wimbledon": "🎾", "golf": "⛳", "pga": "⛳",
                         "ufc": "🥊", "f1": "🏎️", "ncaaf": "🏈", "ncaab": "🏀",
                         "spx": "📈", "wti": "🛢️", "oil": "🛢️",
                         "rookie": "🏀", "award": "🏆", "trophy": "🏆",
                         "crude": "🛢️", "ether": "⟠", "btc": "₿", "eth": "⟠"}
    q_words = set(q_lower.split())
    for kw, emo in sports_q_keywords.items():
        if kw in q_words or kw in q_lower:
            return emo

    # v14.2: last-resort category guessing before 📌
    if any(w in q_lower for w in ["vs", "vs.", "versus", "match", "game"]):
        return "⚽"
    if any(w in q_lower for w in ["price", "above", "below", "hit", "$"]):
        return "📈"
    if any(w in q_lower for w in ["election", "vote", "president", "governor", "senator"]):
        return "🗳️"
    if any(w in q_lower for w in ["war", "military", "ceasefire", "attack", "strike", "troops"]):
        return "⚔️"
    if any(w in q_lower for w in ["tweet", "post", "posts", "followers"]):
        return "🐦"

    return DEFAULT_EMOJI

# ── Question shortening ────────────────────────────────────────────────────────
def _strip_redundant_parens(text: str) -> str:
    def _check(match):
        inner = match.group(1).strip()
        before = text[:match.start()].lower()
        if inner.lower() in before:
            return " "
        return match.group(0)

    return re.sub(r"\s*\(([A-Z]{2,6})\)", _check, text)


def shorten_question(question: str) -> str:
    q = question.strip()
    had_qmark = q.endswith("?")
    if had_qmark:
        q = q[:-1].strip()
    if q.lower().startswith("will "):
        q = q[5:].strip()
    # v14.2: strip Polymarket internal labels
    q = re.sub(r"\s*\((?:HIGH|LOW|CLOSE|OPEN|YES|NO)\)\s*", " ", q, flags=re.IGNORECASE)
    q = re.sub(r"\s*\[(?:HIGH|LOW|CLOSE|OPEN)\]\s*", " ", q, flags=re.IGNORECASE)
    q = _strip_redundant_parens(q)
    # v15: keep the asset name instead of collapsing to just the predicate
    q = re.sub(r"^the price of (\w+) (?:be|has|have|will)\s+", r"\1 ", q, flags=re.IGNORECASE)
    q = re.sub(r"\s+(on|by|before|after)\s+\d{4}-\d{2}-\d{2}$", "", q, flags=re.IGNORECASE)
    q = re.sub(
        r"\s+(on|by|before|after)\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2},?\s*\d{0,4}$",
        "", q, flags=re.IGNORECASE
    )
    q = re.sub(r"\s+in\s+20\d{2}$", "", q, flags=re.IGNORECASE)
    q = re.sub(
        r"\s+from\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2}\s+to\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2},?\s*\d{0,4}$",
        "", q, flags=re.IGNORECASE
    )
    q = re.sub(
        r"\s*(?:get\s+)?between\s+[\d.,]+\s+and\s+[\d.,]+\s*(million|billion|[KkMmBb])?\s*",
        " ", q, flags=re.IGNORECASE
    )
    q = re.sub(r"\s+\d+-\d+\s+", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    if q:
        q = q[0].upper() + q[1:]
    q = q + ("?" if had_qmark else "")
    if len(q) > 55:
        q = q[:52].rsplit(" ", 1)[0] + "...?"
    return q

def shorten_for_lead(question: str, max_chars: int = 45) -> str:
    # v14.2: strip Polymarket internal labels before shortening
    question = re.sub(r"\s*\((?:HIGH|LOW|CLOSE|OPEN|YES|NO)\)\s*", " ", question, flags=re.IGNORECASE)
    question = re.sub(r"\s*\[(?:HIGH|LOW|CLOSE|OPEN)\]\s*", " ", question, flags=re.IGNORECASE)
    question = _strip_redundant_parens(question)
    q = shorten_question(question)
    if len(q) > max_chars:
        q = q[:max_chars - 4].rsplit(" ", 1)[0] + "..."
    return q

# ── Volume formatting ───────────────────────────────────────────────────────────
def format_volume(vol: float) -> str:
    if vol >= 1_000_000:
        return f"${vol/1_000_000:.1f}M"
    elif vol >= 1_000:
        return f"${vol/1_000:.0f}K"
    else:
        return f"${vol:,.0f}"

# ── Context generation (template + LLM grounding) ─────────────────────────────
TWEET_HEADLINE_MAX = 45
MAX_CONTEXT_WORDS = 34

CONTEXT_UP = [
    "Recent developments improved the case for this outcome. Traders are leaning toward follow-through rather than a quick reversal.",
    "Something material changed around this event today. The move suggests confidence is building behind the bullish scenario.",
    "The underlying story appears to have turned more favorable. Traders are repricing toward a stronger near-term path.",
]
CONTEXT_DOWN = [
    "Recent developments weakened the case for this outcome. Traders are pricing in a less favorable path from here.",
    "Confidence in this scenario faded quickly today. The move suggests the latest developments cut against it.",
    "The underlying story appears to have turned less supportive. Traders are repricing toward a softer near-term path.",
]

def _news_evidence_for_market(market: dict, limit: int = 2) -> list[dict]:
    evidence = []
    raw = market.get("news_evidence")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                evidence.append({
                    "title": item.get("title", ""),
                    "source": item.get("source", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("snippet", ""),
                })
    if not evidence and market.get("news_headline"):
        evidence.append({
            "title": market.get("news_headline", ""),
            "source": market.get("news_source", ""),
            "url": market.get("news_url", ""),
            "snippet": market.get("news_snippet", ""),
        })
    return evidence[:limit]

def _source_aliases(source: str) -> list[str]:
    source = (source or "").strip().lower()
    if not source:
        return []
    aliases = {source}
    host = source.replace("www.", "")
    aliases.add(host)
    root = re.sub(r"\.(com|co\.uk|co|org|net|io|tv|jp|in|de|fr|ru|us)$", "", host)
    aliases.add(root)
    aliases.update(part for part in re.split(r"[\W_]+", root) if len(part) >= 4)
    return [a for a in aliases if a]

def _normalize_context(text: str, market: dict) -> str:
    text = (text or "").strip().strip('"').strip("'")
    text = re.sub(r"https?://\S+", "", text)
    for item in _news_evidence_for_market(market):
        for alias in _source_aliases(item.get("source", "")):
            text = re.sub(rf"(?i)\baccording to {re.escape(alias)}\b[:, ]*", "", text)
            text = re.sub(rf"(?i)\b{re.escape(alias)}\b\s+(reported|reports|said|says)\b[:, ]*", "", text)
            text = re.sub(rf"(?i)\bvia {re.escape(alias)}\b[:, ]*", "", text)
            text = re.sub(rf"(?i)\bfrom {re.escape(alias)}\b[:, ]*", "", text)
            text = re.sub(rf"(?i)\b{re.escape(alias)}\b", "", text)
    text = re.sub(r"\([^)]*\.(?:com|co|org|net|io|tv)[^)]*\)", "", text)
    text = re.sub(r"\s+", " ", text).strip(" .,:;-")

    sentences = [s.strip(" \"'") for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sentences) > 2:
        sentences = sentences[:2]
    if len(sentences) == 1:
        follow_up = (
            "That is what traders appear to be reacting to."
            if market.get("news_headline")
            else "That seems to be the main driver behind the repricing."
        )
        sentences.append(follow_up)
    text = " ".join(sentences)

    words = text.split()
    if len(words) > MAX_CONTEXT_WORDS:
        text = " ".join(words[:MAX_CONTEXT_WORDS]).rstrip(" ,;:-")
    if text:
        text = text[0].upper() + text[1:]
    if text and text[-1] not in ".!?":
        text += "."
    return text

def generate_context_template(market: dict, used_patterns: set) -> str:
    going_up = market["delta_pp"] > 0
    pool = CONTEXT_UP if going_up else CONTEXT_DOWN

    available = [p for p in pool if p not in used_patterns]
    if not available:
        available = pool
    pattern = random.choice(available)
    used_patterns.add(pattern)
    return _normalize_context(pattern, market)

def generate_context_llm(market: dict) -> str | None:
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    anthropic_base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
    openai_base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    evidence_items = _news_evidence_for_market(market)
    if evidence_items:
        evidence_lines = []
        for i, item in enumerate(evidence_items, 1):
            cleaned, _ = clean_headline(item.get("title", ""))
            evidence_lines.append(f"Evidence {i} title: {cleaned}")
            if item.get("snippet"):
                evidence_lines.append(f"Evidence {i} excerpt: {item['snippet'][:260]}")
        news_block = "\n".join(evidence_lines)
    else:
        news_block = "No reliable recent article evidence was found."

    prompt = (
        "You are a sharp prediction market analyst writing concise thread commentary. "
        "Write EXACTLY two short sentences explaining what changed in the real world and why traders repriced this contract. "
        "Ground the answer only in the evidence provided when available.\n"
        "Do NOT mention publication names, headlines, article titles, links, 'according to reports', or source domains. "
        "Do NOT mention the probability, direction, volume, or that this is a market. "
        "If evidence is weak, use cautious language instead of inventing facts.\n\n"
        f"Market: {market['question']}\n"
        f"Direction: {'UP' if market['delta_pp'] > 0 else 'DOWN'} "
        f"{market['abs_delta_pp']:.0f}pp in 24h\n"
        f"Tags: {', '.join(market.get('tag_slugs', []))}\n"
        f"{news_block}\n\n"
        "Return only the two-sentence commentary. No bullets, no quotes."
    )

    if anthropic_key:
        import requests as req
        resp = req.post(
            f"{anthropic_base}/messages",
            headers={
                "x-api-key": anthropic_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
                "max_tokens": 8000 if os.environ.get("LLM_MAX_TOKENS") is None else int(os.environ.get("LLM_MAX_TOKENS")),
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return _normalize_context(resp.json()["content"][0]["text"], market)

    elif openai_key:
        import requests as req
        resp = req.post(
            f"{openai_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                "max_tokens": 8000 if os.environ.get("LLM_MAX_TOKENS") is None else int(os.environ.get("LLM_MAX_TOKENS")),
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return _normalize_context(resp.json()["choices"][0]["message"]["content"], market)

    return None

# ── Market URL builder ─────────────────────────────────────────────────────────
def make_market_url(market: dict) -> str:
    # v7: prefer market_url from scanner (canonical URL from slugs)
    base = market.get("market_url")
    if not base or base == "https://polymarket.com":
        event_slug = market.get("event_slug", "")
        market_slug = market.get("market_slug", "")
        if event_slug and market_slug:
            base = f"https://polymarket.com/event/{event_slug}/{market_slug}"
        elif market_slug:
            base = f"https://polymarket.com/event/{market_slug}"
        else:
            base = "https://polymarket.com"
    if REFERRAL_ID and REFERRAL_ID != "__FILL_IN__":
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}ref={REFERRAL_ID}"
    return base

# ── Lead tweet composition (v7: exactly 3 movers + Show more) ─────────────────
def _extract_lead_entity(market: dict) -> str | None:
    q = market.get("question", "").lower()
    keywords = [
        "mrbeast", "mr beast", "trump", "biden", "harris",
        "bitcoin", "btc", "ethereum", "eth",
        "ukraine", "russia", "israel", "gaza", "iran", "china", "taiwan",
        "fed ", "openai", "tesla", "nvidia",
        # v7: award races
        "art ross", "hart trophy", "mvp",
        # v7: NCAA
        "ncaa",
        # v7: token
        "token", "axiom",
    ]
    for kw in keywords:
        if kw in q:
            return kw.replace(" ", "")
    return None

def _pick_hook_mover(lead_picks: list) -> dict | None:
    if not lead_picks:
        return None
    def hook_score(m):
        score = 0
        if m.get("news_headline"):
            score += 100
        if not m.get("is_crypto", False):
            score += 50  # v8: prefer non-crypto for hook
        score += m.get("editorial_weight", 1.0) * 10
        score += min(m.get("volume_24h", 0) / 100000, 5)
        return score
    return max(lead_picks, key=hook_score)





def compose_lead_tweet(movers: list) -> str:
    # v13: select exactly 3 diverse NON-CRYPTO movers for the lead
    lead_picks = []
    used_entities = set()
    for m in movers:
        if len(lead_picks) >= 3:
            break
        if m.get("is_crypto", False):
            continue
        entity = _extract_lead_entity(m)
        if entity and entity in used_entities:
            continue
        lead_picks.append(m)
        if entity:
            used_entities.add(entity)
    while len(lead_picks) < 3 and len(lead_picks) < len(movers):
        for m in movers:
            if m not in lead_picks:
                lead_picks.append(m)
                break

    # v13: branded header
    header = f"\U0001f4ca {to_bold('Polymarket News')}"

    # v13.1: show full title, hide pct range to save space
    for max_q_len in [55, 48, 42, 36]:
        mover_lines = []
        for i, m in enumerate(lead_picks[:3]):
            emoji = m.get("emoji") or get_emoji(m.get("tag_slugs", []), m.get("question", ""))
            theme = get_theme_label(m)
            theme_bold = to_bold(theme)
            short_q = shorten_for_lead(m["question"], max_chars=max_q_len)
            sign = "+" if m["delta_pp"] > 0 else ""
            direction = "\U0001f4c8" if m["delta_pp"] > 0 else "\U0001f4c9"
            line = f"{i+1}. {emoji} {theme_bold} \u00b7 {short_q} {direction}{sign}{m['delta_pp']:.0f}pp"
            mover_lines.append(line)
        body = "\n".join(mover_lines)
        full = f"{header}\n\n{body}\n\nShow more"
        if count_tweet_chars(full) <= 280:
            return full

    # Absolute length guard
    if count_tweet_chars(full) > 280:
        full = full[:277] + "..."
    return full



# ── Reply composition ──────────────────────────────────────────────────────────
def compose_reply(market: dict) -> str:
    emoji = market.get("emoji") or get_emoji(market.get("tag_slugs", []), market.get("question", ""))
    theme = get_theme_label(market)
    short_q = shorten_question(market["question"])
    url = make_market_url(market)
    vol = market["volume_24h"]
    vol_str = format_volume(vol)
    arrow = "\U0001f4c8" if market["delta_pp"] > 0 else "\U0001f4c9"
    sign = "+" if market["delta_pp"] > 0 else ""
    context = market.get("context_line", "")

    # v13: DEFENSIVE — if context somehow still empty, generate inline
    if not context or len(context.strip()) < 10:
        if market["delta_pp"] > 0:
            context = f"A {market['abs_delta_pp']:.0f}pp swing on {vol_str} volume suggests new information"
        else:
            context = f"Dropped {market['abs_delta_pp']:.0f}pp on {vol_str} volume \u2014 market growing skeptical"

    outcome = market.get("primary_outcome", "Yes")
    old_pct = market["price_24h_ago_pct"]
    new_pct = market["price_now_pct"]

    # v13: theme header line + clearer outcome with inline price move
    theme_header = f"{emoji} {to_bold(theme)}"
    pct_line = f"{outcome}: {new_pct:.0f}% {arrow} ({old_pct:.0f}\u2192{new_pct:.0f}%, {sign}{vol_str} vol)"

    lines = [
        theme_header,
        "",
        short_q,
        pct_line,
        "",
        context,
        "",
        f"\u279c  {url}",
    ]
    tweet = "\n".join(lines)
    return _trim_to_limit(tweet, 280)

# ── Validation ──────────────────────────────────────────────────────────────────
def validate_tweet(text: str, label: str) -> list[str]:
    issues = []
    effective = count_tweet_chars(text)
    if effective > 280:
        issues.append(f"{label}: {effective} effective chars (max 280)")
    if "{{" in text or "}}" in text:
        issues.append(f"{label}: contains unresolved template placeholder")
    if "__FILL_IN__" in text:
        issues.append(f"{label}: contains __FILL_IN__ placeholder")
    if "SUBSTACK_URL" in text:
        issues.append(f"{label}: contains SUBSTACK_URL placeholder")
    return issues

# ── Main ───────────────────────────────────────────────────────────────────────


def generate_all_contexts_llm(movers: list) -> dict[int, str]:
    """
    Generate two-sentence commentary grounded in recent news evidence.
    Returns dict mapping rank → context string.
    """
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not anthropic_key and not openai_key:
        return {}

    anthropic_base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
    openai_base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    market_blocks = []
    for m in movers:
        evidence_items = _news_evidence_for_market(m)
        if evidence_items:
            evidence_lines = []
            for i, item in enumerate(evidence_items, 1):
                cleaned, _ = clean_headline(item.get("title", ""))
                evidence_lines.append(f"  Evidence {i} title: {cleaned}")
                if item.get("snippet"):
                    evidence_lines.append(f"  Evidence {i} excerpt: {item['snippet'][:250]}")
            news_section = "\n".join(evidence_lines)
        else:
            news_section = "  No reliable article evidence found."

        market_blocks.append(
            f"{m['rank']}. {m['question'][:100]}\n"
            f"  {'UP' if m['delta_pp'] > 0 else 'DOWN'} {m['abs_delta_pp']:.0f}pp\n"
            f"  Tags: {', '.join(m.get('tag_slugs', []))}\n"
            f"{news_section}"
        )

    prompt = (
        "You are a prediction market analyst writing concise thread commentary. "
        "For EACH market below, write EXACTLY two short sentences explaining what happened in the real world and why traders repriced the contract.\n\n"
        "CRITICAL RULES:\n"
        "- Ground each answer only in the provided evidence when evidence exists\n"
        "- Do NOT invent facts, names, statistics, or events not present in the evidence\n"
        "- Do NOT mention publication names, article titles, links, source domains, or 'according to reports'\n"
        "- Do NOT restate the probability, direction, or volume\n"
        "- If evidence is weak or absent, use cautious language instead of bluffing\n"
        "- Keep each answer compact and plainspoken\n\n"
        "Markets:\n" + "\n\n".join(market_blocks) + "\n\n"
        "Respond with ONLY valid JSON: {\"1\": \"context\", \"2\": \"context\", ...}\n"
        "No markdown, no explanation, no backticks."
    )

    try:
        import requests as req
        if anthropic_key:
            resp = req.post(
                f"{anthropic_base}/messages",
                headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
                      "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", 8000)),
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=90,
            )
            resp.raise_for_status()
            raw = resp.json()["content"][0]["text"].strip()
        elif openai_key:
            resp = req.post(
                f"{openai_base}/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                json={"model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                      "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", 8000)),
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=90,
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            if not raw:
                return {}
            raw = raw.strip()
        else:
            return {}

        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
        result = json.loads(raw)
        return {int(k): _normalize_context(v, next(m for m in movers if m["rank"] == int(k)))
                for k, v in result.items()}
    except Exception as e:
        print(f"[COMPOSE] Batch context LLM failed: {e}", file=sys.stderr)
        return {}

def main():
    if not INPUT_FILE.exists():
        print(f"[COMPOSE] ERROR: {INPUT_FILE} not found", file=sys.stderr)
        sys.exit(1)

    with open(INPUT_FILE) as f:
        ranked_data = json.load(f)

    movers = ranked_data.get("movers", [])
    if not movers:
        print("[COMPOSE] ERROR: No movers in ranked data.", file=sys.stderr)
        sys.exit(1)

    # ── Generate context lines ────────────────────────────────────────────────
    print(f"[COMPOSE] Mode: {COMPOSE_MODE}. Generating context for {len(movers)} movers...")
    used_patterns = set()

    # v12 SPEED: batch all LLM context calls into ONE request
    batch_contexts = {}
    if COMPOSE_MODE == "llm":
        print("[COMPOSE] Generating all contexts in ONE batched LLM call...")
        batch_contexts = generate_all_contexts_llm(movers)
        if batch_contexts:
            print(f"[COMPOSE] LLM returned {len(batch_contexts)} contexts in batch")
        else:
            print("[COMPOSE] Batch LLM failed — falling back to individual calls")

    for m in movers:
        context = batch_contexts.get(m.get("rank"))

        # If batch didn't cover this market, try individual LLM
        if not context and COMPOSE_MODE == "llm" and not batch_contexts:
            try:
                context = generate_context_llm(m)
            except Exception as e:
                print(f" [WARN] LLM failed for '{m['question'][:40]}': {e}")

        # Final fallback: template
        if not context:
            context = generate_context_template(m, used_patterns)

        m["context_line"] = context
        print(f"  [{m['rank']}] {context}")

    # ── SAFETY NET (v7): every mover MUST have a useful context_line ───────────
    for m in movers:
        context = m.get("context_line", "").strip()
        if len(context) < 20:
            print(f" [WARN] Reply {m.get('rank','?')} has short context, regenerating...")
            try:
                m["context_line"] = generate_context_template(m, used_patterns)
            except Exception:
                pass

        context = m.get("context_line", "").strip()
        if len(context) < 20:
            if m["delta_pp"] > 0:
                m["context_line"] = (
                    "Recent developments appear to have improved the case for this outcome. "
                    "Traders are leaning toward a stronger near-term path."
                )
            else:
                m["context_line"] = (
                    "Recent developments appear to have weakened the case for this outcome. "
                    "Traders are pricing in a less favorable near-term path."
                )
            print(f" [WARN] Reply {m.get('rank','?')} safety-net applied: {m['context_line'][:60]}...")

    # v8: reorder movers — non-crypto first, crypto last
    non_crypto = [m for m in movers if not m.get("is_crypto", False)]
    crypto = [m for m in movers if m.get("is_crypto", False)]
    movers_ordered = non_crypto + crypto
    for i, m in enumerate(movers_ordered):
        m["display_rank"] = i + 1

    # ── Compose tweets ────────────────────────────────────────────────────────
    lead = compose_lead_tweet(movers_ordered)
    replies = [compose_reply(m) for m in movers_ordered]

    # ── Validate ──────────────────────────────────────────────────────────────
    all_issues = []
    all_issues.extend(validate_tweet(lead, "LEAD"))
    for i, reply in enumerate(replies):
        all_issues.extend(validate_tweet(reply, f"REPLY_{i+1}"))

    if all_issues:
        print("\n[COMPOSE] VALIDATION ISSUES:")
        for issue in all_issues:
            print(f"  WARNING: {issue}")

    fatal = [i for i in all_issues if "placeholder" in i or "FILL_IN" in i]
    if fatal:
        print("[COMPOSE] FATAL: Placeholder leaks detected. Fix config before publishing.",
              file=sys.stderr)
        sys.exit(1)

    # Length safety net — should rarely trigger now that compose_reply trims
    for i, reply in enumerate(replies):
        eff = count_tweet_chars(reply)
        if eff > 280:
            print(f" [FIX] Reply {i+1} is {eff} chars, trimming...")
            replies[i] = _trim_to_limit(reply, 280)
            print(f" [FIX] Reply {i+1} trimmed → {count_tweet_chars(replies[i])} chars")

    output = {
        "date": DATE,
        "compose_mode": COMPOSE_MODE,
        "lead": lead,
        "replies": replies,
        "validation_issues": all_issues,
    }

    with open(TWEETS_FILE, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    lead_eff = count_tweet_chars(lead)
    mover_count_in_lead = lead.count("%") // 2  # each mover has two percentages
    print(f"\n[COMPOSE] Lead: {lead_eff} effective chars | {mover_count_in_lead} movers | ends with 'Show more': {lead.strip().endswith('Show more')}")
    print(f"[COMPOSE] {len(replies)} replies composed. Written to {TWEETS_FILE}")
    print(f"\n=== LEAD TWEET ===\n{lead}")
    sys.exit(0)

if __name__ == "__main__":
    main()
