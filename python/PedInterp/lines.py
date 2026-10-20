'''
Reading the lines of a pedigree: who are partners, whose children are whose, and which children are twins.

Once the symbols are taken out of the drawing, the lines that join a couple to each other and to their children are
joined to one another, and to nothing else: the partners' line, the line down from it, the line over the children and
the short lines down to each child. Each such network of lines is a family. The lines are thinned to a skeleton one
pixel wide, and where a line ends, it either meets a symbol or it doesn't:

- a line that meets a symbol from the side, at its left or right, joins the person to their partner;
- a line that meets a symbol from above, straight down or slanting, makes the person a child of the couple whose
  network it is. Twins are joined by two slanting lines from one point; identical twins have a bar between them.
- a line that ends near no symbol, as when it was drawn a little short of the line it was meant to meet, is joined to
  the line it points at, if it reaches it within half a symbol or so.

This is how the lines are read whether the pedigree is drawn neatly or sketched by hand: nothing depends on the lines
being straight, level or upright.
'''
import math

import cv2
import numpy as np

#: how near ink must be to the point where the lines to twins meet, as a share of a symbol's size
FORK_INK = 0.3
#: the longest spur that thinning leaves, which a line's direction is measured past, as a share of a symbol's size
SPUR = 0.05

#: the steps to the eight neighbours of a pixel, as (row, column)
N8 = ((-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1))


# ---------------------------------------------------------------------------------------------------------------------
# thinning
# ---------------------------------------------------------------------------------------------------------------------
def _thinning_tables():
    '''
    Zhang and Suen's (1984) two tests for whether a pixel of a line can be taken away without breaking the line or
    shortening it, for each of the 256 ways its eight neighbours can be set. The neighbours are numbered clockwise from
    the one above (P2) to the one above on the left (P9), as bits 0 to 7.
    '''
    first, second = np.zeros(256, bool), np.zeros(256, bool)
    for code in range(256):
        p2, p3, p4, p5, p6, p7, p8, p9 = ((code >> k) & 1 for k in range(8))
        ring = (p2, p3, p4, p5, p6, p7, p8, p9, p2)
        neighbours = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
        crossings = sum(1 for a, b in zip(ring, ring[1:]) if a == 0 and b == 1)
        if 2 <= neighbours <= 6 and crossings == 1:
            first[code] = p2 * p4 * p6 == 0 and p4 * p6 * p8 == 0
            second[code] = p2 * p4 * p8 == 0 and p2 * p6 * p8 == 0
    return first, second


_TABLES = _thinning_tables()


def _neighbour_codes(img):
    '''for each pixel inside a 0/1 image's one-pixel border, the code of its eight neighbours (see _thinning_tables)'''
    return (img[:-2, 1:-1] | img[:-2, 2:] << 1 | img[1:-1, 2:] << 2 | img[2:, 2:] << 3 |
            img[2:, 1:-1] << 4 | img[2:, :-2] << 5 | img[1:-1, :-2] << 6 | img[:-2, :-2] << 7)


def thin(mask):
    '''
    The skeleton of a mask's lines, one pixel wide (Zhang and Suen's thinning), as a 0/1 uint8 array of the same size.
    Only the part of the mask that has lines in it is worked on, which is quick for a drawing that is mostly white.
    '''
    out = np.zeros(mask.shape, np.uint8)
    points = cv2.findNonZero((mask > 0).astype(np.uint8))
    if points is None:
        return out
    x, y, w, h = cv2.boundingRect(points)
    img = np.zeros((h + 2, w + 2), np.uint8)
    img[1:-1, 1:-1] = mask[y:y + h, x:x + w] > 0
    inner = img[1:-1, 1:-1]
    while True:
        changed = False
        for table in _TABLES:
            remove = (inner == 1) & table[_neighbour_codes(img)]
            if remove.any():
                inner[remove] = 0
                changed = True
        if not changed:
            break
    out[y:y + h, x:x + w] = inner
    return out


# ---------------------------------------------------------------------------------------------------------------------
# the skeleton as a graph
# ---------------------------------------------------------------------------------------------------------------------
class Skeleton:
    '''A skeleton's pixels, their neighbours, its ends, and its pieces (each a line, or lines joined together)'''

    def __init__(self, skeleton):
        self.img = skeleton
        kernel = np.ones((3, 3), np.float32)
        kernel[1, 1] = 0
        self.degree = (cv2.filter2D(skeleton.astype(np.float32), -1, kernel, borderType=cv2.BORDER_CONSTANT)
                       * skeleton).astype(np.uint8)
        self.count, self.labels = cv2.connectedComponents(skeleton, connectivity=8)
        ys, xs = np.nonzero((self.degree == 1) & (skeleton > 0))
        self.ends = list(zip(ys.tolist(), xs.tolist()))
        # each piece's length, in pixels of skeleton
        self.length = np.bincount(self.labels.ravel(), minlength=self.count)
        self.length[0] = 0

    def on(self, y, x):
        return 0 <= y < self.img.shape[0] and 0 <= x < self.img.shape[1] and self.img[y, x] > 0

    def neighbours(self, y, x):
        return [(y + dy, x + dx) for dy, dx in N8 if self.on(y + dy, x + dx)]

    def walk(self, start, steps, spur=0):
        '''
        The pixels from an end of a line back along it, for up to steps pixels or until the line branches. A pixel
        with two next steps that are next to each other is a corner of the skeleton's staircase, not a branch, and a
        branch that ends within spur pixels is a spur that thinning left, not a line.
        '''
        path, seen = [start], {start}
        current = start
        for _ in range(steps):
            unseen = [p for p in self.neighbours(*current) if p not in seen]
            ahead = [p for p in unseen if not any(abs(p[0] - q[0]) <= 1 and abs(p[1] - q[1]) <= 1 for q in path[-3:-1])]
            # (the one way on, round a square corner, touches the pixel before the corner)
            if not ahead and len(unseen) == 1:
                ahead = unseen
            if len(ahead) > 1:
                # one step straight on beats a diagonal one when the two are next to each other
                straight = [p for p in ahead if p[0] == current[0] or p[1] == current[1]]
                if len(ahead) == 2 and len(straight) == 1 and abs(ahead[0][0] - ahead[1][0]) + abs(ahead[0][1] - ahead[1][1]) == 1:
                    ahead = straight
                elif spur:
                    ahead = [p for p in ahead if not self._dead_end(p, seen | set(ahead), spur)]
                    if len(ahead) > 1:
                        straight = [p for p in ahead if p[0] == current[0] or p[1] == current[1]]
                        if len(ahead) == 2 and len(straight) == 1 and \
                                abs(ahead[0][0] - ahead[1][0]) + abs(ahead[0][1] - ahead[1][1]) == 1:
                            ahead = straight
            if len(ahead) != 1:
                break
            current = ahead[0]
            seen.add(current)
            path.append(current)
        return path

    def _dead_end(self, start, seen, steps):
        '''whether the skeleton from start comes to an end within steps pixels, without branching'''
        current, visited = start, set(seen) | {start}
        for _ in range(steps):
            ahead = [p for p in self.neighbours(*current) if p not in visited]
            if not ahead:
                return True
            if len(ahead) > 1 and not (len(ahead) == 2 and abs(ahead[0][0] - ahead[1][0]) + abs(ahead[0][1] - ahead[1][1]) == 1):
                return False
            current = ahead[0]
            visited.update(ahead)
        return False

    def lines_out(self, end, steps, radius):
        '''
        How many lines run out of the branch that the line from end comes to, within steps pixels, as far as radius
        from it: the times the skeleton crosses a circle of that radius round the branch. None if the line doesn't
        branch so soon
        '''
        path = self.walk(end, steps)
        if len(path) - 1 >= steps:
            return None
        y0, x0 = path[-1]
        piece = self.labels[end]
        h, w = self.img.shape
        found = []
        for k in range(72):
            a = 2 * math.pi * k / 72
            y, x = int(round(y0 + radius * math.sin(a))), int(round(x0 + radius * math.cos(a)))
            window = self.labels[max(0, y - 1):min(h, y + 2), max(0, x - 1):min(w, x + 2)]
            found.append(bool(np.any(window == piece)))
        if all(found):
            return 1
        return sum(1 for k in range(72) if found[k] and not found[k - 1])

    def direction(self, end, steps, spur=0):
        '''
        The way a line runs into its end, as a unit vector (dx, dy) pointing out of the end, from the line's pixels
        up to steps back from it (past any spur of up to spur pixels that thinning left on the way); and how far back
        that was
        '''
        path = self.walk(end, steps, spur)
        (y0, x0), (y1, x1) = path[-1], path[0]
        dx, dy = x1 - x0, y1 - y0
        norm = math.hypot(dx, dy)
        if norm == 0:
            return (0.0, 0.0), 0
        return (dx / norm, dy / norm), len(path) - 1


# ---------------------------------------------------------------------------------------------------------------------
# where a line meets a symbol
# ---------------------------------------------------------------------------------------------------------------------
def box_distance(point, box):
    '''how far a point (x, y) is from a box (left, top, right, bottom): 0 inside it'''
    x, y = point
    left, top, right, bottom = box
    dx = max(left - x, 0, x - right)
    dy = max(top - y, 0, y - bottom)
    return math.hypot(dx, dy)


def _entry_face(end, direction, box):
    '''
    Which face of a box (left, top, right, bottom) a ray from end in direction first comes in through: 'top', 'left',
    'right' or 'bottom', or None if it misses the box, or starts inside it
    '''
    x, y = end
    dx, dy = direction
    left, top, right, bottom = box
    if left <= x <= right and top <= y <= bottom:
        return None
    t_near, face = -math.inf, None
    t_far = math.inf
    for start, d, low, high, faces in ((x, dx, left, right, ('left', 'right')), (y, dy, top, bottom, ('top', 'bottom'))):
        if abs(d) < 1e-9:
            if not low <= start <= high:
                return None
            continue
        t1, t2 = (low - start) / d, (high - start) / d
        f1, f2 = faces
        if t1 > t2:
            t1, t2, f1, f2 = t2, t1, f2, f1
        if t1 > t_near:
            t_near, face = t1, f1
        t_far = min(t_far, t2)
    if t_near > t_far or t_far < 0 or t_near < 0:
        return None
    return face, (x + t_near * dx, y + t_near * dy)


def _exit_face(point, direction, box):
    '''which face of a box (left, top, right, bottom) a ray from a point inside it goes out through, and where'''
    x, y = point
    dx, dy = direction
    left, top, right, bottom = box
    t, face = min(((left - x) / dx if dx < 0 else math.inf, 'left'), ((right - x) / dx if dx > 0 else math.inf, 'right'),
                  ((top - y) / dy if dy < 0 else math.inf, 'top'), ((bottom - y) / dy if dy > 0 else math.inf, 'bottom'))
    if t == math.inf:
        return None, (x, y)
    return face, (x + t * dx, y + t * dy)


def meeting(end, direction, person, long_line=True):
    '''
    Where a line ending at end, running in direction (pointing out of the end), meets a person's symbol, if it does:
    'top', 'left', 'right' or 'bottom', for the side of the symbol it comes to, or None if it runs past the symbol
    rather than into it.

    The line is carried on from its end, which was cut back where the symbol was blanked out, and the side of the
    symbol it comes in through is the side it meets: a line from above, straight down or slanting as to a twin, comes
    in at the top (the Studio's lines to twins drawn far apart slope at only ten degrees or so, and are cut back
    where they come over a corner of the symbol); a line across to it, at a side. A line that doesn't quite point at
    the symbol, as one drawn by hand may not, is judged by where it ends. A level line that ends over the middle of a
    symbol meets its top only if it is long_line, as the line to a twin far off is, not a stroke of a letter over it.
    '''
    x, y = end
    dx, dy = direction
    left, top, right, bottom = person['inner_box']
    # (from a little way back along the line, for a line that was cut back right at the edge of the symbol; and only
    # if the line doesn't point at the symbol itself, at a box a little larger, for a line drawn by hand that doesn't
    # quite point at it: a line that slants to the middle of the top would otherwise come in at the corner)
    end = (x - 3 * dx, y - 3 * dy)
    entry = _entry_face(end, direction, (left, top, right, bottom))
    if entry is None:
        margin = 0.1 * max(right - left, bottom - top)
        entry = _entry_face(end, direction, (left - margin, top - margin, right + margin, bottom + margin))
    if entry is not None:
        face, (ex, ey) = entry
        if face in ('left', 'right'):
            # a steep line that passes just beside the top of a symbol, and would only come to its side further
            # down, is a line down to it that ends a little off its middle
            if abs(dx) < 0.45:
                if dy > 0 and y < top:
                    return 'top'
                if dy < 0 and y > bottom:
                    return 'bottom'
                # (and a line that ends beside a symbol, but hooks up or down at the end, as a line drawn by hand
                # can, meets its side)
                return 'left' if x < left else 'right' if x > right else None
            # a line that slopes down into the top corner is on its way to the middle of the top, as the lines to
            # twins are
            if dy > 0.08 and ey < top + 0.2 * (bottom - top):
                return 'top'
            return face
        # (a line that comes in at a corner, level or nearly so, meets the side, as a partner's line does; but not one
        # that ends well above the symbol, as no partner's line does, which is on its way down to the middle of the
        # top: a line to a twin drawn far off slopes so gently that it is cut back where it passes over the corner,
        # and what is left of it may run level along the edge of what was blanked out)
        if face == 'top' and abs(dy) < 0.25 and (x < left or x > right) and y > top - 0.08 * (bottom - top):
            return 'left' if x < left else 'right'
        return face
    # a line that ends inside the symbol's box, as one does that comes over a rounded corner of a symbol sketched by
    # hand and runs on a little way along its top, meets the side of the box it came in by: by a top corner, the top
    if left < x < right and top < y < bottom:
        face, (_, ey) = _exit_face((x, y), (-dx, -dy), (left, top, right, bottom))
        if face == 'top' or (face in ('left', 'right') and ey < top + 0.15 * (bottom - top)):
            return 'top'
        if face in ('left', 'right'):
            return face
    pl, pt, pr, pb = person['reach_box']
    cx, cy = (pl + pr) / 2, (pt + pb) / 2
    u = (x - cx) / max((pr - pl) / 2, 1)
    v = (y - cy) / max((pb - pt) / 2, 1)
    towards = (u < 0 and dx > 0) or (u > 0 and dx < 0)
    # a line that ends over the middle of a symbol leads to it, however flat it runs: the Studio joins twins drawn far
    # apart, who have families of their own, by lines that slope at only a few degrees; and the line over a sketched
    # family's children may end over the last child, where the line down to them begins
    if v <= -0.75 and abs(u) <= 0.6 and (dy > 0.15 or (long_line and dy > -0.2)):
        return 'top'
    # (and so does a long line that comes level along the top of a symbol towards its middle, as the line to a twin
    # sketched close over them may, and ends short of the middle, if with a little hook up at the end)
    if v <= -0.75 and abs(u) <= 0.85 and long_line and dy > -0.3 and towards:
        return 'top'
    # (a long line that slopes gently down into the top of a symbol, and was cut short over a corner of it)
    if v <= -0.75 and abs(u) <= 1.0 and long_line and dy > 0.05:
        return 'top'
    if v >= 0.75 and abs(u) <= 0.6 and dy < 0.2:
        return 'bottom'
    if abs(v) < 0.75 and abs(u) >= 0.75 and towards and abs(dx) > 0.5:
        return 'left' if u < 0 else 'right'
    return None


# ---------------------------------------------------------------------------------------------------------------------
# reading the networks of lines
# ---------------------------------------------------------------------------------------------------------------------
class _Union:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, a):
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def join(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def _intersection(p, d, q, e):
    '''where the line through p in direction d meets the line through q in direction e, or None if they're parallel'''
    det = d[0] * (-e[1]) - d[1] * (-e[0])
    if abs(det) < 1e-6:
        return None
    t = ((q[0] - p[0]) * (-e[1]) - (q[1] - p[1]) * (-e[0])) / det
    return p[0] + t * d[0], p[1] + t * d[1]


def read_lines(mask, people, size=None, gap=0.45, debug=None):
    '''
    Reads the lines between the symbols.

    PARAMETERS:
    -----------
    mask: uint8 array, the lines of the drawing (not 0 where there is a line), with the symbols and any text taken out
    people: {id: {'box': (x, y, w, h), 'pad': margin blanked out round the symbol, 'Sex': 1, 2 or 0}}
    size: the typical size of a symbol, in pixels (default: the median of the boxes' larger sides)
    gap: how far a line may stop short of the line it meets, as a share of the typical symbol (a hand-drawn line may
        not quite reach the line it was meant to meet)
    debug: a dict that, if given, is filled with what was found, for drawing it

    RETURN:
    -------
    a dict with:
      'parents': {id: (father or None, mother or None)} for everyone whose parents were found
      'partners': [(id, id)] the couples joined by a line, with or without children
      'twins': [(id, id, 'MZ' or 'DZ')], with the twin drawn on the left first
      'notes': sentences about what couldn't be read, for warnings
      'junctions': the people who are no people, but the point the lines to twins come from (see above)
    '''
    notes = []
    sizes = {pid: max(p['box'][2], p['box'][3]) for pid, p in people.items()}
    size = size or (float(np.median(list(sizes.values()))) if sizes else 100.0)
    # the lines are read at a size where a typical symbol is about 90 pixels across, which is quick
    scale = min(1.0, 90.0 / size)
    if scale < 0.95:
        small = cv2.resize(mask, (max(1, round(mask.shape[1] * scale)), max(1, round(mask.shape[0] * scale))),
                           interpolation=cv2.INTER_AREA)
        lines = (small > 48).astype(np.uint8)
    else:
        scale = 1.0
        lines = (mask > 0).astype(np.uint8)
    S = size * scale
    for pid, p in people.items():
        x, y, w, h = (v * scale for v in p['box'])
        pad = p.get('pad', 0) * scale
        p['_box'] = (x - pad, y - pad, x + w + pad, y + h + pad)
        p['reach_box'] = p['_box']
        p['inner_box'] = (x, y, x + w, y + h)
        p['_size'] = max(w, h)
    # specks, and bits of text, too small to be lines and on their own. A short piece of line next to another, such
    # as the line down to a child under a line drawn close above them, is kept
    count, labels, stats, _ = cv2.connectedComponentsWithStats(lines, connectivity=8)
    near = max(2, int(round(0.15 * S)))
    for k in range(1, count):
        x, y, w, h, _ = stats[k]
        if max(w, h) >= 0.2 * S:
            continue
        x0, y0, x1, y1 = max(0, x - near), max(0, y - near), min(lines.shape[1], x + w + near), min(lines.shape[0], y + h + near)
        window = labels[y0:y1, x0:x1]
        if not np.any((window != 0) & (window != k)):
            lines[labels == k] = 0

    # (a pinhole in a line, as where a line drawn by hand hooks back on itself at its end, would leave a little loop in
    # the skeleton, and no end there: pinholes are filled in)
    count, labels, stats, _ = cv2.connectedComponentsWithStats((lines == 0).astype(np.uint8), connectivity=4)
    pinholes = [k for k in range(1, count) if stats[k, cv2.CC_STAT_AREA] <= max(4.0, (0.03 * S) ** 2)]
    if pinholes:
        lines[np.isin(labels, pinholes)] = 1
    sk = Skeleton(thin(lines))
    steps = max(4, int(0.2 * S))
    # how thick the lines are: thinning a line leaves its end about half as far short of where the line ended
    if sk.img.any():
        depth = cv2.distanceTransform(lines, cv2.DIST_L2, 3)
        thickness = 2 * float(np.median(depth[sk.img > 0]))
    else:
        thickness = 1.0

    def ahead(piece, x, y, dx, dy, reach_px, turns=(0, 10, -10, 20, -20, 30, -30)):
        '''the nearest other piece of line that a line ending at (x, y) points at, within reach_px: (distance, piece,
        point), or None. Not through a symbol.'''
        hit = None
        for turn in turns:
            a = math.radians(turn)
            rx, ry = dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)
            for t in range(1, int(reach_px * (1 if turn == 0 else math.cos(a))) + 1):
                px, py = int(round(x + rx * t)), int(round(y + ry * t))
                if not (0 <= py < lines.shape[0] and 0 <= px < lines.shape[1]):
                    break
                if any(box_distance((px, py), p['_box']) == 0 for p in people.values()):
                    break
                other = int(sk.labels[py, px])
                if other and other != piece:
                    if hit is None or t < hit[0]:
                        hit = (t, other, (px, py))
                    break
            if hit and turn == 0:
                break
        return hit

    # where each line ends: at a symbol, or short of another line, or short of nothing
    attached = []          # (piece, person, side, end, direction)
    free = []              # (piece, end, direction, how far back the direction was measured)
    union = _Union(sk.count)
    bridges = []
    close = max(3.0, 0.15 * S, thickness + 3)
    long_piece = sk.length >= 0.3 * S

    def nearby(piece, x, y, radius):
        '''the nearest pixel of another, longer, piece of line within radius of (x, y), as (distance, piece, point),
        or None: for lines that end a little short of where they meet, at a corner, where neither points at the other'''
        r = int(math.ceil(radius))
        x0, y0 = max(0, int(x) - r), max(0, int(y) - r)
        x1, y1 = min(lines.shape[1], int(x) + r + 1), min(lines.shape[0], int(y) + r + 1)
        window = sk.labels[y0:y1, x0:x1]
        ys, xs = np.nonzero((window != 0) & (window != piece) & long_piece[window])
        if not len(xs):
            return None
        d = np.hypot(xs + x0 - x, ys + y0 - y)
        k = int(np.argmin(d))
        if d[k] > radius:
            return None
        return float(d[k]), int(window[ys[k], xs[k]]), (int(xs[k] + x0), int(ys[k] + y0))

    def symbol_at(x, y, direction, piece):
        '''the symbol a line ending at (x, y) meets, as (distance, id, side), or None'''
        best = None
        long_line = sk.length[piece] >= 0.6 * S
        for pid, p in people.items():
            # (as far as a line drawn by hand may stop short of a symbol, and no less than thinning shortens a line
            # by, for symbols of any size, and for the white inside a symbol drawn with bold lines, which is much
            # smaller than the symbol)
            reach = max(3.0, 0.3 * max(p['_size'], 0.75 * S), thickness + 3)
            distance = box_distance((x, y), p['_box'])
            if distance <= reach:
                side = meeting((x, y), direction, p, long_line)
                if side and (best is None or distance < best[0]):
                    best = (distance, pid, side)
        return best

    short_ends = {}
    for y, x in sk.ends:
        piece = int(sk.labels[y, x])
        direction, back = sk.direction((y, x), steps, SPUR and max(2, int(round(SPUR * S))))
        if back == 0:
            continue
        if not long_piece[piece]:
            short_ends.setdefault(piece, []).append(((x, y), direction))
            continue
        best = symbol_at(x, y, direction, piece)
        # a line drawn down to another line may run on a little past it: the short spur it leaves leads nowhere,
        # however near a symbol it points, unless it all but touches the symbol. (A short line down to a child from
        # the line over the children leaves that line where it runs on to either side, and no line comes down to it
        # from above; a line that ends in a little fork, as one drawn over twice may, branches from no other line)
        if best and back < 0.1 * S and best[0] > max(back, thickness + 3) and \
                (sk.lines_out((y, x), back + 1, max(6.0, 0.15 * S)) or 0) >= 3:
            continue
        # a line that stops just short of another line, nearer than any symbol, was meant to meet that line: as the
        # line down from a couple that stops just above the line over their children, close above a child
        hit = ahead(piece, x, y, direction[0], direction[1], close, turns=(0, 10, -10))
        if not hit:
            # (at a corner, the end of one line may not point at the other: it is enough that it is close)
            hit = nearby(piece, x, y, 0.6 * close)
        if hit and long_piece[hit[1]] and (best is None or hit[0] < best[0]):
            union.join(piece, hit[1])
            bridges.append(((x, y), hit[2]))
            continue
        if best:
            attached.append((piece, best[1], best[2], (x, y), direction))
        else:
            free.append((piece, (x, y), direction, back))

    # a short piece of line counts only as the line down to a child from a line just above them: it comes down to the
    # middle of the child's symbol, from a longer line it all but meets. Anything else so short is a bit of text,
    # such as the numbers Pedigree Studio writes over its symbols, or what is left of a slash through a symbol
    connectors = {}
    for piece, ends in short_ends.items():
        if len(ends) != 2:
            continue
        for (end, direction), (other, other_direction) in (ends, ends[::-1]):
            # (it comes down steeply, as a line down to a child does, not across, as a stroke of a letter may)
            if direction[1] < 0.5:
                continue
            best = symbol_at(end[0], end[1], direction, piece)
            if not best or best[2] != 'top':
                continue
            left, top, right, bottom = people[best[1]]['_box']
            if abs(end[0] - (left + right) / 2) > 0.3 * (right - left):
                continue
            # (in a sketch, the stroke down to a child may stop a little further short of the line above)
            reach = max(close, 0.5 * gap * S)
            hit = ahead(piece, other[0], other[1], other_direction[0], other_direction[1], reach, turns=(0, 10, -10, 20, -20))
            if not hit:
                hit = nearby(piece, other[0], other[1], reach)
            if hit and long_piece[hit[1]]:
                connectors.setdefault(best[1], []).append((piece, best[1], end, direction, other, hit))
                break
    # a child has one line down to them: several short pieces over one symbol are the letters of a label, such as the
    # number Pedigree Studio writes over the symbol of someone who married into the family, under a line
    for pid, found in connectors.items():
        if len(found) != 1:
            continue
        piece, pid, end, direction, other, hit = found[0]
        attached.append((piece, pid, 'top', end, direction))
        union.join(piece, hit[1])
        bridges.append((other, hit[2]))

    # a short piece of line across between two symbols drawn close side by side, that meets the side of each, is the
    # line between partners, of which little is left once their symbols are blanked out: it is a line like any other,
    # which the line down to their children may come from
    taken = {found[0][0] for found in connectors.values() if len(found) == 1}
    for piece, ends in short_ends.items():
        if len(ends) != 2 or piece in taken:
            continue
        (a, da), (b, db) = sorted(ends, key=lambda e: e[0][0])
        if da[0] > -0.7 or db[0] < 0.7:
            continue
        left, right = symbol_at(a[0], a[1], da, piece), symbol_at(b[0], b[1], db, piece)
        if left and right and left[1] != right[1] and left[2] == 'right' and right[2] == 'left':
            attached.append((piece, left[1], 'right', a, da))
            attached.append((piece, right[1], 'left', b, db))
            long_piece[piece] = True

    # two lines that end close together, neither quite reaching the other, as at a corner drawn in two strokes (the
    # line over a family's children, and the line down to the child at its end), are joined end to end, the closest
    # first, if the gap between them lies the way at least one of them runs
    pairs = []
    for i in range(len(free)):
        pi, (xi, yi), (dxi, dyi), _ = free[i]
        for j in range(i + 1, len(free)):
            pj, (xj, yj), (dxj, dyj), _ = free[j]
            if pi == pj:
                continue
            d = math.hypot(xj - xi, yj - yi)
            if d > 0.3 * S or d == 0:
                continue
            vx, vy = (xj - xi) / d, (yj - yi) / d
            if dxi * vx + dyi * vy > 0.5 or -(dxj * vx + dyj * vy) > 0.5:
                pairs.append((d, i, j))
    used = set()
    for d, i, j in sorted(pairs):
        if i in used or j in used or union.find(free[i][0]) == union.find(free[j][0]):
            continue
        used.update((i, j))
        union.join(free[i][0], free[j][0])
        bridges.append((free[i][1], free[j][1]))
    free = [f for k, f in enumerate(free) if k not in used]

    # a line that stops further short of another is joined to the one it points at, if it reaches it within gap. A
    # short piece of line, such as a bit of text that happens to be near a line, is joined only to a line very close
    reach_px = gap * S
    for piece, (x, y), (dx, dy), back in free:
        # (not from the end of a short spur past a junction)
        if back < min(steps, 0.12 * S):
            continue
        hit = ahead(piece, x, y, dx, dy, reach_px)
        if hit and long_piece[hit[1]]:
            union.join(piece, hit[1])
            bridges.append(((x, y), hit[2]))

    # a line that runs over the top of a symbol drawn a little high, so that the symbol covers it, is cut in two where
    # the symbol was blanked out: the two pieces, coming level to the top corners from either side, are one line, and
    # it meets the symbol at its top
    by_person = {}
    behind = set()
    for k, (piece, pid, side, end, direction) in enumerate(attached):
        by_person.setdefault(pid, []).append(k)
    for pid, ks in by_person.items():
        left, top, right, bottom = people[pid]['inner_box']
        cx = (left + right) / 2
        # (the ends may turn at the last, where the symbol's label is written against the line)
        level = [k for k in ks if attached[k][3][1] < top + 0.25 * (bottom - top)]
        from_left = [k for k in level if attached[k][3][0] < left + 0.35 * (right - left) and attached[k][4][0] > 0.3]
        from_right = [k for k in level if attached[k][3][0] > right - 0.35 * (right - left) and attached[k][4][0] < -0.3]
        paired = set()
        for a in from_left:
            for b in from_right:
                if attached[a][0] != attached[b][0] and abs(attached[a][3][1] - attached[b][3][1]) < 0.2 * (bottom - top):
                    union.join(attached[a][0], attached[b][0])
                    bridges.append((attached[a][3], attached[b][3]))
                    paired.update((a, b))
                    behind.add(pid)
                    for k in (a, b):
                        piece, _, _, end, direction = attached[k]
                        attached[k] = (piece, pid, 'top', end, direction)
        # and the line on to a brother or sister may leave the line down to the person from behind their symbol, which
        # was drawn a little higher than theirs: it comes level to one top corner only, and is the line down to them
        # carried on. (Not a partner's line that comes to the corner of a small symbol: its family of lines joins
        # someone else at the side, as the partner)
        down = [k for k in ks if attached[k][2] == 'top' and attached[k][4][1] > 0.5 and left <= attached[k][3][0] <= right]
        for k in from_left + from_right:
            if k in paired or not down:
                continue
            net = union.find(attached[k][0])
            if any(j != k and union.find(attached[j][0]) == net and attached[j][2] in ('left', 'right')
                   for j in range(len(attached))):
                continue
            for d in down:
                if attached[d][0] != attached[k][0]:
                    union.join(attached[k][0], attached[d][0])
                    bridges.append((attached[k][3], attached[d][3]))
                    piece, _, _, end, direction = attached[k]
                    attached[k] = (piece, pid, 'top', end, direction)
                    break

    # a piece of line whose ends all meet the same symbol is a mark by it, as a stroke of a letter written over it
    # may be, not a line from it to anything
    meets, ends_of = {}, {}
    for piece, pid, *_ in attached:
        meets.setdefault(piece, []).append(pid)
    for y, x in sk.ends:
        ends_of[int(sk.labels[y, x])] = ends_of.get(int(sk.labels[y, x]), 0) + 1
    marks = {piece for piece, pids in meets.items()
             if len(set(pids)) == 1 and len(pids) >= 2 and len(pids) == ends_of.get(piece, 0) and sk.length[piece] < S}
    attached = [a for a in attached if a[0] not in marks]

    def group():
        found = {}
        for piece, pid, side, end, direction in attached:
            found.setdefault(union.find(piece), []).append((pid, side, end, direction))
        return found

    # children hang from a line: lines that join children to nothing above them, as the two lines to twins drawn
    # from a point a little below the line over the family's children, are joined to the nearest line of another
    # family of lines from their highest point, if it is close
    networks = group()
    ys, xs = np.nonzero(sk.img)
    tops = {}
    for y, x, label in zip(ys.tolist(), xs.tolist(), sk.labels[ys, xs].tolist()):
        if label not in tops or y < tops[label][0]:
            tops[label] = (y, x)
    for net, atts in list(networks.items()):
        if any(side != 'top' for _, side, _, _ in atts):
            continue
        pieces = [label for label in tops if union.find(label) == net]
        if not pieces:
            continue
        y, x = min(tops[label] for label in pieces)
        # (the line found must be another family's, and one that joins people)
        r = int(math.ceil(0.4 * S))
        window = sk.labels[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1]
        others = {int(v) for v in np.unique(window) if v and union.find(int(v)) != net and long_piece[int(v)]}
        best = None
        for label in others:
            wy, wx = np.nonzero(window == label)
            d = np.hypot(wx + max(0, x - r) - x, wy + max(0, y - r) - y)
            k = int(np.argmin(d))
            if d[k] <= 0.4 * S and (best is None or d[k] < best[0]):
                best = (float(d[k]), label, (int(wx[k] + max(0, x - r)), int(wy[k] + max(0, y - r))))
        if best and union.find(best[1]) in networks:
            union.join(pieces[0], best[1])
            bridges.append(((x, y), best[2]))
    networks = group()

    # what was found as a small symbol, with a line down to its top and lines from it down to two or more people below
    # it, and to no one else, is no person but the point the lines to twins come from, closed in by their bar: read as
    # a symbol, it would be someone of unknown sex, in a row of their own, between the twins and their parents
    def centre_y(pid):
        return (people[pid]['_box'][1] + people[pid]['_box'][3]) / 2
    junctions, junction_twins = [], []
    nets_of = {}
    for net, atts in networks.items():
        for pid, side, end, direction in atts:
            nets_of.setdefault(pid, []).append((net, side))
    for pid, found in nets_of.items():
        above = {net for net, side in found if side == 'top'}
        below_nets = {net for net, side in found if side != 'top'} - above
        if len(above) != 1 or not below_nets or people[pid]['_size'] > 0.8 * S:
            continue
        lower, ok = set(), True
        for net in below_nets:
            for other, side, end, direction in networks[net]:
                if other == pid:
                    continue
                if side == 'top' and centre_y(other) - centre_y(pid) > 0.3 * S:
                    lower.add(other)
                else:
                    ok = False
        if ok and len(lower) >= 2:
            junctions.append(pid)
            first = next(iter(above))
            for net in below_nets:
                union.join(net, first)
            # (closed in by a bar, the twins are identical)
            ordered = sorted(lower, key=lambda other: people[other]['_box'][0])
            junction_twins.extend((a, b, 'MZ') for a, b in zip(ordered, ordered[1:]))
    if junctions:
        attached = [a for a in attached if a[1] not in junctions]
        networks = group()

    parents, partners, twins = {}, [], []
    child_of = {}
    for net, atts in networks.items():
        sides = {}
        for pid, side, end, direction in atts:
            sides.setdefault(pid, set()).add(side)
        couple = [pid for pid, s in sides.items() if s & {'left', 'right'}]
        children = [pid for pid, s in sides.items() if 'top' in s and pid not in couple]
        below = [pid for pid, s in sides.items() if 'bottom' in s and pid not in couple and pid not in children]
        # a child is drawn below their parents, and partners side by side: anything else is a line read wrongly,
        # such as what is left of a slash through a symbol, beside it
        def middle(pid):
            left, top, right, bottom = people[pid]['_box']
            return (left + right) / 2, (top + bottom) / 2
        if len(couple) == 2 and abs(middle(couple[0])[1] - middle(couple[1])[1]) > 0.75 * S:
            couple = []
        if len(couple) > 2:
            # partners are side by side: of more than two people met at a side, the two most nearly level are the
            # couple, and anyone well below them whom the line meets above the middle of their symbol is a child, as
            # a twin is whose line comes nearly level to the corner of their symbol (and the line meets them at the
            # top, for telling twins)
            pairs = sorted((abs(middle(a)[1] - middle(b)[1]), a, b) for i, a in enumerate(couple) for b in couple[i + 1:])
            _, a, b = pairs[0]
            level = max(middle(a)[1], middle(b)[1])
            rest = [pid for pid in couple if pid not in (a, b)]
            couple = [a, b]
            for pid in rest:
                above_middle = any(p == pid and end[1] < middle(pid)[1] for p, side, end, _ in atts)
                if middle(pid)[1] - level > 0.4 * S and above_middle:
                    children.append(pid)
                    atts = [(p, 'top' if p == pid and side in ('left', 'right') and end[1] < middle(pid)[1] else side,
                             end, direction) for p, side, end, direction in atts]
                else:
                    couple = _closest_couple(couple + [pid], people, children)
                    notes.append(f'{", ".join(sorted(sides))}: the lines joining them cross or touch, so who is whose '
                                 'partner may be read wrongly')
                    break
        # (below the couple as it is once it is made out)
        parents_y = [middle(pid)[1] for pid in couple] or [middle(pid)[1] for pid in below[:1]]
        children = [pid for pid in children if all(middle(pid)[1] - y > 0.4 * S for y in parents_y)]
        if len(couple) == 2:
            partners.append(tuple(sorted(couple, key=lambda pid: people[pid]['_box'][0])))
        parent_ids = couple if couple else below[:1]
        if not children or not parent_ids:
            continue
        father, mother = _father_mother(parent_ids, people)
        for child in children:
            child_of.setdefault(child, []).append((net, father, mother))
        # twins: two children joined by slanting lines from one point
        if debug is not None:
            debug.setdefault('networks', []).append({'couple': parent_ids, 'children': children})
        twins += _twins(children, atts, sk, lines, people, S)
    for child, options in child_of.items():
        if len(options) > 1:
            notes.append(f'{child}: lines from more than one couple come down to them, so their parents may be read wrongly')
        _, father, mother = options[0]
        parents[child] = (father, mother)
    # brothers and sisters don't marry: of two partners read as children of the same couple, one whose symbol a line
    # only runs behind, near its top, was drawn high enough to cover the line over their partner's brothers and
    # sisters, and married into the family
    for a, b in partners:
        if parents.get(a) and parents.get(a) == parents.get(b):
            for pid in (a, b):
                if pid in behind and not all(p in behind for p in (a, b)):
                    del parents[pid]
    if debug is not None:
        debug.update(skeleton=sk, scale=scale, attached=attached, free=free, bridges=bridges)
    for p in people.values():
        for key in ('_box', 'reach_box', 'inner_box', '_size'):
            p.pop(key, None)
    twinned = {frozenset(t[:2]) for t in twins}
    twins += [t for t in junction_twins if frozenset(t[:2]) not in twinned]
    return {'parents': parents, 'partners': partners, 'twins': twins, 'notes': notes, 'junctions': junctions}


def _father_mother(parent_ids, people):
    '''the father and the mother of a couple (or of one parent): by their sexes, or else the one on the left is the father'''
    ordered = sorted(parent_ids, key=lambda pid: people[pid]['_box'][0])
    if len(ordered) == 1:
        sex = people[ordered[0]].get('Sex')
        return (ordered[0], None) if sex != 2 else (None, ordered[0])
    left, right = ordered
    if people[left].get('Sex') == 2 or people[right].get('Sex') == 1:
        return right, left
    return left, right


def _closest_couple(couple, people, children):
    '''of more than two people joined at the side, the two nearest above the children'''
    if not children:
        return sorted(couple, key=lambda pid: people[pid]['_box'][0])[:2]
    cx = np.mean([(people[c]['_box'][0] + people[c]['_box'][2]) / 2 for c in children])
    ranked = sorted(couple, key=lambda pid: abs((people[pid]['_box'][0] + people[pid]['_box'][2]) / 2 - cx))
    return ranked[:2]


def _twins(children, atts, sk, lines, people, S):
    '''
    Twins among a couple's children: two children next to each other whose lines slant towards each other and meet
    above them, not too far up. Identical twins have a bar across between the two lines, below where they meet.
    '''
    found = []
    entry = {}
    for pid, side, end, direction in atts:
        if side == 'top' and pid in children:
            # (a child may have more than one line from above that meets them: in a sketch, the end of the bar across
            # the lines to identical twins may come close to one of them)
            entry.setdefault(pid, []).append((end, direction))
    for pid, ends in entry.items():
        # (a child with a steep line down to the top of their symbol has it for their line from above: a level one
        # beside it is the end of the line over the children run on past them, or of the bar across the lines to
        # twins come close to them, and leads to no twin)
        left, _, right, _ = people[pid]['inner_box']
        steep = [e for e in ends if e[1][1] >= 0.3 and left <= e[0][0] <= right]
        if steep:
            entry[pid] = steep + [e for e in ends if e[1][1] >= 0.3 and e not in steep]
    ordered = sorted(entry, key=lambda pid: people[pid]['_box'][0] + people[pid]['_box'][2])
    used = {}
    for a, b in zip(ordered, ordered[1:]):
        best = None
        # (a child has one line down to them: the line that made them a twin of the child on their left is the one
        # that may make them a twin of the child on their right too, as triplets are)
        for ea, da in ([used[a]] if a in used else entry[a]):
            for eb, db in entry[b]:
                meet = _meeting_point(ea, da, eb, db, sk, lines, S)
                if meet and (best is None or meet[0][1] < best[0][1]):
                    best = meet + ((ea, da), (eb, db))
        if best:
            fork, own, (ea, da), (eb, db) = best
            used[a], used[b] = (ea, da), (eb, db)
            found.append((a, b, 'MZ' if _bar(lines, fork, ea, eb, S, own) else 'DZ'))
    return found


def _meeting_point(ea, da, eb, db, sk, lines, S):
    '''
    Where the lines to two children, which end at ea and eb (the line to the left one) and come into those ends going
    da and db, meet above them, if they are twins: (x, y), and each line as followed from its end to there, lists of
    (row, column). None if they aren't twins.
    '''
    # the line to the left twin comes down from the right, and the line to the right twin from the left (or level,
    # or nearly so, as a line drawn by hand may come at the last)
    if not (da[0] < -0.3 and db[0] > 0.3 and da[1] > -0.25 and db[1] > -0.25):
        return None
    fitted = None
    # where the two lines meet: each line is fitted along its length, as far as it goes before it branches (at the
    # bar, if there is one), which gives a truer slope than its last few pixels
    # (the bar of identical twins meets their lines halfway along: the lines are fitted along less than that, and a
    # junction with a bar that leaves at a shallow angle is not followed)
    along = max(0.15 * S, 0.2 * math.hypot(eb[0] - ea[0], eb[1] - ea[1]))
    la, lb = _fit(sk, ea, S, along), _fit(sk, eb, S, along)
    fork = _intersection(la[0], la[1], lb[0], lb[1]) if la and lb else None
    if fork is None:
        fork = _intersection(ea, (-da[0], -da[1]), eb, (-db[0], -db[1]))
    if fork is not None and _above(fork, ea, eb, S):
        # the lines to twins meet: there is a line where they meet, not just where the two lines would meet if they
        # were drawn on (two lines down to children from the line over them, slanting a little towards each other as
        # lines drawn by hand may, would meet in the space above that line)
        fx, fy = fork
        near = max(3, int(round(FORK_INK * S)))
        x0, y0 = max(0, int(round(fx)) - near), max(0, int(round(fy)) - near)
        if lines[y0:int(round(fy)) + near + 1, x0:int(round(fx)) + near + 1].any():
            # (each line followed from the twin to where the lines meet, the shortest way, which passes the bar by: a
            # line drawn by hand may wander off the straight, and no part of it is a bar)
            fitted = (fork, _twin_lines(sk, fork, ea, eb, S))
    # the lines of a sketch may bend as they come to the twins, where they run close by the tops of the symbols, and
    # fitted near their ends they may not meet where they do: where they meet as the skeleton runs is the other way
    # to find it
    apex = _apex(sk, ea, eb, S)
    if apex is None or not _above(apex[0], ea, eb, S):
        return fitted
    if fitted is None:
        return apex
    # (of the two, the higher, if it is on the lines: the bar of identical twins, or the bend of a line, is lower down
    # than where the lines meet, which, as they were fitted, may be in the gap between them, where they meet a little
    # apart, or are joined only by the bar; but lines that bend may be fitted to meet in the white over where they do)
    fx, fy = fitted[0]
    near = max(2, int(round(0.1 * S)))
    on_lines = lines[max(0, int(round(fy)) - near):int(round(fy)) + near + 1,
                     max(0, int(round(fx)) - near):int(round(fx)) + near + 1].any()
    return fitted if fy < apex[0][1] and on_lines else apex


#: how steeply, at the least, the lines to twins slope down to them from where they meet: about 2 degrees
SLOPE = 0.035


def _above(fork, ea, eb, S):
    '''whether where two lines to twins meet is above them, and between them'''
    fx, fy = fork
    # (twins drawn far apart, who have families of their own, are joined by long, flat lines, so how far the point
    # they meet at is from them doesn't matter, but how far above them does: the lines slope down to the twins, if
    # only a little, as no line along over the children does, nor the end of one that runs on past the last child)
    return ea[0] - 0.1 * S <= fx <= eb[0] + 0.1 * S and min(ea[1], eb[1]) - 1.5 * S < fy < min(ea[1], eb[1]) and \
        all(end[1] - fy >= SLOPE * abs(end[0] - fx) for end in (ea, eb))


#: how many pixels further along the lines from two twins (from both together) a pixel of height is worth, where the
#: point their lines meet is looked for along the skeleton (see _apex): less than 2, as a point up a line that leads
#: off theirs is two pixels further for each pixel higher
APEX_RISE = 1.8


def _apex(sk, ea, eb, S):
    '''
    Where the lines to two twins meet, as the skeleton runs, and each line as followed from its twin's end to there
    (lists of (row, column)); or None.

    Of the points that the lines from both twins' ends lead to, it is the one highest up for how far it is along the
    lines from them: each pixel higher up counts for APEX_RISE pixels further along the lines, from both twins
    together. A point up the line to the parents, or along the line over the children, is two pixels further for each
    pixel it is higher up, one from each twin, which is too far for it to be where they meet; the bar across the lines
    to identical twins is a shorter way from one twin to the other than over the top, but not by as much as it is lower
    down. Lines that meet the line over the children a little apart meet in the middle of the stretch of it between
    them.

    Each line, as followed, must run roughly straight from the twin to where they meet, as the line to a twin does,
    not up and then along, as the lines to two children who aren't twins do; and from where they meet, each must
    soon slope down, not run a long way along the line over the children first.
    '''
    H, W = sk.img.shape
    margin = 0.5 * S
    left, right = int(max(0, min(ea[0], eb[0]) - margin)), int(min(W - 1, max(ea[0], eb[0]) + margin))
    top, bottom = int(max(0, min(ea[1], eb[1]) - 1.5 * S)), int(min(H - 1, max(ea[1], eb[1]) + 2))
    window = sk.img[top:bottom + 1, left:right + 1] > 0
    walks = [_steps(window, (int(round(end[1])) - top, int(round(end[0])) - left)) for end in (ea, eb)]
    (dist_a, came_a), (dist_b, came_b) = walks
    both = [p for p in dist_a if p in dist_b]
    if not both:
        return None
    score = {p: -APEX_RISE * p[0] - (dist_a[p] + dist_b[p]) for p in both}
    best = max(score.values())
    # (where the top is level, its middle: the pixels as good as the best, or nearly, that run on from it, as far as
    # a line drawn by hand that is level wanders up and down, two pixels or so)
    tied = {p for p in both if score[p] >= best - 2 * APEX_RISE - 1.0}
    run, frontier = set(), [max(tied, key=lambda p: score[p])]
    run.update(frontier)
    while frontier:
        following = []
        for y, x in frontier:
            for dy, dx in N8:
                q = (y + dy, x + dx)
                if q in tied and q not in run:
                    run.add(q)
                    following.append(q)
        frontier = following
    cy, cx = np.mean([p[0] for p in run]), np.mean([p[1] for p in run])
    goal = min(run, key=lambda p: (p[0] - cy) ** 2 + (p[1] - cx) ** 2)
    paths = []
    for end, came in ((ea, came_a), (eb, came_b)):
        path, p = [], goal
        while p is not None:
            path.append((p[0] + top, p[1] + left))
            p = came[p]
        # roughly straight: no pixel of it far off the straight line from the twin's end to where the lines meet
        (y0, x0), (y1, x1) = path[-1], path[0]
        length = math.hypot(x1 - x0, y1 - y0)
        if length == 0:
            return None
        off = max(abs((x - x0) * (y1 - y0) - (y - y0) * (x1 - x0)) / length for y, x in path)
        if off > 0.25 * length + 2:
            return None
        # (soon sloping down from where they meet: lines to twins drawn close along the line over the children, where
        # they leave it, part from it a little apart, but the lines to two children who aren't twins part from it as
        # far apart as the children are)
        k = 0
        while k < len(path) - 1 and path[k][0] - y1 <= 3:
            k += 1
        if k > 0.35 * S:
            return None
        paths.append(path)
    return (float(goal[1] + left), float(goal[0] + top)), paths


def _steps(window, start):
    '''
    How many steps along a skeleton (a 0/1 or bool array) each of its pixels is from start (row, column), and the pixel
    each was come to from: dicts of (row, column). Start need not be on the skeleton itself, only next to it.
    '''
    h, w = window.shape
    if not (0 <= start[0] < h and 0 <= start[1] < w):
        return {}, {}
    dist, came = {start: 0}, {start: None}
    frontier = [start]
    while frontier:
        following = []
        for y, x in frontier:
            for dy, dx in N8:
                q = (y + dy, x + dx)
                if q not in dist and 0 <= q[0] < h and 0 <= q[1] < w and window[q]:
                    dist[q] = dist[(y, x)] + 1
                    came[q] = (y, x)
                    following.append(q)
        frontier = following
    return dist, came


def _twin_lines(sk, fork, ea, eb, S):
    '''
    The two lines to twins, as the skeleton's pixels from each twin's end to where the lines meet (the pixel of the
    line nearest the point found for it), each the shortest way along the skeleton, which goes by the bar of
    identical twins rather than across it: lists of (row, column)
    '''
    fx, fy = fork
    margin = 0.5 * S
    left, top = int(max(0, min(fx, ea[0], eb[0]) - margin)), int(max(0, min(fy, ea[1], eb[1]) - margin))
    right = int(min(sk.img.shape[1] - 1, max(fx, ea[0], eb[0]) + margin))
    bottom = int(min(sk.img.shape[0] - 1, max(fy, ea[1], eb[1]) + margin))
    window = sk.img[top:bottom + 1, left:right + 1]
    ys, xs = np.nonzero(window)
    if not len(xs):
        return []
    k = int(np.argmin(np.hypot(xs + left - fx, ys + top - fy)))
    goal = (int(ys[k]) + top, int(xs[k]) + left)
    paths = []
    for end in (ea, eb):
        start = (int(end[1]), int(end[0]))
        came = {start: None}
        frontier = [start]
        while frontier and goal not in came:
            following = []
            for y, x in frontier:
                for dy, dx in N8:
                    p = (y + dy, x + dx)
                    if p not in came and top <= p[0] <= bottom and left <= p[1] <= right and sk.img[p] > 0:
                        came[p] = (y, x)
                        following.append(p)
            frontier = following
        path, p = [], goal if goal in came else None
        while p is not None:
            path.append(p)
            p = came[p]
        paths.append(path)
    return paths


def _fit(sk, end, S, along):
    '''a line fitted to the pixels of a line from its end, for up to along pixels or until it branches: a point on it,
    and its direction'''
    path = sk.walk((int(end[1]), int(end[0])), int(along), spur=max(3, int(0.06 * S)))
    if len(path) < 5:
        return None
    points = np.array([(x, y) for y, x in path], np.float32)
    vx, vy, x0, y0 = cv2.fitLine(points, cv2.DIST_L2, 0, 0.01, 0.01).ravel()
    return (float(x0), float(y0)), (float(vx), float(vy))


def _bar(lines, fork, ea, eb, S=90.0, own=()):
    '''
    Whether a line is drawn across between two twins' lines: anything inside the triangle the lines make with the
    line between their ends, away from the two lines themselves and from the point where they meet, that reaches
    most of the way across. A bar drawn by hand may not quite touch the lines. own: the twins' lines as they were
    followed, lists of (row, column), which are no bar however they wander
    '''
    fx, fy = fork
    # (the triangle reaches on a little past the ends of the lines: a symbol sketched by hand is blanked out with what
    # is drawn close against it, and the lines to twins drawn close over their symbols may be cut short as far up as
    # the bar)
    tri = np.array([[fx, fy], [fx + 1.25 * (ea[0] - fx), fy + 1.25 * (ea[1] - fy)],
                    [fx + 1.25 * (eb[0] - fx), fy + 1.25 * (eb[1] - fy)]], np.float32)
    x0, y0 = np.floor(tri.min(axis=0)).astype(int)
    x1, y1 = np.ceil(tri.max(axis=0)).astype(int)
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, lines.shape[1] - 1), min(y1, lines.shape[0] - 1)
    if x1 - x0 < 4 or y1 - y0 < 2:
        return False
    inside = np.zeros((y1 - y0 + 1, x1 - x0 + 1), np.uint8)
    cv2.fillPoly(inside, [np.round(tri - [x0, y0]).astype(np.int32)], 1)
    # away from the twins' lines, as far out as their ink reaches however thick they are drawn (how far it is from the
    # middle of a line to its edge), and from the top, where they meet
    sides = np.zeros_like(inside)
    depth = cv2.distanceTransform((lines[y0:y1 + 1, x0:x1 + 1] > 0).astype(np.uint8), cv2.DIST_L2, 3)
    half = [depth[y - y0, x - x0] for path in own for y, x in path if y0 <= y <= y1 and x0 <= x <= x1]
    band = max(3, int(round(float(np.median(half))))) if half else 3
    for end in tri[1:]:
        cv2.line(sides, (int(round(fx - x0)), int(round(fy - y0))), (int(round(end[0] - x0)), int(round(end[1] - y0))),
                 1, 2 * band + 1)
    for path in own:
        for y, x in path:
            if y0 <= y <= y1 and x0 <= x <= x1:
                cv2.circle(sides, (x - x0, y - y0), band, 1, -1)
    # (the twins may be drawn at different heights, and the bar, which joins the two lines halfway along, then
    # slopes: how far down it is goes by the twins' heights on average)
    middle = (ea[1] + eb[1]) / 2 - fy
    top = int(round(fy + 0.25 * middle)) - y0
    inside[:max(top, 0)] = 0
    ink = (lines[y0:y1 + 1, x0:x1 + 1] > 0) & (inside > 0) & (sides == 0)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    for k in range(1, count):
        x, y, w, h, n = stats[k]
        # how wide the triangle is at this height, between the two lines
        level = y + h / 2 + y0
        t = (level - fy) / max(middle, 1e-9)
        if not 0 < t <= 1.2:
            continue
        across = abs((eb[0] - fx) - (ea[0] - fx)) * min(t, 1.0)
        if w >= 0.4 * across and w >= 4 and _across(labels == k, ea, eb) and not _runs_on(lines, fork, ea, eb, level, S, own):
            return True
    return False


def _across(piece, ea, eb):
    '''
    Whether a piece of line runs across between twins' lines, as a bar does, roughly the way from one twin to the
    other: not along one of their lines, as a bit of a line drawn by hand that wanders off the straight may
    '''
    ys, xs = np.nonzero(piece)
    if len(xs) < 3:
        return False
    xs, ys = xs - xs.mean(), ys - ys.mean()
    angle = 0.5 * math.atan2(2 * float((xs * ys).mean()), float((xs * xs).mean() - (ys * ys).mean()))
    base = math.atan2(eb[1] - ea[1], eb[0] - ea[0])
    turn = abs((angle - base + math.pi / 2) % math.pi - math.pi / 2)
    return turn <= math.radians(30)


def _runs_on(lines, fork, ea, eb, level, S, own=()):
    '''
    Whether a line at this level runs on out past both twins' lines: the line over the children does, where the
    lines to twins leave it from a point a little above it, as they may in a sketch, and it is no bar. (The twins'
    own lines, own, which run on past the bar towards the twins, and nearly level when the twins are far apart, are
    left out)
    '''
    fx, fy = fork

    def x_at(end):
        return fx + (end[0] - fx) * (level - fy) / (end[1] - fy) if abs(end[1] - fy) > 1e-6 else end[0]
    near, far, high = 0.12 * S, 0.35 * S, 0.08 * S
    top, bottom = max(0, int(round(level - high))), min(lines.shape[0], int(round(level + high)) + 1)
    sides = 0
    for x, outwards in ((x_at(ea), -1), (x_at(eb), 1)):
        left, right = sorted((int(round(x + outwards * near)), int(round(x + outwards * far))))
        left, right = max(0, left), max(0, min(lines.shape[1], right))
        window = (lines[top:bottom, left:right] > 0).astype(np.uint8)
        for path in own:
            for y, px in path:
                if top - 4 <= y < bottom + 4 and left - 4 <= px < right + 4:
                    cv2.circle(window, (px - left, y - top), 4, 0, -1)
        # (most of the way across, as a line running on is, not a line down to a child beside the twins)
        if window.size and window.any(axis=0).mean() >= 0.6:
            sides += 1
    return sides == 2
