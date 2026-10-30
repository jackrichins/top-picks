#!/usr/bin/env python3
"""Top Picks: turn an OPML of feeds into two AI-curated feeds.

  docs/top-picks.xml    articles and videos, for Reeder
  docs/top-podcasts.xml podcast episodes with audio, for Overcast

Each run fetches every feed, skips items it has already seen, asks Claude to
score the new ones against interests.md, merges duplicate stories, and keeps
the best picks for `keep_days`.
"""
import argparse
import hashlib
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import feedparser
import requests
import yaml

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
DOCS = ROOT / "docs"
UA = "Mozilla/5.0 (TopPicks feed curator)"
NOW = datetime.now(timezone.utc)


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# ---------- inputs ----------

def load_feeds(opml_path):
    """Return unique feeds as dicts: title, url, folder."""
    feeds, seen = [], set()

    def walk(node, folder):
        for child in node.findall("outline"):
            url = child.get("xmlUrl")
            if url:
                if url not in seen:
                    seen.add(url)
                    feeds.append({"title": child.get("title") or child.get("text") or url,
                                  "url": url, "folder": folder})
            else:
                walk(child, child.get("title") or child.get("text") or folder)

    walk(ET.parse(opml_path).getroot().find("body"), "")
    return feeds


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


# ---------- fetching ----------

def clean_text(s, limit=500):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"\s+", " ", html.unescape(s)).strip()
    return s[:limit]


def parse_date(value):
    if not value:
        return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
    return datetime(*value[:6], tzinfo=timezone.utc)  # time.struct_time


def fetch_feed(feed):
    """Fetch one feed and return a list of normalized items."""
    try:
        r = requests.get(feed["url"], headers={"User-Agent": UA}, timeout=25)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001  one bad feed must not stop the run
        log(f"  ! {feed['title']}: {e}")
        return []

    items = []
    ctype = r.headers.get("content-type", "")
    if "json" in ctype or r.text.lstrip().startswith("{"):
        try:
            data = r.json()
        except ValueError:
            data = {}
        feed_image = data.get("icon") or data.get("favicon")
        for e in data.get("items", []):
            att = (e.get("attachments") or [{}])[0]
            items.append({
                "guid": e.get("id") or e.get("url"),
                "title": e.get("title") or clean_text(e.get("content_text") or e.get("content_html"), 90),
                "link": e.get("url") or e.get("external_url"),
                "summary": clean_text(e.get("summary") or e.get("content_text") or e.get("content_html")),
                "published": parse_date(e.get("date_published")),
                "enclosure": {"url": att["url"], "type": att.get("mime_type", "audio/mpeg"),
                              "length": att.get("size_in_bytes", 0)} if att.get("url") else None,
                "image": e.get("image") or feed_image,
            })
    else:
        parsed = feedparser.parse(r.content)
        feed_image = (parsed.feed.get("image") or {}).get("href")
        for e in parsed.entries:
            enc = next((l for l in e.get("links", []) if l.get("rel") == "enclosure"
                        and str(l.get("type", "")).startswith(("audio", "video"))), None)
            thumb = (e.get("media_thumbnail") or [{}])[0].get("url")
            items.append({
                "guid": e.get("id") or e.get("link"),
                "title": clean_text(e.get("title"), 200),
                "link": e.get("link"),
                "summary": clean_text(e.get("summary") or e.get("description")),
                "published": parse_date(e.get("published_parsed") or e.get("updated_parsed")),
                "enclosure": {"url": enc["href"], "type": enc.get("type", "audio/mpeg"),
                              "length": enc.get("length", 0)} if enc else None,
                "image": (e.get("image") or {}).get("href") or thumb or feed_image,
            })

    for it in items:
        it["feed"] = feed["title"]
        it["folder"] = feed["folder"]
        it["id"] = hashlib.sha1(f"{feed['url']}|{it['guid'] or it['link'] or it['title']}"
                                .encode()).hexdigest()[:16]
    return [it for it in items if it["link"] or it["enclosure"]]


# ---------- scoring ----------

PROMPT = """You curate a personal news feed. Here is the reader's interest profile:

<interests>
{interests}
</interests>

Score each item below from 1 to 10 for how much this reader would want to see it.
10 = must read, 7 = worth their time, 4 = mildly interesting, 1 = noise.
Judge by the profile, not by general popularity. Be strict: most items should score below 7.

For each item also give:
- "reason": one short sentence saying why it matters to this reader (no em dashes).
- "story": a short lowercase slug naming the underlying story, so the same news
  from different sources gets the same slug (for example "apple-m5-macbook-pro-launch").
  Use a unique slug for opinion pieces, videos, and anything that is not shared news.

Return only a JSON array, one object per item: {{"i": <index>, "score": <int>, "reason": "...", "story": "..."}}

Items:
{items}"""


def score_batch(client, model, interests, batch):
    lines = [json.dumps({"i": i, "source": it["feed"], "folder": it["folder"],
                         "kind": "podcast" if it["enclosure"] else "article/video",
                         "title": it["title"], "summary": it["summary"][:400]},
                        ensure_ascii=False)
             for i, it in enumerate(batch)]
    msg = client.messages.create(
        model=model, max_tokens=4000,
        messages=[{"role": "user", "content": PROMPT.format(interests=interests, items="\n".join(lines))}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text")
    match = re.search(r"\[.*\]", text, re.S)
    results = json.loads(match.group(0)) if match else []
    for r in results:
        i = r.get("i")
        if isinstance(i, int) and 0 <= i < len(batch):
            batch[i]["score"] = int(r.get("score", 0))
            batch[i]["reason"] = str(r.get("reason", "")).replace("—", ", ")
            batch[i]["story"] = str(r.get("story") or batch[i]["id"])


def score_items(items, cfg, interests, fake=False):
    if not items:
        return
    if fake:  # offline testing: deterministic pseudo-scores
        for it in items:
            it["score"] = int(it["id"], 16) % 10 + 1
            it["reason"] = "Test score."
            it["story"] = it["id"]
        return
    import anthropic
    client = anthropic.Anthropic()
    size = cfg.get("batch_size", 30)
    batches = [items[i:i + size] for i in range(0, len(items), size)]
    log(f"Scoring {len(items)} items in {len(batches)} batches with {cfg['model']}")

    def run(batch):
        for attempt in range(2):
            try:
                score_batch(client, cfg["model"], interests, batch)
                return
            except Exception as e:  # noqa: BLE001
                log(f"  ! scoring batch failed (attempt {attempt + 1}): {e}")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(run, batches))


# ---------- selection ----------

def select(items, min_score, limit):
    """Keep the best item per story, then the top `limit` at or above min_score."""
    by_story = {}
    for it in items:
        if it.get("score", 0) < min_score:
            continue
        key = it.get("story") or it["id"]
        by_story.setdefault(key, []).append(it)
    picks = []
    for group in by_story.values():
        group.sort(key=lambda x: x["score"], reverse=True)
        best = dict(group[0])
        others = sorted({g["feed"] for g in group[1:]} - {best["feed"]})
        if others:
            best["also"] = others
        picks.append(best)
    picks.sort(key=lambda x: x["score"], reverse=True)
    return picks[:limit]


# ---------- output ----------

def esc(s):
    return html.escape(str(s or ""), quote=True)


def write_rss(path, items, title, description, site_url, podcast=False, image=None):
    ns = ' xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"' if podcast else ""
    out = [f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"{ns}><channel>',
           f"<title>{esc(title)}</title><link>{esc(site_url)}</link>",
           f"<description>{esc(description)}</description>",
           f"<lastBuildDate>{format_datetime(NOW)}</lastBuildDate>"]
    if podcast:
        out.append(f"<itunes:author>Top Picks</itunes:author><itunes:explicit>false</itunes:explicit>")
        if image:
            out.append(f'<itunes:image href="{esc(image)}"/><image><url>{esc(image)}</url>'
                       f"<title>{esc(title)}</title><link>{esc(site_url)}</link></image>")
    for it in sorted(items, key=lambda x: x["picked"], reverse=True):
        body = f"<p><b>Why:</b> {esc(it.get('reason'))} (score {it.get('score')})</p>"
        body += f"<p>From <b>{esc(it['feed'])}</b>"
        if it.get("also"):
            body += f". Also covered by {esc(', '.join(it['also']))}"
        body += f".</p><p>{esc(it.get('summary'))}</p>"
        item_title = f"{it['feed']}: {it['title']}" if podcast else it["title"]
        out.append("<item>")
        out.append(f"<title>{esc(item_title)}</title>")
        if it.get("link"):
            out.append(f"<link>{esc(it['link'])}</link>")
        out.append(f'<guid isPermaLink="false">{esc(it["id"])}</guid>')
        # pubDate = when it was picked, so new picks land at the top of Reeder's timeline
        out.append(f"<pubDate>{format_datetime(datetime.fromisoformat(it['picked']))}</pubDate>")
        out.append(f"<author>{esc(it['feed'])}</author>")
        out.append(f"<description>{esc(body)}</description>")
        if podcast and it.get("enclosure"):
            e = it["enclosure"]
            out.append(f'<enclosure url="{esc(e["url"])}" type="{esc(e["type"])}" length="{esc(e.get("length") or 0)}"/>')
            if it.get("image"):
                out.append(f'<itunes:image href="{esc(it["image"])}"/>')
        out.append("</item>")
    out.append("</channel></rss>\n")
    path.write_text("\n".join(out), encoding="utf-8")


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print picks, change nothing")
    ap.add_argument("--fake-scores", action="store_true", help="skip Claude (for testing)")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    interests = (ROOT / "interests.md").read_text()
    seen = load_json(STATE / "seen.json", {})
    picks = load_json(STATE / "picks.json", [])

    exclude = set(cfg.get("exclude") or [])
    always = set(cfg.get("always_include") or [])
    always_folders = set(cfg.get("always_include_folders") or [])
    pod_folder = cfg["podcasts"]["folder"]
    pods_on = cfg["podcasts"].get("enabled", True)
    feeds = [f for f in load_feeds(ROOT / cfg.get("opml", "feeds.opml"))
             if f["title"] not in exclude and (pods_on or f["folder"] != pod_folder)]
    log(f"Fetching {len(feeds)} feeds")

    with ThreadPoolExecutor(max_workers=16) as pool:
        fetched = [it for batch in pool.map(fetch_feed, feeds) for it in batch]

    first_run = not seen
    cutoff = NOW - timedelta(hours=cfg.get("lookback_hours", 48))
    new = [it for it in fetched if it["id"] not in seen
           and (it["published"] is None or it["published"] >= cutoff)]
    if first_run:  # don't flood the feed on day one: only the last day or so
        new = [it for it in new if it["published"] and it["published"] >= NOW - timedelta(hours=24)]
    log(f"{len(fetched)} items fetched, {len(new)} new")

    skip = re.compile("|".join(cfg.get("skip_title_patterns") or ["$^"]), re.I)
    skipped = [it for it in new if skip.search(it["title"] or "")]
    for it in skipped:
        seen[it["id"]] = NOW.isoformat()  # never look at these again
    new = [it for it in new if not skip.search(it["title"] or "")]
    if skipped:
        log(f"Skipped {len(skipped)} sponsor posts")

    to_score = []
    for it in new:
        it["is_podcast"] = it["folder"] == pod_folder and bool(it["enclosure"])
        if it["feed"] in always or it["folder"] in always_folders:
            it.update(score=10, reason="On your always-include list.", story=it["id"])
        else:
            to_score.append(it)
    score_items(to_score, cfg, interests, fake=args.fake_scores)

    articles = select([i for i in new if not i["is_podcast"]],
                      cfg["articles"]["min_score"], cfg["articles"]["max_per_run"])
    podcasts = select([i for i in new if i["is_podcast"]],
                      cfg["podcasts"]["min_score"], cfg["podcasts"]["max_per_run"])

    for label, group in (("ARTICLES", articles), ("PODCASTS", podcasts)):
        log(f"\n{label} ({len(group)})")
        for p in group:
            log(f"  [{p['score']}] {p['feed']}: {p['title']}  ({p.get('reason', '')})")
    if args.dry_run:
        return

    stamp = NOW.isoformat()
    keep = NOW - timedelta(days=cfg.get("keep_days", 7))
    for p in articles + podcasts:
        p["picked"] = stamp
        p["kind"] = "podcast" if p["is_podcast"] else "article"
        p["published"] = p["published"].isoformat() if p["published"] else None
    known = {p["id"] for p in picks}
    picks = [p for p in picks if datetime.fromisoformat(p["picked"]) >= keep]
    picks += [p for p in articles + podcasts if p["id"] not in known]

    # first run: mark the whole backlog as seen so later runs only score fresh items
    if first_run:
        for it in fetched:
            seen.setdefault(it["id"], stamp)
    # remember everything that got a score; items from a failed batch retry next run
    for it in new:
        if it.get("score") is not None:
            seen[it["id"]] = stamp
    seen = {k: v for k, v in seen.items() if datetime.fromisoformat(v) >= NOW - timedelta(days=30)}

    STATE.mkdir(exist_ok=True)
    DOCS.mkdir(exist_ok=True)
    (STATE / "seen.json").write_text(json.dumps(seen, indent=0))
    (STATE / "picks.json").write_text(json.dumps(picks, indent=1, ensure_ascii=False))

    site = cfg.get("site_url", "")
    write_rss(DOCS / "top-picks.xml", [p for p in picks if p["kind"] == "article"],
              "Top Picks", "The best of my feeds, picked by Claude.", site)
    if pods_on:
        write_rss(DOCS / "top-podcasts.xml", [p for p in picks if p["kind"] == "podcast"],
                  "Top Podcast Picks", "The episodes worth your time, picked by Claude.", site,
                  podcast=True, image=cfg["podcasts"].get("artwork"))
    log(f"\nWrote {len(picks)} picks to docs/")


if __name__ == "__main__":
    main()
