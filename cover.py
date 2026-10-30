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


# Original Sasquatch, built from parts (local units, y down, feet at 394), walking right in the
# classic pose: torso turned partly toward the viewer, hunched back, head low and turned toward us,
# near arm hanging heavy and swinging slightly back, far arm swinging forward with the paper.
SQ_BACK_LEG = [(150, 246), (156, 276), (152, 300), (140, 330), (124, 360), (116, 374), (126, 386),
               (130, 394), (98, 394), (84, 388), (80, 374), (94, 350), (110, 318), (120, 286), (124, 250)]
SQ_FRONT_LEG = [(176, 242), (192, 272), (206, 300), (212, 330), (214, 360), (220, 376), (242, 380),
                (258, 386), (256, 394), (214, 395), (198, 392), (194, 376), (190, 346), (184, 316),
                (172, 292), (158, 272), (158, 248)]
SQ_FAR_ARM = [(178, 110), (198, 116), (212, 148), (222, 180), (232, 204), (236, 222), (222, 230),
              (210, 214), (198, 186), (186, 156), (176, 128)]
SQ_TORSO = [(118, 104), (128, 84), (146, 72), (168, 74), (188, 86), (200, 108), (204, 138), (204, 172), (196, 212),
            (188, 250), (156, 260), (126, 254), (116, 222), (112, 184), (112, 146), (114, 120)]
SQ_HEAD = [(148, 96), (145, 76), (150, 60), (160, 51), (172, 52), (182, 62), (187, 78), (184, 94), (172, 104), (158, 104)]
SQ_NEAR_ARM = [(118, 102), (138, 110), (130, 142), (118, 174), (106, 204), (100, 228), (98, 248),
               (88, 256), (76, 250), (76, 230), (82, 204), (92, 172), (102, 138)]
SASQUATCH_PARTS = [SQ_BACK_LEG, SQ_FRONT_LEG, SQ_FAR_ARM, SQ_TORSO, SQ_HEAD, SQ_NEAR_ARM]


def _smooth(pts, n=10):
    """Closed Catmull-Rom spline through pts."""
    out = []
    for i in range(len(pts)):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % len(pts)], pts[(i + 2) % len(pts)]
        for k in range(n):
            t = k / n
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * (2 * p1[j] + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                                    + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3) for j in (0, 1)))
    return out


def _shaggy(d, outline, x, base, s, fill, rnd):
    """Fill a clockwise outline, then hang tapered hair strands from its undersides and back edges,
    skipping the feet and the face so they stay crisp."""
    d.polygon(outline, fill=fill)
    n = len(outline)
    for i in range(0, n, 2):
        (x0, y0), (x1, y1) = outline[i - 1], outline[(i + 1) % n]
        px, py = outline[i]
        ly = (py - base) / s + 394
        lx = (px - x) / s + 168
        if ly > 372 or (ly < 104 and lx > 160):
            continue
        tx, ty = x1 - x0, y1 - y0
        L = math.hypot(tx, ty) or 1
        nx, ny = ty / L, -tx / L
        if ny < 0.15 and nx > -0.55:
            continue
        dx, dy = nx * 0.45, max(ny, 0.35) + 0.35
        k = math.hypot(dx, dy)
        dx, dy = dx / k, dy / k
        length = rnd.uniform(4, 8) * s
        w = rnd.uniform(1.4, 2.4) * s
        d.polygon([(px - tx / L * w, py - ty / L * w), (px + tx / L * w, py + ty / L * w),
                   (px + dx * length, py + dy * length)], fill=fill)


def sasquatch(d, x, base, s, fill=INK):
    """An original striding Sasquatch silhouette carrying a folded newspaper.
    (x, base) is the ground point between his feet; s is pixels per unit (the figure is ~355 units tall)."""
    rnd = random.Random(11)
    for shape in SASQUATCH_PARTS:
        _shaggy(d, [(x + (px - 168) * s, base + (py - 394) * s) for px, py in _smooth(shape)], x, base, s, fill, rnd)
    # the folded newspaper in his forward hand
    def T(pts):
        return [(x + (px - 168) * s, base + (py - 394) * s) for px, py in pts]
    d.polygon(T([(226, 200), (264, 190), (272, 232), (232, 242)]), fill=PAPER, outline=fill)
    d.polygon(T([(229, 205), (262, 196), (264, 203), (231, 212)]), fill=fill)          # masthead
    for row in range(5):
        y0 = 218 + row * 4.5
        d.line(T([(232, y0), (267, y0 - 8)]), fill=90, width=max(1, int(1.2 * s)))
    d.ellipse([x + (222 - 168) * s, base + (204 - 394) * s, x + (240 - 168) * s, base + (230 - 394) * s], fill=fill)  # hand


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
    clearing = (sw * 0.48, sw * 0.70) if sasquatch_on else (-1, -1)
    x = -40
    while x < sw + 60:
        if not (clearing[0] < x < clearing[1]):
            h = rnd.uniform(sh * 0.40, sh * 0.62)
            tree(d, x, sh * 0.88, h, h * 0.42)
        x += rnd.uniform(110, 170)
    if sasquatch_on:
        sasquatch(d, sw * 0.585, sh * 0.875, 1.65)

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
