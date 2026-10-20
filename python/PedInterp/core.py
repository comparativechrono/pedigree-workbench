import cv2
import math
import os
import sys
import warnings
import numpy as np
from PIL import Image, ImageChops
from os import makedirs
import pandas as pd
from .lines import read_lines
from .shapes import SEX, TRIANGLE, find_sketched_symbols, shape_of, twins_bar
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

#: the condition that a GA4GH Pedigree from PedInterp records when none is given: Mondo's most general term, as a
#: picture doesn't say what the condition is
GA4GH_CONDITION = ('MONDO:0000001', 'disease')

def ga4gh_condition(condition=None):
    '''
    A condition for a GA4GH Pedigree, as (id, label): an ontology term that a GA4GH file can name, such as
    ('MONDO:0007739', 'Huntington disease') or ('HP:0000365', 'Hearing impairment'), with its id tidied. None gives
    GA4GH_CONDITION. Raises ValueError, saying what is wrong, for anything else.
    '''
    from pedigree_ga4gh import ontology
    if condition is None:
        return GA4GH_CONDITION
    if isinstance(condition, str) or len(condition) != 2:
        raise ValueError(f"the condition must be an ontology term and its label, such as "
                         f"('MONDO:0007739', 'Huntington disease'), not {condition!r}")
    cid, label = ontology.tidy_curie(str(condition[0])), str(condition[1]).strip()
    if not ontology.is_curie(cid) or not ontology.can_declare(ontology.prefix_of(cid)):
        raise ValueError(f'{cid!r} is not an ontology term that a GA4GH file can name: give one such as '
                         f'MONDO:0007739 (Mondo), HP:0000365 (the HPO), OMIM:143100 or ORPHA:399')
    if not label:
        raise ValueError(f'the condition {cid} needs a label, its name in its ontology')
    return cid, label

def _id(value):
    '''An id as text: 3, not 3.0'''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)

def twin_groups(PED_df):
    '''
    The sets of twins (or triplets, and so on) in a dataframe read by pedigree_processing, from its attrs['twins']:
    a list of (first, [(other, identical), ...]), with the first of each set the one listed first in the dataframe,
    which is the one on the left, and each other twin with whether they are identical to the first. Twins joined only
    through a third are identical only if every pair of them is, as studio2ga4gh has it.
    '''
    order = {_id(person): k for k, person in enumerate(PED_df['IndividualID'])}
    pairs = [(_id(a), _id(b), str(kind).upper()) for a, b, kind in PED_df.attrs.get('twins') or []
             if _id(a) in order and _id(b) in order and _id(a) != _id(b)]
    root = {}
    def find(person):
        while root.setdefault(person, person) != person:
            person = root[person]
        return person
    for a, b, _ in pairs:
        root[find(a)] = find(b)
    sets = {}
    for person in list(root):
        sets.setdefault(find(person), []).append(person)
    found = []
    for group in sorted(sets.values(), key= lambda group: min(order[p] for p in group)):
        group.sort(key= order.get)
        first, links = group[0], [(a, b, kind) for a, b, kind in pairs if a in group]
        others = []
        for other in group[1:]:
            direct = [kind for a, b, kind in links if {a, b} == {first, other}]
            others.append((other, direct[0] == 'MZ' if direct else all(kind == 'MZ' for _, _, kind in links)))
        found.append((first, others))
    return found

def GA4GH_export(PED_df, output_dir = '.', condition = None):
    '''
    Writes a PED file-formatted dataframe as a GA4GH Pedigree, output_dir/<FamilyID>_ga4gh-pedigree.json, and returns
    the file's path. It is the form that studio2ga4gh writes and the lab's other GA4GH tools read (ga4gh2studio,
    phenopacket-toolkit, PedNet): each person is a Phenopacket, and each parent is joined to their children by a
    relationship (KIN:028 for a father, KIN:027 for a mother). It needs pedigree-ga4gh, which pip installs with
    PedInterp.

    A GA4GH Pedigree records who is affected only through their conditions, so condition is the one the pedigree is
    about, as an ontology term (id, label): see ga4gh_condition. Affected people have it, unaffected people have it
    marked as excluded (looked for, and not found), and anyone whose phenotype is unknown has nothing, so that the
    PED file's phenotypes can be read back from the GA4GH file.

    Twins, which a PED file can't hold, are written from the dataframe's attrs['twins'] (as pedigree_processing reads
    them), as studio2ga4gh writes them: each twin is related to the first of their set, on the left, as an identical
    twin (KIN:010, isMonozygoticMultipleBirthSiblingOf) or a non-identical one (KIN:011,
    isPolyzygoticMultipleBirthSiblingOf).
    '''
    from pedigree_ga4gh import DISEASE, PHENOTYPE, Kindred, Member, Relation, Term, dumps, kin, ontology, to_ga4gh_pedigree
    from . import __version__
    cid, label = ga4gh_condition(condition)
    kind = PHENOTYPE if ontology.prefix_of(cid) == 'HP' else DISEASE
    FamID = _id(PED_df['FamilyID'].iloc[0])
    members, relations = [], []
    for row in PED_df.itertuples(index= False):
        person, phenotype = _id(row.IndividualID), int(row.Phenotype)
        terms = [Term(label, cid, kind= kind, excluded= phenotype == 1)] if phenotype in (1, 2) else []
        members.append(Member(person, sex= {1: 'MALE', 2: 'FEMALE'}.get(int(row.Sex), 'UNKNOWN_SEX'), terms= terms))
        for parent, code in ((row.PaternalID, kin.BIOLOGICAL_FATHER), (row.MaternalID, kin.BIOLOGICAL_MOTHER)):
            if _id(parent) not in ('0', ''):
                relations.append(Relation(_id(parent), code, person))
    twin_sets = twin_groups(PED_df)
    for first, others in twin_sets:
        for other, identical in others:
            relations.append(Relation(first, kin.MONOZYGOTIC_MULTIPLE_BIRTH_SIBLING if identical
                                      else kin.POLYZYGOTIC_MULTIPLE_BIRTH_SIBLING, other))
    narrative = f'Read with PedInterp {__version__}'
    if PED_df.attrs.get('image'):
        narrative += f' from {PED_df.attrs["image"]}'
    if PED_df.attrs.get('upscale_factor'):
        narrative += f', enlarged {PED_df.attrs["upscale_factor"]:g} times'
    affected = int((PED_df['Phenotype'] == 2).sum())
    narrative += f'. {len(members)} people, {affected} affected with {label} ({cid}).'
    if twin_sets:
        narrative += ' Twins: ' + '; '.join(
            ', '.join([first] + [other for other, _ in others]) +
            (' (identical)' if all(identical for _, identical in others) else
             ' (not identical)' if not any(identical for _, identical in others) else '')
            for first, others in twin_sets) + '.'
    doc, _ = to_ga4gh_pedigree(Kindred(FamID, members= members, relations= relations, narrative= narrative),
                               created_by= f'PedInterp {__version__}')
    makedirs(output_dir, exist_ok= True)
    path = f'{output_dir}/{FamID}_ga4gh-pedigree.json'
    with open(path, 'w', encoding= 'utf-8') as fh:
        fh.write(dumps(doc))
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

def open_picture(image_path):
    '''
    A picture as an RGB image, with anything transparent made white, as a drawing is black on white: a PNG saved with
    a transparent background would otherwise be read as black all over
    '''
    img = Image.open(image_path)
    if img.mode in ('RGBA', 'LA', 'PA') or (img.mode == 'P' and 'transparency' in img.info):
        img = img.convert('RGBA')
        white = Image.new('RGBA', img.size, (255, 255, 255, 255))
        white.alpha_composite(img)
        img = white
    return img.convert('RGB')

def ink_image(img):
    '''
    A picture in grey, as dark as its darkest colour at each pixel (the least of red, green and blue): black and grey
    stay as they are, and coloured ink, a red line or a symbol filled in yellow as Pedigree Studio fills them, is dark,
    where in an ordinary grey image a yellow, orange or light grey is as light as white is taken to be
    '''
    red, green, blue = img.split()
    return ImageChops.darker(ImageChops.darker(red, green), blue)

def upscaled_image(image_path, upscale_factor = 10):
    '''
    Reads a pedigree image and upscales it in memory, without writing a copy next to it

    RETURN:
    -------
    the upscaled image as an OpenCV (BGR) array
    '''
    img = open_picture(image_path)
    new_size = (round(img.width * upscale_factor), round(img.height * upscale_factor))
    upscaled_img = img.resize(new_size, _resample_filter())
    return cv2.cvtColor(np.array(upscaled_img), cv2.COLOR_RGB2BGR)

def upscaled_gray_image(image_path, upscale_factor = 10):
    '''
    Reads a pedigree image and upscales it in memory, in grey (ink_image: coloured ink is dark). The image is made
    grey before it is enlarged rather than after, which takes a third of the memory, and gives the same image for a
    drawing in black, white and grey

    RETURN:
    -------
    the upscaled image as a grey OpenCV array
    '''
    img = ink_image(open_picture(image_path))
    new_size = (round(img.width * upscale_factor), round(img.height * upscale_factor))
    return np.array(img.resize(new_size, _resample_filter()))

#: the size, across, that a symbol is read best at once the picture is enlarged, in pixels. The lines are traced and
#: joined with distances in pixels that suit symbols of about this size: the Lynch family's picture, enlarged by
#: different factors, reads correctly with its symbols from about 140 to 425 pixels across, but not at 106 or 531
SYMBOL_PIXELS = 200
#: the most pixels that an enlarged picture may have, as memory is short in a browser and the work grows with the
#: pixels: about as many as the default of 10 used to make of a picture 1,000 pixels across
MAX_PIXELS = 60_000_000
#: the size, across, that the symbols of a pedigree drawn by hand are read at (hand_drawn=True): about the size that
#: Pedigree Studio saves its pictures at, so that a sketch made with its Draw tool is read as it is
SKETCH_PIXELS = 100
#: how dark a pixel must be to be taken as ink, from 0 (black) to 255 (white): anything nearer white than black is
#: white, which clears the grey haze that JPEG compression and scanning leave around lines and text. In a sketch, the
#: lines are thin and drawn in colour, and anything darker than a light grey is ink
INK = 127
SKETCH_INK = 160
#: how dark the lines of a drawing usually are, at the lightest: Pedigree Studio draws its lines and symbols in a dark
#: blue-grey (#1a2332) and writes its numbers over the symbols in a lighter grey (#6b7a8d), and the numbers are told
#: from the lines by it (erase_labels). Enlarging the picture makes the thin strokes of the numbers a little darker
#: than they were, but no darker than this
DARK = 55
LABELS = True
#: what a warning says when a pedigree may have been drawn by hand
HAND_DRAWN_HINT = ("If the pedigree is drawn by hand, in whole or in part, as with Pedigree Studio's Draw tool, read "
                   'it with hand_drawn=True, which allows for rough symbols and lines')

def _upscale_needed(image_path, hand_drawn= False):
    '''
    The factor that makes a picture's symbols SYMBOL_PIXELS across (SKETCH_PIXELS for a sketch), before any limit: the
    symbols are found in a copy of the picture 2,000 pixels across on its longer side (enlarged, or shrunk, which is
    quicker than measuring a large picture whole), and their median size is measured. None if no symbols are found
    there. Also the picture's size.

    The symbols are looked for as the reading looks for them, and only if none are found, down to a tenth of the
    usual size, as a small pedigree on a large page may have small ones. Looked for so small from the start, the
    holes in the letters of the labels pass for symbols when the lines are thinner than the strokes of the text, and
    the picture would be enlarged as much as the holes need.
    '''
    img = ink_image(open_picture(image_path))
    width, height = img.size
    probe = 2000 / max(width, height)
    small = np.array(img.resize((max(1, round(width*probe)), max(1, round(height*probe))), _resample_filter()))
    del img
    _, binary = cv2.threshold(small, SKETCH_INK if hand_drawn else INK, 255, cv2.THRESH_BINARY)
    del small
    if hand_drawn:
        symbols, _, _ = sketched_symbols(binary)
        target = SKETCH_PIXELS
    else:
        area = binary.shape[0]*binary.shape[1]
        symbols, _ = detect_symbols(binary, area)
        if not symbols:
            symbols, _ = detect_symbols(binary, area, min_share= 0.00001)
        target = SYMBOL_PIXELS
    sizes = [max(w, h) for (_, _, w, h), *_ in symbols]
    return (target*probe/float(np.median(sizes)) if sizes else None), width, height

def _limit_upscale(factor, width, height):
    '''A factor kept between 0.25 and 20, and so that the enlarged picture has no more than MAX_PIXELS pixels, rounded
    down to one decimal place (down, so as not to pass the limits)'''
    factor = min(factor, 20, (MAX_PIXELS/(width*height))**0.5)
    return max(0.25, math.floor(factor*10 + 1e-9)/10)

def choose_upscale(image_path, hand_drawn= False):
    '''
    How many times to enlarge a picture before reading it, so that its symbols are about SYMBOL_PIXELS across
    (SKETCH_PIXELS, with hand_drawn).

    The symbols are found in a copy of the picture 2,000 pixels across on its longer side, and their median size is
    measured. If none are found there, the picture is enlarged to 5,000 pixels across (2,500 for a sketch), which suits
    most pictures of a whole pedigree. The factor is kept between 0.25 and 20, and small enough that the enlarged
    picture has no more than MAX_PIXELS pixels.

    RETURN:
    -------
    the factor (a number, rounded down to one decimal place)
    '''
    needed, width, height = _upscale_needed(image_path, hand_drawn)
    return _limit_upscale(needed if needed is not None else (2500 if hand_drawn else 5000)/width, width, height)

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
    the top down, and a new row starts where there is a gap of more than half a symbol's height from one to the next,
    and the symbol is more than a symbol's height below the first of the row. So a symbol drawn a little higher or
    lower than the others in its row stays in it, and so does a row that slopes, as one drawn by hand may, and as
    rows can in Pedigree Studio, which takes everyone up to 80 pixels below the top of a row, a symbol and a half, as
    in it.

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
    height = float(np.median([h for _, _, _, h in boxes]))
    from_top = sorted(range(len(boxes)), key= lambda i: middles[i])
    rows = [[from_top[0]]]
    for above, i in zip(from_top, from_top[1:]):
        if middles[i] - middles[above] > 0.5*height and middles[i] - middles[rows[-1][0]] > height:
            rows.append([])
        rows[-1].append(i)
    places = [None]*len(boxes)
    for row, members in enumerate(rows):
        for place, i in enumerate(sorted(members, key= lambda i: boxes[i][0] + boxes[i][2]/2)):
            places[i] = (row, place)
    return places

def number_people(boxes, labelled):
    '''
    IDs for the people at the symbols with the given boxes: their labels where they were read (labelled: index -> label),
    and otherwise numbered by their place in the drawing (generation_places, generation_id). A label that was read can
    be the same as such a number (when the drawing's own labels are numbered like this, and one was misread), so a
    star is added to the number to keep the IDs apart.

    RETURN:
    -------
    IDs (index -> ID), the places (row, place) of the symbols, the indices in the order people are listed (by row, and
    from the left in each), and the IDs that were numbered
    '''
    IDs = dict(labelled)
    places = generation_places(boxes)
    in_order = sorted(range(len(boxes)), key= lambda i: places[i])
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
    return IDs, places, in_order, numbered

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
    Sex from a symbol's shape: a circle is female (2), a square male (1), and a diamond, or the triangle of a pregnancy
    loss, of unknown sex (0), as studio2ped writes them. The shape is read from the way the outline turns (see
    shapes.turning), which copes with ragged outlines, as in a JPEG or a scan, with corners rounded off, and with
    shapes drawn by hand.
    '''
    return SEX[shape_of(contour)]

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
    symbols (list of (bounding box (x, y, w, h), Sex, Phenotype, shape)), with the shape 'square', 'circle', 'diamond' or
    'triangle', and the width of the drawing's lines in pixels
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
    symbols = []
    ink = None
    for c in join_overlapping(candidates):
        contour = c['contours'][0] if len(c['contours']) == 1 else cv2.convexHull(np.vstack(c['contours']))
        shape = shape_of(contour)
        if shape == TRIANGLE:
            #the space between the lines to identical twins and the bar across them is a triangle too, and would be read
            #as someone of unknown sex between the twins
            if ink is None:
                ink = cv2.compare(gray_img, 127, cv2.CMP_LT)
            if twins_bar(contour, ink, typical):
                continue
        symbols.append((c['box'], SEX[shape], c['phenotype'], shape))
    return symbols, line_width

def sketched_symbols(binary_img):
    '''
    Finds the symbols of a pedigree drawn by hand (shapes.find_sketched_symbols), in a black and white image (0 where
    dark) at a size where a symbol is roughly 60 to 200 pixels across.

    RETURN:
    -------
    symbols (list of (bounding box (x, y, w, h), Sex, Phenotype, shape)), as detect_symbols gives them, the width of
    the drawing's lines in pixels, and the outline of the whole of each symbol, outline and all, to blank it out with
    '''
    ink = (binary_img == 0).astype(np.uint8)
    line_width = stroke_width(ink)
    found, _ = find_sketched_symbols(ink, line_width)
    symbols = [(cv2.boundingRect(c['outer']), SEX[c['shape']], 2 if c['filled'] else 1, c['shape']) for c in found]
    return symbols, line_width, [c['outer'] for c in found]

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

def erase_labels(line_mask, dark, boxes, size):
    '''
    Takes out of the lines of a drawing the labels written just above its symbols, as Pedigree Studio writes its
    numbers over them. A label written close under a line that passes over the symbol, as the line over a family's
    children passes over someone who married into it, touches the line, crosses it or nearly touches it, and its
    letters would be read as a line down to the person.

    A label is a word: two or more small pieces of ink side by side, the letters, taller than a line is thick but no
    taller than letters are, above a symbol; or one such piece that is wider than it is tall, as letters run together
    are. A line, even a short one down to a child, is a single stroke, and is kept.

    Where a label is written in a lighter colour than the lines, as Pedigree Studio writes its numbers in grey, and
    touches a line or crosses it, the two are told apart by how dark they are: the light edge of a dark line is cut
    away from it, so that the letters it touches stand on their own, and a line that the letters cross is kept whole
    where they cross it. Only long dark lines count, not the darker spots of a line drawn in a lighter colour, where it
    was drawn over twice.

    PARAMETERS:
    -----------
    line_mask: the lines of the drawing, not 0 where there is ink, with the symbols blanked out; changed in place
    dark: where the ink is as dark as the lines usually are (DARK), not 0
    boxes: the symbols, as (x, y, w, h)
    size: the typical size of a symbol, in pixels

    RETURN:
    -------
    how many letters were taken out
    '''
    ink = line_mask > 0
    if not boxes or not ink.any():
        return 0
    #the dark lines, with the gaps closed that the letters of a label written over a line leave in it
    #(an odd size, so that closing keeps every pixel of the lines: OpenCV's closing with an even-sized kernel drops
    #a row or column of them)
    closing = max(3, int(round(0.06*size))) | 1
    dark_ink = ink & (dark > 0)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        cv2.morphologyEx(dark_ink.astype(np.uint8), cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_RECT, (closing, closing))), connectivity= 8)
    long = np.zeros(count, bool)
    long[1:] = np.maximum(stats[1:, 2], stats[1:, 3]) >= 0.5*size
    band = long[labels]
    del labels
    light = ink & (dark == 0)
    #the light edge that smoothing leaves along a dark line, straight beside its dark ink (a letter that crosses the
    #line, where it breaks the dark ink, is not beside it there)
    edge = max(2, int(round(0.025*size)))
    beside = cv2.dilate((dark_ink & band).astype(np.uint8),
                        cv2.getStructuringElement(cv2.MORPH_CROSS, (2*edge + 1, 2*edge + 1))) > 0
    del dark_ink
    count, labels, stats, _ = cv2.connectedComponentsWithStats((ink & ~band & ~(light & beside)).astype(np.uint8),
                                                               connectivity= 8)
    del beside
    #above each symbol, where its label is written: across its top, and as far again as a label is wide to either side
    zones = [(x - 0.8*size, y - 0.45*size, x + w + 0.8*size, y + 0.1*size) for x, y, w, h in boxes]
    pieces = [k for k in range(1, count) if max(stats[k][2], stats[k][3]) <= 0.3*size and
              any(left <= stats[k][0] and stats[k][0] + stats[k][2] <= right and
                  top <= stats[k][1] and stats[k][1] + stats[k][3] <= bottom for left, top, right, bottom in zones)]
    def joined(pairs):
        group = {k: k for k in pieces}
        def find(k):
            while group[k] != k:
                group[k] = group[group[k]]
                k = group[k]
            return k
        for a, b in pairs:
            group[find(a)] = find(b)
        found = {}
        for k in pieces:
            found.setdefault(find(k), []).append(k)
        return list(found.values())
    def extent(members):
        left = min(stats[k][0] for k in members)
        top = min(stats[k][1] for k in members)
        return (left, top, max(stats[k][0] + stats[k][2] for k in members) - left,
                max(stats[k][1] + stats[k][3] for k in members) - top)
    #a letter that crosses a line is cut in two by it, one piece above the other, which are one letter
    letters = joined((a, b) for i, a in enumerate(pieces) for b in pieces[i + 1:]
                     if min(stats[a][0] + stats[a][2], stats[b][0] + stats[b][2]) - max(stats[a][0], stats[b][0])
                        >= 0.5*min(stats[a][2], stats[b][2])
                     and max(stats[b][1] - (stats[a][1] + stats[a][3]), stats[a][1] - (stats[b][1] + stats[b][3]))
                        <= 0.08*size)
    boxes_of = [extent(members) for members in letters]
    #letters side by side, level with each other, make words (with room between them for a hyphen, which a label written
    #on a line, as in "III-4", loses into the line)
    def beside_each_other(a, b):
        ax, ay, aw, ah = boxes_of[a]
        bx, by, bw, bh = boxes_of[b]
        return min(ay + ah, by + bh) - max(ay, by) >= 0.5*min(ah, bh) and max(bx - (ax + aw), ax - (bx + bw)) <= 0.15*size
    word_of = list(range(len(letters)))
    def word(k):
        while word_of[k] != k:
            word_of[k] = word_of[word_of[k]]
            k = word_of[k]
        return k
    for a in range(len(letters)):
        for b in range(a + 1, len(letters)):
            if beside_each_other(a, b):
                word_of[word(a)] = word(b)
    words = {}
    for k in range(len(letters)):
        words.setdefault(word(k), []).append(k)
    #a letter is taller than a line is thick, and a word is no taller than a letter
    tall = 0.06*size
    text = np.zeros(count, bool)
    for members in words.values():
        _, top, _, height = extent([k for m in members for k in letters[m]])
        high = [m for m in members if boxes_of[m][3] >= tall]
        if height > 0.25*size:
            continue
        if len(high) >= 2 or (len(members) == 1 and high and boxes_of[members[0]][2] >= 1.2*boxes_of[members[0]][3]):
            for m in members:
                text[letters[m]] = True
    if not text.any():
        return 0
    found = text[labels]
    del labels
    #the line where the letters cross it is kept: within the dark line, and where a letter crosses the end of a level
    #or upright line, in line with it, as where the line runs on under the letters to a symbol and the last letter
    #is written against the symbol, with no dark line beyond it to close the gap with
    run = max(3, int(round(0.1*size)))
    reach = max(2, int(round(0.08*size)))
    keep = band.astype(np.uint8)
    level = cv2.morphologyEx(keep, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (run, 1)))
    upright = cv2.morphologyEx(keep, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, run)))
    keep = band | (cv2.dilate(level, cv2.getStructuringElement(cv2.MORPH_RECT, (2*reach + 1, 1))) > 0) | \
           (cv2.dilate(upright, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 2*reach + 1))) > 0)
    del level, upright
    #(with the light edge of the letters, and of a light label what was cut from the line it touches)
    disc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*edge + 1, 2*edge + 1))
    line_mask[(found | ((cv2.dilate(found.astype(np.uint8), disc) > 0) & light)) & ~keep] = 0
    return int(np.count_nonzero(text))


#-----------------------------
# LINE DETECTION
#-----------------------------
def missed_lines(IndvDataDict, partners, any_lines, row_of):
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
    partners: the couples joined by a partners' line, as pairs of IDs
    any_lines: whether there are any lines between the symbols
    row_of: each person's row in the drawing, from 0 at the top
    '''
    found = []
    for IndvID, person in IndvDataDict.items():
        if bool(person['PaternalID']) != bool(person['MaternalID']):
            found.append(f"{IndvID}: only {'a father' if person['PaternalID'] else 'a mother'} was found, so a line may "
                         'have been missed')
    parents = {p for person in IndvDataDict.values() for p in (person['PaternalID'], person['MaternalID']) if p}
    anyone = bool(parents)
    partnered = {p for pair in partners for p in pair}
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
    if rows > 1 and any_lines and not anyone:
        found.append(f"No one's parents were found, though the symbols are in {rows} rows, so the lines between them "
                     'may not have been read')
    return found

def read_relations(line_mask, IndvDataDict, gap= 0.45):
    '''
    Reads who is whose partner, parent and twin from the lines between the symbols (lines.read_lines), and sets each
    person's PaternalID and MaternalID (0 when not found).

    PARAMETERS:
    -----------
    line_mask: the drawing with its symbols blanked out, not 0 where there are lines
    IndvDataDict: the people, with their node_coords (x, y, w, h), pad (the margin blanked out round the symbol) and Sex
    gap: how far a line may stop short of the line it meets, as a share of a symbol's size

    RETURN:
    -------
    what lines.read_lines found: a dict of parents, partners, twins and notes
    '''
    people = {pid: {'box': d['node_coords'], 'pad': d.get('pad', 0), 'Sex': d.get('Sex')} for pid, d in IndvDataDict.items()}
    found = read_lines(line_mask, people, gap= gap)
    for pid, d in IndvDataDict.items():
        father, mother = found['parents'].get(pid, (None, None))
        d['PaternalID'] = father if father is not None else 0
        d['MaternalID'] = mother if mother is not None else 0
    return found

def pedigree_processing(FamID,
                        raw_image_dir = '.',
                        export= False,
                        output_dir = '.',
                        image_path = None,
                        upscale_factor = None,
                        ocr = 'auto',
                        hand_drawn = False):
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
    ocr: how to read the labels (default = 'auto')
        'auto': with Tesseract, unless the pedigree is hand_drawn: its labels, if it has any, are written by hand,
            which Tesseract can't read, and it may take the strokes that fill a sketched symbol in for letters, so
            people are numbered
        'tesseract': with Tesseract. If pytesseract isn't installed or the tesseract program can't be run,
            people are numbered instead, with a warning that says why
        None or 'none': the labels aren't read, and people are numbered
        a function: given the grey image to be read (a numpy uint8 array of the image enlarged at most 3 times),
            it returns the words in it as (text, left, top, width, height), in that image's pixels.
            This is how other OCR, such as tesseract.js in a browser, can read the labels
    hand_drawn (bool): whether the pedigree is sketched by hand, as with Pedigree Studio's Draw tool, in part or in
        whole (default = False). The symbols may then be of unequal sizes, their outlines may not quite close, and
        filled ones may be scribbled in; the lines may wobble, slope, and stop short of what they join. The picture
        is read at a size where its symbols are about SKETCH_PIXELS across, and any colour darker than a light grey
        is taken as ink

    Twins are read from the lines that join them to their parents' line at one point, and identical twins from the bar
    between those lines; the result lists them in attrs['twins'], as [twin, twin, 'MZ' or 'DZ'], with the twin on the
    left first. A PED file can't hold them, and PED_export leaves them out, but GA4GH_export and Studio_export write
    them. So do the couples joined by a line, with children or without (attrs['partners'], as [partner, partner]), and
    where each person was drawn (attrs['layout']: id -> {'box': [x, y, width, height] in the picture's pixels, 'row':
    the row of symbols from the top, counted from 0, 'shape': 'square', 'circle', 'diamond' or 'triangle'}), which
    Studio_export lays the drawing out by.

    People are numbered the standard way: the generations are the rows of symbols from the top, in Roman numerals,
    and the people in each row are numbered from the left: I-1, I-2, II-1 and so on. When the labels are read,
    anyone whose label wasn't read is numbered in the same way, with a warning.

    RETURN:
    -------
    pandas.DataFrame with the columns FamilyID, IndividualID, PaternalID, MaternalID, Sex and Phenotype,
    with a row for each person, generation by generation, and from left to right in each
    '''
    if isinstance(ocr, str) and ocr.lower() == 'auto':
        ocr = None if hand_drawn else 'tesseract'
    if ocr is None or (isinstance(ocr, str) and ocr.lower() == 'none'):
        read_words = None
    elif isinstance(ocr, str) and ocr.lower() == 'tesseract':
        read_words = tesseract_words
    elif callable(ocr):
        read_words = ocr
    else:
        raise ValueError(f"ocr must be 'auto', 'tesseract', 'none', None or a function, not {ocr!r}")
    numbering = 'numbered by generation instead (I-1, I-2, II-1 and so on)'

    #----------------------------------------
    # ENHANCE IMAGE
    #----------------------------------------
    if image_path is None:
        image_path = f'{raw_image_dir}/{FamID}.png'
    needed = None
    if upscale_factor is None:
        needed, picture_width, picture_height = _upscale_needed(image_path, hand_drawn)
        upscale_factor = _limit_upscale(needed if needed is not None else (2500 if hand_drawn else 5000)/picture_width,
                                        picture_width, picture_height)
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
    #that JPEG compression and scanning leave around lines and text (in a sketch, anything darker than a light grey is
    #ink, as its lines are thin and often drawn in colour)
    _, redacted_img = cv2.threshold(gray_img, SKETCH_INK if hand_drawn else INK, 255, cv2.THRESH_BINARY)
    #where the ink is as dark as lines are, to tell lighter text from them (erase_labels), kept a bit a pixel
    dark_bits = np.packbits(gray_img <= DARK)
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
    outlines = None
    if hand_drawn:
        symbols, line_width, outlines = sketched_symbols(redacted_img)
    else:
        symbols, line_width = detect_symbols(redacted_img, img_area)
    if not symbols:
        if upscale_factor >= 20:
            raise ValueError(f'No pedigree symbols were found in {image_path}, even enlarged {upscale_factor:g} times: '
                             'the picture may be too small to read, and a larger copy of it would read better' +
                             ('' if hand_drawn else f'. {HAND_DRAWN_HINT}'))
        raise ValueError(f'No pedigree symbols were found in {image_path}. If the pedigree is only a small part of '
                         'the picture, as on a page, cut the picture down to the pedigree' +
                         ('' if hand_drawn else f'. {HAND_DRAWN_HINT}'))

    #each symbol goes with the nearest label, and each label keeps the nearest of the symbols that chose it
    label_dict = {label: {'label_coords': box} for label, box in labels.items()}
    nearest = {}
    for i, ((x, y, w, h), *_) in enumerate(symbols):
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
    label_IDs = dict(IDs)
    IDs, places, in_order, numbered = number_people([symbol[0] for symbol in symbols], label_IDs)
    if labels and numbered:
        warnings.warn(f'{len(numbered)} symbol(s) had no label of their own near them, and are numbered by their '
                      f'place in the drawing instead: {", ".join(numbered)}.' +
                      (' Tesseract often misses labels of a single character.' if read_words is tesseract_words else ''))

    IndvIDsDict = {}
    for i in in_order:
        (x, y, w, h), sex, phenotype, shape = symbols[i]
        #the margin round the symbol that is blanked out, so that only the lines between symbols are left
        #(an unfilled symbol was found by the space inside its outline, so its outline is a line's width further out)
        #(in a sketch, a symbol's outline wobbles, and a scribble may fall short of the outline round it)
        #(a sketch's symbols are blanked out by their own outlines, which they were found with whole)
        pad = 2 if hand_drawn else (2 if phenotype == 1 else 1)*line_width + int(0.05*max(w, h))
        IndvIDsDict[IDs[i]] = {'node_coords': (x,y,w,h), 'Phenotype': phenotype, 'Sex': sex, 'pad': pad, 'shape': shape}
        if outlines is not None:
            IndvIDsDict[IDs[i]]['outline'] = outlines[i]

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
        if 'outline' in person:
            cv2.drawContours(nodeless_img, [person['outline']], -1, 255, -1)
            cv2.drawContours(nodeless_img, [person['outline']], -1, 255, 2*pad + 1)
        else:
            nodeless_img = cv2.rectangle(nodeless_img, (x-pad, y-pad), (x+w+pad, y+h+pad), (255,255,255), -1)


    #----------------------------------------
    # RELATION DETECTION
    #----------------------------------------
    #the lines are read as networks of lines, one for each family (lines.read_lines): who are partners, whose children
    #are whose, and which children are twins
    row_of = {IDs[i]: places[i][0] for i in range(len(symbols))}
    line_mask = cv2.threshold(nodeless_img, 127, 255, cv2.THRESH_BINARY_INV)[1]
    del nodeless_img
    #the numbers written over the symbols in a lighter colour than the lines, as Pedigree Studio writes them, which
    #a line may pass close above
    if LABELS:
        dark = np.unpackbits(dark_bits, count= line_mask.size).reshape(line_mask.shape)
        boxes = [person['node_coords'] for person in IndvIDsDict.values()]
        erase_labels(line_mask, dark, boxes, float(np.median([max(w, h) for _, _, w, h in boxes])))
        del dark
    del dark_bits
    any_lines = bool(line_mask.any())
    #(a line drawn by hand may stop well short of the line it was meant to meet)
    found = read_relations(line_mask, IndvIDsDict, gap= 0.45 if hand_drawn else 0.25)
    del line_mask
    partners, twins, notes = found['partners'], found['twins'], found['notes']
    if found['junctions']:
        #what was taken for a symbol at the point the lines to twins come from is no person: the others are
        #numbered again without it
        gone = set(found['junctions'])
        keep = [i for i in range(len(symbols)) if IDs[i] not in gone]
        new_IDs, new_places, new_order, _ = number_people([symbols[i][0] for i in keep],
                                                          {k: label_IDs[i] for k, i in enumerate(keep) if i in label_IDs})
        renamed = {IDs[i]: new_IDs[k] for k, i in enumerate(keep)}
        IndvIDsDict = {renamed[IDs[keep[k]]]: IndvIDsDict[IDs[keep[k]]] for k in new_order}
        for person in IndvIDsDict.values():
            for parent in ('PaternalID', 'MaternalID'):
                person[parent] = renamed.get(person[parent], 0) if person[parent] else 0
        partners = [tuple(renamed[p] for p in pair) for pair in partners if all(p in renamed for p in pair)]
        twins = [(renamed[a], renamed[b], kind) for a, b, kind in twins if a in renamed and b in renamed]
        row_of = {new_IDs[k]: new_places[k][0] for k in range(len(keep))}
    if len(symbols) > 1 and not any_lines:
        warnings.warn(f'No lines were found between the symbols in {image_path}, so no one\'s parents are known')
    for note in notes:
        warnings.warn(note)
    missed = missed_lines(IndvIDsDict, partners, any_lines, row_of)
    for warning in missed:
        warnings.warn(f'{warning}. The picture was enlarged {upscale_factor:g} times: try a little more or less')
    if missed and not hand_drawn:
        warnings.warn(HAND_DRAWN_HINT)

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
    PedFileDF.attrs['image'] = os.path.basename(str(image_path))
    PedFileDF.attrs['twins'] = [list(t) for t in twins]
    PedFileDF.attrs['hand_drawn'] = bool(hand_drawn)
    #what a PED file can't hold, for a drawing made from the table (Studio_export): the couples joined by a line, with
    #children or without, and where each person was drawn, in the picture's own pixels, with their row and the shape
    #of their symbol
    PedFileDF.attrs['partners'] = [list(pair) for pair in partners]
    PedFileDF.attrs['layout'] = {person: {'box': [round(v/upscale_factor, 1) for v in data['node_coords']],
                                          'row': int(row_of[person]), 'shape': data['shape']}
                                 for person, data in IndvIDsDict.items()}

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


