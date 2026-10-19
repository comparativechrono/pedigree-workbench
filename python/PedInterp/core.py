import cv2
import math
import sys
import warnings
import numpy as np
from PIL import Image
from os import makedirs
import pandas as pd
#pytesseract is imported only when the labels are read with Tesseract (see tesseract_words), so that PedInterp
#works without it, as in a browser under Pyodide, which can't run the tesseract program

#-----------------------------
# PED Data Frame Object Class
#-----------------------------
#TODO implement class for PED file dataframes


#-----------------------------
# PED FILE EXPORT
#-----------------------------
def PED_export(PED_df, output_dir = '.'):
    '''
    Writes a PED file-formatted dataframe to output_dir/<FamilyID>.ped and returns the file's path
    '''
    FamID = PED_df['FamilyID'].iloc[0]
    makedirs(output_dir, exist_ok= True)
    path = f'{output_dir}/{FamID}.ped'
    PED_df.to_csv(path_or_buf= path,
                  sep = '\t',
                  header= False,
                  index= False)
    return path

#-----------------------------
# IMAGE ENHANCEMENT
#-----------------------------
def _resample_filter():
    return Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS

def image_enhance(FamID, input_dir, upscale_factor = 10):
    '''
    Intakes raw pedigree image file and upscales for downstream analysis

    PARAMETERS:
    -----------
    FamID (string): ID denoting the particular pedigree for intake (should match PNG file name exactly)
    input_dir (string): file path where input pedigree image is found
    upscale_factor (int): the degree to which the raw pedigree image should be upscaled (default = 10)

    RETURN:
    -------
    output_path (string): complete file path from wd to upscaled image
    '''
    input_path = f'{input_dir}/{FamID}.png'

    img = Image.open(input_path)

    new_size = (img.width * upscale_factor, img.height * upscale_factor)
    upscaled_img = img.resize(new_size, _resample_filter())
    output_path = f'{input_dir}/{FamID}_{upscale_factor}Xupscaled.png'
    upscaled_img.save(output_path)
    return output_path

def upscaled_image(image_path, upscale_factor = 10):
    '''
    Reads a pedigree image and upscales it in memory, without writing a copy next to it

    RETURN:
    -------
    the upscaled image as an OpenCV (BGR) array
    '''
    img = Image.open(image_path).convert('RGB')
    new_size = (round(img.width * upscale_factor), round(img.height * upscale_factor))
    upscaled_img = img.resize(new_size, _resample_filter())
    return cv2.cvtColor(np.array(upscaled_img), cv2.COLOR_RGB2BGR)

def upscaled_gray_image(image_path, upscale_factor = 10):
    '''
    Reads a pedigree image and upscales it in memory, in grey. The image is made grey before it is enlarged rather
    than after, which takes a third of the memory, and gives the same image for a drawing in black, white and grey

    RETURN:
    -------
    the upscaled image as a grey OpenCV array
    '''
    img = Image.open(image_path).convert('RGB').convert('L')
    new_size = (round(img.width * upscale_factor), round(img.height * upscale_factor))
    return np.array(img.resize(new_size, _resample_filter()))

#: the size, across, that a symbol is read best at once the picture is enlarged, in pixels. The lines are traced and
#: joined with distances in pixels that suit symbols of about this size: the Lynch family's picture, enlarged by
#: different factors, reads correctly with its symbols from about 140 to 425 pixels across, but not at 106 or 531
SYMBOL_PIXELS = 200
#: the most pixels that an enlarged picture may have, as memory is short in a browser and the work grows with the
#: pixels: about as many as the default of 10 used to make of a picture 1,000 pixels across
MAX_PIXELS = 60_000_000

def _upscale_needed(image_path):
    '''
    The factor that makes a picture's symbols SYMBOL_PIXELS across, before any limit: the symbols are found in a copy
    of the picture 2,000 pixels across on its longer side (enlarged, or shrunk, which is quicker than measuring a large
    picture whole), and their median size is measured. None if no symbols are found there. Also the picture's size.
    '''
    img = Image.open(image_path).convert('RGB').convert('L')
    width, height = img.size
    probe = 2000 / max(width, height)
    small = np.array(img.resize((max(1, round(width*probe)), max(1, round(height*probe))), _resample_filter()))
    del img
    _, binary = cv2.threshold(small, 127, 255, cv2.THRESH_BINARY)
    del small
    #(symbols are looked for down to a tenth of the usual size, as a small pedigree on a large page may have small ones)
    symbols, _ = detect_symbols(binary, binary.shape[0]*binary.shape[1], min_share= 0.00001)
    sizes = [max(w, h) for (_, _, w, h), _, _ in symbols]
    return (SYMBOL_PIXELS*probe/float(np.median(sizes)) if sizes else None), width, height

def _limit_upscale(factor, width, height):
    '''A factor kept between 0.25 and 20, and so that the enlarged picture has no more than MAX_PIXELS pixels, rounded
    down to one decimal place (down, so as not to pass the limits)'''
    factor = min(factor, 20, (MAX_PIXELS/(width*height))**0.5)
    return max(0.25, math.floor(factor*10 + 1e-9)/10)

def choose_upscale(image_path):
    '''
    How many times to enlarge a picture before reading it, so that its symbols are about SYMBOL_PIXELS across.

    The symbols are found in a copy of the picture 2,000 pixels across on its longer side, and their median size is
    measured. If none are found there, the picture is enlarged to 5,000 pixels across, which suits most pictures of a
    whole pedigree. The factor is kept between 0.25 and 20, and small enough that the enlarged picture has no more
    than MAX_PIXELS pixels.

    RETURN:
    -------
    the factor (a number, rounded down to one decimal place)
    '''
    needed, width, height = _upscale_needed(image_path)
    return _limit_upscale(needed if needed is not None else 5000/width, width, height)

def linDist(coord1, coord2):
    x1, y1 = coord1
    x2, y2 = coord2

    return((x2-x1)**2+(y2-y1)**2)**0.5


def closestLabel(marker_coords, label_dict):
    closest_distance = math.inf
    closestLabel = None
    for label in label_dict.keys():
        label_x, label_y, label_w, label_h = label_dict[label]['label_coords']
        label_coords = ((label_x + label_w/2), (label_y + label_h/2))
        distance = linDist(marker_coords, label_coords)
        if distance < closest_distance:
            closest_distance = distance
            closestLabel = label
    return closestLabel


#-----------------------------
# READING THE LABELS
#-----------------------------
class TesseractUnavailable(RuntimeError):
    '''Tesseract can't be used: pytesseract isn't installed, or the tesseract program can't be run'''

def tesseract_words(image):
    '''
    Reads the words in a grey image with Tesseract. The labels are scattered over the drawing rather than set in
    lines of text, which is what Tesseract's sparse text mode (11) is for.

    RETURN:
    -------
    a list of (text, left, top, width, height), in the image's pixels.
    Raises TesseractUnavailable, saying why, if pytesseract isn't installed or the tesseract program can't be run
    '''
    if sys.platform == 'emscripten':
        raise TesseractUnavailable('Pyodide cannot run other programs, such as tesseract')
    try:
        import pytesseract
    except ImportError:
        raise TesseractUnavailable('pytesseract is not installed') from None
    try:
        data = pytesseract.image_to_data(image, config= '--psm 11', output_type= pytesseract.Output.DICT)
    except pytesseract.TesseractNotFoundError:
        raise TesseractUnavailable(f'the tesseract program was not found (pytesseract looked for '
                                   f'"{pytesseract.pytesseract.tesseract_cmd}")') from None
    except OSError as error:
        raise TesseractUnavailable(f'the tesseract program could not be run ({error})') from None
    return list(zip(data['text'], data['left'], data['top'], data['width'], data['height']))

def label_boxes(words, scale):
    '''
    Picks out the labels from the words that OCR read, and scales their boxes up to the enlarged image

    PARAMETERS:
    -----------
    words: (text, left, top, width, height) for each word, in the pixels of the image that was read
    scale (number): how much larger the enlarged image is than the image that was read

    RETURN:
    -------
    a dict of each label's box (x, y, w, h) in the enlarged image, and a list of the boxes of all the labels,
    which includes any label that appears more than once
    '''
    words = [('' if text is None else str(text).strip(), left, top, width, height)
             for text, left, top, width, height in words]
    words = [word for word in words if word[0]]
    #a symbol is sometimes read as a letter (a circle as O): such "text" is as tall as a symbol, much taller than the labels
    label_height = float(np.median([height for _, _, _, _, height in words])) if words else 0
    labels = {}
    boxes = []
    for text, left, top, width, height in words:
        if height <= 1.5*label_height:
            box = tuple(int(scale*value) for value in (left, top, width, height))
            if text in labels:
                warnings.warn(f'The label {text} appears more than once; only the last is used')
            labels[text] = box
            boxes.append(box)
    return labels, boxes


#-----------------------------
# NUMBERING PEOPLE
#-----------------------------
def roman_numeral(number):
    '''A whole number from 1 up in Roman numerals'''
    numerals = ((1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'), (100, 'C'), (90, 'XC'),
                (50, 'L'), (40, 'XL'), (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I'))
    roman = ''
    for value, numeral in numerals:
        while number >= value:
            roman += numeral
            number -= value
    return roman

def generation_places(boxes):
    '''
    Places symbols in the rows of the drawing, which are the generations. The middles of the symbols are taken from
    the top down, and a gap of more than half a symbol's height from one to the next starts a new row, so a symbol
    drawn a little higher or lower than the others in its row stays in it.

    PARAMETERS:
    -----------
    boxes: the symbols' bounding boxes (x, y, w, h)

    RETURN:
    -------
    for each box, (row, place in the row), both counted from 0, with the rows from the top and the places from the left
    '''
    if not boxes:
        return []
    middles = [y + h/2 for _, y, _, h in boxes]
    gap = 0.5*float(np.median([h for _, _, _, h in boxes]))
    from_top = sorted(range(len(boxes)), key= lambda i: middles[i])
    rows = [[from_top[0]]]
    for above, i in zip(from_top, from_top[1:]):
        if middles[i] - middles[above] > gap:
            rows.append([])
        rows[-1].append(i)
    places = [None]*len(boxes)
    for row, members in enumerate(rows):
        for place, i in enumerate(sorted(members, key= lambda i: boxes[i][0] + boxes[i][2]/2)):
            places[i] = (row, place)
    return places

def generation_id(row, place):
    '''The usual ID for the person at a place in a row (both counted from 0): generation, in Roman numerals, and number'''
    return f'{roman_numeral(row + 1)}-{place + 1}'


#-----------------------------
# SYMBOL DETECTION
#-----------------------------
def stroke_width(dark_mask):
    '''
    Estimates the width of the drawing's lines from a mask of its dark pixels (255 where dark).
    Most runs of dark pixels across a row or down a column cross a line, so the most common run length is the line width.
    '''
    runs = []
    for arr in (dark_mask, dark_mask.T):
        step = max(1, arr.shape[0] // 400)
        for row in arr[::step]:
            dark = np.concatenate(([0], (row > 0).astype(np.int8), [0]))
            edges = np.flatnonzero(np.diff(dark))
            runs.extend((edges[1::2] - edges[0::2]).tolist())
    if not runs:
        return 1
    counts = np.bincount(runs)
    return max(1, int(np.argmax(counts)))

def symbol_sex(contour):
    '''
    Sex from a symbol's shape: a circle is female (2), a square male (1) and a diamond of unknown sex (0).
    A circle fills about 79% (pi/4) of the smallest rectangle around it, at any angle, where a square or a diamond
    fills nearly all of it. A square also fills its upright bounding box, but a diamond only fills half of its box.
    Measuring areas rather than counting corners copes with ragged outlines, as in a JPEG or a scan,
    and with corners rounded off.
    '''
    area = cv2.contourArea(contour)
    (_, _), (rw, rh), _ = cv2.minAreaRect(contour)
    _, _, w, h = cv2.boundingRect(contour)
    if not (rw and rh and w and h):
        return 0
    if area / (rw * rh) < 0.89:
        return 2
    return 1 if area / (w * h) > 0.8 else 0

def open_with_disc(mask, radius):
    '''
    Morphological opening of a mask (255 where set) with a disc of the given radius: what is left is every part that
    a disc of that size fits inside. Done with two distance transforms, which take the same time for a disc of any size.
    The distances take four bytes a pixel, so one array of them serves for both transforms, and the masks made from
    them take a byte a pixel: an image enlarged ten times is large, and memory is short in a browser.
    '''
    #erosion: the places more than the radius from the edge of the mask (the core), where the distances are over it
    distance = cv2.distanceTransform(mask, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    if cv2.minMaxLoc(distance)[1] <= radius:
        return np.zeros_like(mask)
    outside_core = cv2.compare(distance, radius, cv2.CMP_LE)
    #dilation: the places within the radius of the core
    distance = cv2.distanceTransform(outside_core, cv2.DIST_L2, cv2.DIST_MASK_PRECISE, dst= distance)
    del outside_core
    opened = cv2.compare(distance, radius, cv2.CMP_LE)
    del distance
    opened[mask == 0] = 0
    return opened

def detect_symbols(gray_img, img_area, min_share= 0.0001):
    '''
    Finds the pedigree's symbols: filled (affected) symbols from the dark parts of the image, with the lines
    removed first so that a line touching a symbol doesn't join it to the rest of the drawing, and
    unfilled (unaffected) symbols from the white space inside their outlines.

    The holes in the letters and numbers of any labels left in the drawing (in 0, 6, 8, 9, A, B, D and so on) are
    white space inside an outline too, but they are much smaller than the symbols. Each shape is measured outline
    and all: an unfilled symbol is found by the white inside it, so the width of the outline round that white is
    added on either side (and for a hole in a letter, the width of the letter's stroke).
    Anything less than half the size of a typical symbol is then left out: the median size of the filled symbols,
    which text never passes for, or if none is filled, the size that nine in ten of the shapes found are smaller
    than. So is anything less than three line widths across, which alone wouldn't do, as the lines of a drawing can
    be much thinner than the strokes of its text.

    Shapes that overlap are one symbol: a slash through the symbol of someone who has died cuts the white inside
    it in two, and the two pieces are joined again, the symbol's shape taken from the hull around both. A small
    shape inside a larger one of the other kind, such as a carrier's dot, is left out.

    RETURN:
    -------
    symbols (list of (bounding box (x, y, w, h), Sex, Phenotype)), and the width of the drawing's lines in pixels
    '''
    #(each mask is made only when it's needed, and let go as soon as it isn't, to save memory)
    _, threshold_dark = cv2.threshold(gray_img, 5, 255, cv2.THRESH_BINARY_INV)

    #lines are narrower than the symbols: opening the dark parts with a disc wider than a line removes the lines and keeps filled symbols
    line_width = stroke_width(threshold_dark)
    filled_symbols = open_with_disc(threshold_dark, 1.5*line_width)
    del threshold_dark
    dark_contours, _ = cv2.findContours(filled_symbols, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    del filled_symbols

    _, threshold_light = cv2.threshold(gray_img, 250, 255, cv2.THRESH_BINARY)
    light_contours, hierarchy = cv2.findContours(threshold_light, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    #the white inside an outline is a patch of white of its own, whose edge is an outer contour, at an even depth in
    #the tree of contours. The contours at odd depths are the edges of dark shapes seen from the white around them:
    #one of these goes all the way round the drawing, and could otherwise pass for a very large symbol
    def depth(i):
        d = 0
        while hierarchy[0][i][3] != -1:
            i = hierarchy[0][i][3]
            d += 1
        return d
    light_contours = [contour for i, contour in enumerate(light_contours) if depth(i) % 2 == 0]

    candidates = []
    for phenotype, contours in ((2, dark_contours), (1, light_contours)):
        for contour in contours:
            #scaling epsilon used in polyaprox based on perimeter of the contour
            epsilon =0.02 * cv2.arcLength(contour, closed= True)
            approx = cv2.approxPolyDP(contour, epsilon, True)

            x,y,w,h = cv2.boundingRect(approx)
            bounding_area = w*h
            if bounding_area < 0.25*img_area and bounding_area > min_share*img_area and abs(w-h) < (min(w,h) * 0.25):
                outline = outline_width(threshold_light, (x, y, w, h), line_width) if phenotype == 1 else 0
                candidates.append({'box': (x, y, w, h), 'contours': [contour], 'phenotype': phenotype,
                                   'size': max(w, h), 'outer': max(w, h) + 2*outline})
    del threshold_light
    if not candidates:
        return [], line_width

    #leaving out the holes in text. Labels can have more holes than there are symbols, so when no symbol is filled,
    #the typical symbol is one bigger than nine in ten of what was found
    sizes = [c['outer'] for c in candidates]
    filled_sizes = [c['outer'] for c in candidates if c['phenotype'] == 2]
    typical = float(np.median(filled_sizes)) if filled_sizes else float(np.percentile(sizes, 90))
    candidates = [c for c in candidates if c['outer'] >= max(3*line_width, 0.5*typical)]
    symbols = [(c['box'], symbol_sex(c['contours'][0] if len(c['contours']) == 1
                                     else cv2.convexHull(np.vstack(c['contours']))), c['phenotype'])
               for c in join_overlapping(candidates)]
    return symbols, line_width

def outline_width(light_mask, box, line_width):
    '''
    The width of the outline round the white inside a symbol (or the stroke round a hole in a letter): the longest
    run of dark pixels outwards from the middle of a side of the white's box, but no more than two line widths. The
    longest, because blanking out a label can cut into the outline on one side; no more than two line widths,
    because a line meeting the symbol makes the run on that side longer.
    '''
    x, y, w, h = box
    height, width = light_mask.shape[:2]
    cap = 2*line_width

    def inside(px, py):
        return 0 <= px < width and 0 <= py < height

    runs = []
    for (px, py), (dx, dy) in (((x + w//4, y + h//2), (-1, 0)), ((x + 3*w//4, y + h//2), (1, 0)),
                               ((x + w//2, y + h//4), (0, -1)), ((x + w//2, y + 3*h//4), (0, 1))):
        #from inside the white (the box of a simplified outline can fall short of it), out to its edge, then across
        #the dark outline
        while inside(px, py) and light_mask[py, px] != 0:
            px, py = px + dx, py + dy
        run = 0
        while run < cap and inside(px, py) and light_mask[py, px] == 0:
            run += 1
            px, py = px + dx, py + dy
        runs.append(run)
    return max(runs)

def join_overlapping(candidates):
    '''
    Joins candidates whose boxes overlap: those of the same kind (filled or not) into one, with the box round them
    all, and of different kinds by keeping the larger
    '''
    def overlap(a, b):
        ax, ay, aw, ah = a['box']
        bx, by, bw, bh = b['box']
        return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah

    joined = []
    for c in sorted(candidates, key= lambda c: -c['size']):
        for kept in joined:
            if overlap(c, kept):
                if c['phenotype'] == kept['phenotype']:
                    kx, ky, kw, kh = kept['box']
                    cx, cy, cw, ch = c['box']
                    left, top = min(kx, cx), min(ky, cy)
                    right, bottom = max(kx + kw, cx + cw), max(ky + kh, cy + ch)
                    kept['box'] = (left, top, right - left, bottom - top)
                    kept['contours'].extend(c['contours'])
                    kept['size'] = max(right - left, bottom - top)
                break
        else:
            joined.append(c)
    return joined

def erase_loose_marks(binary_img, boxes):
    '''
    Whitens every dark shape in a black and white image (0 where dark) that reaches into none of the boxes, and
    returns the image. With the boxes round the symbols, this clears away any text left in the drawing, and stray
    marks, whose strokes could otherwise be taken for lines. Every line touches a symbol, so the lines stay.

    PARAMETERS:
    -----------
    binary_img: the image, changed in place
    boxes: the boxes, as (left, top, right, bottom)
    '''
    #each dark shape is numbered, from 1, and the white is 0
    count, shapes = cv2.connectedComponents(cv2.bitwise_not(binary_img), connectivity= 8)
    keep = np.zeros(count, dtype= bool)
    keep[0] = True
    height, width = binary_img.shape[:2]
    for left, top, right, bottom in boxes:
        left, top = max(0, int(left)), max(0, int(top))
        right, bottom = min(width, int(right)), min(height, int(bottom))
        if left < right and top < bottom:
            keep[np.unique(shapes[top:bottom, left:right])] = True
    binary_img[(~keep)[shapes]] = 255
    return binary_img


#-----------------------------
# LINE DETECTION
#-----------------------------
def merge_duplicate_lines(norm_cat_lines, angle_threshold= 10, distance_threshold= 50):
    '''
    Joins lines that run along one another, less than distance_threshold apart, and that overlap or meet end to end:
    Hough finds both edges of a thick line, and often finds a line in pieces. Each joined line keeps the position
    of the longer of the two. The lines are gone over again until no more can be joined, so that the pieces of a
    line are all joined whatever order they come in.
    '''
    def merge_horizontal(lines):
        merged_horizontal_lines = []
        for horz_line in lines:
            a,hy1,b,hy2 = horz_line
            for i in range(len(merged_horizontal_lines)):
                c,mhy1,d,mhy2 = merged_horizontal_lines[i]
                #sufficiently close vertically, and overlapping or touching
                if abs(mhy1 - hy1) < distance_threshold and a <= d and c <= b:
                    y = hy1 if b - a > d - c else mhy1
                    merged_horizontal_lines[i] = (min(a, c), y, max(b, d), y)
                    break
            else:
                merged_horizontal_lines.append(horz_line)
        return merged_horizontal_lines

    #vertical lines run from the bottom (the larger y) up
    def merge_vertical(lines):
        merged_vertical_lines = []
        for vert_line in lines:
            vx1,a,vx2,b = vert_line
            for j in range(len(merged_vertical_lines)):
                mvx1,c,mvx2,d = merged_vertical_lines[j]
                #sufficiently close horizontally, and overlapping or touching
                if abs(mvx1 - vx1) < distance_threshold and b <= c and d <= a:
                    x = vx1 if a - b > c - d else mvx1
                    merged_vertical_lines[j] = (x, max(a, c), x, min(b, d))
                    break
            else:
                merged_vertical_lines.append(vert_line)
        return merged_vertical_lines

    directional_merged_lines = {}
    for direction, merge in (('vertical', merge_vertical), ('horizontal', merge_horizontal)):
        lines = list(norm_cat_lines[direction])
        while True:
            merged = merge(lines)
            if len(merged) == len(lines):
                break
            lines = merged
        directional_merged_lines[direction] = merged

    return directional_merged_lines



def categorize_normalize_lines(lines, img_width, img_height, tilt_threshold = 200):
    categorized_normalized_lines = {
    'vertical': [],
    'horizontal': []
    }

    #HoughLinesP returns None when it finds no lines, and its array's shape is (n, 1, 4) in OpenCV 4 but (n, 4) in OpenCV 5
    if lines is None:
        return categorized_normalized_lines
    uncategorized = 0
    for line in np.asarray(lines).reshape(-1, 4):
        x1,y1,x2,y2 = (int(v) for v in line)
        #deleting exessively long and short duplicates/artifacts
        if (
            (abs(x2-x1) > 0.8*img_width or abs(y2-y1) > 0.8*img_height) or
            (abs(x2-x1) < 0.01*img_width and abs(y2-y1) < 0.01*img_height)
        ):
            continue
        if abs(x1 - x2) < tilt_threshold:
            if y1 < y2:
                z = y1
                y1 = y2
                y2 = z
            categorized_normalized_lines['vertical'].append((x1, y1, x2, y2))
        elif abs(y1 - y2) < tilt_threshold:
            if x1 > x2:
                z = x1
                x1 = x2
                x2 = z
            categorized_normalized_lines['horizontal'].append((x1, y1, x2, y2))
        else:
            uncategorized += 1

    if uncategorized:
        warnings.warn(f'{uncategorized} line(s) were neither horizontal nor vertical and were left out')
    return categorized_normalized_lines



def cut_at_symbols(norm_cat_lines, boxes):
    '''
    Cuts the lines where they cross a symbol, keeping the pieces outside. No line passes through a symbol, but Hough
    joins the pieces of a line across gaps, and the blank left where a symbol was taken out is a gap like any other.
    Without this, the line down to a child is joined to the line above them that leads down to their parent drawn
    straight above them, and the child is given their grandparents; and the lines from someone to partners on either
    side of them are joined into one, which makes the partners a couple.
    boxes: the symbols, as (left, top, right, bottom) with the margin blanked out round them
    '''
    def outside(start, end, cuts):
        pieces, at = [], start
        for a, b in sorted(cuts):
            if b <= at or a >= end:
                continue
            if a > at:
                pieces.append((at, a))
            at = max(at, b)
        if at < end:
            pieces.append((at, end))
        return pieces

    cut = {'vertical': [], 'horizontal': []}
    #a vertical line runs from the bottom (x1, y1) up to the top (x2, y2)
    for x1, y1, x2, y2 in norm_cat_lines['vertical']:
        x_at = lambda y: x1 if y1 == y2 else x1 + (x2 - x1)*(y1 - y)/(y1 - y2)
        crossed = [(top, bottom) for left, top, right, bottom in boxes if left <= max(x1, x2) and min(x1, x2) <= right]
        for top, bottom in outside(y2, y1, crossed):
            cut['vertical'].append((int(round(x_at(bottom))), int(bottom), int(round(x_at(top))), int(top)))
    #a horizontal line runs from the left (x1, y1) to the right (x2, y2)
    for x1, y1, x2, y2 in norm_cat_lines['horizontal']:
        y_at = lambda x: y1 if x1 == x2 else y1 + (y2 - y1)*(x - x1)/(x2 - x1)
        crossed = [(left, right) for left, top, right, bottom in boxes if top <= max(y1, y2) and min(y1, y2) <= bottom]
        for left, right in outside(x1, x2, crossed):
            cut['horizontal'].append((int(left), int(round(y_at(left))), int(right), int(round(y_at(right)))))
    return cut



def partners_at_ends(line, IndvID, IndvDataDict, distance_threshold):
    '''
    The people at the two ends of a horizontal line: at each end, whoever has a side of their symbol within
    distance_threshold of it (the closest, if several do), or None if no one does. IndvID itself is left out.
    '''
    x1, y1, x2, y2 = line
    partners = []
    for end in ((x1, y1), (x2, y2)):
        best, best_distance = None, distance_threshold
        for PartnerID in IndvDataDict.keys():
            if PartnerID == IndvID:
                continue
            px_left, py_top, pw, ph = IndvDataDict[PartnerID]['node_coords']
            #a line now stops at the edge of the margin blanked out round the symbol
            ppad = IndvDataDict[PartnerID].get('pad', 0)
            for side in ((px_left - ppad, py_top + ph/2), (px_left + pw + ppad, py_top + ph/2)):
                distance = linDist(side, end)
                if distance < best_distance:
                    best, best_distance = PartnerID, distance
        partners.append(best)
    return partners

def first_line_above(vert_line, horizontal_lines, below, distance_threshold):
    '''
    The horizontal line that a vertical line meets first going up from the height below: the nearest line above it
    that the vertical line crosses or reaches (to within distance_threshold), or None. Not just the line at its top:
    Hough can carry a line on past the line it meets, across a gap to a line further up.
    '''
    Vx1, Vy1, Vx2, Vy2 = vert_line
    best, best_y = None, None
    for horz_line in horizontal_lines:
        Hx1, Hy1, Hx2, Hy2 = horz_line
        Hy = (Hy1 + Hy2)/2
        if not (Vy2 - distance_threshold < Hy < below):
            continue
        #where the vertical line is at that height (it may lean a little)
        Vx = Vx1 if Vy1 == Vy2 else Vx1 + (Vx2 - Vx1)*(Vy1 - Hy)/(Vy1 - Vy2)
        if Hx1 - distance_threshold < Vx < Hx2 + distance_threshold and (best_y is None or Hy > best_y):
            best, best_y = horz_line, Hy
    return best

def trackRelation(normalized_categorized_lines, IndvDataDict):
    connection_lines = []

    for IndvID in IndvDataDict.keys():
        IndvDataDict[IndvID]['PaternalID'] = 0
        IndvDataDict[IndvID]['MaternalID'] = 0
        inheritence_known = False
        #finding starting coordinate (top anchor)
        x_left, y_top, w, h = IndvDataDict[IndvID]['node_coords']
        #the symbol was blanked out with a margin round it, so the lines meeting it now stop at the edge of the margin
        pad = IndvDataDict[IndvID].get('pad', 0)
        x_mid = int(x_left + w/2)
        top_center_coord = (x_mid, y_top - pad)
        IndvDataDict[IndvID]['lat_coords'] = [(int(x_left+w+pad), int(y_top+(h/2))), (int(x_left-pad), int(y_top+(h/2)))]
        distance_threshold = h/2
        #finding if there is veritcal line close to top anchor (i.e. if inheritence is known)
        for vert_line in normalized_categorized_lines['vertical']:
            Vx1,Vy1,Vx2,Vy2 = vert_line
            if linDist(top_center_coord, (Vx1,Vy1)) < distance_threshold:
                start_coord = (Vx1,Vy1)
                current_coord = (Vx2, Vy2)
                inheritence_known = True

                break

        #checking if parental relationship was found
        #tracing back to parents if known
        if inheritence_known:
            horizontal = normalized_categorized_lines['horizontal']
            #(a line that Hough makes at the foot of this one, where it meets the symbol, out of the end of the line and
            #what is left of a slash through the symbol, isn't one it leads to: the line it leads to is further up)
            endpoints = first_line_above(vert_line, horizontal, start_coord[1] - distance_threshold/2, distance_threshold)
            if endpoints is None:
                warnings.warn(f'{IndvID}: a line leaves the top of the symbol but leads to no other line, so the parents are unknown')
                continue

            #a line with someone at each end is the partners' line, which is reached straight away from an only child,
            #or from a child drawn right under the partners' line. Otherwise this is the line over a sibship, and the
            #partners' line is the first line that the line coming down to it meets on the way up
            left_parent, right_parent = partners_at_ends(endpoints, IndvID, IndvDataDict, distance_threshold)
            if left_parent is None and right_parent is None:
                Cx1,Cy1,Cx2,Cy2 = endpoints
                for vert_line in normalized_categorized_lines['vertical']:
                    Vx1,Vy1,Vx2,Vy2 = vert_line
                    #a line that crosses the sibship's line and goes on up: adding distance threshold to Vy2 leaves out
                    #the lines that go down from it to the children. A child's line that Hough has carried on up past
                    #it leads to no partners' line, so the lines are tried until one does
                    if (Vy1+distance_threshold > Cy1 and Cy1 > Vy2+distance_threshold) and (Cx1-distance_threshold < Vx1 and Vx1 < Cx2+distance_threshold):
                        above = first_line_above(vert_line, horizontal, Cy1 - distance_threshold/2, distance_threshold)
                        if above is None:
                            continue
                        partners = partners_at_ends(above, IndvID, IndvDataDict, distance_threshold)
                        if partners != [None, None]:
                            endpoints = above
                            left_parent, right_parent = partners
                            break

            fx1,fy1,fx2,fy2 = endpoints
            sx, sy = start_coord
            connection_lines = connection_lines + [(sx,sy,fx1,fy1), (sx,sy,fx2,fy2)]

            #the father is the male partner, and the mother the female one, wherever they are drawn.
            #only when their sexes don't tell is the left partner taken as the father, as pedigrees are usually drawn
            father, mother = left_parent, right_parent
            left_sex = IndvDataDict[left_parent].get('Sex') if left_parent is not None else None
            right_sex = IndvDataDict[right_parent].get('Sex') if right_parent is not None else None
            if left_sex == 2 or right_sex == 1:
                father, mother = right_parent, left_parent
            if father is not None:
                IndvDataDict[IndvID]['PaternalID'] = father
            if mother is not None:
                IndvDataDict[IndvID]['MaternalID'] = mother

    return IndvDataDict, connection_lines

def missed_lines(IndvDataDict, lines, row_of):
    '''
    What a line missed between the symbols looks like, in the people read, as sentences for warnings:
    - someone with only one parent;
    - someone below the top row with neither parents nor children, and no partners' line to them either (a partner
      with no children is joined by one, though a PED file can't join them to anyone);
    - people joined by parents and children into more than one family of two or more, as when the line up from
      someone who has children is missed;
    - no one with parents at all, though there are symbols in more than one row and lines between them.

    PARAMETERS:
    -----------
    IndvDataDict: the people, with their PaternalID and MaternalID (0 if not found) and node_coords
    lines: the lines found, {'horizontal': [...], 'vertical': [...]}
    row_of: each person's row in the drawing, from 0 at the top
    '''
    found = []
    for IndvID, person in IndvDataDict.items():
        if bool(person['PaternalID']) != bool(person['MaternalID']):
            found.append(f"{IndvID}: only {'a father' if person['PaternalID'] else 'a mother'} was found, so a line may "
                         'have been missed')
    parents = {p for person in IndvDataDict.values() for p in (person['PaternalID'], person['MaternalID']) if p}
    anyone = bool(parents)
    #partners: the people at the two ends of a horizontal line
    threshold = float(np.median([person['node_coords'][3] for person in IndvDataDict.values()]))/2
    partnered = set()
    for line in lines['horizontal']:
        ends = partners_at_ends(line, None, IndvDataDict, threshold)
        if None not in ends:
            partnered.update(ends)
    alone = [IndvID for IndvID, person in IndvDataDict.items()
             if row_of[IndvID] > 0 and not (person['PaternalID'] or person['MaternalID'])
             and IndvID not in parents and IndvID not in partnered]
    if alone and anyone:
        found.append(f'{", ".join(alone)}: joined to no one, with neither parents, children nor a partner found, so a '
                     'line may have been missed')
    #the families that parents and children join people into, leaving out anyone on their own
    family_of = {IndvID: IndvID for IndvID in IndvDataDict}
    def root(IndvID):
        while family_of[IndvID] != IndvID:
            family_of[IndvID] = family_of[family_of[IndvID]]
            IndvID = family_of[IndvID]
        return IndvID
    for IndvID, person in IndvDataDict.items():
        for parent in (person['PaternalID'], person['MaternalID']):
            if parent in family_of:
                family_of[root(IndvID)] = root(parent)
    sizes = {}
    for IndvID in IndvDataDict:
        sizes[root(IndvID)] = sizes.get(root(IndvID), 0) + 1
    families = sorted((n for n in sizes.values() if n > 1), reverse=True)
    if len(families) > 1:
        found.append(f'The people read fall into {len(families)} families, not one (of {", ".join(map(str, families))} '
                     'people), so a line joining them may have been missed')
    rows = len(set(row_of.values()))
    #(with no lines at all, pedigree_processing says so)
    if rows > 1 and (lines['vertical'] or lines['horizontal']) and not anyone:
        found.append(f"No one's parents were found, though the symbols are in {rows} rows, so the lines between them "
                     'may not have been read')
    return found

def pedigree_processing(FamID,
                        raw_image_dir = '.',
                        export= False,
                        output_dir = '.',
                        image_path = None,
                        upscale_factor = None,
                        ocr = 'tesseract'):
    '''
    Reads a pedigree image into a dataframe laid out like a PED file

    PARAMETERS:
    -----------
    FamID (string): the family's ID. Unless image_path is given, the image is raw_image_dir/<FamID>.png
    raw_image_dir (string): the folder the image is in
    export (bool): whether to write the PED file too, as output_dir/<FamID>.ped
    output_dir (string): the folder to write the PED file in
    image_path (string, optional): the image to read, in any format Pillow reads
    upscale_factor (number, optional): how many times to enlarge the image before reading it. By default, the
        factor that makes its symbols about SYMBOL_PIXELS across (choose_upscale), which the result records in its
        attrs['upscale_factor']
    ocr: how to read the labels (default = 'tesseract')
        'tesseract': with Tesseract. If pytesseract isn't installed or the tesseract program can't be run,
            people are numbered instead, with a warning that says why
        None or 'none': the labels aren't read, and people are numbered
        a function: given the grey image to be read (a numpy uint8 array of the image enlarged at most 3 times),
            it returns the words in it as (text, left, top, width, height), in that image's pixels.
            This is how other OCR, such as tesseract.js in a browser, can read the labels

    People are numbered the standard way: the generations are the rows of symbols from the top, in Roman numerals,
    and the people in each row are numbered from the left: I-1, I-2, II-1 and so on. When the labels are read,
    anyone whose label wasn't read is numbered in the same way, with a warning.

    RETURN:
    -------
    pandas.DataFrame with the columns FamilyID, IndividualID, PaternalID, MaternalID, Sex and Phenotype,
    with a row for each person, generation by generation, and from left to right in each
    '''
    if ocr is None or (isinstance(ocr, str) and ocr.lower() == 'none'):
        read_words = None
    elif isinstance(ocr, str) and ocr.lower() == 'tesseract':
        read_words = tesseract_words
    elif callable(ocr):
        read_words = ocr
    else:
        raise ValueError(f"ocr must be 'tesseract', 'none', None or a function, not {ocr!r}")
    numbering = 'numbered by generation instead (I-1, I-2, II-1 and so on)'

    #----------------------------------------
    # ENHANCE IMAGE
    #----------------------------------------
    if image_path is None:
        image_path = f'{raw_image_dir}/{FamID}.png'
    needed = None
    if upscale_factor is None:
        needed, picture_width, picture_height = _upscale_needed(image_path)
        upscale_factor = _limit_upscale(needed if needed is not None else 5000/picture_width, picture_width, picture_height)
    if needed is not None and needed > 1.5*upscale_factor:
        #(a limit kept the factor well short of what the symbols need: a picture too small, or one too large to enlarge so far)
        if upscale_factor >= 20:
            warnings.warn(f"The symbols in {image_path} are very small: the picture is enlarged 20 times, the most, but "
                          f"they need {needed:.0f} times. A larger copy of the picture would read better")
        else:
            warnings.warn(f"The picture is too large to enlarge {needed:.1f} times, as its symbols need, so it is "
                          f"enlarged {upscale_factor:g} times. If the pedigree is only part of the picture, cut the "
                          f"picture down to it")
    gray_img = upscaled_gray_image(image_path, upscale_factor)
    img_height, img_width = gray_img.shape
    img_area = img_height * img_width

    #the drawing is black on white, so anything nearer white than black is taken as white: this clears the grey haze
    #that JPEG compression and scanning leave around lines and text
    _, redacted_img = cv2.threshold(gray_img, 127, 255, cv2.THRESH_BINARY)
    del gray_img

    #----------------------------------------
    # INDIVIDUAL ID DETECTION
    #----------------------------------------
    #Tesseract reads text best when it's a few tens of pixels high, and starts to misread labels enlarged ten times,
    #so the labels are read from a copy of the image enlarged no more than three times (in grey, which it also reads
    #better), and their places are scaled up to match
    labels, label_area = {}, []
    if read_words is not None:
        ocr_factor = min(upscale_factor, 3)
        ocr_img = cv2.cvtColor(upscaled_image(image_path, ocr_factor), cv2.COLOR_BGR2GRAY)
        try:
            words = read_words(ocr_img)
        except TesseractUnavailable as reason:
            warnings.warn(f"The labels can't be read with Tesseract, as {reason}, so people are {numbering}. "
                          'Pass ocr=None to number people without this warning.')
        else:
            labels, label_area = label_boxes(words if words is not None else [], upscale_factor / ocr_factor)
            if not labels:
                warnings.warn(f'No labels were read in {image_path}, so people are {numbering}.' +
                              (' Tesseract seldom reads labels of a single character.' if read_words is tesseract_words else ''))
        del ocr_img
    for x, y, w, h in label_area:
        #draw a white rectangle over the ID number (with a little extra size for buffer)
        redacted_img = cv2.rectangle(redacted_img, (x-10,y-10), (x+w+20, y+h+20), (255,255,255), -1)

    #----------------------------------------
    # PHENOTYPE AND SEX DETECTION
    #----------------------------------------
    symbols, line_width = detect_symbols(redacted_img, img_area)
    if not symbols:
        if upscale_factor >= 20:
            raise ValueError(f'No pedigree symbols were found in {image_path}, even enlarged {upscale_factor:g} times: '
                             'the picture may be too small to read, and a larger copy of it would read better')
        raise ValueError(f'No pedigree symbols were found in {image_path}. If the pedigree is only a small part of '
                         'the picture, as on a page, cut the picture down to the pedigree')

    #each symbol goes with the nearest label, and each label keeps the nearest of the symbols that chose it
    label_dict = {label: {'label_coords': box} for label, box in labels.items()}
    nearest = {}
    for i, ((x, y, w, h), _, _) in enumerate(symbols):
        if not label_dict:
            break
        center_coords = ((x + w/2), y + h/2)
        label = closestLabel(marker_coords= center_coords, label_dict= label_dict)
        lx, ly, lw, lh = labels[label]
        distance = linDist(center_coords, (lx + lw/2, ly + lh/2))
        if distance <= 3*max(w, h) and (label not in nearest or distance <= nearest[label][0]):
            nearest[label] = (distance, i)
    IDs = {i: label for label, (_, i) in nearest.items()}

    unmatched = [label for label in labels if label not in nearest]
    if unmatched:
        warnings.warn(f'No symbol was found for the text {", ".join(unmatched)}, which is left out')

    #anyone without a label is numbered by their place in the drawing, which is also the order people are listed in.
    #A label that was read can be the same as such a number (when the drawing's own labels are numbered like this,
    #and one was misread), so a star is added to the number to keep the IDs apart
    places = generation_places([box for box, _, _ in symbols])
    in_order = sorted(range(len(symbols)), key= lambda i: places[i])
    taken = set(IDs.values())
    numbered = []
    for i in in_order:
        if i not in IDs:
            IndvID = generation_id(*places[i])
            while IndvID in taken:
                IndvID += '*'
            IDs[i] = IndvID
            taken.add(IndvID)
            numbered.append(IndvID)
    if labels and numbered:
        warnings.warn(f'{len(numbered)} symbol(s) had no label of their own near them, and are numbered by their '
                      f'place in the drawing instead: {", ".join(numbered)}.' +
                      (' Tesseract often misses labels of a single character.' if read_words is tesseract_words else ''))

    IndvIDsDict = {}
    for i in in_order:
        (x, y, w, h), sex, phenotype = symbols[i]
        #the margin round the symbol that is blanked out, so that only the lines between symbols are left
        #(an unfilled symbol was found by the space inside its outline, so its outline is a line's width further out)
        pad = (2 if phenotype == 1 else 1)*line_width + int(0.05*max(w, h))
        IndvIDsDict[IDs[i]] = {'node_coords': (x,y,w,h), 'Phenotype': phenotype, 'Sex': sex, 'pad': pad}

    #clearing away any text left in the drawing (all of it, when the labels aren't read) and any stray marks: whatever
    #doesn't come near enough a symbol for the lines to be traced from it. A line is traced from the top of a symbol
    #and from its sides, up to half the symbol's height beyond the margin blanked out round it, so a line that stops
    #short of the symbol is kept as long as the tracing would reach it. Lines don't meet a symbol from below, where its
    #label usually is, so below a symbol only what touches its outline is kept
    reach = [(x - person['pad'] - h/2, y - person['pad'] - h/2, x + w + person['pad'] + h/2, y + h + line_width)
             for person in IndvIDsDict.values() for x, y, w, h in [person['node_coords']]]
    nodeless_img = erase_loose_marks(np.copy(redacted_img), reach)
    #then blanking out the symbols
    for person in IndvIDsDict.values():
        x, y, w, h = person['node_coords']
        pad = person['pad']
        nodeless_img = cv2.rectangle(nodeless_img, (x-pad, y-pad), (x+w+pad, y+h+pad), (255,255,255), -1)


    #----------------------------------------
    # RELATION DETECTION
    #----------------------------------------
    edges = cv2.Canny(nodeless_img, 0, 50, apertureSize= 3)
    raw_lines = cv2.HoughLinesP(edges,
                            rho=1,
                            theta= np.pi/180,
                            threshold= 50,
                            minLineLength= 5,
                            maxLineGap= img_width*0.1)

    line_img = np.copy(redacted_img)*0
    cat_norm_lines = categorize_normalize_lines(raw_lines, img_width, img_height)
    boxes = [(x - person['pad'], y - person['pad'], x + w + person['pad'], y + h + person['pad'])
             for person in IndvIDsDict.values() for x, y, w, h in [person['node_coords']]]
    cat_norm_lines = cut_at_symbols(cat_norm_lines, boxes)

    lines = merge_duplicate_lines(cat_norm_lines)
    if len(symbols) > 1 and not (lines['vertical'] or lines['horizontal']):
        warnings.warn(f'No lines were found between the symbols in {image_path}, so no one\'s parents are known')
    for direction in lines.keys():
        for line in lines[direction]:
            x1, y1, x2, y2 = line
            line_img = cv2.line(line_img, (x1,y1), (x2,y2), (255,255,255), 5)

    IndvIDsDict, connection_lines = trackRelation(lines, IndvIDsDict)

    for warning in missed_lines(IndvIDsDict, lines, {IDs[i]: places[i][0] for i in range(len(symbols))}):
        warnings.warn(f'{warning}. The picture was enlarged {upscale_factor:g} times: try a little more or less')

    for line in connection_lines:
        x1, y1, x2, y2 = line
        line_img = cv2.line(line_img, (x1,y1), (x2,y2), (255,255,255), 5)
    for individual in IndvIDsDict.keys():
        for coord in IndvIDsDict[individual]['lat_coords']:
            line_img = cv2.circle(line_img, coord, radius=10, color=(255,255,255), thickness=-1)

    #package pedigree data into dataframe structured like PED file
    PedFileDataFields = ['PaternalID', 'MaternalID', 'Sex', 'Phenotype']
    #constructs df and subsets to PED file format-relevant fields
    PedFileDF = pd.DataFrame.from_dict(IndvIDsDict, orient= 'index')[PedFileDataFields]

    #adding individualID and FamilyID Fields (reordered to fit PED file format)
    PedFileDF.index.name = 'IndividualID'
    PedFileDF = PedFileDF.reset_index()
    PedFileDF['FamilyID'] = [FamID]*len(PedFileDF)
    PedFileDF = PedFileDF.reindex(columns= ['FamilyID', 'IndividualID']+PedFileDataFields)
    PedFileDF.attrs['upscale_factor'] = upscale_factor

    if export:
        PED_export(PedFileDF, output_dir= output_dir)

    return PedFileDF

#---------------------------------------------
# Main Pedigree Interpretation Function Test
#---------------------------------------------
if __name__ == '__main__':
    ChosenID = input('Enter A Family ID for testing: ')
    image_dir = 'data/Pedigree_Images/Raw_Images'
    FamilyPEdFileDF = pedigree_processing(FamID= ChosenID, raw_image_dir= image_dir, export= True)
    print(FamilyPEdFileDF)


