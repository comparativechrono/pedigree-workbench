'''
Telling a symbol's shape, and finding the symbols of a pedigree sketched by hand.

A symbol's sex is read from the way its outline turns. Going round a square, the outline runs level or upright almost
all the way; round a diamond, it runs at 45 degrees; round a circle, it runs every way in turn; and round a triangle, the
symbol of a pregnancy loss, it runs three ways. This tells shapes apart however roughly they are drawn: sides that
wobble, corners rounded off, and a shape a little squashed or tilted.

The symbols of a sketch are found as the white inside an outline that may not quite close, and as patches filled in,
solidly or by scribbling, of any size.
'''
import math

import cv2
import numpy as np

SQUARE, CIRCLE, DIAMOND, TRIANGLE = 'square', 'circle', 'diamond', 'triangle'
_OUTLINE_HULL = True
#: the sex a shape stands for, as in a PED file: 1 male, 2 female, 0 unknown (a pregnancy loss's sex is unknown, as
#: studio2ped writes it)
SEX = {SQUARE: 1, CIRCLE: 2, DIAMOND: 0, TRIANGLE: 0}
#: the smallest a symbol drawn by hand may be, as a share of the typical symbol's size
SMALLEST = 0.4
#: how much of the edge of a symbol filled in by hand must be ink
FILLED_EDGE = 0.8


def turning(contour):
    '''
    How an outline turns: the strength of its four-fold and three-fold patterns of direction (from 0, none, to 1), and
    the angle of the four-fold one in degrees (0 when the sides are level and upright, 45 for a diamond's). The outline
    is followed in even steps, and its direction measured across a 24th of the way round, which smooths over the steps
    of the pixels and the wobbles of a hand.
    '''
    pts = contour.reshape(-1, 2).astype(np.float64)
    if len(pts) < 4:
        return 0.0, 0.0, 0.0
    closed = np.vstack([pts, pts[:1]])
    seg = np.diff(closed, axis=0)
    s = np.concatenate([[0], np.cumsum(np.hypot(seg[:, 0], seg[:, 1]))])
    total = s[-1]
    if total <= 0:
        return 0.0, 0.0, 0.0
    n = max(24, int(total / 2))
    t = np.linspace(0, total, n, endpoint=False)
    x, y = np.interp(t, s, closed[:, 0]), np.interp(t, s, closed[:, 1])
    k = max(2, n // 48)
    theta = np.arctan2(np.roll(y, -k) - np.roll(y, k), np.roll(x, -k) - np.roll(x, k))
    four, three = np.exp(4j * theta).mean(), np.exp(6j * theta).mean()
    return float(abs(four)), float(math.degrees(np.angle(four) / 4)), float(abs(three))


def shape_of(contour):
    '''A symbol's shape from its outline: SQUARE, CIRCLE, DIAMOND or TRIANGLE (see turning)'''
    four, angle, three = turning(contour)
    if four >= 0.3 and four >= 0.6 * three:
        return SQUARE if abs(angle) < 22.5 else DIAMOND
    if three >= 0.45:
        return TRIANGLE
    return CIRCLE


def twins_bar(contour, ink, size):
    '''
    Whether a triangle is not a symbol but the space between the two lines to identical twins and the bar across
    them: its two sides run on past its lower corners, down to the twins, where a triangle drawn as a symbol (a
    pregnancy loss) ends at its corners. Read as a symbol, it would be someone of unknown sex between the twins.

    PARAMETERS:
    -----------
    contour: the triangle's outline (of the white inside it, or of the patch, if filled)
    ink: the drawing, not 0 where there is ink
    size: the size of a typical symbol in the drawing, in pixels
    '''
    pts = contour.reshape(-1, 2).astype(np.float64)
    if len(pts) < 3:
        return False
    _, triangle = cv2.minEnclosingTriangle(pts.astype(np.float32).reshape(-1, 1, 2))
    corners = triangle.reshape(-1, 2)
    if len(corners) != 3:
        return False
    apex = corners[np.argmin(corners[:, 1])]
    lower = [c for c in corners if not np.array_equal(c, apex)]
    if len(lower) != 2:
        return False
    h, w = ink.shape[:2]
    on = 0
    for corner in lower:
        d = corner - apex
        n = float(np.hypot(*d))
        if n == 0:
            return False
        d = d / n
        hits = total = 0
        for t in np.linspace(0.12 * size, 0.35 * size, 12):
            x, y = corner + d * t
            xi, yi = int(round(x)), int(round(y))
            if not (2 <= xi < w - 2 and 2 <= yi < h - 2):
                continue
            total += 1
            hits += bool(np.any(ink[yi - 2:yi + 3, xi - 2:xi + 3]))
        if total and hits >= 0.6 * total:
            on += 1
    return on == 2


def _lines_down_both_ways(c, ink, size):
    '''
    Whether two lines leave a patch going down and outwards, one to each side, as the lines to twins leave the point
    they share: with a bold pen, the space between those lines and the bar of identical twins fills in, when the gaps
    of scribbles are closed, and looks like a small symbol filled in
    '''
    pts = c['contour'].reshape(-1, 2).astype(np.float64)
    cx, cy = pts.mean(axis=0)
    region = np.zeros(ink.shape, np.uint8)
    cv2.drawContours(region, [c['contour']], -1, 1, -1)
    h, w = ink.shape
    found = 0
    for angles in (range(20, 75, 5), range(105, 160, 5)):
        best = 0.0
        for a in angles:
            dx, dy = math.cos(math.radians(a)), math.sin(math.radians(a))
            t, start, gap, run = 0.0, None, 0, 0.0
            while t < 1.5 * size:
                x, y = int(round(cx + dx * t)), int(round(cy + dy * t))
                if not (0 <= x < w and 0 <= y < h):
                    break
                if start is None:
                    if not region[y, x]:
                        start = t
                elif ink[y, x]:
                    gap, run = 0, t - start
                else:
                    gap += 1
                    if gap > 3:
                        break
                t += 1
            best = max(best, run)
        found += best >= 0.25 * size
    return found == 2


# ---------------------------------------------------------------------------------------------------------------------
# finding the symbols of a sketch
# ---------------------------------------------------------------------------------------------------------------------
def _disc_open(mask, radius):
    '''the parts of a 0/1 mask that a disc of the given radius fits inside (a morphological opening)'''
    if radius <= 0:
        return mask.copy()
    inside = cv2.distanceTransform(mask, cv2.DIST_L2, 5) > radius
    near = cv2.distanceTransform((~inside).astype(np.uint8), cv2.DIST_L2, 5) <= radius
    return (near & (mask > 0)).astype(np.uint8)


def _disc_close(mask, radius):
    '''a 0/1 mask with gaps narrower than twice the radius filled in (a morphological closing)'''
    if radius <= 0:
        return mask.copy()
    grown = cv2.distanceTransform((mask == 0).astype(np.uint8), cv2.DIST_L2, 5) <= radius
    return (cv2.distanceTransform(grown.astype(np.uint8), cv2.DIST_L2, 5) > radius).astype(np.uint8)


def _regions(mask, min_area):
    '''the connected parts of a 0/1 mask, as (label image, stats), leaving out any touching the edge of the picture'''
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
    keep = []
    h, w = mask.shape
    for k in range(1, count):
        x, y, bw, bh, area = stats[k]
        if area < min_area or x == 0 or y == 0 or x + bw >= w or y + bh >= h:
            continue
        keep.append(k)
    return labels, stats, keep


def _measure(contour, how, gap, pixels=None):
    '''
    A symbol's measurements, from its outline (the edge of the white inside it, or of the patch filled in) and how many
    pixels it covers, which is less than the outline holds when it has a hole in it
    '''
    outline_area = cv2.contourArea(contour)
    area = float(pixels) if pixels is not None else outline_area
    if area <= 0 or outline_area <= 0 or len(contour) < 5:
        return None
    hull = cv2.convexHull(contour)
    (_, _), (rw, rh), _ = cv2.minAreaRect(contour)
    if min(rw, rh) <= 0:
        return None
    x, y, w, h = cv2.boundingRect(contour)
    return {'box': (x, y, w, h), 'contour': contour, 'shape_contour': contour, 'area': area,
            'solidity': area / max(cv2.contourArea(hull), 1e-9), 'aspect': max(rw, rh) / min(rw, rh),
            'rect_fill': outline_area / (rw * rh), 'how': how, 'gap': gap, 'size': max(w, h)}


def _reshape(c, contour):
    '''a candidate whose shape is told from another outline'''
    if len(contour) >= 3 and cv2.contourArea(contour) > 0:
        c['shape_contour'] = contour
    return c


def _outline_hull(c, ink, stroke):
    '''
    The hull round a symbol's outline, for telling its shape when the white inside it was found in pieces or through
    a gap: a slash from corner to corner leaves no white in those corners, and white found by a disc is rounded off in
    every corner, but the outline's ink is there
    '''
    x, y, w, h = c['box']
    band = stroke + 2 + 0.5 * c['gap']
    m = int(math.ceil(band)) + 2
    x0, y0 = max(0, x - m), max(0, y - m)
    x1, y1 = min(ink.shape[1], x + w + m), min(ink.shape[0], y + h + m)
    region = np.zeros((y1 - y0, x1 - x0), np.uint8)
    parts = c.get('parts_contours') or [c['contour']]
    cv2.drawContours(region, [part - np.array([x0, y0], dtype=part.dtype) for part in parts], -1, 1, -1)
    size = 2 * int(math.ceil(band)) + 1
    near = cv2.dilate(region, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    ys, xs = np.nonzero((ink[y0:y1, x0:x1] & near) | region)
    if len(xs) < 5:
        return c['contour']
    points = np.stack([xs + x0, ys + y0], axis=1).astype(np.int32).reshape(-1, 1, 2)
    return cv2.convexHull(points)


def _outline_of(region):
    cs, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return max(cs, key=cv2.contourArea) if cs else None


def _enclosed(contour, near_ink):
    '''how much of an outline runs along ink: 1 for the white inside a closed outline, less where it was left open'''
    pts = contour.reshape(-1, 2)
    h, w = near_ink.shape
    xs, ys = np.clip(pts[:, 0], 0, w - 1), np.clip(pts[:, 1], 0, h - 1)
    return float(near_ink[ys, xs].mean()) if len(pts) else 0.0


def _overlap(a, b):
    '''how much of the smaller of two boxes (x, y, w, h) the other covers'''
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    w = min(ax + aw, bx + bw) - max(ax, bx)
    h = min(ay + ah, by + bh) - max(ay, by)
    if w <= 0 or h <= 0:
        return 0.0
    return w * h / max(min(aw * ah, bw * bh), 1)


def _thick_parts(patch):
    '''
    The parts of a patch of closed-up ink much thicker than a line, the largest first, and any others nearly as
    large and well apart from it: closing the gaps in a scribble also closes the gap between the symbol and a line
    drawn close by it, such as the line to a twin, and between two symbols filled in that lines run close between, as
    twins' do. What is much thinner than the symbols is opened away again. (Parts close together are pieces of one
    symbol, scribbled in unevenly, of which the largest is taken.) The patch itself, if nothing is left.
    '''
    bh, bw = patch.shape
    trimmed = _disc_open(np.pad(patch, 1), 0.15 * min(bw, bh))[1:-1, 1:-1]
    if not trimmed.any():
        return [patch]
    n, parts, stats, _ = cv2.connectedComponentsWithStats(trimmed, connectivity=4)
    order = sorted(range(1, n), key=lambda j: -stats[j, cv2.CC_STAT_AREA])
    first = order[0]

    def apart(j):
        (ax, ay, aw, ah), (bx, by, bw_, bh_) = stats[first, :4], stats[j, :4]
        gap = max(ax - (bx + bw_), bx - (ax + aw), ay - (by + bh_), by - (ay + ah))
        return gap >= 0.25 * min(max(aw, ah), max(bw_, bh_))
    keep = [first] + [j for j in order[1:] if stats[j, cv2.CC_STAT_AREA] >= 0.25 * stats[first, cv2.CC_STAT_AREA]
                      and apart(j)]
    return [(parts == j).astype(np.uint8) for j in keep]


def _solid(patch, ink, stroke):
    '''
    The symbols filled in solidly in a patch of closed-up ink, the largest first, if the patch is solid ink: nearly all
    of the ink in it is thicker than a line, and covers most of it. None if not, as for a symbol filled in by
    scribbling or hatching, whose strokes are as thin as lines. (Solid patches much smaller than the largest, as
    where lines meet, are left out.)
    '''
    raw = (ink & patch).astype(np.uint8)
    total = int(raw.sum())
    if not total:
        return None
    radius = 1.7 * stroke + 1
    inside = cv2.distanceTransform(raw, cv2.DIST_L2, 5) > radius
    # (the ink a disc fits in, with the corners that the disc rounds off, but not the lines that meet it)
    thick = ((cv2.distanceTransform((~inside).astype(np.uint8), cv2.DIST_L2, 5) <= 1.5 * radius) & (raw > 0)).astype(np.uint8)
    if thick.sum() < 0.95 * total or thick.sum() < 0.8 * patch.sum():
        return None
    n, parts, stats, _ = cv2.connectedComponentsWithStats(thick, connectivity=4)
    if n < 2:
        return None
    order = sorted(range(1, n), key=lambda j: -stats[j, cv2.CC_STAT_AREA])
    keep = [j for j in order if stats[j, cv2.CC_STAT_AREA] >= 0.25 * stats[order[0], cv2.CC_STAT_AREA]]
    return [(parts == j).astype(np.uint8) for j in keep]


def _iou(a, b):
    '''how much two boxes (x, y, w, h) overlap, as a share of the two together'''
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    w = min(ax + aw, bx + bw) - max(ax, bx)
    h = min(ay + ah, by + bh) - max(ay, by)
    if w <= 0 or h <= 0:
        return 0.0
    return w * h / (aw * ah + bw * bh - w * h)


def _same_box(a, b):
    '''whether two boxes (x, y, w, h) are much the same: the box of the same piece of white, found by discs of two sizes'''
    return _iou(a, b) > 0.7


def _join(pieces, largest=None):
    '''
    Joins the pieces of white inside one outline: a slash through the symbol of someone who has died cuts it in two,
    and so do the lines of a symbol shaded with a few strokes. Pieces whose boxes overlap a good deal are one symbol,
    whose outline is the hull round them all. A piece of white larger across than largest is no symbol, nor a piece of
    one: a symbol's box may lie inside the box of the white between a family's lines round it, but it isn't a piece of
    that white.
    '''
    joined = []
    for piece in sorted(pieces, key=lambda c: -c['area']):
        for kept in joined:
            if _overlap(kept['box'], piece['box']) > 0.3 and (largest is None or kept['size'] <= largest):
                kept['parts'].append(piece)
                break
        else:
            joined.append(dict(piece, parts=[piece]))
    out = []
    for c in joined:
        if len(c['parts']) > 1:
            hull = cv2.convexHull(np.vstack([part['contour'] for part in c['parts']]))
            m = _measure(hull, c['how'], c['gap'], pixels=sum(part['area'] for part in c['parts']))
            if m is None:
                continue
            # (the pieces fill the hull but for the lines between them)
            m['solidity'] = min(1.0, m['solidity'] + 0.15)
            m['enclosed'] = min(part.get('enclosed', 1.0) for part in c['parts'])
            m['pieces'] = len(c['parts'])
            m['parts_contours'] = [part['contour'] for part in c['parts']]
            m['parts_boxes'] = [part['box'] for part in c['parts']]
            c = m
        out.append(c)
    return out


def _under_a_line(c, ink, typical):
    '''
    Whether a patch of white is the space under (or over, or beside) a line that runs on past it both ways, as the
    space between the line over a family's children, the line down to a child and the child's symbol is: a side of a
    symbol ends at its corners
    '''
    x, y, w, h = c['box']
    H, W = ink.shape
    band = max(2, int(round(0.06 * typical)))
    far, near = int(round(0.3 * typical)), int(round(0.05 * typical))

    def runs(x0, x1, y0, y1, across):
        x0, x1, y0, y1 = max(0, x0), min(W, x1), max(0, y0), min(H, y1)
        if x1 - x0 < 2 or y1 - y0 < 2:
            return False
        window = ink[y0:y1, x0:x1]
        # how much of the way along there is ink in the band
        along = window.any(axis=0) if across == 'rows' else window.any(axis=1)
        return float(along.mean()) >= 0.6

    for edge in (y, y + h):
        if runs(x - far, x - near, edge - band, edge + band, 'rows') and runs(x + w + near, x + w + far, edge - band, edge + band, 'rows'):
            return True
    for edge in (x, x + w):
        if runs(edge - band, edge + band, y - far, y - near, 'cols') and runs(edge - band, edge + band, y + h + near, y + h + far, 'cols'):
            return True
    return False


def _ellipse_misfit(contour):
    '''how far an outline strays from the ellipse fitted to it: the root mean square of its distance from it, as a
    share of the ellipse's radius'''
    pts = contour.reshape(-1, 2).astype(np.float64)
    (cx, cy), (a, b), angle = cv2.fitEllipse(pts.astype(np.float32))
    if a <= 0 or b <= 0:
        return 1.0
    t = math.radians(angle)
    x, y = pts[:, 0] - cx, pts[:, 1] - cy
    u = (x * math.cos(t) + y * math.sin(t)) / (a / 2)
    v = (-x * math.sin(t) + y * math.cos(t)) / (b / 2)
    return float(np.sqrt(np.mean((np.hypot(u, v) - 1) ** 2)))


def _well_shaped(c, strict):
    '''
    Whether a candidate looks like a symbol: compact, and as near the shape it is read as as a hand would draw it. A
    patch of white that lines happen to close round, as between a couple's line, the line down from it and a symbol,
    is seldom as round as a circle, as square as a square, or as pointed as a diamond. With strict, as for white found
    only by closing a gap, the shape must be nearer still.
    '''
    # (a patch filled in by hand is no longer than a symbol drawn by hand is: where a scribble's gaps are closed, the
    # gaps between lines close by are closed too, and they are long and thin)
    if c['aspect'] > (1.5 if c['how'] == 'filled' else 1.6 if strict else 1.8) or c['solidity'] < (0.85 if strict else 0.75):
        return False
    if c['how'] == 'outline' and c.get('enclosed', 1.0) < (0.8 if strict else 0.75):
        return False
    # a gap closed by a disc large for the symbol is more likely the space between other things
    if c['gap'] > 0.2 * c['size'] + 1:
        return False
    shape = shape_of(c['shape_contour'])
    c['shape'] = shape
    if shape == CIRCLE:
        return abs(c['rect_fill'] - math.pi / 4) < (0.07 if strict else 0.12) and \
            _ellipse_misfit(c['contour']) < (0.06 if strict else 0.1)
    if shape in (SQUARE, DIAMOND):
        return c['rect_fill'] > (0.82 if strict else 0.75)
    return abs(c['rect_fill'] - 0.5) < (0.12 if strict else 0.18)


def _outlines(white, distance, near_ink, radii, min_side, stroke, largest=None):
    '''the white inside outlines, found by discs of each radius (see find_sketched_symbols); largest: see _join'''
    found = []
    for radius in radii:
        core = (distance > radius).astype(np.uint8) if radius else white
        count, labels, stats, _ = cv2.connectedComponentsWithStats(core, connectivity=4)
        h, w = white.shape
        pieces = []
        for k in range(1, count):
            x, y, bw, bh, area = stats[k]
            if area < 16 or x == 0 or y == 0 or x + bw >= w or y + bh >= h or max(bw, bh) + 2 * radius + 2 * stroke < min_side:
                continue
            # (worked on in a window round the piece, which is quick)
            pad = int(radius) + 2
            x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(w, x + bw + pad), min(h, y + bh + pad)
            part = (labels[y0:y1, x0:x1] == k).astype(np.uint8)
            if radius:
                # the white inside, out to the outline: as far as the disc reaches from where it fits
                part = ((cv2.distanceTransform((1 - part).astype(np.uint8), cv2.DIST_L2, 5) <= radius) &
                        (white[y0:y1, x0:x1] > 0)).astype(np.uint8)
            contour = _outline_of(part)
            if contour is None:
                continue
            contour = contour + np.array([x0, y0], dtype=contour.dtype)
            c = _measure(contour, 'outline', radius, pixels=int(part.sum()))
            if c:
                c['enclosed'] = _enclosed(contour, near_ink)
                pieces.append(c)
        for c in _join(pieces, largest):
            # (the same symbol is found again by larger discs: it is kept as the smallest found it, unless only a piece
            # of it was found before. A symbol cut in two by a slash, whose outline has a gap on one side of the slash,
            # is found whole only by a disc that closes the gap, when the white each side of the slash is joined. The
            # same: much the same box, not a box inside a larger one, as a symbol's is inside the box of the white
            # between the lines round it, which a smaller disc found through a gap in the symbol's outline)
            same = [d for d in found if _iou(c['box'], d['box']) > 0.5]
            if same and c.get('pieces', 1) > 1 and all(d.get('pieces', 1) < c['pieces'] and
                                                       any(_same_box(d['box'], b) for b in c['parts_boxes'])
                                                       for d in same):
                found = [d for d in found if not any(d is e for e in same)]
                same = []
            if not same:
                if _OUTLINE_HULL and (c.get('pieces', 1) > 1 or c['gap'] > 0):
                    _reshape(c, _outline_hull(c, 1 - white, stroke))
                found.append(c)
    return found


def find_sketched_symbols(ink, stroke):
    '''
    The symbols of a pedigree sketched by hand: outlines that may not quite close, of unequal sizes, and symbols filled
    in solidly or by scribbling.

    The white inside an outline is found even where the outline doesn't quite close. A disc is rolled through the
    white of the drawing: where it can't get in through a gap from outside, the white inside is found as it is inside a
    closed outline. Larger discs close larger gaps, but only fit inside larger symbols, so they are sized to the
    symbols found first, inside outlines that close or nearly so. Filled symbols are found by closing the gaps between
    the strokes of a scribble, and then opening away the lines, which are much narrower than a filled symbol.

    PARAMETERS:
    -----------
    ink: 0/1 uint8 array, 1 where there is ink, at a size where a typical symbol is 60 to 200 pixels across
    stroke: the width of the drawing's lines, in pixels

    RETURN:
    -------
    a list of symbols, each a dict with 'box' (x, y, w, h), 'contour', 'shape' (SQUARE, CIRCLE, DIAMOND or TRIANGLE)
    and 'filled' (bool), from the top left; and the typical size of a symbol, in pixels (0 if none was found)
    '''
    ink = (ink > 0).astype(np.uint8)
    stroke = max(1, int(round(stroke)))
    min_side = 6 * stroke
    near_ink = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * stroke + 3, 2 * stroke + 3)))

    # bits of text, such as the numbers Pedigree Studio writes over its symbols, close in the white beside them, as
    # if it were the inside of a symbol: anything far smaller than the symbols found inside closed outlines is taken
    # out first
    white = (1 - ink).astype(np.uint8)
    first = [c for c in _outlines(white, None, near_ink, (0,), min_side, stroke) if _well_shaped(c, strict=False)]
    guess = float(np.median([c['size'] + 2 * stroke for c in first])) if first else 25.0 * stroke
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    small = np.flatnonzero(np.maximum(stats[:, 2], stats[:, 3]) < min(0.25 * guess, 8 * stroke))
    small = small[small > 0]
    if len(small):
        ink = ink.copy()
        ink[np.isin(labels, small)] = 0
        near_ink = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * stroke + 3, 2 * stroke + 3)))

    filled = []
    solid = _disc_open(_disc_close(ink, 1.6 * stroke + 1), 1.7 * stroke + 1)

    def as_filled(patch, x, y):
        '''the symbol filled in that a patch of closed-up ink at (x, y) is, or None'''
        bh, bw = patch.shape
        # (what is much thinner than the symbol, as a line drawn close by it, is opened away)
        patch = _thick_parts(patch)[0]
        # (a symbol filled in solidly, as Pedigree Studio fills its symbols, is its own ink: closing the gaps, which a
        # scribble needs, also closes in the white between the symbol and the lines drawn close to it, as between the
        # line to a twin, the bar across the twins' lines and the top of the twin's symbol)
        solid_ink = _solid(patch, ink[y:y + bh, x:x + bw], stroke)
        if solid_ink:
            patch = solid_ink[0]
        # (closing gaps also fills the white inside a small outline, or between lines close together: a patch filled
        # in has ink in it)
        inside = cv2.erode(patch, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * stroke + 3, 2 * stroke + 3)))
        if not inside.any():
            inside = np.zeros_like(patch)
            inside[bh // 3:2 * bh // 3 + 1, bw // 3:2 * bw // 3 + 1] = 1
            inside &= patch
        if not inside.any() or float(ink[y:y + bh, x:x + bw][inside > 0].mean()) < 0.25:
            return None
        contour = _outline_of(patch)
        if contour is None:
            return None
        # (a symbol filled in has ink all round its edge, its outline or its fill: text whose letters were run
        # together by closing the gaps, as a label written in large letters, has white between the letters there)
        pts = contour.reshape(-1, 2)
        edge = cv2.dilate(ink[y:y + bh, x:x + bw], np.ones((5, 5), np.uint8))
        if float(edge[np.clip(pts[:, 1], 0, bh - 1), np.clip(pts[:, 0], 0, bw - 1)].mean()) < FILLED_EDGE:
            return None
        c = _measure(contour + np.array([x, y], dtype=contour.dtype), 'filled', 0, pixels=int(patch.sum()))
        if c is not None:
            c['solid'] = bool(solid_ink)
        return c

    count, labels, stats, _ = cv2.connectedComponentsWithStats(solid, connectivity=4)
    for k in range(1, count):
        x, y, bw, bh, area = stats[k]
        if max(bw, bh) < min_side:
            continue
        whole = (labels[y:y + bh, x:x + bw] == k).astype(np.uint8)
        # (two symbols filled in, such as twins', may be run together by closing the gaps between the lines drawn
        # close between them: each is a part of the patch, thick as a symbol; and two symbols filled in solidly, drawn
        # close side by side, are each a patch of solid ink, however thick the white closed in between them is)
        parts = _solid(whole, ink[y:y + bh, x:x + bw], stroke) or _thick_parts(whole)
        for patch in (parts if len(parts) > 1 else [whole]):
            c = as_filled(patch, x, y)
            if c is None or not _well_shaped(c, strict=False):
                # the letters of a label written close to a symbol filled in are run into it by closing the gaps: the
                # symbol is what is left without the small pieces of ink that stand apart from it
                pieces = (ink[y:y + bh, x:x + bw] & patch).astype(np.uint8)
                n, bits, bit_stats, _ = cv2.connectedComponentsWithStats(pieces, connectivity=8)
                size = max(cv2.boundingRect(patch)[2:])
                big = [j for j in range(1, n) if max(bit_stats[j][2], bit_stats[j][3]) >= 0.35 * size]
                if big and len(big) < n - 1:
                    rest = _disc_open(_disc_close(np.isin(bits, big).astype(np.uint8), 1.6 * stroke + 1), 1.7 * stroke + 1)
                    again = as_filled(rest & patch, x, y) if (rest & patch).any() else None
                    if again is not None and _well_shaped(again, strict=False):
                        c = again
            if c:
                filled.append(c)

    white = (1 - ink).astype(np.uint8)
    distance = cv2.distanceTransform(white, cv2.DIST_L2, 5)
    # (nothing far larger than the symbols found first is a symbol)
    first = _outlines(white, distance, near_ink, (0, 1.5 * stroke), min_side, stroke, largest=2.5 * guess)
    sure = [c for c in filled + first if _well_shaped(c, strict=c['gap'] > 0)]
    if not sure:
        return [], 0.0
    typical = float(np.median([c['size'] + (2 * stroke if c['how'] == 'outline' else 0) for c in sure]))
    # larger gaps, for larger symbols
    radii = [r for r in (0.05 * typical, 0.09 * typical, 0.13 * typical) if r > 1.5 * stroke + 1]
    more = _outlines(white, distance, near_ink, radii, min_side, stroke, largest=2.5 * typical) if radii else []

    candidates = []
    for c in filled + first + more:
        size = c['size'] + (2 * stroke if c['how'] == 'outline' else 0)
        # leaving out anything far smaller than a symbol (the holes in letters) or far larger
        # (a symbol is no thinner than this either: where lines cross at a sharp angle, as at the point twins' lines
        # come from, closing the gaps between the strokes of scribbles leaves a small patch)
        narrow = min(c['box'][2], c['box'][3]) + (2 * stroke if c['how'] == 'outline' else 0)
        if SMALLEST * typical <= size <= 2.5 * typical and narrow >= SMALLEST * typical and _well_shaped(c, strict=c['gap'] > 0):
            # (a small patch of white closed in by lines that run on past it is the space between them)
            if size < (0.75 if c['how'] == 'outline' else 1.0) * typical and _under_a_line(c, ink, typical):
                continue
            # (the space between the lines to identical twins and the bar across them is a triangle, or with a bold
            # pen, a small patch filled in)
            if c['shape'] == TRIANGLE and twins_bar(c['shape_contour'], ink, typical):
                continue
            if c['how'] == 'filled' and size < 0.8 * typical and _lines_down_both_ways(c, ink, typical):
                continue
            candidates.append(c)
    # one symbol in each place: white closed all round first, then patches filled in, then white inside a gap. White
    # found only through a gap, beside a symbol found already, is more likely the space between that symbol and the
    # lines round it: it is left out if much of its edge runs along that symbol
    candidates.sort(key=lambda c: (c['gap'] > 0, c['how'] == 'outline', c['gap'], -c['area']))
    symbols = []
    taken = np.zeros(ink.shape, np.uint8)
    for c in candidates:
        if any(_overlap(c['box'], d['box']) > 0.3 for d in symbols):
            continue
        # (and so is a small space closed in against a symbol, as by the letters of a label written close under it)
        if symbols and (c['gap'] > 0 or (c['how'] == 'outline' and c['size'] + 2 * stroke < typical)):
            pts = c['contour'].reshape(-1, 2)
            ys, xs = np.clip(pts[:, 1], 0, ink.shape[0] - 1), np.clip(pts[:, 0], 0, ink.shape[1] - 1)
            if float(taken[ys, xs].mean()) > 0.15:
                continue
        symbols.append(c)
        mark = np.zeros(ink.shape, np.uint8)
        cv2.drawContours(mark, [c['contour']], -1, 1, -1)
        grow = 2 * stroke + 5
        x, y, w, h = c['box']
        x0, y0 = max(0, x - grow), max(0, y - grow)
        x1, y1 = min(ink.shape[1], x + w + grow), min(ink.shape[0], y + h + grow)
        taken[y0:y1, x0:x1] |= cv2.dilate(mark[y0:y1, x0:x1], cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
    # a small patch filled in that runs into a larger symbol is something written or drawn against it, as a label is,
    # written close under it (the symbol reaches out past the white inside it by its outline's width)
    def outer(d):
        x, y, w, h = d['box']
        grow = stroke + 2 if d['how'] == 'outline' else 0
        return (x - grow, y - grow, w + 2 * grow, h + 2 * grow)

    def stuck(c):
        narrow = min(c['box'][2], c['box'][3])
        return c['how'] == 'filled' and narrow < 0.8 * typical and \
            any(d is not c and max(outer(d)[2:]) > narrow and _overlap(c['box'], outer(d)) > 0.1 for d in symbols)
    symbols = [c for c in symbols if not stuck(c)]
    for c in symbols:
        # filled in, or not: how much of the inside, away from the outline, is ink
        x, y, w, h = c['box']
        m = 2 * stroke + 3
        x0, y0 = max(0, x - m), max(0, y - m)
        x1, y1 = min(ink.shape[1], x + w + m), min(ink.shape[0], y + h + m)
        region = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.drawContours(region, [c['contour'] - np.array([x0, y0], dtype=c['contour'].dtype)], -1, 1, -1)
        inner = cv2.erode(region, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * stroke + 3, 2 * stroke + 3)))
        if not inner.any():
            # (a symbol too small to look inside away from its outline: the white inside an outline is white)
            inner = cv2.erode(region, np.ones((3, 3), np.uint8)) if c['how'] == 'outline' else region
        n = int(inner.sum())
        c['density'] = float((ink[y0:y1, x0:x1] & inner).sum()) / n if n else 0.0
        c['filled'] = c['how'] == 'filled' or c['density'] >= 0.25
        c['outer'] = _outer(c, ink, stroke)
    symbols.sort(key=lambda c: (c['box'][1], c['box'][0]))
    return symbols, typical


def _outer(c, ink, stroke):
    '''
    The whole of a symbol, outline and all, as an outline of its own: what is blanked out to leave the lines between
    the symbols. For the white inside an outline, that is the white with the outline round it. For a patch filled in,
    the scribble may stop short of the outline round it, and the gap between them is closed first, which leaves the
    lines that meet the outline as thin as they were.
    '''
    if c['how'] == 'outline':
        x, y, w, h = c['box']
        grow = stroke + 2
        m = grow + 2
        x0, y0 = max(0, x - m), max(0, y - m)
        x1, y1 = min(ink.shape[1], x + w + m), min(ink.shape[0], y + h + m)
        region = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.drawContours(region, [c['contour'] - np.array([x0, y0], dtype=c['contour'].dtype)], -1, 1, -1)
        region = cv2.dilate(region, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
    elif c.get('solid'):
        # (a symbol filled in solidly is its own ink, edge and all, but for the soft edge that smoothing leaves: the
        # lines that meet it are left as long as they were drawn, as the short line down to a child under a line
        # drawn close over the child)
        x, y, w, h = c['box']
        grow = 2
        m = grow + 2
        x0, y0 = max(0, x - m), max(0, y - m)
        x1, y1 = min(ink.shape[1], x + w + m), min(ink.shape[0], y + h + m)
        region = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.drawContours(region, [c['contour'] - np.array([x0, y0], dtype=c['contour'].dtype)], -1, 1, -1)
        region = cv2.dilate(region, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
    else:
        # a scribble may stop short of the outline round it. Looking out from the patch in every direction: if an
        # outline is found close round it nearly all the way, as round a scribble that stops short, the symbol
        # reaches out to that outline; if not, as when the scribble fills the symbol to its outline and only the
        # lines that meet it are close by, the patch is the symbol
        x, y, w, h = c['box']
        size = max(w, h)
        m = int(round(0.25 * size)) + stroke + 2
        x0, y0 = max(0, x - m), max(0, y - m)
        x1, y1 = min(ink.shape[1], x + w + m), min(ink.shape[0], y + h + m)
        window = ink[y0:y1, x0:x1]
        patch = np.zeros(window.shape, np.uint8)
        cv2.drawContours(patch, [c['contour'] - np.array([x0, y0], dtype=c['contour'].dtype)], -1, 1, -1)
        cx, cy = x - x0 + w / 2, y - y0 + h / 2
        reach = 0.18 * size + stroke
        points, found = [], 0
        for k in range(48):
            a = 2 * math.pi * k / 48
            dx, dy = math.cos(a), math.sin(a)
            t, edge = 0.0, None
            while True:
                px, py = int(round(cx + dx * t)), int(round(cy + dy * t))
                if not (0 <= px < window.shape[1] and 0 <= py < window.shape[0]):
                    break
                if patch[py, px]:
                    edge = t
                elif edge is not None and t - edge > 1:
                    break
                t += 1
            if edge is None:
                continue
            # out from the edge of the patch, across any white, to the far side of the first ink
            t = edge + 1
            hit = None
            while t <= edge + reach:
                px, py = int(round(cx + dx * t)), int(round(cy + dy * t))
                if not (0 <= px < window.shape[1] and 0 <= py < window.shape[0]):
                    break
                if window[py, px]:
                    hit = t
                    while t <= edge + reach + stroke and 0 <= px < window.shape[1] and 0 <= py < window.shape[0] and window[py, px]:
                        t += 1
                        px, py = int(round(cx + dx * t)), int(round(cy + dy * t))
                    hit = t
                    break
                t += 1
            if hit is not None and hit - edge > stroke + 1:
                found += 1
                points.append((cx + dx * hit, cy + dy * hit))
            else:
                points.append((cx + dx * (edge + 1), cy + dy * (edge + 1)))
        region = patch
        if len(points) >= 24 and found >= 0.7 * len(points):
            ring = np.zeros(window.shape, np.uint8)
            cv2.fillPoly(ring, [np.round(np.array(points)).astype(np.int32)], 1)
            region = (patch | ring).astype(np.uint8)
            grow = 2
        else:
            grow = stroke + 2
        region = cv2.dilate(region, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
    contour = _outline_of(region)
    if contour is None:
        return c['contour']
    return contour + np.array([x0, y0], dtype=contour.dtype)
