"""The pedgen command: generate a pedigree and write it as a PED file.

    pedgen --mode AR --generations 4 --family FAM2 --seed 7 -d results

writes results/FAM2.ped, as pedigree_generator and gen_PED_export do in Python; with --ga4gh, a GA4GH Pedigree too
(gen_GA4GH_export); and with --genotypes FILE, the number of copies of the alternate allele that each person has
(gen_genotype_export).
"""
import argparse
import re
import sys

from . import __version__
from .core import ga4gh_condition, gen_GA4GH_export, gen_genotype_export, gen_PED_export, pedigree_generator


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
                        'first child always does, in every generation but the last)')
    p.add_argument('--ancestors', type=_fraction, default=0.25, metavar='CHANCE',
                   help="the chance that a partner's parents are added, and theirs in turn (default: 0.25)")
    p.add_argument('--allele-frequency', type=_fraction, default=0.001, metavar='FREQUENCY',
                   help='the frequency of the alternate allele in the population that partners come from '
                        '(default: 0.001, a rare allele)')
    p.add_argument('--cousins', type=_fraction, default=0.0, metavar='CHANCE',
                   help='the chance that someone in the family who has a partner marries a cousin, if one has no '
                        'partner yet, rather than someone from outside the family (default: 0). A rare recessive '
                        'allele seldom comes together twice in a family in any other way')
    p.add_argument('--min-affected', type=_at_least_one, default=1, metavar='N',
                   help='make families until one has at least N affected people, as families come to notice through '
                        'their affected members (default: 1)')
    p.add_argument('--unaffected-partners', action='store_true',
                   help="partners never carry the alternate allele, though their parents and grandparents, if added, "
                        "still can (--allele-frequency 0 keeps it to the founder's descendants)")
    p.add_argument('--ga4gh', action='store_true',
                   help='also write the pedigree as a GA4GH Pedigree, FAMILY_ga4gh-pedigree.json, which the GA4GH '
                        'tools read (ga4gh2studio, phenopacket-toolkit, PedNet)')
    p.add_argument('--condition', nargs=2, metavar=('ID', 'LABEL'),
                   help='with --ga4gh, the condition the pedigree is about, as an ontology term and its label, such '
                        'as MONDO:0007739 "Huntington disease" (default: MONDO:0000001 disease). The affected have '
                        'it, and the unaffected have it marked as looked for and not found')
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
    if args.condition and not args.ga4gh:
        print('pedgen: --condition is for the GA4GH Pedigree that --ga4gh writes', file=sys.stderr)
        return 1
    try:
        condition = ga4gh_condition(args.condition) if args.ga4gh else None
    except ValueError as e:
        print(f'pedgen: {e}', file=sys.stderr)
        return 1
    try:
        df = pedigree_generator(max_children=args.max_children, FamilyID=args.family, mode=args.mode,
                                generation_count=args.generations, SpouseLikelihood=args.partners,
                                AffectedSpouse=not args.unaffected_partners, BackpropLikelihood=args.ancestors,
                                alt_freq=args.allele_frequency, seed=args.seed, CousinLikelihood=args.cousins,
                                min_affected=args.min_affected)
    except ValueError as e:
        print(f'pedgen: {e}', file=sys.stderr)
        return 1
    affected = int((df['Phenotype'] == 2).sum())
    print(f'Family {args.family}: {len(df)} people, {affected} affected ({args.mode})')
    print(f'wrote {gen_PED_export(df, args.output_dir)}')
    if args.ga4gh:
        print(f'wrote {gen_GA4GH_export(df, args.output_dir, condition=condition)}')
    if args.genotypes:
        print(f'wrote {gen_genotype_export(df, args.genotypes, alt_freq=args.allele_frequency)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
