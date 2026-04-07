#!/usr/bin/env node
/**
 * X/Twitter Reader via Nitter RSS — FREE, no API needed
 *
 * Usage:
 *   node read_nitter.js elonmusk
 *   node read_nitter.js elonmusk 10
 *
 * Args:
 *   username  - X username (without @)
 *   count     - number of tweets (default 10, max 30)
 *
 * Output: formatted tweet list to stdout, debug to stderr
 */
const https = require('https');

const USERNAME = process.argv[2] || die('Usage: node read_nitter.js <username> [count]');
const COUNT = Math.min(parseInt(process.argv[3]) || 10, 30);

function die(msg) { console.error(msg); process.exit(1); }

function fetch(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => resolve(data));
    }).on('error', reject);
  });
}

function parseRSS(xml) {
  const items = [];
  // Split by items
  const parts = xml.split('<item>');
  for (let i = 1; i < parts.length; i++) {
    const block = parts[i].split('</item>')[0];
    
    // Extract title
    const titleMatch = block.match(/<title><!\[CDATA\[([\s\S]*?)\]\]><\/title>/);
    const title = titleMatch ? titleMatch[1].trim() : '';

    // Extract description (CDATA)
    const descMatch = block.match(/<description><!\[CDATA\[([\s\S]*?)\]\]><\/description>/);
    let description = descMatch ? descMatch[1] : '';
    // Strip HTML tags
    description = description.replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').trim();

    // Extract pubDate
    const pubMatch = block.match(/<pubDate>([\s\S]*?)<\/pubDate>/);
    const pubDate = pubMatch ? pubMatch[1].trim() : '';

    // Extract link
    const linkMatch = block.match(/<link>([\s\S]*?)<\/link>/);
    const link = linkMatch ? linkMatch[1].trim() : '';

    if (title || description) {
      items.push({ title, description, pubDate, link });
    }
  }
  return items;
}

function formatRelativeTime(gmtString) {
  try {
    const date = new Date(gmtString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);
    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return diffMins + 'm ago';
    if (diffHours < 24) return diffHours + 'h ago';
    if (diffDays < 7) return diffDays + 'd ago';
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch { return gmtString; }
}

function stripRetweet(text) {
  return text.replace(/^RT @\w+:\s*/, '');
}

async function main() {
  const instances = [
    'nitter.net',
    'nitter.privacydev.net',
    'nitter.poast.org',
  ];

  let xml = null;
  for (const inst of instances) {
    const rssUrl = `https://${inst}/${USERNAME}/rss`;
    console.error(`Fetching: ${rssUrl}`);
    try {
      xml = await fetch(rssUrl);
      if (xml && xml.includes('<item>')) {
        console.error(`OK via ${inst}`);
        break;
      }
    } catch (e) {
      console.error(`Failed (${inst}): ${e.message}`);
    }
    xml = null;
  }

  if (!xml) die('All Nitter instances failed. Try again later.');

  const items = parseRSS(xml);
  if (items.length === 0) die('No tweets found (account may not exist or is private)');

  let count = 0;
  for (const item of items) {
    if (count >= COUNT) break;
    // Prefer description (full tweet), fall back to title
    let text = item.description || item.title;
    text = stripRetweet(text).trim();
    if (!text) continue;

    const time = formatRelativeTime(item.pubDate);
    const link = item.link.replace('#m', '').replace(/\#m$/, '');

    count++;
    console.log(`\n[${count}] ${text}`);
    console.log(`    🕐 ${time} | ${link}`);
  }

  console.error(`\n(${items.length} tweets fetched)`);
}

main();
