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
STRIP_LINK_HOSTS = []  # set from config.yaml (kindle.strip_link_hosts)

CSS = """
body { font-family: serif; line-height: 1.45; }
h1 { font-size: 1.5em; margin: 0 0 0.3em; }
h2.section { font-family: sans-serif; font-size: 1.0em; text-transform: uppercase; letter-spacing: 0.08em;
             border-bottom: 1px solid #000; margin-top: 1.4em; }
p.meta { font-family: sans-serif; font-size: 0.8em; color: #444; margin: 0 0 0.2em; }
p.why { font-size: 0.9em; font-style: italic; margin: 0 0 1.2em; }
img { max-width: 100%; height: auto; }
div.code { font-family: monospace; font-size: 0.8em; white-space: pre-wrap; margin: 0.8em 0; }
figure { margin: 1em 0; }
.front li { margin-bottom: 0.6em; }
h3 { font-family: sans-serif; font-size: 1.0em; margin: 1.1em 0 0.2em; }
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
    # plain reading markup only: drop widgets (with their contents), unwrap any other unknown tag
    body = re.sub(r"(?is)<(svg|button|script|style|form|noscript|select|textarea|nav|aside|template)\b.*?</\1\s*>", "", body)
    body = re.sub(r"(?is)<(source|input|link|meta)\b[^>]*>", "", body)
    allowed = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "em", "strong", "b", "i",
               "a", "img", "figure", "figcaption", "table", "thead", "tbody", "tr", "td", "th", "br", "hr", "pre",
               "code", "div", "span", "sup", "sub", "small", "cite", "q"}
    body = re.sub(r"</?([a-zA-Z][a-zA-Z0-9:-]*)\b[^>]*>",
                  lambda m: m.group(0) if m.group(1).lower() in allowed else "", body)
    # keep only safe attributes (pages sometimes carry framework attributes like x-bind:class that break EPUB)
    def clean_tag(m):
        name, attrs = m.group(1), m.group(2) or ""
        keep = re.findall(r'\s(href|src|alt|colspan|rowspan)\s*=\s*("[^"]*"|\'[^\']*\')', attrs, re.I)
        closing = "/" if attrs.rstrip().endswith("/") else ""
        return "<" + name + "".join(f" {a.lower()}={v}" for a, v in keep) + closing + ">"
    body = re.sub(r"<([a-zA-Z][a-zA-Z0-9]*)(\s[^<>]*)?>", clean_tag, body)
    # keep links to regular web pages; unwrap links the Kindle browser can't load (video, social)
    def link(m):
        href = re.search(r'href="([^"]+)"', m.group(1))
        host = urlparse(html.unescape(href.group(1))).netloc.lower().removeprefix("www.") if href else ""
        blocked = not host or any(host == b or host.endswith("." + b) for b in STRIP_LINK_HOSTS)
        return m.group(2) if blocked else f'<a href="{href.group(1)}">{m.group(2)}</a>'
    body = re.sub(r"(?is)<a\b([^>]*)>(.*?)</a>", link, body)
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


APPLE_EPOCH = 978307200  # Reeder stores save dates as seconds since 2001-01-01


def later_items(kc, sent_ids):
    """New articles from Reeder's Later tag (a shared JSON feed), skipping video, audio, and social posts."""
    items = []
    # the feed link is private (anyone with it can read the list), so it normally comes from the
    # REEDER_LATER_FEED environment variable rather than this public repo
    sources = list(kc.get("later_feeds") or []) + [u for u in os.environ.get("REEDER_LATER_FEED", "").split() if u]
    for src in sources:
        try:
            if src.startswith("http"):
                r = requests.get(src, headers={"User-Agent": UA}, timeout=25)
                r.raise_for_status()
                data = r.json()
            else:
                data = json.loads(Path(src).read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001  the edition still goes out without them
            log(f"  ! Later feed {src}: {e}")
            continue
        tag = data.get("title") or "Later"
        for e in data.get("items", []):
            url = e.get("url") or e.get("external_url") or ""
            host = urlparse(url).netloc.lower().removeprefix("www.")
            meta = e.get("_reeder") or {}
            media_types = {m.get("type") for m in meta.get("media") or []}
            if (not url or any(host == b or host.endswith("." + b) for b in STRIP_LINK_HOSTS)
                    or any(str(a.get("mime_type", "")).startswith(("audio", "video")) for a in e.get("attachments") or [])
                    or media_types & {"video", "audio"}):
                continue
            iid = "later-" + re.sub(r"[^a-z0-9]+", "-", (e.get("id") or url).lower())[-60:]
            if iid in sent_ids:
                continue
            saved = datetime.fromtimestamp(meta["date"] + APPLE_EPOCH, timezone.utc) if meta.get("date") else None
            if not saved or saved < datetime.now(timezone.utc) - timedelta(days=kc.get("later_window_days", 7)):
                continue  # only articles saved within the last week
            text = e.get("content_text") or re.sub(r"<[^>]+>", " ", e.get("content_html") or "")
            title = e.get("title") or (text.strip().split(". ")[0][:90] if text.strip() else host)
            items.append({"id": iid, "kind": "article", "title": title, "link": url, "feed": host or "Later",
                          "folder": "__later__", "summary": text[:500], "score": 8,
                          "reason": f"You saved this to {tag} in Reeder.",
                          "content_html": e.get("content_html") or "", "saved": saved})
    seen_links, unique = set(), []
    for i in items:  # the same article saved to both Later and Links appears once
        key = i["link"].split("#")[0].rstrip("/")
        if key not in seen_links:
            seen_links.add(key)
            unique.append(i)
    items = unique
    items.sort(key=lambda i: i["saved"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items[: kc.get("later_max", 40)]


def techmeme_top(limit=15):
    """The day's top stories from Techmeme's Top News column: headline, lede, source, link."""
    r = requests.get("https://www.techmeme.com/", headers={"User-Agent": UA}, timeout=25)
    r.raise_for_status()
    page = r.text
    start = page.find('<DIV ID="topcol1">')
    end = page.find('<DIV ID="topcol2"', start)
    col = page[start:end if end > 0 else None]
    stories = []
    for clus in col.split('<DIV CLASS="clus">')[1:]:
        m = re.search(r'<A CLASS="ourh" HREF="([^"]+)">(.*?)</A></STRONG>(.*?)</DIV>', clus, re.S)
        if not m:
            continue
        cite = re.search(r"<CITE>(.*?)</CITE>", clus, re.S)
        source = re.sub(r"<[^>]+>", "", cite.group(1)).strip().rstrip(":") if cite else ""
        lede = html.unescape(re.sub(r"<[^>]+>", "", m.group(3))).replace("\u2014", "").strip(" \u00a0-")
        more = len(re.findall(r"<A HREF=", clus.split('CLASS="drhed"')[-1])) if 'CLASS="drhed"' in clus else 0
        stories.append({"rank": len(stories) + 1, "headline": html.unescape(re.sub(r"<[^>]+>", "", m.group(2))),
                        "lede": lede[:400], "source": html.unescape(source), "link": m.group(1),
                        "coverage": more})
        if len(stories) >= limit:
            break
    return stories


def briefing_chapter(path, style):
    """Build the Techmeme briefing article from Claude's summaries (JSON written during the run)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("items") or []
    if not items:
        return None
    parts = ["<h1>The Day in Tech</h1>",
             "<p class='meta'>Techmeme's top stories, summarized by Claude</p>"]
    for it in items:
        link = html.escape(it.get("link") or "")
        src = html.escape(it.get("source") or "")
        parts.append(f"<h3>{html.escape(it.get('topic') or '')}</h3>"
                     f"<p>{html.escape(it.get('summary') or '')}"
                     + (f" <span class='meta'>({src})</span>" if src else "")
                     + (f" <a href=\"{link}\">Read more</a>" if link else "") + "</p>")
    ch = epub.EpubHtml(title="The Day in Tech", file_name="briefing.xhtml", lang="en")
    ch.content = "".join(parts)
    ch.add_item(style)
    return ch


def build(cfg, picks, out_path, briefing=None):
    kc = cfg["kindle"]
    tz = ZoneInfo(kc.get("timezone", "America/Los_Angeles"))
    today = datetime.now(tz)
    date_label = f"{today:%A, %B} {today.day}, {today.year}"
    title = f"{kc.get('title', 'Top Picks')}, {today:%a %b} {today.day}"

    folder_map = {f: s for s, folders in kc["sections"].items() for f in folders}
    later_name = kc.get("later_section", "Saved for Later")
    folder_map["__later__"] = later_name
    order = [later_name] + list(kc["sections"]) + [kc.get("other_section", "More")]
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
    # cover headlines: real top stories first; always-include items (score 10 by rule) rank like a 7
    top = sorted(picks, key=lambda p: -(7 if (p.get("reason") or "").startswith("On your always-include")
                                       else p.get("score", 0)))
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

    if cover.PHOTO.exists():
        front_html.append("<p class='meta'>Cover art of Mount Rainier adapted from \"Aerial Seattle and Mt Rainier\" by Liesl Matthies, "
                          "CC BY-SA 3.0 (commons.wikimedia.org): outline traced, tones simplified.</p>")
    brief = briefing_chapter(briefing, style) if briefing else None
    if brief:
        book.add_item(brief)
        front_html.insert(1, "<h2 class='section'>The Day in Tech</h2><ul class='front'><li>"
                             "<a href='briefing.xhtml'>Techmeme's top stories in a few sentences each</a></li></ul>")
    front = epub.EpubHtml(title="Front Page", file_name="front.xhtml", lang="en")
    front.content = "".join(front_html)
    front.add_item(style)
    book.add_item(front)
    book.toc = [epub.Link("front.xhtml", "Front Page", "front")] + (
        [epub.Link("briefing.xhtml", "The Day in Tech", "briefing")] if brief else []) + toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    cover_page = book.get_item_with_id("cover")
    if cover_page is not None:
        cover_page.is_linear = True  # keep the cover page in the reading order
    book.spine = ["cover", front] + ([brief] if brief else []) + chapters
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
    ap.add_argument("--techmeme-export", metavar="FILE",
                    help="save Techmeme's top stories as JSON for Claude to summarize, then exit")
    ap.add_argument("--briefing", metavar="FILE",
                    help="JSON of Claude's Techmeme summaries to include as 'The Day in Tech'")
    ap.add_argument("--mark-sent", action="store_true",
                    help="record that the edition was sent (when Mail on the Mac sent it) and exit")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    kc = cfg.get("kindle") or {}
    last_path = ROOT / "state" / "kindle_last.json"
    if args.techmeme_export:
        stories = techmeme_top(kc.get("techmeme_stories", 15))
        Path(args.techmeme_export).write_text(json.dumps(stories, indent=1, ensure_ascii=False))
        log(f"Saved {len(stories)} Techmeme top stories to {args.techmeme_export}")
        return
    if args.mark_sent:
        last_path.write_text(json.dumps({"sent": datetime.now(timezone.utc).isoformat()}))
        pending, sent = ROOT / "state" / "later_pending.json", ROOT / "state" / "later_sent.json"
        if pending.exists():
            done = set(json.loads(sent.read_text())) if sent.exists() else set()
            done |= set(json.loads(pending.read_text()))
            sent.write_text(json.dumps(sorted(done)))
            pending.unlink()
        log("Recorded the Kindle edition as sent.")
        return
    STRIP_LINK_HOSTS[:] = kc.get("strip_link_hosts") or []
    if not kc.get("enabled"):
        log("Kindle edition is turned off in config.yaml.")
        return
    picks = json.loads((ROOT / "state" / "picks.json").read_text(encoding="utf-8"))
    # everything picked since the last edition that was sent (first edition: the last day)
    try:
        since = datetime.fromisoformat(json.loads(last_path.read_text())["sent"])
    except (FileNotFoundError, KeyError, ValueError):
        since = datetime.now(timezone.utc) - timedelta(hours=kc.get("window_hours", 24))
    picks = [p for p in picks if p.get("kind") == "article"
             and datetime.fromisoformat(p["picked"]) >= since
             and not p.get("enclosure")  # no podcast episodes or other audio/video files
             and not urlparse(p.get("link") or "").netloc.removeprefix("www.").startswith(VIDEO_HOSTS)]
    skip = re.compile("|".join(cfg.get("skip_title_patterns") or ["$^"]), re.I)
    picks = [p for p in picks if not skip.search(p.get("title") or "")]
    picks = sorted(picks, key=lambda p: -p.get("score", 0))[: kc.get("max_articles", 25)]
    sent_path = ROOT / "state" / "later_sent.json"
    sent_ids = set(json.loads(sent_path.read_text())) if sent_path.exists() else set()
    later = later_items(kc, sent_ids)
    known = {p.get("link") for p in picks}
    later = [i for i in later if i["link"] not in known]
    (ROOT / "state" / "later_pending.json").write_text(json.dumps([i["id"] for i in later]))
    if later:
        log(f"Adding {len(later)} articles from your Later list")
    picks = later + picks
    if len(picks) < kc.get("min_articles", 3):
        log(f"Only {len(picks)} articles today; skipping the Kindle edition.")
        return

    out = ROOT / args.out
    title = build(cfg, picks, out, briefing=args.briefing)
    log(f"Built {out.name} ({out.stat().st_size // 1024} KB, {len(picks)} articles)")
    print(json.dumps({"file": str(out), "title": title, "articles": len(picks)}))
    if not args.no_send and send(out, title):
        last_path.write_text(json.dumps({"sent": datetime.now(timezone.utc).isoformat(), "title": title}))


if __name__ == "__main__":
    main()
