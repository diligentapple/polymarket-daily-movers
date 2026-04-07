"""
URL Verifier subagent v8.
Checks every Polymarket URL in composed tweets.
Replaces broken URLs with event-level fallbacks or generic polymarket.com.
Non-blocking: always exits 0 so the brief can still publish.

INPUT: {DATA_DIR}/briefs/{date}/tweets.json
       {DATA_DIR}/briefs/{date}/ranked.json (for fallback URL data)
OUTPUT: {DATA_DIR}/briefs/{date}/tweets.json (updated in-place)
        {DATA_DIR}/briefs/{date}/url_verification.json (report)
EXIT: 0 (always — unfixable URLs fall back to generic)
"""

import os, sys, json, re, time
import requests
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR     = Path(os.environ.get("DATA_DIR", "/home/diligentapple/.openclaw/workspace/polymarket"))
DATE         = os.environ.get("RUN_DATE")
TWEETS_FILE  = DATA_DIR / "briefs" / DATE / "tweets.json"
RANKED_FILE  = DATA_DIR / "briefs" / DATE / "ranked.json"
REPORT_FILE  = DATA_DIR / "briefs" / DATE / "url_verification.json"
TMP_FILE     = DATA_DIR / "briefs" / DATE / "tweets.verified.tmp.json"
REFERRAL_ID  = os.environ.get("POLYMARKET_REFERRAL_ID", "")
CHECK_TIMEOUT = int(os.environ.get("URL_CHECK_TIMEOUT", 8))

def extract_urls(text: str) -> list[str]:
    return re.findall(r"https?://polymarket\.com/event/[^\s\)]+", text)

def check_url(url: str) -> dict:
    clean = re.sub(r"[?&]ref=[^&\s]*", "", url).rstrip("?&")
    try:
        resp = requests.head(clean, timeout=CHECK_TIMEOUT, allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PolymarketBrief/1.0)"})
        result = {"url": url, "clean_url": clean, "status_code": resp.status_code,
                  "ok": resp.status_code < 400,
                  "redirect_url": str(resp.url) if str(resp.url) != clean else None}
        if resp.status_code == 405:
            resp = requests.get(clean, timeout=CHECK_TIMEOUT, allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; PolymarketBrief/1.0)"},
                stream=True)
            resp.close()
            result["status_code"] = resp.status_code
            result["ok"] = resp.status_code < 400
        return result
    except requests.exceptions.Timeout:
        return {"url": url, "clean_url": clean, "status_code": 0, "ok": False, "error": "timeout"}
    except requests.exceptions.ConnectionError as e:
        return {"url": url, "clean_url": clean, "status_code": 0, "ok": False, "error": str(e)[:100]}
    except Exception as e:
        return {"url": url, "clean_url": clean, "status_code": 0, "ok": False, "error": str(e)[:100]}

def fallback_url(event_slug: str) -> str:
    base = f"https://polymarket.com/event/{event_slug}"
    if REFERRAL_ID:
        return f"{base}?ref={REFERRAL_ID}"
    return base

def try_fix(broken: str, movers: list) -> str | None:
    match = re.search(r"polymarket\.com/event/([^\s?&]+)", broken)
    if not match:
        return None
    broken_slug = match.group(1).lower()
    for m in movers:
        event_slug = m.get("event_slug", "")
        market_slug = m.get("market_slug", "")
        if market_slug and (market_slug.lower() in broken_slug or broken_slug in market_slug.lower()):
            if event_slug:
                fb = fallback_url(event_slug)
                if check_url(fb)["ok"]:
                    return fb
        q_words = set(m.get("question", "").lower().split())
        slug_words = set(broken_slug.replace("-", " ").split())
        if len(q_words & slug_words) >= 3 and event_slug:
            fb = fallback_url(event_slug)
            if check_url(fb)["ok"]:
                return fb
    return None

def main():
    if not TWEETS_FILE.exists():
        print(f"[URL-VERIFY] ERROR: {TWEETS_FILE} not found", file=sys.stderr)
        sys.exit(1)

    with open(TWEETS_FILE) as f:
        tweets = json.load(f)

    movers = []
    if RANKED_FILE.exists():
        with open(RANKED_FILE) as f:
            movers = json.load(f).get("movers", [])

    lead = tweets.get("lead", "")
    replies = tweets.get("replies", [])
    all_texts = [lead] + replies

    print(f"[URL-VERIFY] Checking {len(all_texts)} tweets...")
    results = []
    fixed = 0
    unfixable = 0
    generic = f"https://polymarket.com{('?ref=' + REFERRAL_ID) if REFERRAL_ID and REFERRAL_ID != '__FILL_IN__' else ''}"

    for i, text in enumerate(all_texts):
        label = "LEAD" if i == 0 else f"REPLY_{i}"
        urls = extract_urls(text)
        for url in urls:
            print(f" [{label}] Checking: {url[:70]}...", end=" ", flush=True)
            time.sleep(0.5)
            check = check_url(url)
            if check["ok"]:
                print(f"✅ {check['status_code']}")
                results.append({**check, "tweet": label, "action": "ok"})
            else:
                print(f"❌ {check.get('status_code', 'ERR')}")
                fb = try_fix(url, movers)
                if fb:
                    print(f"  🔧 Fixed → {fb}")
                    if i == 0:
                        tweets["lead"] = tweets["lead"].replace(url, fb)
                    else:
                        tweets["replies"][i-1] = tweets["replies"][i-1].replace(url, fb)
                    results.append({**check, "tweet": label, "action": "fixed", "fixed_url": fb})
                    fixed += 1
                else:
                    print(f"  ⚠️ Unfixable — using generic")
                    if i == 0:
                        tweets["lead"] = tweets["lead"].replace(url, generic)
                    else:
                        tweets["replies"][i-1] = tweets["replies"][i-1].replace(url, generic)
                    results.append({**check, "tweet": label, "action": "generic_fallback", "fallback": generic})
                    unfixable += 1

    ok_count = sum(1 for r in results if r["action"] == "ok")
    report = {
        "date": DATE, "verified_at": datetime.now(timezone.utc).isoformat(),
        "total_urls": len(results), "ok": ok_count, "fixed": fixed,
        "unfixable": unfixable, "results": results,
    }
    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)
    with open(TMP_FILE, "w") as f:
        json.dump(tweets, f, indent=2, ensure_ascii=False)
    TMP_FILE.rename(TWEETS_FILE)

    print(f"\n[URL-VERIFY] Done. {ok_count} OK | {fixed} fixed | {unfixable} generic fallback")
    if unfixable > 0:
        print(f"[URL-VERIFY] WARNING: {unfixable} URLs could not be verified",
              file=sys.stderr)
    sys.exit(0)

if __name__ == "__main__":
    main()
