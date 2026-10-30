'''
Reading what the marks on a pedigree's symbols say about the people, besides their sex and whether they are affected:

- a slash through the symbol of someone who has died, rising to the right. Through a symbol left empty, it is seen
  inside it; a symbol filled in hides it, but for where it runs out past the symbol at both ends, as a slash drawn by
  hand does, and as Pedigree Studio draws one through a circle or a diamond
- an arrow pointing at the proband's symbol from below on the left, with a head at the end by the symbol
- a dot in the middle of a carrier's symbol: dark in a symbol left empty, and white in one filled in solidly

pedigree_processing reads them when it is given marks=True. A PED file has no place for them, so a table with them is
written as a GA4GH Pedigree (GA4GH_export) or a Pedigree Studio drawing (Studio_export).
'''
import math

import cv2
import numpy as np

#: how steep a proband's arrow may be: degrees from the level, rising to the right
ARROW_SLOPES = (20.0, 70.0)
#: how steep a slash may be
SLASH_SLOPES = (30.0, 60.0)
#: how much of a line through the inside of a symbol must run along ink for it to be a slash
SLASH_INSIDE = 0.7


def _disc(radius):
    radius = max(1, int(round(radius)))
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def _polygon(shape, box):
    '''the outline of a symbol of a shape ('square', 'circle', 'diamond' or 'triangle') that fills a box (x, y, w, h)'''
    x, y, w, h = box
    if shape == 'circle':
        return cv2.ellipse2Poly((int(round(x + w / 2)), int(round(y + h / 2))),
                                (max(1, int(round(w / 2))), max(1, int(round(h / 2)))), 0, 0, 360, 4)
    if shape == 'diamond':
        points = [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]
    elif shape == 'triangle':
        points = [(x + w / 2, y), (x + w, y + h), (x, y + h)]
    else:
        points = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    return np.round(np.array(points, np.float64)).astype(np.int32)


def _symbol(person, line_width):
    '''
    A symbol as the marks are looked for in it: its outline, outline and all, its middle, its size and whether it is
    filled in. The outline of a symbol in a sketch is the one it was found with; that of a symbol in a drawing is its
    shape round the box it was found in, a line's width and a pixel larger all round: the box of an empty symbol is that
    of the white inside its outline, and that of a filled one stops a little short of sharp corners, such as a
    diamond's, as it was found with the lines opened away
    '''
    x, y, w, h = person['node_coords']
    filled = int(person['Phenotype']) == 2
    if person.get('outline') is not None:
        contour = np.asarray(person['outline']).reshape(-1, 2).astype(np.int32)
    else:
        grow = line_width + 1
        contour = _polygon(person.get('shape', 'square'), (x - grow, y - grow, w + 2 * grow, h + 2 * grow))
    bx, by, bw, bh = cv2.boundingRect(contour.reshape(-1, 1, 2))
    return {'contour': contour, 'box': (bx, by, bw, bh), 'centre': (bx + bw / 2, by + bh / 2),
            'size': float(max(bw, bh)), 'filled': filled}


def _window(ink, symbol, margin):
    '''the part of the drawing round a symbol, out to margin pixels past it, and the symbol's outline there'''
    bx, by, bw, bh = symbol['box']
    height, width = ink.shape
    x0, y0 = max(0, bx - margin), max(0, by - margin)
    x1, y1 = min(width, bx + bw + margin), min(height, by + bh + margin)
    outer = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillPoly(outer, [symbol['contour'] - np.array([x0, y0], np.int32)], 1)
    return ink[y0:y1, x0:x1], outer, (x0, y0)


def _slashed(ink, symbol, line_width):
    '''
    Whether a slash runs through a symbol, rising to the right through the middle of it; and, for a symbol filled in,
    whether a piece of line runs out of its upper right, as the end of a slash would (see _proband).

    In a symbol left empty, a line through the inside of it, at a slope in SLASH_SLOPES and a little to either side of
    the middle, runs along ink nearly all the way on both sides of the middle, where a carrier's dot may be: ink close to
    the line counts, as a slash drawn by hand wobbles, but only ink across the line from each point of it, so that a
    row of dots, as in a symbol that Pedigree Studio shades with them, or of specks, doesn't run along ink between them.
    A symbol hatched or shaded with lines is not slashed, as much ink is left inside it away from the line. A symbol
    filled in hides the slash, but for where it runs out past the symbol: a short line out of its upper right and one
    out of its lower left, in line with each other (_stubs)
    '''
    size = symbol['size']
    margin = int(0.5 * size) + 2 * line_width + 4
    window, outer, (x0, y0) = _window(ink, symbol, margin)
    cx, cy = symbol['centre'][0] - x0, symbol['centre'][1] - y0
    if symbol['filled']:
        return _stubs(window, outer, (cx, cy), size, line_width)
    near = 0.04 * size + 1
    ink_near = cv2.dilate(window, _disc(near))
    inner = cv2.erode(outer, _disc(line_width + 3 + 0.04 * size))
    if not inner.any():
        return False, False
    angles = np.radians(np.arange(SLASH_SLOPES[0], SLASH_SLOPES[1] + 0.1, 2.5))
    offsets = np.arange(-0.14, 0.1401, 0.02) * size
    reach = 0.5 * size + margin
    t = np.arange(-reach, reach + 0.5, 1.0)
    along = np.stack([np.cos(angles), -np.sin(angles)], axis=1)            # (rising to the right, as y runs down)
    across = np.stack([np.sin(angles), np.cos(angles)], axis=1)
    px = cx + across[:, None, None, 0] * offsets[None, :, None] + along[:, None, None, 0] * t[None, None, :]
    py = cy + across[:, None, None, 1] * offsets[None, :, None] + along[:, None, None, 1] * t[None, None, :]
    xi = np.clip(np.round(px).astype(np.int64), 0, window.shape[1] - 1)
    yi = np.clip(np.round(py).astype(np.int64), 0, window.shape[0] - 1)
    inside = inner[yi, xi] > 0
    # (the middle, where a carrier's dot is, doesn't count, and the slash must run along ink on either side of it)
    clear = 0.15 * size
    sides = []
    for part in (inside & (t < -clear), inside & (t > clear)):
        chord = part.sum(axis=2)
        sides.append(np.where(chord >= 0.05 * size, ((ink_near[yi, xi] > 0) & part).sum(axis=2) / np.maximum(chord, 1),
                              0.0))
    lengths = (inside & (np.abs(t) > clear)).sum(axis=2)
    cover = np.where(lengths >= 0.15 * size, np.minimum(sides[0], sides[1]), 0.0)
    # (the lines near enough ink for it, looked at again with only the ink across each line from each point of it)
    best, best_cover = None, 0.0
    steps = np.arange(-near, near + 0.5, 1.0)
    for k, m in np.argwhere(cover >= SLASH_INSIDE):
        line_x = cx + across[k, 0] * offsets[m] + along[k, 0] * t
        line_y = cy + across[k, 1] * offsets[m] + along[k, 1] * t
        sx = np.clip(np.round(line_x[:, None] + across[k, 0] * steps[None, :]).astype(np.int64), 0, window.shape[1] - 1)
        sy = np.clip(np.round(line_y[:, None] + across[k, 1] * steps[None, :]).astype(np.int64), 0, window.shape[0] - 1)
        on = (window[sy, sx] > 0).any(axis=1)
        sides = []
        for part in (inside[k, m] & (t < -clear), inside[k, m] & (t > clear)):
            chord = int(part.sum())
            sides.append(float(on[part].sum()) / chord if chord >= 0.05 * size else 0.0)
        if min(sides) > best_cover:
            best, best_cover = (k, m), min(sides)
    if best_cover < SLASH_INSIDE:
        return False, False
    # (hatching or shading: much ink inside away from the line, and from the middle, where a carrier's dot is; or many
    # pieces of ink inside, each too big for a speck, as the dots of the Studio's shading are, where the inside is too
    # small to tell a slash from a row of them: a slash is one piece, with a carrier's dot or a letter beside it at most)
    k, m = best
    ys, xs = np.nonzero(window & inner)
    dx, dy = xs - cx, ys - cy
    distance = np.abs(dx * across[k, 0] + dy * across[k, 1] - offsets[m])
    away = (distance > near + line_width) & (np.hypot(dx, dy) > 0.18 * size)
    if float(away.sum()) > 0.08 * float(inner.sum()):
        return False, False
    _, _, stats, _ = cv2.connectedComponentsWithStats((window & inner).astype(np.uint8), connectivity=8)
    return int((stats[1:, cv2.CC_STAT_AREA] >= line_width ** 2).sum()) < 5, False


def _stubs(window, outer, centre, size, line_width):
    '''
    Whether a slash runs out past a symbol filled in, at both ends: a short piece of line out of the symbol's upper right,
    and one out of its lower left, the line between where they meet the symbol rising to the right through its middle.
    Each is a piece on its own, not a part of the lines that join the symbols, which run on past it, and a piece long
    enough to tell which way it runs must run the way the slash does: a line down to a child drawn as a stroke of its
    own, not meeting the line above, is upright. Returns that, and whether there is a piece out of the upper right
    '''
    cx, cy = centre
    away_from = cv2.distanceTransform((1 - outer).astype(np.uint8), cv2.DIST_L2, 5)
    free = (window & (away_from > 2)).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=8)
    height, width = window.shape
    touch = 4.0
    shortest = max(4.0, 0.06 * size)
    low, high = SLASH_SLOPES[0] - 15, SLASH_SLOPES[1] + 15
    stubs = {}
    for k in range(1, n):
        x, y, w, h, _ = stats[k]
        if x == 0 or y == 0 or x + w >= width or y + h >= height or max(w, h) > 0.9 * size:
            continue
        ys, xs = np.nonzero(labels[y:y + h, x:x + w] == k)
        xs, ys = xs + x, ys + y
        d = away_from[ys, xs]
        meets = d <= touch
        if not meets.any() or float(d.max()) < shortest + 2:
            continue
        # where it meets the symbol, seen from the middle
        mx, my = xs[meets].mean(), ys[meets].mean()
        side = math.degrees(math.atan2(-(my - cy), mx - cx))
        if 15 <= side <= 75:
            corner = 'upper right'
        elif -165 <= side <= -105:
            corner = 'lower left'
        else:
            continue
        points = np.stack([xs, ys], axis=1).astype(np.float64)
        mean = points.mean(axis=0)
        values, vectors = np.linalg.eigh(np.cov((points - mean).T))
        axis = vectors[:, int(np.argmax(values))]
        a = (points - mean) @ axis
        b = (points - mean) @ np.array([-axis[1], axis[0]])
        length, thickness = float(a.max() - a.min()), float(b.max() - b.min())
        # (the slope of the line it runs along, rising to the right, from 0 to 180 degrees)
        slope = math.degrees(math.atan2(-axis[1], axis[0])) % 180
        if length >= 2 * thickness and not low <= slope <= high:
            continue
        reach = float(d.max())
        if corner not in stubs or reach > stubs[corner][1]:
            stubs[corner] = (np.array([mx, my]), reach)
    upper = 'upper right' in stubs
    if len(stubs) < 2:
        return False, upper
    p, q = stubs['upper right'][0], stubs['lower left'][0]
    rise = math.degrees(math.atan2(-(p[1] - q[1]), p[0] - q[0]))
    joining = (p - q) / max(1e-9, float(np.hypot(*(p - q))))
    miss = abs(float((np.array([cx, cy]) - q) @ np.array([-joining[1], joining[0]])))
    return SLASH_SLOPES[0] - 8 <= rise <= SLASH_SLOPES[1] + 8 and miss <= 0.15 * size, upper


def _outline_width(window, outer, contour_length, line_width):
    '''how thick a symbol's outline is drawn, from the ink in a band round its edge'''
    band = outer & ~cv2.erode(outer, _disc(2 * line_width + 3))
    if contour_length <= 0:
        return float(line_width)
    return max(1.0, float((window & band).sum()) / contour_length)


def _dotted(ink, symbol, line_width):
    '''
    Whether a carrier's dot is in the middle of a symbol: a round spot, thicker than the lines are drawn, of ink in a
    symbol left empty, or of white in one filled in solidly (as Pedigree Studio draws it). A slash may run through it.
    Letters written in a symbol are no thicker than lines, and a symbol scribbled in is white between its strokes all
    over, not only in the middle
    '''
    size = symbol['size']
    margin = 2 * line_width + 4
    window, outer, (x0, y0) = _window(ink, symbol, margin)
    inner = cv2.erode(outer, _disc(line_width + 2 + 0.03 * size))
    if not inner.any():
        return False
    cx, cy = symbol['centre'][0] - x0, symbol['centre'][1] - y0
    yy, xx = np.ogrid[:window.shape[0], :window.shape[1]]
    middle = (np.hypot(xx - cx, yy - cy) <= 0.3 * size) & (inner > 0)
    if symbol['filled']:
        spot = ((1 - window) & inner).astype(np.uint8)
        thickness = float(line_width)
    else:
        spot = (window & inner).astype(np.uint8)
        thickness = _outline_width(window, outer, cv2.arcLength(symbol['contour'].reshape(-1, 1, 2), True), line_width)
    if not spot[middle].any():
        return False
    distance = cv2.distanceTransform(spot, cv2.DIST_L2, 5)
    peak = float(distance[middle].max())
    if peak < max(0.85 * thickness, 0.045 * size, 2.0):
        return False
    # the spot itself, without the lines that run into it: what a disc a little smaller than it fits inside
    py, px = np.unravel_index(int(np.argmax(np.where(middle, distance, 0))), distance.shape)
    opened = cv2.morphologyEx(spot, cv2.MORPH_OPEN, _disc(0.7 * peak))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    k = labels[py, px]
    if k == 0:
        return False
    x, y, w, h, area = stats[k]
    extent = max(w, h)
    if not (1.5 * peak <= extent <= min(0.5 * size, 3.5 * peak) and min(w, h) >= 0.6 * extent and
            area >= 0.55 * math.pi * (extent / 2) ** 2):
        return False
    if symbol['filled']:
        # filled in solidly, as Pedigree Studio fills its symbols: all ink but for the dot (a symbol scribbled in has
        # white between its strokes all over)
        rest = (inner > 0) & (cv2.dilate((labels == k).astype(np.uint8), _disc(3)) == 0)
        return bool(rest.any()) and float(window[rest].mean()) >= 0.97
    return True


def _free_ink(ink, symbols, box):
    '''
    The ink apart from the symbols, in a part of the drawing, box (left, top, right, bottom): all but what lies within a
    few pixels of the outline each symbol was found with (where the edge of its ink may be)
    '''
    x0, y0, x1, y1 = box
    covered = np.zeros((y1 - y0, x1 - x0), np.uint8)
    for s in symbols.values():
        bx, by, bw, bh = s['box']
        if bx < x1 + 4 and by < y1 + 4 and bx + bw > x0 - 4 and by + bh > y0 - 4:
            cv2.fillPoly(covered, [s['contour'] - np.array([x0, y0], np.int32)], 1)
    covered = cv2.dilate(covered, _disc(3))
    return (ink[y0:y1, x0:x1] & (1 - covered)).astype(np.uint8)


def _lower_left(ink, symbol):
    '''the part of the drawing where an arrow at a symbol is looked for, below it on the left, as (left, top, right,
    bottom)'''
    size = symbol['size']
    cx, cy = symbol['centre']
    height, width = ink.shape
    return (max(0, int(cx - 2.2 * size)), max(0, int(cy - 0.6 * size)),
            min(width, int(cx + 0.6 * size)), min(height, int(cy + 2.2 * size)))


def _arrow(points, line_width, size):
    '''
    Whether ink is an arrow, rising to the right (from below on the left): a line with a head at the top end, wider than
    the line, in a V that opens back along the line (so it is no wider at its tip than further back); or a line on its
    own, whose head may be hidden by the symbol it points at. Returns where its tip is, which way it points, and
    whether it has a head; or None. points: the ink's (x, y)
    '''
    if len(points) < 10:
        return None
    mean = points.mean(axis=0)
    centred = points - mean
    values, vectors = np.linalg.eigh(np.cov(centred.T))
    axis = vectors[:, int(np.argmax(values))]
    a = centred @ axis
    b = centred @ np.array([-axis[1], axis[0]])
    length = float(a.max() - a.min())
    if length < 0.25 * size or length > 1.6 * size:
        return None
    # how wide the ink is along its length, in short pieces
    pieces = max(6, min(16, int(length / max(2.0, 0.06 * size))))
    edges = np.linspace(a.min(), a.max() + 1e-9, pieces + 1)
    which = np.clip(np.searchsorted(edges, a, side='right') - 1, 0, pieces - 1)
    widths = np.zeros(pieces)
    for j in range(pieces):
        bj = b[which == j]
        if len(bj):
            widths[j] = bj.max() - bj.min() + 1
    head = int(np.argmax(widths))
    widest_line = max(2.5 * line_width, 0.12 * size)
    headed = None
    if head != pieces // 2 or pieces % 2 == 0:
        at_start = head < pieces / 2
        shaft = widths[pieces // 2:] if at_start else widths[:pieces - pieces // 2]
        shaft = shaft[shaft > 0]
        line = float(np.median(shaft)) if len(shaft) else 0.0
        tip_piece, behind = (0, 1) if at_start else (pieces - 1, pieces - 2)
        headed = (0 < line <= widest_line and max(2.0 * line, 0.1 * size) <= widths[head] <= 0.6 * size and
                  (head != tip_piece or widths[behind] >= 0.8 * widths[head]))
    if headed:
        point = -axis if at_start else axis
        middle = float(np.median(b[which == (pieces - 1 if at_start else 0)]))
        tip_a = float(a.min() if at_start else a.max())
    elif widths[1:-1].max() <= max(2.5 * line_width, 0.15 * size):
        # a line on its own (with what can be seen of a head hidden by the symbol, at its end): it points up to the right
        point = axis if axis[0] > 0 else -axis
        middle = float(np.median(b))
        tip_a = float(a.max() if point is axis else a.min())
    else:
        return None
    slope = math.degrees(math.atan2(-point[1], point[0]))
    if not ARROW_SLOPES[0] <= slope <= ARROW_SLOPES[1]:
        return None
    tip = mean + tip_a * axis + middle * np.array([-axis[1], axis[0]])
    return tip, point, bool(headed)


def _three_ways(ink, xs, ys, radii):
    '''
    Of the points (xs, ys), those round which ink runs three ways, as from the tip of an arrow's head: where circles at
    two of the radii next to each other each cross the ink in three arcs. The others can't be the tip, and are looked at
    no further. Returns each point kept, (x, y, arcs), with, for each radius, the middle of each arc and how wide it is,
    in degrees (anticlockwise from the right, as the picture is seen), or None where the circle doesn't cross the ink in
    three arcs. All the points are looked round at once, as looking round each in turn is slow in a drawing with much
    writing in it.
    '''
    if len(radii) < 2 or not len(xs):
        return []
    step = 3
    angles = np.arange(0, 360, step)
    ons, three = [], []
    for radius in radii:
        sx = np.round(xs[:, None] + radius * np.cos(np.radians(angles))[None, :]).astype(np.int64)
        sy = np.round(ys[:, None] - radius * np.sin(np.radians(angles))[None, :]).astype(np.int64)
        inside = (sx >= 0) & (sy >= 0) & (sx < ink.shape[1]) & (sy < ink.shape[0])
        on = np.zeros(sx.shape, bool)
        on[inside] = ink[sy[inside], sx[inside]] > 0
        ons.append(on)
        # (the arcs, each counted where it starts, going round)
        three.append((on & ~np.roll(on, 1, axis=1)).sum(axis=1) == 3)
    three = np.stack(three, axis=1)
    kept = np.nonzero((three[:, :-1] & three[:, 1:]).any(axis=1))[0]
    arcs = {point: [None] * len(radii) for point in kept.tolist()}
    for r, on in enumerate(ons):
        rows = kept[three[kept, r]]
        if not len(rows):
            continue
        # (each circle from where it is first off the ink, so no arc is cut in two: each arc runs from k up to j)
        first = np.argmin(on[rows], axis=1)
        turned = on[rows[:, None], (first[:, None] + np.arange(len(angles))[None, :]) % len(angles)]
        edges = np.diff(np.pad(turned.astype(np.int8), ((0, 0), (1, 1))), axis=1)
        k = np.nonzero(edges == 1)[1].reshape(-1, 3)
        j = np.nonzero(edges == -1)[1].reshape(-1, 3)
        middles = (angles[first][:, None] + step * (k + j - 1) / 2) % 360
        widths = step * (j - k)
        for row, middle, width in zip(rows.tolist(), middles, widths):
            arcs[row][r] = list(zip(middle, width))
    return [(xs[point], ys[point], arcs[point]) for point in kept.tolist()]


def _runs_straight(ink, x, y, angle, start, end, line_width):
    '''
    Whether ink runs in a straight line from start to end pixels away from (x, y), about the way angle points (in
    degrees, as _arcs measures them, give or take a few), with hardly a gap, near enough to the line for a stroke drawn
    by hand
    '''
    t = np.arange(start, end + 0.5, 1.5)
    reach = max(2.0, 0.5 * line_width + 1)
    across = np.arange(-reach, reach + 0.5, 1.0)
    for turn in (0, -4, 4, -8, 8):
        a = math.radians(angle + turn)
        ux, uy = math.cos(a), -math.sin(a)
        xs = np.round(x + ux * t[:, None] - uy * across[None, :]).astype(np.int64)
        ys = np.round(y + uy * t[:, None] + ux * across[None, :]).astype(np.int64)
        inside = (xs >= 0) & (ys >= 0) & (xs < ink.shape[1]) & (ys < ink.shape[0])
        on = np.zeros(xs.shape, bool)
        on[inside] = ink[ys[inside], xs[inside]] > 0
        if float(on.any(axis=1).mean()) >= 0.9:
            return True
    return False


def _turn(a, b):
    '''the angle from a to b, in degrees, between -180 and 180'''
    return (b - a + 180) % 360 - 180


def _arrowhead(free, origin, symbol, line_width):
    '''
    Whether the head of an arrow points at a symbol from below on the left, where the arrow's line may run into other
    lines further on, as a line drawn down to children from a couple: a point near the symbol, on its lower left, from
    which three straight strokes run away from the symbol, the line straight on away from it and running on well past
    the head, and the two sides of the head either side of it, much alike. Found by looking round each point of the ink
    there (thinned to a line), at a few distances: the strokes of the letters of a name or an age written under a
    symbol are too short and too crooked to pass for these.

    free: the ink apart from the symbols, in the part of the drawing below the symbol on the left (_lower_left), whose
    top left corner is at origin
    '''
    from .lines import thin
    size = symbol['size']
    cx, cy = symbol['centre']
    ox, oy = origin
    # (the head is within the symbol's size of its middle)
    x0, y0 = max(0, int(cx - 1.3 * size) - ox), max(0, int(cy - 0.2 * size) - oy)
    x1, y1 = min(free.shape[1], int(cx + 0.2 * size) - ox), min(free.shape[0], int(cy + 1.3 * size) - oy)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return False
    window = free[y0:y1, x0:x1]
    if not window.any():
        return False
    x0, y0 = x0 + ox, y0 + oy
    skeleton = thin(window)
    ys, xs = np.nonzero(skeleton)
    if not len(xs):
        return False
    contour = symbol['contour'].reshape(-1, 1, 2).astype(np.float32)
    # (looked round in the whole of the part below on the left, as the arrow's line runs on out of this window)
    thick = cv2.dilate(free, _disc(1))
    # the three strokes are seen at two distances from the point next to each other: far enough from it to see them
    # apart, however thick the pen, and near enough not to pass the end of a short head, as Pedigree Studio draws it
    radii = [radius for radius in (r * size for r in (0.06, 0.08, 0.1, 0.12, 0.14)) if radius >= 1.8 * line_width + 2]
    fx, fy = xs[::2] + (x0 - ox), ys[::2] + (y0 - oy)
    # (first, all at once and with a little to spare, the points on the symbol's lower left and near it, as each point
    # must be below: so not the writing straight under the symbol, nor the lines further off)
    sides = np.degrees(np.arctan2(-(fy + oy - cy), fx + ox - cx))
    keep = (sides >= -171) & (sides <= -99)
    bx, by, bw, bh = symbol['box']
    if bx >= ox and by >= oy and bx + bw <= ox + free.shape[1] and by + bh <= oy + free.shape[0]:
        filled = np.zeros(free.shape, np.uint8)
        cv2.fillPoly(filled, [symbol['contour'] - np.array([ox, oy], np.int32)], 1)
        off = cv2.distanceTransform(1 - filled, cv2.DIST_L2, 5)
        keep &= off[fy, fx] <= 0.52 * size + 3
    points = _three_ways(thick, fx[keep], fy[keep], radii)
    for x, y, arcs_at in points:
        px, py = float(x + ox), float(y + oy)
        away = math.degrees(math.atan2(-(py - cy), px - cx))
        if not -170 <= away <= -100:
            continue
        if -cv2.pointPolygonTest(contour, (px, py), True) > 0.5 * size:
            continue
        # the three strokes, at each distance: straight, so the same ways at both
        seen = []
        for radius, arcs in zip(radii, arcs_at):
            if arcs is None or any(w * math.pi / 180 * radius > 3 * line_width + 4 for _, w in arcs):
                seen.append(None)
                continue
            seen.append(sorted(_turn(away, a) for a, _ in arcs))
        for near, far in zip(seen, seen[1:]):
            if near is None or far is None or any(abs(a - b) > 15 for a, b in zip(near, far)):
                continue
            left, middle, right = far
            # the line straight on away from the symbol, and the sides of the head either side of it, much alike
            if not (abs(middle) <= 35 and 15 <= middle - left <= 80 and 15 <= right - middle <= 80 and
                    abs((middle - left) - (right - middle)) <= 30):
                continue
            # and the line runs on from the head, straight and unbroken, well past it (where it may cross another
            # line): the strokes of letters are too short, and a word has gaps between its letters
            line = (away + middle) % 360
            if _runs_straight(thick, x, y, line, 0.15 * size, 0.35 * size, line_width):
                return True
    return False


def _runs_on(ink, symbol, tip, point, line_width):
    '''
    Whether a line that ends at a symbol runs on into it: whether there is ink along most of the way on from its end,
    inside the symbol's outline, for a quarter of the symbol's size (in a symbol filled in, there always is)
    '''
    if symbol['filled']:
        return False
    size = symbol['size']
    contour = symbol['contour'].reshape(-1, 1, 2).astype(np.float32)
    hits = total = 0
    # (from just inside the outline, past its own ink)
    for t in np.arange(0, 0.6 * size, 1.0):
        x, y = tip[0] + point[0] * t, tip[1] + point[1] * t
        if cv2.pointPolygonTest(contour, (float(x), float(y)), True) < line_width + 3:
            continue
        total += 1
        xi, yi = int(round(x)), int(round(y))
        r = int(round(0.04 * size)) + 1
        patch = ink[max(0, yi - r):yi + r + 1, max(0, xi - r):xi + r + 1]
        hits += bool(patch.any())
        if total >= 0.25 * size:
            break
    return total >= 0.1 * size and hits >= 0.5 * total


def _proband(ink, symbol, symbols, line_width):
    '''
    Whether an arrow points at a symbol, in the part of the drawing below it on the left: a piece of ink apart from the
    symbols shaped as an arrow (_arrow), whose line runs on to the middle of the symbol, not far past its tip (an arrow
    whose head can't be seen must end at the symbol's lower left, and the symbol must have no slash, which such a line
    could be the end of); or the head of an arrow whose line runs into other lines further on (_arrowhead)
    '''
    box = _lower_left(ink, symbol)
    x0, y0, x1, y1 = box
    if x1 - x0 < 3 or y1 - y0 < 3:
        return False
    free = _free_ink(ink, symbols, box)
    if not free.any():
        return False
    size = symbol['size']
    contour = symbol['contour'].reshape(-1, 1, 2).astype(np.float32)
    height, width = ink.shape
    # (the strokes of an arrow drawn by hand may not quite touch: its head drawn apart from its line)
    joined = cv2.dilate(free, _disc(max(1.0, 0.03 * size)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    for k in range(1, n):
        x, y, w, h, _ = stats[k]
        # (not a part of a line that runs on out of this part of the drawing)
        if (x == 0 and x0 > 0) or (y == 0 and y0 > 0) or (x + w >= x1 - x0 and x1 < width) or \
                (y + h >= y1 - y0 and y1 < height):
            continue
        if not 0.25 * size <= max(w, h) <= 1.6 * size:
            continue
        ys, xs = np.nonzero((labels[y:y + h, x:x + w] == k) & (free[y:y + h, x:x + w] > 0))
        if len(xs) < 10:
            continue
        points = np.stack([xs + x + x0, ys + y + y0], axis=1).astype(np.float64)
        arrow = _arrow(points, line_width, size)
        if arrow is None:
            continue
        tip, point, headed = arrow
        to_middle = np.array(symbol['centre']) - tip
        ahead = float(to_middle @ point)
        aside = abs(float(to_middle[0] * point[1] - to_middle[1] * point[0]))
        off = -cv2.pointPolygonTest(contour, (float(tip[0]), float(tip[1])), True)
        # (the end of a slash, where it runs out of the corner of a symbol beside the corner of its outline, may look
        # like an arrow at the symbol, but an arrow at someone who has died is drawn clear of the symbol)
        ok = 0 < ahead <= 1.5 * size and aside <= 0.45 * size and (off >= 0.1 * size or not symbol.get('slashed'))
        if ok and not headed:
            # (a line on its own ends at the symbol's lower left, on it or a few pixels off it, and doesn't run on
            # into it, as a slash would)
            side = math.degrees(math.atan2(-(tip[1] - symbol['centre'][1]), tip[0] - symbol['centre'][0]))
            ok = (off <= 6 and -170 <= side <= -100 and aside <= 0.25 * size and not symbol.get('slashed')
                  and not symbol.get('upper_stub') and not _runs_on(ink, symbol, tip, point, line_width))
        if ok:
            return True
    return _arrowhead(free, (x0, y0), symbol, line_width)


def read_marks(binary_img, people, line_width):
    '''
    The marks on each person's symbol: whether a slash through it says they have died, an arrow says they are the
    proband, and a dot says they are a carrier.

    PARAMETERS:
    -----------
    binary_img: the drawing in black and white, 0 where there is ink
    people: id -> the person, as pedigree_processing finds them: 'node_coords' (the box their symbol was found in, x, y,
        w, h), 'Phenotype' (2 if it is filled in), 'shape', and, for a sketch, 'outline' (the symbol, outline and all)
    line_width: how wide the drawing's lines are, in pixels

    RETURN:
    -------
    id -> {'deceased': bool, 'proband': bool, 'carrier': bool}
    '''
    ink = (binary_img == 0).astype(np.uint8)
    line_width = max(1, int(round(line_width)))
    symbols = {pid: _symbol(person, line_width) for pid, person in people.items()}
    for symbol in symbols.values():
        slashed, upper_stub = _slashed(ink, symbol, line_width)
        symbol['slashed'], symbol['upper_stub'] = bool(slashed), bool(upper_stub)
    return {pid: {'deceased': symbol['slashed'], 'proband': bool(_proband(ink, symbol, symbols, line_width)),
                  'carrier': bool(_dotted(ink, symbol, line_width))} for pid, symbol in symbols.items()}
