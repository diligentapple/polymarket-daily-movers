#!/usr/bin/env node
/**
 * X/Twitter Posting via Official API v2 — OAuth 1.0a
 * Credentials: TWITTER_CONSUMER_KEY, TWITTER_CONSUMER_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET
 */
const crypto = require('crypto');
const https = require('https');

const CK  = process.env.TWITTER_CONSUMER_KEY    || '';
const CS  = process.env.TWITTER_CONSUMER_SECRET || '';
const AT  = process.env.TWITTER_ACCESS_TOKEN    || '';
const ATS = process.env.TWITTER_ACCESS_TOKEN_SECRET || '';

function die(msg) { console.error(JSON.stringify({ ok: false, error: msg })); process.exit(1); }
if (!CK || !CS || !AT || !ATS) die('Missing Twitter OAuth env vars');

function penc(s) { return encodeURIComponent(s).replace(/[!'()*]/g, c => '%' + c.charCodeAt(0).toString(16).toUpperCase()); }

function oauthSign(method, url, params) {
  const paramStr = Object.keys(params).sort().map(k => penc(k) + '=' + penc(params[k])).join('&');
  const baseStr = method + '&' + penc(url) + '&' + penc(paramStr);
  const sigKey = penc(CS) + '&' + penc(ATS);
  return crypto.createHmac('sha1', sigKey).update(baseStr).digest('base64');
}

function authHeader(method, url) {
  const ts = Math.floor(Date.now() / 1000).toString();
  const nonce = crypto.randomBytes(32).toString('hex');
  const params = {
    oauth_consumer_key: CK,
    oauth_nonce: nonce,
    oauth_signature_method: 'HMAC-SHA1',
    oauth_timestamp: ts,
    oauth_token: AT,
    oauth_version: '1.0'
  };
  const allParams = { ...params };
  const paramStr = Object.keys(allParams).sort().map(k => penc(k) + '=' + penc(allParams[k])).join('&');
  const baseStr = method + '&' + penc(url) + '&' + penc(paramStr);
  const sigKey = penc(CS) + '&' + penc(ATS);
  params.oauth_signature = crypto.createHmac('sha1', sigKey).update(baseStr).digest('base64');
  return 'OAuth ' + Object.keys(params).sort().map(k => penc(k) + '="' + penc(params[k]) + '"').join(', ');
}

async function postTweet(text, opts) {
  opts = opts || {};
  const body = { text };
  if (opts.replyTo) body.reply = { in_reply_to_tweet_id: opts.replyTo };
  if (opts.quoteTweetId) body.quote_tweet_id = opts.quoteTweetId;
  const bodyStr = JSON.stringify(body);
  const urlStr = 'https://api.twitter.com/2/tweets';
  const h = authHeader('POST', urlStr);
  return new Promise((resolve) => {
    const req = https.request({
      hostname: 'api.twitter.com', port: 443, path: '/2/tweets',
      method: 'POST',
      headers: { Authorization: h, 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(bodyStr) }
    }, res => {
      let d = ''; res.on('data', c => d += c); res.on('end', () => {
        try {
          const j = JSON.parse(d);
          if (res.statusCode === 201) resolve({ ok: true, id: j.data.id, url: 'https://x.com/i/status/' + j.data.id });
          else resolve({ ok: false, error: res.statusCode + ': ' + JSON.stringify(j) });
        } catch { resolve({ ok: false, error: d }); }
      });
    });
    req.on('error', e => resolve({ ok: false, error: e.message }));
    req.write(bodyStr); req.end();
  });
}

async function main() {
  const args = process.argv.slice(2);
  let replyTo = null, quoteTweetId = null, thread = false;
  const texts = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--reply-to' && args[i+1]) { replyTo = args[++i]; continue; }
    if (args[i] === '--quote' && args[i+1]) { quoteTweetId = args[++i]; continue; }
    if (args[i] === '--thread') { thread = true; continue; }
    texts.push(args[i]);
  }
  if (!texts.length) die('Usage: node post_tweet.js "text" [--reply-to id] [--quote id] [--thread] "tweet2" "tweet3"...');

  if (thread && texts.length > 1) {
    const results = [];
    let prevId = replyTo;
    for (const t of texts) {
      const r = await postTweet(t, { replyTo: prevId });
      results.push(r);
      if (!r.ok) break;
      prevId = r.id;
    }
    console.log(JSON.stringify({ ok: true, thread: results }));
  } else {
    const r = await postTweet(texts.join(' '), { replyTo, quoteTweetId });
    console.log(JSON.stringify(r));
  }
}

main().catch(e => die(e.message));
