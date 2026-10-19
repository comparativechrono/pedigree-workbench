"""The pedgen command: generate a pedigree and write it as a PED file.

    pedgen --mode AR --generations 4 --family FAM2 --seed 7 -d results

writes results/FAM2.ped, as pedigree_generator and gen_PED_export do in Python, and with --genotypes FILE, the
number of copies of the alternate allele that each person has (gen_genotype_export).
"""
import argparse
import re
import sys

from . import __version__
from .core import gen_genotype_export, gen_PED_export, pedigree_generator


def _fraction(text):
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f'expected a number between 0 and 1, not {text!r}')
    if not 0 <= value <= 1:
        raise argparse.ArgumentTypeError(f'expected a number between 0 and 1, not {text}')
    return value


def _at_least_one(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f'expected a whole number, not {text!r}')
    if value < 1:
        raise argparse.ArgumentTypeError(f'expected 1 or more, not {value}')
    return value


def parser():
    p = argparse.ArgumentParser(
        prog='pedgen',
        description='Generate a genetically realistic pedigree, by Mendelian inheritance from an affected founder, '
                    'and write it as a PED file named after the family.')
    p.add_argument('--version', action='version', version=f'pedgen {__version__}')
    p.add_argument('-m', '--mode', choices=('AD', 'AR'), default='AD',
                   help='the mode of inheritance: autosomal dominant or autosomal recessive (default: AD)')
    p.add_argument('-g', '--generations', type=_at_least_one, default=3, help='the number of generations (default: 3)')
    p.add_argument('-c', '--max-children', type=_at_least_one, default=3,
                   help='the most children a couple can have (default: 3)')
    p.add_argument('-f', '--family', default='FAM1', help='the family ID, which names the file (default: FAM1)')
    p.add_argument('-d', '--output-dir', default='.', help='the folder to write FAMILY.ped in (default: here)')
    p.add_argument('-s', '--seed', type=int,
                   help='makes the pedigree reproducible: the same seed and settings always give the same pedigree')
    p.add_argument('--partners', type=_fraction, default=0.6, metavar='CHANCE',
                   help='the chance that a child has a partner, and so children of their own (default: 0.6; the '
                        'first child always does)')
    p.add_argument('--ancestors', type=_fraction, default=0.25, metavar='CHANCE',
                   help="the chance that a partner's parents are added, and theirs in turn (default: 0.25)")
    p.add_argument('--allele-frequency', type=_fraction, default=0.1, metavar='FREQUENCY',
                   help='the frequency of the alternate allele in the population that partners come from '
                        '(default: 0.1)')
    p.add_argument('--unaffected-partners', action='store_true',
                   help='partners and their ancestors never carry the alternate allele')
    p.add_argument('--genotypes', metavar='FILE',
                   help="also write each person's copies of the alternate allele to FILE, as a table that PedNet "
                        "reads as a candidate variant (pednet rank FAMILY.ped FILE)")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if not args.family or re.search(r'\s', args.family):
        print(f'pedgen: the family ID {args.family!r} must be a word with no spaces, as PED files are split at spaces',
              file=sys.stderr)
        return 1
    df = pedigree_generator(max_children=args.max_children, FamilyID=args.family, mode=args.mode,
                            generation_count=args.generations, SpouseLikelihood=args.partners,
                            AffectedSpouse=not args.unaffected_partners, BackpropLikelihood=args.ancestors,
                            alt_freq=args.allele_frequency, seed=args.seed)
    affected = int((df['Phenotype'] == 2).sum())
    print(f'Family {args.family}: {len(df)} people, {affected} affected ({args.mode})')
    print(f'wrote {gen_PED_export(df, args.output_dir)}')
    if args.genotypes:
        print(f'wrote {gen_genotype_export(df, args.genotypes, alt_freq=args.allele_frequency)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
