#!/usr/bin/env python3
"""Keep interests.md current with what Jack has recently favorited or bookmarked in Reeder.

Reads Reeder shared-feed links (Favorites, Bookmarks) from the TASTE_FEEDS environment variable
(space or newline separated; the links are private and never stored in this repo), then rewrites
the "Recently favorited" section of interests.md with the newest titles and their sources.
"""
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent
START, END = "<!-- recent-favorites:start -->", "<!-- recent-favorites:end -->"
APPLE_EPOCH = 978307200
UA = "Mozilla/5.0 (TopPicks taste tracker)"
DAYS, MAX_ITEMS = 90, 30
SKIP_HOSTS = ("youtube.com", "youtu.be", "x.com", "twitter.com")


def main():
    urls = [u for u in os.environ.get("TASTE_FEEDS", "").split() if u]
    if not urls:
        print("TASTE_FEEDS is not set; leaving interests.md unchanged.", file=sys.stderr)
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS)
    items, seen = [], set()
    for url in urls:
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            print(f"  ! could not read a taste feed: {type(e).__name__}", file=sys.stderr)
            continue
        tag = data.get("title") or "Favorites"
        for e in data.get("items", []):
            link = e.get("url") or ""
            host = urlparse(link).netloc.lower().removeprefix("www.")
            if not link or host.startswith(SKIP_HOSTS):
                continue
            meta = e.get("_reeder") or {}
            saved = datetime.fromtimestamp(meta["date"] + APPLE_EPOCH, timezone.utc) if meta.get("date") else None
            if not saved or saved < cutoff:
                continue
            text = e.get("content_text") or re.sub(r"<[^>]+>", " ", e.get("content_html") or "")
            title = (e.get("title") or text.strip().split(". ")[0][:90] or host).strip()
            key = link.split("#")[0].rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            items.append((saved, html.unescape(title), host, tag))
    items.sort(reverse=True)
    items = items[:MAX_ITEMS]
    lines = [START, "## Recently favorited (updated automatically)",
             f"What I've saved to Favorites or Bookmarks in Reeder over the last {DAYS} days, newest first. "
             "Treat these as the freshest signal of my tastes; weigh similar topics and writers higher.", ""]
    lines += [f"- {t} ({h}, {tag.lower()})" for _, t, h, tag in items] or ["- (nothing saved recently)"]
    lines.append(END)
    block = "\n".join(lines)
    path = ROOT / "interests.md"
    text = path.read_text(encoding="utf-8")
    if START in text and END in text:
        text = text[:text.index(START)] + block + text[text.index(END) + len(END):]
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    path.write_text(text, encoding="utf-8")
    print(f"Updated interests.md with {len(items)} recent favorites and bookmarks.", file=sys.stderr)


if __name__ == "__main__":
    main()
