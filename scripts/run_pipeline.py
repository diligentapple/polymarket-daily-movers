#!/usr/bin/env python3
"""
Polymarket Daily Mover Brief — One-Shot Pipeline Runner
Invoked by the skill's SKILL.md instructions. Runs all 8 stages sequentially
for a given date without daemonizing or waiting for a publish hour.

Usage:
    python3 run_pipeline.py 2026-04-06

Or set RUN_DATE env var:
    RUN_DATE=2026-04-06 python3 run_pipeline.py

Environment variables (also in config/secrets.env):
    DATA_DIR               — working directory (default: derived from script location)
    RUN_DATE              — date string YYYY-MM-DD
    POLYMARKET_REFERRAL_ID
    TWITTER_API_KEY / TWITTER_API_SECRET / TWITTER_ACCESS_TOKEN / TWITTER_ACCESS_SECRET
    TWITTER_BEARER_TOKEN
    ANTHROPIC_API_KEY     — optional; enables LLM emoji/title/ranking
    OPENAI_API_KEY        — optional fallback for ANTHROPIC_API_KEY
    COMPOSE_MODE          — "template" (default) or "llm"
    MIN_VOLUME_24H        — default 2000
    TOP_N_MOVERS          — default 8
    MAX_SPORTS / MAX_CRYPTO / MAX_PER_CATEGORY
    SKIP_TAGS             — comma-separated tags to skip

Output files written to: {DATA_DIR}/briefs/{RUN_DATE}/
"""

import os, sys, json, time, shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
DATA_DIR   = Path(os.environ.get("DATA_DIR", str(SCRIPT_DIR.parent)))
BRIEFS_DIR = DATA_DIR / "briefs"
CONFIG_DIR = DATA_DIR / "config"
LOG_DIR    = DATA_DIR / "logs"
ALERT_FILE = DATA_DIR / "alerts" / "latest.json"

PUBLISH_HOUR_UTC = 13
MAX_RETRIES = 3


# Stages that need LLM API keys â others get keys stripped for security
LLM_STAGES = {"EMOJI_PICKING", "INTEREST_RANKING", "COMPOSING"}

# Non-critical stages â skip on failure instead of halting
NON_CRITICAL_STAGES = {"NEWS_ENRICHING", "EMOJI_PICKING", "INTEREST_RANKING", "URL_VERIFYING"}

STAGES = [
    ("SCANNING",      "scanner/run.py",         "scan_output.json",       1200),
    ("RANKING",       "ranker/run.py",           "ranked.json",            120),
    ("NEWS_ENRICHING","news_enricher/run.py",    "enriched.json",          300),
    ("EMOJI_PICKING", "emoji_picker/run.py",     "enriched.json",          60),
    ("INTEREST_RANKING","interest_ranker/run.py","enriched.json",           60),
    ("COMPOSING",     "composer/run.py",         "tweets.json",            300),
    ("URL_VERIFYING", "url_verifier/run.py",     "url_verification.json",  120),
    ("PUBLISHING_X",  "publisher_x/run.py",      "publish_x.json",         180),
]
STATES = {s[0]: i for i, s in enumerate(STAGES)}

def log(msg):
    # SECURITY: never log env vars containing secrets
    if any(s in str(msg).lower() for s in ['api_key', 'api_secret', 'token_secret', 'password']):
        msg = '[REDACTED â contains sensitive data]'
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    print(f"[{ts}] [PIPELINE] {msg}", flush=True)

def load_ck(date):
    f = BRIEFS_DIR / date / "checkpoint.json"
    if f.exists():
        return json.loads(f.read_text())
    return {
        "date": date, "state": "IDLE",
        "retries": {s[0]: 0 for s in STAGES},
        "started_at": None, "completed_at": None, "errors": [],
    }

def save_ck(ck):
    f = BRIEFS_DIR / ck["date"] / "checkpoint.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(ck, indent=2))

def alert(subject, body, state="alert"):
    ALERT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALERT_FILE.write_text(json.dumps({
        "subject": subject, "body": body,
        "state": state, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, indent=2))
    log(f"ALERT: {subject}")

def run_stage(date, stage_name, script_rel, expected_file, timeout_s):
    script_path = SCRIPT_DIR / script_rel
    secrets = {}
    sp = CONFIG_DIR / "secrets.env"
    if sp.exists():
        for line in sp.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                secrets[k.strip()] = v.strip()
    env = {**os.environ, **secrets,
           "RUN_DATE": date, "DATA_DIR": str(DATA_DIR), "BRIEFS_DIR": str(BRIEFS_DIR)}
    # Security: strip LLM keys from stages that don't need them
    if stage_name not in LLM_STAGES:
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("OPENAI_API_KEY", None)
    out_log = LOG_DIR / date / f"{stage_name.lower()}.out.log"
    err_log = LOG_DIR / date / f"{stage_name.lower()}.err.log"
    (LOG_DIR / date).mkdir(parents=True, exist_ok=True)
    start = time.time()
    try:
        import subprocess
        with open(out_log, "w") as out, open(err_log, "w") as err:
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                env=env, timeout=timeout_s, stdout=out, stderr=err,
            )
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        log(f"{stage_name} timed out after {timeout_s}s")
        return False, -1, "timeout"
    duration = time.time() - start
    err_snippet = err_log.read_text()[-800:] if err_log.exists() else ""
    out_exists = (BRIEFS_DIR / date / expected_file).exists()
    if exit_code == 0 and out_exists:
        log(f"{stage_name} OK in {duration:.1f}s → {expected_file}")
        return True, 0, ""
    else:
        log(f"{stage_name} FAILED (exit={exit_code}) in {duration:.1f}s")
        return False, exit_code, err_snippet[-300:]

def validate(date, stage_name):
    try:
        if stage_name == "SCANNING":
            f = BRIEFS_DIR / date / "scan_output.json"
            if not f.exists(): return False
            d = json.loads(f.read_text())
            markets = d.get("markets", [])
            if not isinstance(markets, list) or len(markets) < 1: return False
            for m in markets:
                p = m.get("price_now")
                if p is not None and (p >= 0.97 or p <= 0.03):
                    log(f"VALIDATION FAIL: resolved market passed scanner: {m.get('question','')[:60]}")
                    return False
            return True

        if stage_name == "RANKING":
            f = BRIEFS_DIR / date / "ranked.json"
            if not f.exists(): return False
            d = json.loads(f.read_text())
            movers = d.get("movers", [])
            if len(movers) < 1: return False
            return all(m.get("question") and m.get("price_now") is not None
                       and m.get("delta_pp") is not None and m.get("mover_score")
                       for m in movers)

        if stage_name == "NEWS_ENRICHING":
            f = BRIEFS_DIR / date / "enriched.json"
            if not f.exists(): return False
            d = json.loads(f.read_text())
            movers = d.get("movers", [])
            found = sum(1 for m in movers if m.get("news_headline"))
            log(f"NEWS_ENRICHING: {found}/{len(movers)} movers have headlines")
            return True

        if stage_name == "COMPOSING":
            f = BRIEFS_DIR / date / "tweets.json"
            if not f.exists(): return False
            d = json.loads(f.read_text())
            lead = d.get("lead", "")
            replies = d.get("replies", [])
            # v12.1: use X-aware char counting (URLs = 23 chars via t.co)
            # v14.2: BMP-aware — Unicode bold chars count as 2 on X
            import re as _re_v
            def _count_chars(t):
                url_pattern = _re_v.compile(r"https?://\S+")
                urls = url_pattern.findall(t)
                c = 0
                for ch in t:
                    if ord(ch) > 0xFFFF:
                        c += 2
                    else:
                        c += 1
                for u in urls:
                    u_len = sum(2 if ord(ch) > 0xFFFF else 1 for ch in u)
                    c -= u_len
                    c += 23
                return c

            if not lead or _count_chars(lead) > 280: return False
            if not replies: return False
            all_texts = [lead] + replies
            for text in all_texts:
                if "{{" in text or "}}" in text or "__FILL_IN__" in text or "SUBSTACK_URL" in text:
                    log(f"VALIDATION FAIL: placeholder leak: {text[:80]}")
                    return False
            return all(_count_chars(r) <= 280 for r in replies)
    except Exception as e:
        log(f"VALIDATION ERROR: {e}")
        return False
    return True

def run_pipeline(date):
    log(f"=== Starting pipeline for {date} ===")
    ck = load_ck(date)
    if ck["state"] == "DONE":
        log(f"Pipeline already DONE for {date}")
        return True
    if ck["started_at"] is None:
        ck["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    current_idx = STATES.get(ck.get("state", "IDLE"), 0)

    for stage_name, script_rel, expected_file, timeout_s in STAGES:
        stage_idx = STATES[stage_name]
        if stage_idx < current_idx:
            log(f"Skipping {stage_name} — already done")
            continue
        # v15.1: only skip via file existence if no earlier stage shares this output file.
        # NEWS_ENRICHING, EMOJI_PICKING, and INTEREST_RANKING all write enriched.json.
        out_exists = (BRIEFS_DIR / date / expected_file).exists()
        earlier_stages_share_file = any(
            STAGES[j][2] == expected_file
            for j in range(stage_idx)
        )
        if out_exists and not earlier_stages_share_file:
            log(f"{stage_name}: output exists, advancing")
            ck["state"] = STAGES[stage_idx+1][0] if stage_idx+1 < len(STAGES) else "DONE"
            save_ck(ck)
            continue
        log(f"--- Stage: {stage_name} (timeout={timeout_s}s) ---")
        ck["state"] = stage_name
        save_ck(ck)

        attempt = 0
        while ck["retries"][stage_name] < MAX_RETRIES:
            attempt += 1
            log(f"{stage_name} attempt {attempt}/{MAX_RETRIES}")
            ok, code, err = run_stage(date, stage_name, script_rel, expected_file, timeout_s)
            if ok and validate(date, stage_name):
                next_name = STAGES[stage_idx+1][0] if stage_idx+1 < len(STAGES) else "DONE"
                ck["state"] = next_name
                save_ck(ck)
                break
            if not ok:
                ck["retries"][stage_name] += 1
                ck["errors"].append({
                    "stage": stage_name, "attempt": attempt,
                    "exit_code": code, "error": str(err)[:500],
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                })
                save_ck(ck)
                if ck["retries"][stage_name] < MAX_RETRIES:
                    log(f"Retrying in 30s...")
                    time.sleep(30)

        if ck["retries"][stage_name] >= MAX_RETRIES:
            if stage_name in NON_CRITICAL_STAGES:
                log(f"{stage_name} failed after {MAX_RETRIES} retries — non-critical, skipping")
                # Special fallback for NEWS_ENRICHING: copy ranked.json as enriched.json
                if stage_name == "NEWS_ENRICHING":
                    ranked_f = BRIEFS_DIR / date / "ranked.json"
                    enriched_f = BRIEFS_DIR / date / "enriched.json"
                    if ranked_f.exists() and not enriched_f.exists():
                        shutil.copy2(ranked_f, enriched_f)
                        log(f"  Copied ranked.json → enriched.json as fallback")
                # Advance to next stage
                next_idx = stage_idx + 1
                if next_idx < len(STAGES):
                    ck["state"] = STAGES[next_idx][0]
                else:
                    ck["state"] = "DONE"
                save_ck(ck)
                continue
            ck["state"] = f"FAILED_{stage_name}"
            save_ck(ck)
            alert(f"Pipeline failed at {stage_name}",
                  f"Ran out of retries for {date}. Last error: {err[:300]}", state=ck["state"])
            return False

    ck["state"] = "DONE"
    ck["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_ck(ck)
    log(f"Pipeline complete for {date}")
    return True

def main():
    date = os.environ.get("RUN_DATE") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not date:
        print("Usage: python3 run_pipeline.py YYYY-MM-DD\n  or set RUN_DATE env var")
        sys.exit(1)
    success = run_pipeline(date)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
