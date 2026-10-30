#!/usr/bin/env python3
"""Kindle edition (text only): bundle the last day's article picks into an EPUB and email it to your Kindle.

Reads state/picks.json (written by curate.py), fetches each article's full text,
groups articles into sections, adds a dated cover, and sends the book to your
Send to Kindle address.

Needs these environment variables (GitHub secrets) to send:
  KINDLE_EMAIL    your Send to Kindle address, like name_abc@kindle.com
  SMTP_USER       the sending address (must be on Amazon's approved list)
  SMTP_PASSWORD   for Gmail, an app password
  SMTP_HOST       optional, default smtp.gmail.com
"""
import argparse
import html
import io
import json
import os
import re
import smtplib
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
import trafilatura
import yaml
from ebooklib import epub
from PIL import Image

import cover
from curate import load_feeds

ROOT = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com")

CSS = """
body { font-family: serif; line-height: 1.45; }
h1 { font-size: 1.5em; margin: 0 0 0.3em; }
h2.section { font-size: 1.1em; text-transform: uppercase; letter-spacing: 0.08em;
             border-bottom: 1px solid #000; margin-top: 1.4em; }
p.meta { font-size: 0.85em; color: #444; margin: 0 0 0.2em; }
p.why { font-size: 0.9em; font-style: italic; margin: 0 0 1.2em; }
img { max-width: 100%; height: auto; }
div.code { font-family: monospace; font-size: 0.8em; white-space: pre-wrap; margin: 0.8em 0; }
figure { margin: 1em 0; }
.front li { margin-bottom: 0.6em; }
.front .why { font-size: 0.85em; font-style: italic; }
"""


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def fetch_image(url, idx):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        r.raise_for_status()
        im = Image.open(io.BytesIO(r.content))
        if im.width < 200 or im.height < 120:  # skip icons and tracking pixels
            return None
        im = im.convert("L")
        im.thumbnail((1000, 1400))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=70)
        return epub.EpubItem(uid=f"img{idx}", file_name=f"images/img{idx}.jpg",
                             media_type="image/jpeg", content=buf.getvalue())
    except Exception:  # noqa: BLE001  a broken image should never sink the edition
        return None


def full_text(pick, want_images, max_images):
    """Return (body_html, [image items]). Falls back to the summary when extraction fails."""
    url = pick.get("link") or ""
    body = pick.get("content_html")  # full text saved by curate.py, images included
    if len(re.sub(r"<[^>]+>", "", body or "")) < 400 and "<img" not in (body or ""):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
            r.raise_for_status()
            body = trafilatura.extract(r.text, url=url, output_format="html", include_images=want_images,
                                       include_links=False, include_tables=True, favor_recall=True)
        except Exception as e:  # noqa: BLE001
            log(f"  ! {url}: {e}")
            body = None

    text_len = len(re.sub(r"<[^>]+>", "", body or ""))
    if not body or (text_len < 400 and "<img" not in body):
        return (f"<p>{html.escape(pick.get('summary') or '')}</p>"
                f"<p><i>Full text wasn't available. Read it online: {html.escape(url)}</i></p>"), []

    body = re.sub(r"(?is)^.*?<body[^>]*>|</body>.*$", "", body)
    body = re.sub(r"(?is)<(/?)(main|doc|article)[^>]*>", "", body)
    body = re.sub(r"(?is)<a\b[^>]*>(.*?)</a>", r"\1", body)
    # no audio or video on the Kindle: drop players and embeds
    body = re.sub(r"(?is)<(video|audio|iframe|object|embed)\b.*?(</\1>|/>)", "", body)
    # code and table-like blocks: trafilatura emits <code><pre>; make them valid block divs
    body = re.sub(r"(?is)<code>\s*<pre[^>]*>", '<div class="code">', body)
    body = re.sub(r"(?is)</pre>\s*</code>", "</div>", body)
    body = re.sub(r"(?is)<pre[^>]*>", '<div class="code">', body).replace("</pre>", "</div>")
    images = []
    if want_images:
        def swap(m):
            if len(images) >= max_images:
                return ""
            src = urljoin(url, html.unescape(m.group(1)))
            item = fetch_image(src, f"{pick['id']}_{len(images)}")
            if not item:
                return ""
            images.append(item)
            return f'<img src="{item.file_name}" alt=""/>'
        body = re.sub(r'(?is)<img[^>]*?src="([^"]+)"[^>]*/?>', swap, body)
    else:
        body = re.sub(r"(?is)<img[^>]*>", "", body)
    return body, images


def build(cfg, picks, out_path):
    kc = cfg["kindle"]
    tz = ZoneInfo(kc.get("timezone", "America/Los_Angeles"))
    today = datetime.now(tz)
    date_label = f"{today:%A, %B} {today.day}, {today.year}"
    title = f"{kc.get('title', 'Top Picks')}, {today:%a %b} {today.day}"

    folder_map = {f: s for s, folders in kc["sections"].items() for f in folders}
    order = list(kc["sections"]) + [kc.get("other_section", "More")]
    for p in picks:
        p["section"] = folder_map.get(p.get("folder"), order[-1])
    picks.sort(key=lambda p: (order.index(p["section"]), -p.get("score", 0)))

    log(f"Fetching full text for {len(picks)} articles")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda p: full_text(p, kc.get("images", True), kc.get("max_images", 4)), picks))

    book = epub.EpubBook()
    book.set_identifier(f"top-picks-{today:%Y%m%d}")
    book.set_title(title)
    book.set_language("en")
    book.add_author("Top Picks")
    top = sorted(picks, key=lambda p: -p.get("score", 0))
    start = datetime.fromisoformat(str(kc.get("start_date", today.date()))).date()
    issue = max(1, (today.date() - start).days + 1)
    volume = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"][min(9, max(0, (issue - 1) // 365))]
    pod = cfg.get("podcasts", {})
    feed_count = sum(1 for f in load_feeds(ROOT / cfg.get("opml", "feeds.opml"))
                     if f["title"] not in set(cfg.get("exclude") or [])
                     and (pod.get("enabled", True) or f["folder"] != pod.get("folder")))
    book.set_cover("cover.jpg", cover.make_cover(
        kc.get("title", "Top Picks"), kc.get("tagline", ""), date_label,
        f"Vol. {volume}, No. {issue}", kc.get("place", ""), top, feed_count,
        sasquatch=kc.get("sasquatch", False)))
    style = epub.EpubItem(uid="style", file_name="style.css", media_type="text/css", content=CSS)
    book.add_item(style)

    # Front page: every headline by section, with Claude's one-line reason
    front_html = [f"<h1>{html.escape(kc.get('title', 'Top Picks'))}</h1><p class='meta'>{date_label}</p>"]
    chapters, toc, spine = [], [], []
    for sec in order:
        items = [(p, r) for p, r in zip(picks, results) if p["section"] == sec]
        if not items:
            continue
        front_html.append(f"<h2 class='section'>{html.escape(sec)}</h2><ul class='front'>")
        sec_chapters = []
        for p, (body, images) in items:
            n = len(chapters) + 1
            fname = f"a{n:02d}.xhtml"
            front_html.append(f"<li><a href='{fname}'>{html.escape(p['title'])}</a> "
                              f"<span class='meta'>({html.escape(p['feed'])})</span><br/>"
                              f"<span class='why'>{html.escape(p.get('reason') or '')}</span></li>")
            ch = epub.EpubHtml(title=p["title"], file_name=fname, lang="en")
            ch.content = (f"<h1>{html.escape(p['title'])}</h1>"
                          f"<p class='meta'>{html.escape(p['feed'])} | {html.escape(sec)}</p>"
                          f"<p class='why'>Why: {html.escape(p.get('reason') or '')}</p>{body}")
            ch.add_item(style)
            for im in images:
                book.add_item(im)
            book.add_item(ch)
            chapters.append(ch)
            sec_chapters.append(ch)
        front_html.append("</ul>")
        toc.append((epub.Section(sec, href=sec_chapters[0].file_name), sec_chapters))

    front = epub.EpubHtml(title="Front Page", file_name="front.xhtml", lang="en")
    front.content = "".join(front_html)
    front.add_item(style)
    book.add_item(front)
    book.toc = [epub.Link("front.xhtml", "Front Page", "front")] + toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    cover_page = book.get_item_with_id("cover")
    if cover_page is not None:
        cover_page.is_linear = True  # keep the cover page in the reading order
    book.spine = ["cover", front] + chapters
    epub.write_epub(str(out_path), book)
    return title


def send(path, title):
    to, user, pw = os.environ.get("KINDLE_EMAIL"), os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
    if not (to and user and pw):
        log("Kindle email secrets not set; built the file but did not send it.")
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = title, user, to
    msg.set_content("Your Top Picks Kindle edition is attached.")
    safe = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-") + ".epub"
    msg.add_attachment(path.read_bytes(), maintype="application", subtype="epub+zip", filename=safe)
    with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST", "smtp.gmail.com"), 465) as s:
        s.login(user, pw)
        s.send_message(msg)
    log(f"Sent {safe} to {to}")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-send", action="store_true", help="build the EPUB only")
    ap.add_argument("--out", default="kindle-edition.epub")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    kc = cfg.get("kindle") or {}
    if not kc.get("enabled"):
        log("Kindle edition is turned off in config.yaml.")
        return
    picks = json.loads((ROOT / "state" / "picks.json").read_text(encoding="utf-8"))
    since = datetime.now(timezone.utc) - timedelta(hours=kc.get("window_hours", 24))
    picks = [p for p in picks if p.get("kind") == "article"
             and datetime.fromisoformat(p["picked"]) >= since
             and not p.get("enclosure")  # no podcast episodes or other audio/video files
             and not urlparse(p.get("link") or "").netloc.removeprefix("www.").startswith(VIDEO_HOSTS)]
    skip = re.compile("|".join(cfg.get("skip_title_patterns") or ["$^"]), re.I)
    picks = [p for p in picks if not skip.search(p.get("title") or "")]
    picks = sorted(picks, key=lambda p: -p.get("score", 0))[: kc.get("max_articles", 25)]
    if len(picks) < kc.get("min_articles", 3):
        log(f"Only {len(picks)} articles today; skipping the Kindle edition.")
        return

    out = ROOT / args.out
    title = build(cfg, picks, out)
    log(f"Built {out.name} ({out.stat().st_size // 1024} KB, {len(picks)} articles)")
    if not args.no_send:
        send(out, title)


if __name__ == "__main__":
    main()
