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


def _furry(poly, step=7, depth=4, seed=3):
    """Turn a smooth outline into a shaggy one: small zigzags pushed outward from the center."""
    rnd = random.Random(seed)
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    out = []
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        for i in range(n):
            t = i / n
            x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            if i % 2:
                dx, dy = x - cx, y - cy
                k = depth * rnd.uniform(0.6, 1.4) / (math.hypot(dx, dy) or 1)
                x, y = x + dx * k, y + dy * k
            out.append((x, y))
    return out


def sasquatch(d, x, base, s, fill=INK):
    """The classic striding Sasquatch, seen in profile mid-step: long arms swinging, hunched back,
    pointed crown, pure silhouette like a Bigfoot crossing sign, a folded newspaper in his forward hand.
    (x, base) is the ground point under his hips."""
    def P(pts, fur=True, depth=3.2):
        pts = [(x + px * s, base - py * s) for px, py in pts]
        return _furry(pts, step=5 * s, depth=depth * s) if fur else pts
    # trailing leg stretched back, toes pushing off
    d.polygon(P([(-14, 100), (-36, 56), (-62, 14), (-76, 0), (-48, 0), (-42, 12), (-18, 50), (10, 92)]), fill=fill)
    # leading leg reaching forward, knee bent, heel down
    d.polygon(P([(-6, 96), (22, 60), (28, 12), (22, 0), (60, 0), (58, 8), (44, 14), (46, 62), (20, 102)]), fill=fill)
    # trailing arm: long, swinging back to knee height
    d.polygon(P([(-24, 188), (-46, 144), (-66, 98), (-62, 86), (-48, 92), (-30, 136), (-6, 178)]), fill=fill)
    # torso leaning into the stride, big hump of shoulders and back
    d.polygon(P([(-24, 96), (-38, 132), (-40, 168), (-28, 194), (-6, 206), (16, 200), (30, 178),
                 (34, 142), (26, 104)], depth=3.8), fill=fill)
    # head set low and forward, pointed crown
    d.polygon(P([(2, 194), (-2, 214), (6, 232), (16, 240), (28, 228), (32, 210), (26, 194)]), fill=fill)
    # leading arm swinging forward, hand low, holding the paper
    d.polygon(P([(10, 186), (34, 146), (48, 104), (60, 98), (62, 110), (48, 150), (28, 190)]), fill=fill)
    paper = [(52, 118), (88, 112), (86, 74), (50, 80)]
    d.polygon(P(paper, fur=False), fill=PAPER, outline=fill)
    d.polygon(P([(54, 112), (85, 107), (85, 101), (54, 106)], fur=False), fill=fill)  # masthead
    for row in range(5):
        y0 = 97 - row * 4.2
        d.line(P([(55, y0), (84, y0 - 5)], fur=False), fill=90, width=max(1, int(1.2 * s)))
    d.polygon(P([(50, 108), (62, 110), (64, 98), (52, 94)]), fill=fill)  # big hand over the paper


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
        sasquatch(d, sw * 0.585, sh * 0.865, 2.15)

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
