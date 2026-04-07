"""
Interest Ranker subagent v9.
Reorders top N movers by engagement potential using an LLM.
Crypto is always last. Non-critical — falls back to mover-score order on failure.

INPUT: {DATA_DIR}/briefs/{date}/ranked.json (or enriched.json)
OUTPUT: Reorders movers in the input file in-place
EXIT: 0 always (non-blocking)
"""

import os, sys, json, requests
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR  = Path(os.environ.get("DATA_DIR", "/home/diligentapple/.openclaw/workspace/polymarket"))
DATE      = os.environ.get("RUN_DATE") or "2026-04-06"
RANKED    = DATA_DIR / "briefs" / DATE / "ranked.json"
ENRICHED  = DATA_DIR / "briefs" / DATE / "enriched.json"
INPUT_FILE = ENRICHED if ENRICHED.exists() else RANKED
TMP_FILE  = INPUT_FILE.parent / f"{INPUT_FILE.stem}.interest_tmp.json"

ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY")
OPENAI_KEY    = os.environ.get("OPENAI_API_KEY")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

def rank_llm(movers: list) -> list[int] | None:
    lines = []
    for m in movers:
        emoji  = m.get("emoji", "📌")
        q      = m.get("question", "?")
        delta  = m.get("delta_pp", 0)
        vol    = m.get("volume_24h", 0)
        news   = (m.get("news_headline") or "no news")[:80]
        crypto = "yes" if m.get("is_crypto") else "no"
        lines.append(
            f"{m['rank']}. {emoji} {q}\n"
            f"   delta:{delta:+.0f}pp | vol:${vol:,.0f} | crypto:{crypto} | {news}"
        )
    prompt = (
        "Rank these prediction markets from MOST to LEAST engaging for a Twitter audience.\n\n"
        "High engagement: major geopolitics, entertainment, surprising moves, big volume.\n"
        "Low engagement: niche esports, crypto price markets (up/down), obscure sports.\n"
        "If you don't recognize the teams or event, rank it lower — obscure markets are low engagement.\n\n"
        "Markets:\n" + "\n\n".join(lines) + "\n\n"
        "Respond with ONLY a JSON array of market numbers in engagement order.\n"
        "Example: [3, 1, 5, 2, 4, 8, 7, 6]\n"
        "No markdown, no explanation."
    )
    try:
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
            raw = msg.get("content")
            if not raw:
                raise ValueError(f"Interest ranker LLM empty content. reasoning[:80]: {msg.get('reasoning','')[:80]}")
            raw = raw.strip()
        else:
            return None
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
        order = json.loads(raw)
        return [int(x) for x in order]
    except Exception as e:
        print(f"[INTEREST] LLM ranking failed: {e}", file=sys.stderr)
        return None

def main():
    if not INPUT_FILE.exists():
        print(f"[INTEREST] ERROR: {INPUT_FILE} not found", file=sys.stderr)
        sys.exit(1)
    with open(INPUT_FILE) as f:
        data = json.load(f)
    movers = data.get("movers", [])
    if not movers:
        print("[INTEREST] No movers — skipping.", file=sys.stderr)
        sys.exit(0)

    print(f"[INTEREST] Ranking {len(movers)} movers by engagement...")
    rank_map = {m["rank"]: m for m in movers}
    interest_order = rank_llm(movers)

    if interest_order:
        print(f"[INTEREST] LLM order: {interest_order}")
        reordered = []
        seen = set()
        for r in interest_order:
            if r in rank_map and r not in seen:
                reordered.append(rank_map[r])
                seen.add(r)
        for m in movers:
            if m["rank"] not in seen:
                reordered.append(m)
        movers = reordered
    else:
        print("[INTEREST] LLM unavailable — keeping mover-score order.")

    # Enforce: crypto always last
    non_crypto = [m for m in movers if not m.get("is_crypto")]
    crypto      = [m for m in movers if     m.get("is_crypto")]
    movers = non_crypto + crypto

    # Assign display ranks
    for i, m in enumerate(movers):
        m["original_rank"]    = m.get("rank", i+1)
        m["rank"]             = i + 1
        m["interest_rank"]    = i + 1

    data["movers"] = movers
    data["interest_ranked_at"] = datetime.now(timezone.utc).isoformat()
    with open(TMP_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    TMP_FILE.rename(INPUT_FILE)

    print("[INTEREST] Final order:")
    for m in movers:
        tag = " [CRYPTO]" if m.get("is_crypto") else ""
        print(f"  {m['rank']}. {m.get('emoji','📌')} {m['question'][:50]}...{tag}")
    sys.exit(0)

if __name__ == "__main__":
    main()
