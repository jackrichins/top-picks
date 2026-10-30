"""Newspaper-style Kindle cover: blackletter masthead, ears, dateline, a woodcut
Cascades scene (mountain, evergreens, sunrise, and a Sasquatch reading the paper),
and the day's headlines.

Designed for e-ink: pure grayscale, high contrast, 1600 x 2560 (Kindle's 1:1.6 ratio).
"""
import io
import math
import random
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).resolve().parent / "fonts"
W, H, M = 1600, 2560, 90
INK, PAPER = 0, 250


def F(name, size):
    try:
        return ImageFont.truetype(str(FONTS / name), size)
    except OSError:
        return ImageFont.load_default(size=size)


def clean(s):
    return " ".join("".join(c for c in (s or "") if unicodedata.category(c) != "So").split())


def wrap(d, text, fnt, width, max_lines):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if d.textlength(trial, font=fnt) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
            if len(lines) == max_lines:
                break
    if line and len(lines) < max_lines:
        lines.append(line)
    if len(lines) == max_lines and " ".join(lines) != text:
        while lines[-1] and d.textlength(lines[-1] + "...", font=fnt) > width:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "..."
    return [l for l in lines if l]


# ---------- the woodcut scene ----------

def tree(d, x, base, h, w, fill=INK):
    """An evergreen made of stacked, slightly drooping tiers."""
    tiers = max(4, int(h / 38))
    for i in range(tiers):
        t = i / tiers
        top = base - h + t * h * 0.82
        bot = top + h / tiers * 1.9
        half = w * (0.18 + 0.82 * (i + 1) / tiers) / 2
        d.polygon([(x, top), (x - half, bot), (x - half * 0.35, bot - 10), (x, bot + 6),
                   (x + half * 0.35, bot - 10), (x + half, bot)], fill=fill)


def sasquatch(d, x, base, s, fill=INK):
    """Sasquatch sitting on a stump, reading the paper. (x, base) is the stump's foot."""
    def P(pts):
        return [(x + px * s, base - py * s) for px, py in pts]
    # stump with growth rings on top
    d.rectangle([x - 56 * s, base - 58 * s, x + 56 * s, base], fill=150, outline=fill, width=int(3 * s))
    for bx in (-40, -22, 22, 40):  # bark lines
        d.line([(x + bx * s, base - 50 * s), (x + bx * s, base - 6 * s)], fill=fill, width=max(1, int(2 * s)))
    d.ellipse([x - 56 * s, base - 70 * s, x + 56 * s, base - 46 * s], fill=215, outline=fill, width=int(3 * s))
    d.ellipse([x - 34 * s, base - 64 * s, x + 34 * s, base - 52 * s], outline=fill, width=int(2 * s))
    # legs and big feet dangling in front of the stump
    d.polygon(P([(-30, 66), (-32, 30), (-28, 12), (-14, 12), (-12, 30), (-8, 66)]), fill=fill)
    d.polygon(P([(8, 66), (12, 30), (14, 12), (28, 12), (32, 30), (30, 66)]), fill=fill)
    d.ellipse([x - 42 * s, base - 16 * s, x - 6 * s, base + 2 * s], fill=fill)
    d.ellipse([x + 6 * s, base - 16 * s, x + 42 * s, base + 2 * s], fill=fill)
    # shaggy body and head peeking over the paper
    d.polygon(P([(-46, 60), (-50, 120), (-36, 150), (36, 150), (50, 120), (46, 60)]), fill=fill)
    d.ellipse([x - 26 * s, base - 196 * s, x + 26 * s, base - 140 * s], fill=fill)
    d.polygon(P([(-10, 194), (-4, 206), (2, 196), (8, 206), (12, 192)]), fill=fill)  # tuft of hair
    d.ellipse([x - 13 * s, base - 176 * s, x - 5 * s, base - 168 * s], fill=PAPER)  # eyes
    d.ellipse([x + 5 * s, base - 176 * s, x + 13 * s, base - 168 * s], fill=PAPER)
    d.ellipse([x - 10 * s, base - 173 * s, x - 6 * s, base - 169 * s], fill=fill)
    d.ellipse([x + 6 * s, base - 173 * s, x + 10 * s, base - 169 * s], fill=fill)
    # the newspaper, held open, with a masthead rule, a headline bar, and columns
    pw, ph, top = 78, 96, 160
    d.polygon(P([(-pw, top), (pw, top - 6), (pw + 4, top - ph), (-pw - 4, top - ph + 6)]), fill=PAPER, outline=fill)
    d.line(P([(0, top - 3), (2, top - ph + 3)]), fill=fill, width=max(1, int(2 * s)))  # fold
    for side in (-1, 1):
        x0 = 8 if side > 0 else -pw + 10
        d.rectangle([x + x0 * s, base - (top - 14) * s, x + (x0 + 60) * s, base - (top - 22) * s], fill=fill)
        for row in range(5):
            yy = top - 32 - row * 11
            d.line([(x + x0 * s, base - yy * s), (x + (x0 + 60) * s, base - yy * s)], fill=90, width=max(1, int(2 * s)))
    # hands gripping the edges
    d.ellipse([x - (pw + 14) * s, base - 128 * s, x - (pw - 8) * s, base - 104 * s], fill=fill)
    d.ellipse([x + (pw - 8) * s, base - 130 * s, x + (pw + 14) * s, base - 106 * s], fill=fill)


def scene(width, height, seed=7, sasquatch_on=False):
    """Draw at 2x and downsample for smooth edges."""
    sw, sh = width * 2, height * 2
    img = Image.new("L", (sw, sh), PAPER)
    d = ImageDraw.Draw(img)
    rnd = random.Random(seed)

    # sun with woodcut rays
    cx, cy, r = sw * 0.78, sh * 0.30, sh * 0.11
    for k in range(36):
        a = k * math.pi / 18
        r2 = r * (2.6 if k % 2 else 1.9)
        d.polygon([(cx + math.cos(a - 0.03) * r * 1.25, cy + math.sin(a - 0.03) * r * 1.25),
                   (cx + math.cos(a) * r2, cy + math.sin(a) * r2),
                   (cx + math.cos(a + 0.03) * r * 1.25, cy + math.sin(a + 0.03) * r * 1.25)], fill=170)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=PAPER, outline=INK, width=8)

    # the big mountain: shaded body, hatching clipped to its shape, bright snowcap
    px, py = sw * 0.36, sh * 0.10
    outline = [(sw * -0.02, sh * 0.80), (sw * 0.24, sh * 0.30), (px, py), (sw * 0.47, sh * 0.26), (sw * 0.80, sh * 0.80)]
    mask = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(mask).polygon(outline, fill=255)
    hatch = Image.new("L", (sw, sh), 120)
    hd = ImageDraw.Draw(hatch)
    for i in range(-40, 120):
        x0 = px + i * 26
        hd.line([(x0, py), (x0 - 520, py + 1300)], fill=80, width=6)
    img.paste(hatch, (0, 0), mask)
    snow = [(sw * 0.205, sh * 0.37), (sw * 0.24, sh * 0.30), (px, py), (sw * 0.47, sh * 0.26),
            (sw * 0.535, sh * 0.355), (sw * 0.49, sh * 0.33), (sw * 0.455, sh * 0.39), (sw * 0.42, sh * 0.32),
            (sw * 0.38, sh * 0.41), (sw * 0.34, sh * 0.33), (sw * 0.30, sh * 0.40), (sw * 0.26, sh * 0.34)]
    d.polygon(snow, fill=PAPER, outline=INK, width=5)
    d.line(outline, fill=INK, width=8, joint="curve")

    # middle ridge
    pts, x = [(0, sh)], 0
    while x <= sw:
        pts.append((x, sh * 0.62 + math.sin(x / 210) * 50 + rnd.uniform(-20, 20)))
        x += 60
    d.polygon(pts + [(sw, sh)], fill=150)
    d.line(pts[1:], fill=INK, width=6)

    # far tree line on the ridge
    for x in range(20, sw, 46):
        h = rnd.uniform(70, 120)
        tree(d, x, sh * 0.70 + rnd.uniform(-10, 10), h, h * 0.45, fill=60)

    # foreground ground and big trees, leaving a clearing for our friend
    d.rectangle([0, sh * 0.86, sw, sh], fill=INK)
    clearing = (sw * 0.50, sw * 0.68) if sasquatch_on else (-1, -1)
    x = -40
    while x < sw + 60:
        if not (clearing[0] < x < clearing[1]):
            h = rnd.uniform(sh * 0.40, sh * 0.62)
            tree(d, x, sh * 0.88, h, h * 0.42)
        x += rnd.uniform(110, 170)
    if sasquatch_on:
        sasquatch(d, sw * 0.59, sh * 0.862, 2.4)

    d.rectangle([0, 0, sw - 1, sh - 1], outline=INK, width=10)
    return img.resize((width, height), Image.LANCZOS)


# ---------- the cover ----------

def make_cover(name, tagline, date_label, edition, place, picks, feed_count, sasquatch=False):
    """picks: list of dicts with title, section, reason (sorted best first)."""
    img = Image.new("L", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    cw = W - 2 * M

    # ears
    ear = F("body-italic.woff", 30)
    d.multiline_text((M, 70), "Today's forecast:\nask Cliff Mass", font=ear, fill=INK, spacing=6)
    d.multiline_text((W - M, 70), "Price: free to\none subscriber", font=ear, fill=INK, spacing=6, align="right", anchor="ra")

    # masthead, sized to fit
    size = 200
    while size > 80 and d.textlength(name, font=F("masthead.woff", size)) > cw - 40:
        size -= 6
    d.text((W / 2, 230), name, font=F("masthead.woff", size), fill=INK, anchor="mm")
    d.text((W / 2, 370), tagline, font=F("body-italic.woff", 38), fill=INK, anchor="mm")

    # dateline between rules
    y = 420
    d.line([(M, y), (W - M, y)], fill=INK, width=7)
    d.line([(M, y + 14), (W - M, y + 14)], fill=INK, width=2)
    small = F("body-bold.woff", 28)
    d.text((M, y + 46), edition.upper(), font=small, fill=INK, anchor="lm")
    d.text((W / 2, y + 46), f"{place}, {date_label}".upper(), font=small, fill=INK, anchor="mm")
    d.text((W - M, y + 46), "CURATED BY CLAUDE", font=small, fill=INK, anchor="rm")
    d.line([(M, y + 78), (W - M, y + 78)], fill=INK, width=2)
    d.line([(M, y + 92), (W - M, y + 92)], fill=INK, width=7)

    # illustration
    art_h = 640
    img.paste(scene(cw, art_h, sasquatch_on=sasquatch), (M, y + 125))
    y = y + 125 + art_h + 50

    picks = [dict(p, title=clean(p.get("title"))) for p in picks if clean(p.get("title"))]
    if picks:
        lead = picks[0]
        d.text((M, y), (lead.get("section") or "Top story").upper(), font=F("body-bold.woff", 30), fill=INK)
        y += 50
        hf = F("headline-black.woff", 92)
        for line in wrap(d, lead["title"], hf, cw, 3):
            d.text((M, y), line, font=hf, fill=INK)
            y += 104
        rf = F("body-italic.woff", 38)
        y += 18
        for line in wrap(d, lead.get("reason") or "", rf, cw, 2):
            d.text((M, y + 6), line, font=rf, fill=INK)
            y += 50
        y += 40

    # two columns of more headlines
    d.line([(M, y), (W - M, y)], fill=INK, width=3)
    y += 30
    colw = (cw - 60) / 2
    d.line([(W / 2, y), (W / 2, H - 200)], fill=INK, width=2)
    cols = [[M, y], [M + colw + 60, y]]
    kf, hf2 = F("body-bold.woff", 24), F("headline-bold.woff", 46)
    ci = 0
    for p in picks[1:]:
        lines = wrap(d, p["title"], hf2, colw, 3)
        need = 40 + len(lines) * 56 + 40
        if cols[ci][1] + need > H - 210:
            ci += 1
            if ci > 1:
                break
        cx, cy = cols[ci]
        d.text((cx, cy), (p.get("section") or "").upper(), font=kf, fill=INK)
        cy += 38
        for line in lines:
            d.text((cx, cy), line, font=hf2, fill=INK)
            cy += 56
        d.line([(cx, cy + 14), (cx + 90, cy + 14)], fill=INK, width=2)
        cols[ci][1] = cy + 40

    # footer
    d.line([(M, H - 170), (W - M, H - 170)], fill=INK, width=7)
    d.text((W / 2, H - 115), f"{len(picks)} stories inside, picked from {feed_count} feeds",
           font=F("body-italic.woff", 36), fill=INK, anchor="mm")

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()
