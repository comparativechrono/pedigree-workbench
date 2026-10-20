"""The pedinterp command: read a pedigree from a picture of one and write it as a PED file.

    pedinterp FAM1.png -d results               # writes results/FAM1.ped
    pedinterp scan.jpg -f FAM2 --labels none    # people numbered by generation: I-1, I-2, II-1 ...
    pedinterp FAM1.png --ga4gh                  # FAM1.ped, and FAM1_ga4gh-pedigree.json
    pedinterp sketch.png --hand-drawn           # a pedigree sketched by hand, in whole or in part

does what pedigree_processing, PED_export and GA4GH_export do in Python.
"""
import argparse
import os
import re
import sys
import warnings

from . import __version__
from .core import GA4GH_export, PED_export, ga4gh_condition, pedigree_processing, twin_groups


def _factor(text):
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f'expected a number, not {text!r}')
    if not value > 0:
        raise argparse.ArgumentTypeError(f'expected a number above 0, not {text}')
    return int(value) if value == int(value) else value


def parser():
    p = argparse.ArgumentParser(
        prog='pedinterp',
        description='Read a pedigree from a picture of one, drawn in the usual symbols on white, and write it as a '
                    'PED file named after the family. Each person\'s parents, sex and whether they are affected are '
                    'printed as a table too, with any twins, which a PED file can\'t hold but a GA4GH Pedigree '
                    '(--ga4gh) can.')
    p.add_argument('--version', action='version', version=f'pedinterp {__version__}')
    p.add_argument('image', help='the picture: PNG, JPEG or any other format Pillow reads')
    p.add_argument('-f', '--family',
                   help="the family ID, which names the PED file (default: the picture's name without its ending, "
                        'with any spaces made underscores)')
    p.add_argument('-d', '--output-dir', default='.', help='the folder to write FAMILY.ped in (default: here)')
    p.add_argument('--hand-drawn', action='store_true',
                   help="the pedigree is sketched by hand, in whole or in part, as with Pedigree Studio's Draw tool: "
                        'its symbols may be of unequal sizes, with outlines that don\'t quite close and fills '
                        'scribbled in, and its lines may wobble and stop short of what they join. Its labels '
                        'aren\'t read unless --labels tesseract is given')
    p.add_argument('--upscale', type=_factor, metavar='FACTOR',
                   help='how many times to enlarge the picture before reading it (by default, as many as make its '
                        'symbols about 200 pixels across, or 100 for a sketch, which reads best; the factor is printed '
                        'with the table)')
    p.add_argument('--labels', choices=('tesseract', 'none'),
                   help='read the labels by the symbols with Tesseract, or number the people by generation instead: '
                        'I-1, I-2, II-1 and so on (default: tesseract, or none with --hand-drawn)')
    p.add_argument('--ga4gh', action='store_true',
                   help='also write the pedigree as a GA4GH Pedigree, FAMILY_ga4gh-pedigree.json, which the GA4GH '
                        'tools read (ga4gh2studio, phenopacket-toolkit, PedNet)')
    p.add_argument('--condition', nargs=2, metavar=('ID', 'LABEL'),
                   help='with --ga4gh, the condition the pedigree is about, as an ontology term and its label, such '
                        'as MONDO:0007739 "Huntington disease" (default: MONDO:0000001 disease). The affected have '
                        'it, and the unaffected have it marked as looked for and not found')
    p.add_argument('-q', '--quiet', action='store_true', help="don't print the table")
    return p


def _warn(warning):
    # PedInterp's warnings speak to someone calling it from Python
    text = str(warning.message).replace('Pass ocr=None to number people', 'Give --labels none to number people')
    text = text.replace('read it with hand_drawn=True', 'read it with --hand-drawn')
    print(f'warning: {text}', file=sys.stderr)


def main(argv=None):
    args = parser().parse_args(argv)
    if not os.path.isfile(args.image):
        print(f'pedinterp: {args.image}: no such file', file=sys.stderr)
        return 1
    if args.family is not None and (not args.family or re.search(r'\s', args.family)):
        print(f'pedinterp: the family ID {args.family!r} must be a word with no spaces, as PED files are split '
              'at spaces', file=sys.stderr)
        return 1
    if args.condition and not args.ga4gh:
        print('pedinterp: --condition is for the GA4GH Pedigree that --ga4gh writes', file=sys.stderr)
        return 1
    try:
        condition = ga4gh_condition(args.condition) if args.ga4gh else None
    except ValueError as error:
        print(f'pedinterp: {error}', file=sys.stderr)
        return 1
    family = args.family or re.sub(r'\s+', '_', os.path.splitext(os.path.basename(args.image))[0])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        try:
            df = pedigree_processing(family, image_path=args.image, upscale_factor=args.upscale,
                                     ocr=args.labels or 'auto', hand_drawn=args.hand_drawn)
        except (ValueError, OSError) as error:
            for warning in caught:
                _warn(warning)
            print(f'pedinterp: {str(error).replace("read it with hand_drawn=True", "read it with --hand-drawn")}',
                  file=sys.stderr)
            return 1
    for warning in caught:
        _warn(warning)
    if not args.quiet:
        print(df.to_string(index=False))
        for first, others in twin_groups(df):
            names = [first] + [other for other, _ in others]
            kinds = {identical for _, identical in others}
            print(f'twins: {", ".join(names[:-1])} and {names[-1]}' +
                  (' (identical)' if kinds == {True} else ' (not identical)' if kinds == {False} else ''))
        print(f'(the picture was read enlarged {df.attrs["upscale_factor"]:g} times)')
    print(f'wrote {PED_export(df, args.output_dir)}')
    if args.ga4gh:
        print(f'wrote {GA4GH_export(df, args.output_dir, condition=condition)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
