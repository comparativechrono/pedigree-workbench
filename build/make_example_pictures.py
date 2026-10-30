#!/usr/bin/env python3
"""Make the example pictures for Picture -> PED file and drawing (PedInterp) with Pedigree Studio itself, in headless Chromium:

    okafor.png          the Okafor family as Pedigree Studio saves it (its Save as image): identical twins, and
                        parents who are cousins
    okafor-sketch.png   the same family sketched roughly with the Studio's Draw tool, as it might be in a clinic:
                        symbols of unequal sizes, drawn in one stroke or two that don't quite close or run on past
                        where they began, filled ones scribbled in, slashes for those who have died, an arrow at the
                        proband, and wobbly lines that stop short of what they join or run a little past it

The sketch's strokes are made by a program that imitates a hand, from the people's places in okafor.studio.json, with
a fixed seed, so that making them again gives the same picture, with the pen the Draw tool starts with: black, 4 pixels
wide. PedInterp reads both pictures as the Okafor family, with its twins, and with --marks, who has died and the
proband: the sketch with --hand-drawn (the tests check it).

It needs Playwright and its Chromium (pip install playwright; playwright install chromium), numpy and Pillow, which
saves the pictures again, compressed as far as PNG goes without changing a pixel. Nothing is fetched from the network:
the Studio is the copy in assets/studio.

Run:  python3 build/make_example_pictures.py
"""
import json
import math
import os

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLES = os.path.join(ROOT, "data", "examples")
STUDIO = os.path.join(ROOT, "assets", "studio", "index.html")
#: the seed of the sketch, one that PedInterp reads right: not every sketch is read right, as the help says
SEED = 3
#: the pen the Draw tool starts with: black, the colour of the Studio's own lines, and 4 pixels wide
PEN, WIDTH = "#1a2332", 4
HALF = 26   # half the Studio's symbol, in its canvas pixels


# ---------------------------------------------------------------------------------------------------- strokes by hand
def densify(points, rng, step=(2.0, 6.0)):
    """points along a path about every step pixels, as a pointer's events would come"""
    out = [points[0]]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        length = math.hypot(x1 - x0, y1 - y0)
        t = 0.0
        while True:
            t += float(rng.uniform(*step)) / max(length, 1e-9)
            if t >= 1:
                break
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        out.append((x1, y1))
    return out


def wobble(points, rng, amp, waves=2):
    """a slow sideways wander of up to amp pixels along a path, and a little tremor"""
    pts = np.array(points, float)
    if len(pts) < 3:
        return [tuple(p) for p in pts]
    s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])
    d = np.gradient(pts, axis=0)
    norm = np.hypot(d[:, 0], d[:, 1]) + 1e-9
    normal = np.stack([-d[:, 1] / norm, d[:, 0] / norm], axis=1)
    offset = sum(float(rng.normal(0, amp / math.sqrt(waves))) *
                 np.sin(2 * math.pi * s / (s[-1] or 1) * float(rng.uniform(0.5, 2)) + float(rng.uniform(0, 6.3)))
                 for _ in range(waves))
    pts = pts + normal * offset[:, None] + rng.normal(0, 0.4, pts.shape)
    return [tuple(p) for p in pts]


def rough_line(p0, p1, rng):
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    return wobble(densify([p0, p1], rng), rng, min(3.0, 0.03 * length + 0.5))


def rough_symbol(cx, cy, size, shape, rng):
    """a symbol's outline, in one stroke or two, which may not quite close or may run on; and its polygon"""
    w, h = size * float(rng.uniform(0.92, 1.08)), size * float(rng.uniform(0.92, 1.08))
    if shape == "female":
        start = float(rng.uniform(0, 2 * math.pi))
        poly = [(cx + w / 2 * math.cos(start + 2 * math.pi * k / 64), cy + h / 2 * math.sin(start + 2 * math.pi * k / 64))
                for k in range(65)]
    elif shape == "miscarriage":
        poly = [(cx, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
        poly.append(poly[0])
    else:
        corners = ([(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
                   if shape == "male" else [(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)])
        poly = [(x + float(rng.normal(0, 0.03 * size)), y + float(rng.normal(0, 0.03 * size))) for x, y in corners]
        poly.append(poly[0])
    pts = wobble(densify(poly, rng, (2.0, 5.0)), rng, 0.012 * size + 0.3, waves=3)
    if rng.random() < 0.5:
        pts = pts[:-max(1, int(len(pts) * float(rng.uniform(0.01, 0.04))))]
    else:
        pts = pts + pts[1:1 + int(len(pts) * float(rng.uniform(0.01, 0.05)))]
    if rng.random() < 0.25:
        k = len(pts) // 2
        return [pts[:k + 1], pts[k:]], poly[:-1]
    return [pts], poly[:-1]


def scribble(poly, rng):
    """filled in by hand: zig-zags across the symbol, a little more than the pen's width apart"""
    pts = np.array(poly, float)
    cx, cy = pts.mean(axis=0)
    angle = float(rng.uniform(0, math.pi))
    c, s = math.cos(-angle), math.sin(-angle)
    rot = (pts - [cx, cy]) @ np.array([[c, -s], [s, c]]).T
    path, flip, y = [], False, rot[:, 1].min() + WIDTH
    while y < rot[:, 1].max():
        xs = [x0 + (x1 - x0) * (y - y0) / (y1 - y0) for (x0, y0), (x1, y1) in zip(rot, np.roll(rot, -1, axis=0))
              if (y0 - y) * (y1 - y) <= 0 and y0 != y1]
        if len(xs) >= 2:
            seg = [(min(xs) + 1, y), (max(xs) - 1, y)]
            path += seg[::-1] if flip else seg
            flip = not flip
        y += float(rng.uniform(1.8, 2.6)) * WIDTH
    c, s = math.cos(angle), math.sin(angle)
    return wobble(densify([(cx + x * c - y * s, cy + x * s + y * c) for x, y in path], rng, (2.0, 5.0)), rng, 0.6)


def arrow(cx, cy, size, rng):
    """a proband's arrow drawn by hand: a line up from below on the left to just off the symbol, and a head of two
    strokes drawn in one, in to the tip and out again"""
    angle = math.radians(float(rng.uniform(38, 52)))
    d = (-math.cos(angle), math.sin(angle))
    tip_at = size * float(rng.uniform(0.78, 0.88))
    tip = (cx + d[0] * tip_at, cy + d[1] * tip_at)
    tail = (tip[0] + d[0] * 0.6 * size, tip[1] + d[1] * 0.6 * size)
    ends = [(tip[0] + 0.2 * size * math.cos(math.atan2(d[1], d[0]) + turn),
             tip[1] + 0.2 * size * math.sin(math.atan2(d[1], d[0]) + turn)) for turn in (0.6, -0.6)]
    return [rough_line(tail, tip, rng), rough_line(ends[0], tip, rng) + rough_line(tip, ends[1], rng)[1:]]


def sketch(doc, rng):
    """the strokes of a drawing's family, sketched by hand where its people are"""
    people = {}
    for p in doc["persons"]:
        size = 52 * float(rng.uniform(0.75, 1.25)) * (0.85 if p["shape"] == "miscarriage" else 1.0)
        people[p["id"]] = {"x": p["x"] + HALF, "y": p["y"] + HALF, "size": size, "shape": p["shape"],
                           "filled": p.get("fillMode") == "solid", "deceased": p.get("deceased"),
                           "proband": p.get("proband")}
    strokes = []
    for pid, p in people.items():
        outline, poly = rough_symbol(p["x"], p["y"], p["size"], p["shape"], rng)
        strokes += outline
        if p["filled"]:
            strokes.append(scribble(poly, rng))
        if p["deceased"]:
            r = p["size"] * float(rng.uniform(0.55, 0.7))
            strokes.append(rough_line((p["x"] - r, p["y"] + r), (p["x"] + r, p["y"] - r), rng))
        if p["proband"]:
            strokes += arrow(p["x"], p["y"], p["size"], rng)
    gap = lambda: float(rng.uniform(-2, 6))
    twin_of = {}
    for t in doc.get("twinLinks") or []:
        twin_of[t["child1Id"]], twin_of[t["child2Id"]] = (t["child2Id"], t["type"]), (t["child1Id"], t["type"])
    for couple in doc["partnerships"]:
        a, b = sorted((people[couple["fromId"]], people[couple["toId"]]), key=lambda q: q["x"])
        y0 = (a["y"] + b["y"]) / 2
        x0, x1 = a["x"] + a["size"] / 2 + gap(), b["x"] - b["size"] / 2 - gap()
        strokes.append(rough_line((x0, y0), (x1, y0), rng))
        kids = [c["childId"] for c in doc["childLinks"] if c["partnershipId"] == couple["id"]]
        if not kids:
            continue
        mx = (x0 + x1) / 2
        ysib = min(people[k]["y"] - people[k]["size"] / 2 for k in kids) - float(rng.uniform(22, 30))
        strokes.append(rough_line((mx, y0 + gap()), (mx, ysib + float(rng.uniform(-2, 3))), rng))
        xs, done = [mx], set()
        for k in kids:
            q = people[k]
            if k in twin_of and twin_of[k][0] in kids:
                if k in done:
                    continue
                other, kind = twin_of[k]
                done.update((k, other))
                o = people[other]
                apex = ((q["x"] + o["x"]) / 2, ysib)
                xs.append(apex[0])
                ends = [(t["x"], t["y"] - t["size"] / 2 - float(rng.uniform(0, 4))) for t in (q, o)]
                for end in ends:
                    strokes.append(rough_line(apex, end, rng))
                if kind == "identical":
                    f = 0.5
                    strokes.append(rough_line((apex[0] + (ends[0][0] - apex[0]) * f, apex[1] + (ends[0][1] - apex[1]) * f),
                                              (apex[0] + (ends[1][0] - apex[0]) * f, apex[1] + (ends[1][1] - apex[1]) * f),
                                              rng))
            else:
                xs.append(q["x"])
                strokes.append(rough_line((q["x"], ysib + float(rng.uniform(-3, 3))), (q["x"], q["y"] - q["size"] / 2 - gap()),
                                          rng))
        strokes.append(rough_line((min(xs) - 2, ysib), (max(xs) + 2, ysib), rng))
    return strokes


def session(doc=None, strokes=()):
    """a Studio session: a drawing as it is, or strokes of its Draw tool alone"""
    data = dict(doc) if doc else {"version": 4, "personIdCounter": 0, "labelIdCounter": 0, "lineIdCounter": 100,
                                  "persons": [], "labels": [], "partnerships": [], "childLinks": [], "twinLinks": [],
                                  "legendLabels": {}, "legendVisible": False, "legendX": 100, "legendY": 100,
                                  "numberingMode": "numbers", "partnerGapMultiplier": 2, "childHeightMultiplier": 2.5}
    if strokes:
        data["drawStrokes"] = [{"points": [{"x": round(x, 2), "y": round(y, 2)} for x, y in pts], "color": PEN,
                                "width": WIDTH} for pts in strokes if len(pts) >= 2]
    return data


def main():
    from playwright.sync_api import sync_playwright
    with open(os.path.join(EXAMPLES, "okafor.studio.json"), encoding="utf-8") as fh:
        okafor = json.load(fh)
    pictures = {"okafor.png": session(okafor),
                "okafor-sketch.png": session(strokes=sketch(okafor, np.random.default_rng(SEED)))}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(accept_downloads=True, viewport={"width": 1400, "height": 900})
        # nothing from the network
        context.route(lambda url: not url.startswith("file://"), lambda route: route.abort())
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("file://" + STUDIO)
        page.wait_for_function('typeof restoreSession === "function" && typeof saveAsImage === "function"')
        for name, data in pictures.items():
            page.evaluate("data => restoreSession(data)", data)
            page.wait_for_timeout(100)
            with page.expect_download() as download:
                page.evaluate("saveAsImage()")
            path = os.path.join(EXAMPLES, name)
            download.value.save_as(path)
            # (the same pixels, in fewer bytes)
            with Image.open(path) as picture:
                picture.load()
            picture.save(path, optimize=True)
            print(name)
        browser.close()
    if errors:
        raise SystemExit(f"Pedigree Studio failed: {errors}")


if __name__ == "__main__":
    main()
