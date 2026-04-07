# Pre-Launch Checklist

Run through every item before entering daily automated production.

## Credentials

```
[ ] 1. POLYMARKET_REFERRAL_ID is a real ID (not __FILL_IN__)
    grep "__FILL_IN__" config/secrets.env
    should return nothing

[ ] 2. Twitter API credentials are valid
    python3 -c "import tweepy; c=tweepy.Client(bearer_token='...'); print(c.get_me())"

[ ] 3. LLM API key works (enables LLM emoji, interest ranking, lead title)
    make a test API call and confirm response

[ ] 4. All 8 subagent scripts compile
    for f in scripts/*/run.py; do python3 -m py_compile "$f" && echo "OK: $f"; done
```

## Stage dry runs

```
[ ] 5. Scanner dry run:
    [ ] scan_output.json has >0 enriched markets
    [ ] No market has volume_24h < $2,000
    [ ] No market has price_now >= 0.97 or <= 0.03
    [ ] Every market has market_url field using eventSlug
    [ ] Every market has primary_outcome field

[ ] 6. Ranker dry run:
    [ ] ranked.json has diverse movers
    [ ] No two movers share the same event_slug
    [ ] Max 1 per person entity, max 1 crypto, max 2 sports
    [ ] mover_score, editorial_weight, volume_confidence fields present
    [ ] Markets with <$5K vol have volume_confidence 0.3

[ ] 7. News enricher dry run:
    [ ] enriched.json has at least 1 non-null news_headline
    [ ] No Polymarket self-links as news
    [ ] No obviously off-topic headlines

[ ] 8. Emoji picker dry run:
    [ ] Every mover has emoji field
    [ ] No 📌 on markets with obvious categories (check LLM + fallback)
    [ ] CS2 esports markets get 🎮

[ ] 9. Interest ranker dry run:
    [ ] Movers reordered by engagement potential
    [ ] Crypto forced to end
    [ ] interest_rank field present

[ ] 10. Composer dry run:
    [ ] Lead ≤ 280 effective chars
    [ ] Lead has generic title (not event-specific)
    [ ] Lead has exactly 3 non-crypto movers
    [ ] Lead ends with "Show more" on its own line
    [ ] Every reply has outcome label ("Yes: X%", "Cooper Flagg: X%", "Up: X%")
    [ ] Every reply has a context line ≥ 15 chars
    [ ] No placeholder strings anywhere
    [ ] All replies ≤ 280 effective chars

[ ] 11. URL verifier dry run:
    [ ] url_verification.json exists
    [ ] >75% URLs valid (ok + fixed)
    [ ] Manually click 5+ URLs — all load correct pages

[ ] 12. Full end-to-end dry run (do NOT publish to X):
    [ ] All 8 stages complete: IDLE → DONE
    [ ] Read the full thread aloud — does it sound human?
    [ ] Show to someone unfamiliar with prediction markets — can they follow every tweet?
    [ ] No 📌 emoji
    [ ] No duplicate volume lines
    [ ] No grammatically broken headlines
    [ ] Thread reads like a curated newsletter, not a data dump
```

## First live publish

```
[ ] 13. Publish to X (run Stage 8 only or full pipeline with real credentials)
    [ ] Click every URL in the live thread
    [ ] Check thread renders correctly (no broken threading)
    [ ] Monitor for 1 hour — no rate limit issues
    [ ] Save engagement metrics after 24h for baseline
```

## Production scheduling

```
[ ] 14.
    [ ] Publish time set to peak engagement window (9am ET = 13:00 UTC recommended)
    [ ] Orchestrator handles restart/resume via checkpoint
    [ ] Alert mechanism tested (deliberate failure → alert fires)
    [ ] Cookie refresh procedure documented (for future Substack re-enable)
```

## Common issues and fixes

| Problem | Likely cause | Fix |
|---------|-------------|-----|
| Scanner returns 0 markets | Gamma API down or network | Check API status |
| Ranker no movers | Scanner output empty or all low-vol | Check scan_output.json |
| News enricher 0 headlines | Search blocked or query bad | Check news.log |
| Emoji picker all 📌 | No LLM key + keyword miss | Add keywords to FALLBACK map |
| Composer placeholder leak | config __FILL_IN__ not replaced | Fill in all __FILL_IN__ in secrets.env |
| URL verifier 404s | Gamma slug changed | Check url_verification.json |
| Publisher blocked | Preflight check failed | Read blockers in publish_x.json |
| Publisher 503 timeout | Twitter API rate limit | Wait and retry; check Twitter status |
