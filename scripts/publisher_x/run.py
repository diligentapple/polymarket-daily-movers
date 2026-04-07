"""
X/Twitter Publisher subagent v2.
Posts a thread. Validates content before posting. No Substack dependency.

INPUT: {DATA_DIR}/briefs/{date}/tweets.json
OUTPUT: {DATA_DIR}/briefs/{date}/publish_x.json
EXIT: 0 on success, 1 on failure
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path(os.environ.get("DATA_DIR", "/home/diligentapple/.openclaw/workspace/polymarket"))
DATE = os.environ.get("RUN_DATE")
TWEETS_FILE = DATA_DIR / "briefs" / DATE / "tweets.json"
RECEIPT_FILE = DATA_DIR / "briefs" / DATE / "publish_x.json"

def preflight_check(tweets: dict) -> list[str]:
    """Final safety check before posting. Returns list of blockers."""
    blockers = []
    lead = tweets.get("lead", "")
    replies = tweets.get("replies", [])

    if not lead.strip():
        blockers.append("Lead tweet is empty")

    all_texts = [lead] + replies
    for i, text in enumerate(all_texts):
        label = "LEAD" if i == 0 else f"REPLY_{i}"
        if "{{" in text or "}}" in text:
            blockers.append(f"{label}: unresolved {{ }} placeholder")
        if "__FILL_IN__" in text:
            blockers.append(f"{label}: __FILL_IN__ present")
        if "SUBSTACK_URL" in text:
            blockers.append(f"{label}: SUBSTACK_URL present")
        if len(text) > 280:
            blockers.append(f"{label}: {len(text)} chars exceeds 280 limit")

        # Check for valid Polymarket URLs in replies
        import re as _re_url
        if i > 0:
            urls_in_text = _re_url.findall(r"https?://polymarket\.com/event/\S+", text)
            if not urls_in_text:
                blockers.append(f"{label}: missing Polymarket URL")
        # v7: check for obviously broken slugs
        for url_match in _re_url.finditer(r"polymarket\.com/event/([^\s?&]+)", text):
            slug_path = url_match.group(1)
            # "will-" slug as top-level event path suggests a multi-outcome market
            # whose market_slug was used as the event path (common with Gamma API)
            # NOTE: URL verifier has already validated all URLs — this check is redundant
            # and produces false positives on legitimate event slugs like "will-ukraine-re-enter-rodynske"
            # Disabled in favour of URL verifier's more accurate HEAD-request validation.
            pass
            # Very short slug paths that are unlikely to be valid event slugs
            if len(slug_path) < 5:
                blockers.append(f"{label}: URL slug '{slug_path}' too short to be valid")

    return blockers

def main():
    if not TWEETS_FILE.exists():
        print(f"[PUB-X] ERROR: {TWEETS_FILE} not found", file=sys.stderr)
        sys.exit(1)

    with open(TWEETS_FILE) as f:
        tweets = json.load(f)

    # Preflight
    blockers = preflight_check(tweets)
    if blockers:
        print("[PUB-X] BLOCKED - preflight check failed:", file=sys.stderr)
        for b in blockers:
            print(f"  X {b}", file=sys.stderr)
        receipt = {
            "status": "blocked",
            "reason": "preflight_check_failed",
            "blockers": blockers,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(RECEIPT_FILE, "w") as f:
            json.dump(receipt, f, indent=2)
        sys.exit(1)

    lead_text = tweets["lead"]
    replies = tweets.get("replies", [])

    try:
        import tweepy

        client = tweepy.Client(
            bearer_token=os.environ.get("TWITTER_BEARER_TOKEN"),
            consumer_key=os.environ.get("TWITTER_CONSUMER_KEY"),
            consumer_secret=os.environ.get("TWITTER_CONSUMER_SECRET"),
            access_token=os.environ.get("TWITTER_ACCESS_TOKEN"),
            access_token_secret=os.environ.get("TWITTER_ACCESS_TOKEN_SECRET"),
        )

        # Post lead tweet
        lead_resp = client.create_tweet(text=lead_text)
        lead_id = lead_resp.data["id"]
        tweet_ids = [lead_id]
        print(f"[PUB-X] Lead posted: https://x.com/i/status/{lead_id}")

        # Post reply thread with small delay between tweets
        prev_id = lead_id
        for i, reply_text in enumerate(replies):
            time.sleep(1.5)
            resp = client.create_tweet(
                text=reply_text,
                in_reply_to_tweet_id=prev_id,
            )
            tid = resp.data["id"]
            tweet_ids.append(tid)
            prev_id = tid
            print(f"[PUB-X] Reply {i+1} posted: https://x.com/i/status/{tid}")

        receipt = {
            "status": "published",
            "tweet_count": len(tweet_ids),
            "tweet_ids": tweet_ids,
            "lead_url": f"https://x.com/i/status/{lead_id}",
            "published_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        receipt = {
            "status": "failed",
            "error": str(e),
            "error_type": type(e).__name__,
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        print(f"[PUB-X] FAILED: {e}", file=sys.stderr)

    with open(RECEIPT_FILE, "w") as f:
        json.dump(receipt, f, indent=2)

    sys.exit(0 if receipt["status"] == "published" else 1)

if __name__ == "__main__":
    main()
