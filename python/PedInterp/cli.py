"""The pedinterp command: read a pedigree from a picture of one and write it as a PED file.

    pedinterp FAM1.png -d results               # writes results/FAM1.ped
    pedinterp scan.jpg -f FAM2 --labels none    # people numbered by generation: I-1, I-2, II-1 ...

does what pedigree_processing and PED_export do in Python.
"""
import argparse
import os
import re
import sys
import warnings

from . import __version__
from .core import PED_export, pedigree_processing


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
        description='Read a pedigree from a picture of one, drawn in the usual symbols in black on white, and write '
                    'it as a PED file named after the family. Each person\'s parents, sex and whether they are '
                    'affected are printed as a table too.')
    p.add_argument('--version', action='version', version=f'pedinterp {__version__}')
    p.add_argument('image', help='the picture: PNG, JPEG or any other format Pillow reads')
    p.add_argument('-f', '--family',
                   help="the family ID, which names the PED file (default: the picture's name without its ending, "
                        'with any spaces made underscores)')
    p.add_argument('-d', '--output-dir', default='.', help='the folder to write FAMILY.ped in (default: here)')
    p.add_argument('--upscale', type=_factor, metavar='FACTOR',
                   help='how many times to enlarge the picture before reading it (by default, as many as make its '
                        'symbols about 200 pixels across, which reads best; the table says what was used)')
    p.add_argument('--labels', choices=('tesseract', 'none'), default='tesseract',
                   help='read the labels under the symbols with Tesseract (the default), or number the people by '
                        'generation instead: I-1, I-2, II-1 and so on')
    p.add_argument('-q', '--quiet', action='store_true', help="don't print the table")
    return p


def _warn(warning):
    # PedInterp's warnings speak to someone calling it from Python
    text = str(warning.message).replace('Pass ocr=None to number people', 'Give --labels none to number people')
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
    family = args.family or re.sub(r'\s+', '_', os.path.splitext(os.path.basename(args.image))[0])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        try:
            df = pedigree_processing(family, image_path=args.image, upscale_factor=args.upscale, ocr=args.labels)
        except (ValueError, OSError) as error:
            for warning in caught:
                _warn(warning)
            print(f'pedinterp: {error}', file=sys.stderr)
            return 1
    for warning in caught:
        _warn(warning)
    if not args.quiet:
        print(df.to_string(index=False))
        print(f'(the picture was read enlarged {df.attrs["upscale_factor"]:g} times)')
    print(f'wrote {PED_export(df, args.output_dir)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
