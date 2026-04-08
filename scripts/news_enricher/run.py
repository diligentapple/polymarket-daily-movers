"""
News Enricher subagent.
For each ranked mover, searches the web for recent news that likely caused the move.
Attaches headline + source to each mover for the composer to use.

INPUT: {DATA_DIR}/briefs/{date}/ranked.json
OUTPUT: {DATA_DIR}/briefs/{date}/enriched.json
EXIT: 0 on success, 1 on failure
"""

import os
import sys
import json
import re
import time
import requests
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote_plus

DATA_DIR = Path(os.environ.get("DATA_DIR", "/home/diligentapple/.openclaw/workspace/polymarket"))
DATE = os.environ.get("RUN_DATE")
INPUT_FILE = DATA_DIR / "briefs" / DATE / "ranked.json"
OUTPUT_FILE = DATA_DIR / "briefs" / DATE / "enriched.json"
TMP_FILE = DATA_DIR / "briefs" / DATE / "enriched.tmp.json"

PER_MARKET_TIMEOUT = int(os.environ.get("NEWS_SEARCH_TIMEOUT", 10))

# ============================================================
# KNOWN ENTITIES AND GEO WORDS
# ============================================================

KNOWN_ENTITIES = {
    "mrbeast", "trump", "biden", "harris", "modi", "macron", "putin",
    "zelensky", "netanyahu", "xi jinping", "elon musk", "openai",
    "google", "apple", "tesla", "nvidia", "spacex", "amazon", "meta",
    "bitcoin", "ethereum", "solana", "cardano",
    "nato", "eu", "imf", "fed", "ecb", "opec",
    "ukraine", "russia", "israel", "gaza", "iran", "china", "taiwan",
    "north korea", "syria", "lebanon", "yemen",
}

GEO_WORDS = {
    "peru", "ecuador", "brazil", "argentina", "mexico", "colombia", "chile",
    "india", "pakistan", "bangladesh", "japan", "korea", "philippines",
    "nigeria", "south africa", "kenya", "egypt", "turkey", "indonesia",
    "australia", "canada", "uk", "france", "germany", "italy", "spain",
    "poland", "romania", "hungary", "california", "texas", "florida",
    "new york", "london", "paris", "berlin", "tokyo", "beijing",
}

# ============================================================
# QUERY CONSTRUCTION
# ============================================================

def build_search_query(market: dict) -> str:
    q = market.get("question", "")

    # Special case: crypto up/down
    crypto_match = re.match(r"(?i)(bitcoin|btc|ethereum|eth|solana|sol).*(?:up|down)", q)
    if crypto_match:
        coin = crypto_match.group(1)
        canonical = {"btc": "bitcoin", "eth": "ethereum", "sol": "solana"}.get(coin.lower(), coin)
        return f"{canonical} price today"

    # Special case: sports matches
    sports_match = re.match(r"(?i)(.+?)\s+(?:vs\.?|versus)\s+(.+?)(?:\s+(?:win|draw|end|on).*)?$", q)
    if sports_match:
        team1 = sports_match.group(1).strip()
        team2 = sports_match.group(2).strip()
        return f"{team1} vs {team2}"

    # General case
    q = q.rstrip("?").strip()
    q = re.sub(r"^(will|does|is|are|has|have|can|could|should|would)\s+", "", q, flags=re.IGNORECASE)
    q = re.sub(r"\s*(by|on|before|after)\s+\d{4}[-/]\d{2}[-/]\d{2}", "", q, flags=re.IGNORECASE)
    q = re.sub(r"\s*(by|on|before|after|in)\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s*\d{0,4}", "", q, flags=re.IGNORECASE)
    q = re.sub(r"\s+20\d{2}\s*$", "", q)
    q = re.sub(r"\s*between\s+[\d.,]+\s+and\s+[\d.,]+\s*(million|billion|[KkMmBb])?\s*", " ", q)
    q = re.sub(r"\s*(?:get|reach|hit|exceed|over|under)\s+[\d.,]+\s*[KkMmBb]?\s*", " ", q)
    q = re.sub(r"\s+", " ", q).strip()

    if q:
        q = q[0].upper() + q[1:]

    # Verify at least one entity or geo word survived
    q_check = q.lower()
    has_entity = any(ent in q_check for ent in KNOWN_ENTITIES)
    has_geo = any(geo in q_check for geo in GEO_WORDS)

    if not has_entity and not has_geo:
        original_lower = market.get("question", "").lower()
        for ent in KNOWN_ENTITIES:
            if ent in original_lower:
                q = f"{ent.title()} {q}"
                break
        else:
            for geo in GEO_WORDS:
                if geo in original_lower:
                    q = f"{geo.title()} {q}"
                    break

    words = q.split()
    if len(words) > 8:
        original_lower = market.get("question", "").lower()
        first_eight = " ".join(words[:8]).lower()
        priority_word = None
        for geo in GEO_WORDS:
            if geo in original_lower and geo not in first_eight:
                priority_word = geo
                break
        if priority_word is None:
            for ent in KNOWN_ENTITIES:
                if ent in original_lower and ent not in first_eight:
                    priority_word = ent
                    break
        if priority_word:
            for i, w in enumerate(words):
                if w.lower().rstrip(".,;:!?)s") == priority_word.lower():
                    q = " ".join(words[:i+1])
                    break
            else:
                    q = " ".join(words[:8])
        else:
            q = " ".join(words[:8])
    q_lower = q.lower()
    if len(q.split()) > 5 and any(kw in q_lower for kw in
            ["military action", "continues through", "ceasefire",
             "strike on", "invade", "troops", "conflict ends"]):
        entities = []
        for ent in KNOWN_ENTITIES:
            if ent in market.get("question", "").lower():
                entities.append(ent.title())
        if entities:
            action_words = []
            for aw in ["ceasefire", "military", "strike", "war", "conflict",
                       "invasion", "peace", "attack"]:
                if aw in q_lower:
                    action_words.append(aw)
                    break
            if action_words:
                q = " ".join(entities[:2]) + " " + action_words[0]
    return q

# ============================================================
# SEARCH BACKENDS
# ============================================================

def search_duckduckgo(query: str) -> list[dict]:
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": f"{query} news", "t": "h_", "ia": "news"},
            headers={"User-Agent": "Mozilla/5.0 (compatible; PolymarketBrief/1.0)"},
            timeout=PER_MARKET_TIMEOUT,
        )
        resp.raise_for_status()
        html = resp.text

        results = []
        pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            re.DOTALL
        )
        for match in pattern.finditer(html):
            url = match.group(1)
            title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            if title and url and not url.startswith("//duckduckgo"):
                source_match = re.match(r"https?://(?:www\.)?([^/]+)", url)
                source = source_match.group(1) if source_match else ""
                results.append({"title": title, "url": url, "source": source})
            if len(results) >= 5:
                break
        return results
    except Exception as e:
        print(f"  [WARN] DuckDuckGo failed: {e}", file=sys.stderr)
        return []

def search_google_news_rss(query: str) -> list[dict]:
    try:
        rss_url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en&gl=US&ceid=US:en"
        resp = requests.get(
            rss_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PolymarketBrief/1.0)"},
            timeout=PER_MARKET_TIMEOUT,
        )
        resp.raise_for_status()
        xml = resp.text

        results = []
        items = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
        for item in items[:5]:
            title_match = re.search(r"<title>(.*?)</title>", item)
            link_match = re.search(r"<link>(.*?)</link>", item)
            source_match = re.search(r"<source[^>]*>(.*?)</source>", item)
            title = title_match.group(1).strip() if title_match else ""
            url = link_match.group(1).strip() if link_match else ""
            source = source_match.group(1).strip() if source_match else ""
            title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            title = title.replace("&#39;", "'").replace("&quot;", '"')
            if title:
                results.append({"title": title, "url": url, "source": source})
        return results
    except Exception as e:
        print(f"  [WARN] Google News RSS failed: {e}", file=sys.stderr)
        return []

def fetch_article_snippet(url: str, max_chars: int = 300) -> str:
    """
    v14: Fetch the first ~300 chars of article body text.
    Used to ground the composer's LLM context in real reporting.
    Returns empty string on failure — non-blocking.
    """
    if not url or "google.com/rss" in url:
        return ""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PolymarketBrief/1.0)"},
            timeout=6,
            allow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text[:20000]  # don't parse huge pages

        # Strip HTML tags
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        # Extract meaningful chunk — skip short fragments
        # Find first sentence-like chunk > 80 chars (skips nav/header text)
        sentences = re.split(r"(?<=[.!?])\s+", text)
        buffer = ""
        for s in sentences:
            if len(s) < 20:
                continue
            buffer += s + " "
            if len(buffer) >= max_chars:
                break

        snippet = buffer.strip()[:max_chars]
        if len(snippet) < 50:
            return ""  # too short to be useful
        return snippet
    except Exception:
        return ""

def find_best_headline(results: list[dict], query: str) -> dict | None:
    """
    Pick the most relevant headline from search results.
    Returns None if the best score is below MIN_RELEVANCE_SCORE (2).
    """
    if not results:
        return None

    MIN_RELEVANCE_SCORE = 2

    query_words = set(w.lower() for w in query.split() if len(w) > 2)

    preferred_domains = {
        "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk",
        "nytimes.com", "washingtonpost.com", "theguardian.com",
        "bloomberg.com", "ft.com", "wsj.com", "cnbc.com",
        "aljazeera.com", "cnn.com", "politico.com", "axios.com",
        "coindesk.com", "theblock.co", "decrypt.co", "cointelegraph.com",
        "espn.com", "theathletic.com", "france24.com", "dw.com",
        "scmp.com", "japantimes.co.jp", "timesofindia.indiatimes.com",
    }
    junk_domains = {
        "youtube.com", "reddit.com", "twitter.com", "x.com",
        "tiktok.com", "facebook.com", "instagram.com",
        "pinterest.com", "quora.com", "amazon.com",
        # Prediction market sites — strip TLD to catch bare source names too
        "polymarket", "polymarket.com", "kalshi", "kalshi.com",
        "metaculus", "metaculus.com", "predictit", "predictit.org",
        "manifold", "manifold.markets",
    }
    junk_phrases = ["how to", "top 10", "best ", "buy now", "sign up",
                    "subscribe", "what is", "definition of",
                    "polymarket", "kalshi", "predictit", "metaculus",
                    "prediction market"]

    scored = []
    for r in results:
        title_lower = r["title"].lower()
        source_lower = r.get("source", "").lower()

        if any(d in source_lower for d in junk_domains):
            continue
        if any(p in title_lower for p in junk_phrases):
            continue

        title_words = set(re.findall(r"\w+", title_lower))
        overlap = len(query_words & title_words)
        domain_bonus = 2 if any(d in source_lower for d in preferred_domains) else 0
        score = overlap + domain_bonus
        scored.append((score, r))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_result = scored[0]

    if best_score < MIN_RELEVANCE_SCORE:
        print(f"  [SKIP] Headline scored {best_score} (floor={MIN_RELEVANCE_SCORE}): "
              f"'{best_result['title'][:60]}' — rejecting as off-topic")
        return None

    return best_result

# ============================================================
# MAIN
# ============================================================

def main():
    if not INPUT_FILE.exists():
        print(f"[NEWS] ERROR: {INPUT_FILE} not found", file=sys.stderr)
        sys.exit(1)

    with open(INPUT_FILE) as f:
        ranked_data = json.load(f)

    movers = ranked_data.get("movers", [])
    if not movers:
        print("[NEWS] ERROR: No movers in ranked data.", file=sys.stderr)
        sys.exit(1)

    print(f"[NEWS] Enriching {len(movers)} movers with news context...")

    # v12: Parallel news search â 4 workers, 0.3s delay instead of 1s
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _enrich_one_market(m):
        query = build_search_query(m)
        results = search_google_news_rss(query)
        search_source = "google_news_rss"
        if results and all("polymarket.com" in r.get("source", "").lower() for r in results):
            ddg_results = search_duckduckgo(query)
            non_poly = [r for r in ddg_results if "polymarket.com" not in r.get("source", "").lower()]
            if non_poly:
                results = non_poly
                search_source = "duckduckgo"
        results = [r for r in results
                   if "polymarket.com" not in r.get("source", "").lower()
                   and "kalshi.com" not in r.get("source", "").lower()
                   and "predictit.org" not in r.get("source", "").lower()]
        best = find_best_headline(results, query)
        # v14: fetch article snippet for LLM grounding
        snippet = ""
        if best and best.get("url"):
            snippet = fetch_article_snippet(best["url"])
        time.sleep(0.3)
        return m["rank"], query, best, search_source, snippet

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_enrich_one_market, m): m for m in movers}
        for future in as_completed(futures):
            m = futures[future]
            rank, query, best, search_source, snippet = future.result()
            print(f"  {rank}. Query: '{query}'")
            if best:
                m["news_headline"] = best["title"]
                m["news_source"] = best.get("source", "")
                m["news_url"] = best.get("url", "")
                m["news_search_source"] = search_source
                m["news_snippet"] = snippet
                snip_note = f" [+{len(snippet)}ch snippet]" if snippet else ""
                print(f"  -> {best['title'][:80]}... ({best.get('source', '?')}){snip_note}")
            else:
                m["news_headline"] = None
                m["news_source"] = None
                m["news_url"] = None
                m["news_search_source"] = None
                m["news_snippet"] = ""
                print(f"  -> No relevant news found")

    output = {
        **ranked_data,
        "enriched_at": datetime.now(timezone.utc).isoformat(),
        "movers": movers,
    }

    with open(TMP_FILE, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    TMP_FILE.rename(OUTPUT_FILE)

    found = sum(1 for m in movers if m.get("news_headline"))
    print(f"[NEWS] Done. {found}/{len(movers)} movers matched to news headlines.")
    sys.exit(0)

if __name__ == "__main__":
    main()
