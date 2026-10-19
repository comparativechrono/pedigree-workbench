"""The pednet command:

    pednet graph FAMILY.ped                the pedigree as a graph: its structure, loops, kinship and patterns
    pednet mode FAMILY.ped                 the mode of inheritance
    pednet rank FAMILY.ped VARIANTS.vcf    candidate variants ranked by co-segregation
    pednet check FAMILY.ped                what PedNet makes of a pedigree file

Each reads a PED file, or a GA4GH Pedigree or Phenopackets Family (FAMILY_ga4gh-pedigree.json).
"""
import argparse
import csv
import os
import sys
from typing import List, Optional

from . import __version__
from . import graph as pedgraph
from .features import classify_by_metrics, classify_by_patterns, network_metrics, pattern_features
from .genotypes import read_genotype_table, read_vcf, vcf_samples
from .inheritance import DEFAULT_PENETRANCE, DEFAULT_PHENOCOPY, infer_mode, infer_shared_mode
from .models import MODES
from .ga4gh import UNRECORDED
from .pedigree import PedigreeError, read_pedigree
from .segregation import DEFAULT_ERROR_RATE, MIN_VARIANT_FREQUENCY, rank_variants, rank_variants_across


def _floats(text: str) -> List[float]:
    try:
        return [float(x) for x in text.replace(',', ' ').split()]
    except ValueError:
        raise argparse.ArgumentTypeError(f'expected numbers separated by commas, not {text!r}')


def _families(args):
    families = read_pedigree(args.ped, args.family, args.condition, args.unrecorded)
    if not families:
        raise PedigreeError(f'There are no people in {args.ped}')
    if getattr(args, 'proband', None) and len(families) > 1:
        raise PedigreeError('--proband needs --family, since the file has more than one family')
    return families


def _ga4gh(parser):
    parser.add_argument('--condition', help='for a GA4GH file that names several conditions, the one that makes '
                                            'someone affected, by its ontology ID or its label (by default any)')
    parser.add_argument('--unrecorded', choices=UNRECORDED,
                        help='for a GA4GH file, what to take people with no record of the condition to be (by '
                             'default unaffected, unless the file marks some people as not having it)')


def _common(parser):
    parser.add_argument('ped', help='the PED file, or a GA4GH Pedigree or Phenopackets Family (.json)')
    parser.add_argument('--family', help='only this family (by default every family in the file)')
    _ga4gh(parser)
    parser.add_argument('--proband', help='the person through whom the family was found (by default each affected '
                                          'person in turn)')
    parser.add_argument('--modes', default=','.join(MODES),
                        help='the modes of inheritance to weigh up, separated by commas (default: all four)')
    parser.add_argument('--penetrance', type=_floats, default=list(DEFAULT_PENETRANCE),
                        help='the penetrance, or several to average over (default: 0.6,0.8,0.95,0.99)')
    parser.add_argument('--phenocopy', type=float, default=DEFAULT_PHENOCOPY,
                        help=f'the chance of being affected without the disease genotype (default: {DEFAULT_PHENOCOPY})')


def _write_tsv(rows, handle):
    fields = []
    for row in rows:
        fields.extend(k for k in row if k not in fields)
    writer = csv.DictWriter(handle, fieldnames=fields or ['candidate'], delimiter='\t', lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)


def _mode(args) -> int:
    families = _families(args)
    if args.method != 'likelihood':
        if args.together:
            raise ValueError('--together works with the likelihood method only')
        return _mode_by_graph(args, families)
    if args.together:
        results = [infer_shared_mode(families, args.modes, args.penetrance, phenocopy=args.phenocopy,
                                     threshold=args.threshold)]
    else:
        results = [infer_mode(pedigree, args.modes, args.penetrance, phenocopy=args.phenocopy, proband=args.proband,
                              threshold=args.threshold) for pedigree in families.values()]
    if args.tsv:
        _write_tsv([row for r in results for row in r.table()], sys.stdout)
        return 0
    for result in results:
        print(result)
        print()
    return 0


def _mode_by_graph(args, families) -> int:
    unused = [option for option, given in (
        ('--proband', args.proband is not None), ('--modes', args.modes != ','.join(MODES)),
        ('--penetrance', list(args.penetrance) != list(DEFAULT_PENETRANCE)),
        ('--phenocopy', args.phenocopy != DEFAULT_PHENOCOPY),
        ('--threshold', args.method == 'metrics' and args.threshold != 0.8)) if given]
    if unused:
        listed = unused[0] if len(unused) == 1 else ', '.join(unused[:-1]) + ' and ' + unused[-1]
        classifier = 'pattern classifier' if args.method == 'patterns' else 'metric classifier'
        print(f'note: the {classifier} learnt from simulated families and takes no account of {listed}, which '
              'the likelihood method uses', file=sys.stderr)
    rows = []
    for name, pedigree in families.items():
        if args.method == 'patterns':
            result = classify_by_patterns(pedigree, threshold=args.threshold)
            rows.extend({'family': name, 'mode': m, 'probability': p} for m, p in result.probabilities.items())
            text = str(result)
        else:
            call = classify_by_metrics(pedigree)
            values = network_metrics(pedigree)
            rows.append({'family': name, 'call': call, **values})
            text = (f'Family {name}, by the original PedNet metric classifier: {call}\n  ' +
                    ', '.join(f'{k} {v:.3f}' for k, v in values.items()))
        if not args.tsv:
            print(text)
            print()
    if args.tsv:
        _write_tsv(rows, sys.stdout)
    return 0


def _graph(args) -> int:
    families = _families(args)
    if (args.kinship or args.graphml) and len(families) > 1:
        raise PedigreeError('--kinship and --graphml need --family, since the file has more than one family')
    for name, pedigree in families.items():
        graph = pedgraph.pedigree_graph(pedigree)
        couples = {(p.father, p.mother) for p in pedigree.people if p.father is not None}
        generations = pedigree.generations()
        founders = [n for n in graph if graph.in_degree(n) == 0]
        print(f'Family {name}: {_count(graph.number_of_nodes(), "person", "people")} in '
              f'{_count(max(generations.values()) + 1, "generation")}, {len(pedigree.affected())} affected; '
              f'{_count(len(founders), "founder")} and {_count(len(couples), "couple")} with children')
        found = pedgraph.loops(pedigree)
        if found:
            for loop in found:
                print(f'  a loop, from {loop.kind}: {", ".join(loop.people)}')
        else:
            print('  no loops')
        inbred = {pid: f for pid, f in pedgraph.inbreeding(pedigree).items() if f > 0}
        if inbred:
            print('  inbred: ' + ', '.join(f'{pid} (F = {f:.4f})' for pid, f in inbred.items()))
        print(f'  width {pedgraph.pedigree_width(pedigree)} (the most people no one of whom is another\'s ancestor)')
        plan = pedgraph.elimination(pedigree)
        print(f'  exact likelihoods: elimination width {plan.width}, so the moral graph\'s treewidth is at most '
              f'{plan.width - 1}' + ('' if plan.exact else
                                     f'; too many loops for exact likelihoods (a table of {plan.largest_table:,} '
                                     'states)'))
        affected = pedigree.affected()
        pairs = [(a, b) for i, a in enumerate(affected) for b in affected[i + 1:]]
        matrix = pedgraph.kinship_matrix(pedigree)
        named = [(a, b, pedgraph.relationship(pedigree, a, b, matrix)) for a, b in pairs]
        named = [x for x in named if x[2].degree is not None]
        named.sort(key=lambda x: (-x[2].kinship, x[0], x[1]))
        if named:
            print('  affected relatives, the closest first:')
            for a, b, r in named[:args.pairs]:
                print(f'    {b} is the {r.name} of {a} ({_ordinal_degree(r.degree)} degree, kinship {r.kinship:.4f})')
            if len(named) > args.pairs:
                print(f'    ... and {len(named) - args.pairs} more pairs')
        values = network_metrics(pedigree)
        print('  network metrics (the original PedNet\'s):')
        _print_values(values)
        print('  pattern features:')
        _print_values(pattern_features(pedigree))
        central = sorted(pedgraph.centrality(pedigree).items(), key=lambda x: -x[1])[:3]
        print('  most central (betweenness): ' + ', '.join(f'{pid} {v:.3f}' for pid, v in central))
        if args.kinship:
            ids, phi = pedgraph.kinship_matrix(pedigree, x_linked=args.x)
            keep = [k for k, pid in enumerate(ids) if not pedigree[pid].placeholder]
            with open(args.kinship, 'w', newline='') as handle:
                writer = csv.writer(handle, delimiter='\t', lineterminator='\n')
                writer.writerow([''] + [ids[k] for k in keep])
                for k in keep:
                    writer.writerow([ids[k]] + [f'{phi[k, j]:.6g}' for j in keep])
            print(f'  wrote the {"X-linked " if args.x else ""}kinship coefficients to {args.kinship}')
        if args.graphml:
            pedgraph.write_graph(pedigree, args.graphml, mating=args.mating)
            print(f'  wrote the {"mating" if args.mating else "pedigree"} graph to {args.graphml}')
    return 0


def _print_values(values, per_line=4):
    items = [f'{k} {v:.3f}' for k, v in values.items()]
    for start in range(0, len(items), per_line):
        print('    ' + ', '.join(items[start:start + per_line]))


def _ordinal_degree(degree: int) -> str:
    return {1: 'first', 2: 'second', 3: 'third', 4: 'fourth', 5: 'fifth'}.get(degree, f'{degree}th')


def _count(n: int, one: str, many: Optional[str] = None) -> str:
    """'1 variant', '2 variants'"""
    return f'{n} {one if n == 1 else (many or one + "s")}'


def _format(value, digits=2):
    if value is None:
        return '-'
    if isinstance(value, float):
        return f'{value:.{digits}f}'
    return str(value)


def _print_table(header, table):
    widths = [max(len(str(row[i])) for row in [header] + table) for i in range(len(header))]
    for row in [header] + table:
        print('  '.join(str(cell).ljust(w) for cell, w in zip(row, widths)).rstrip())


def _note_strangers(names, people):
    """Say which genotyped samples are in no family, and stop if none of them is in one"""
    missing = sorted(set(names) - set(people))
    if missing and len(missing) == len(set(names)):
        raise PedigreeError('None of the genotyped samples is in the pedigree: their names must be the IDs of the '
                            f'people in it ({", ".join(missing[:3])}{"..." if len(missing) > 3 else ""})')
    if missing:
        print(f'note: {_count(len(missing), "genotyped sample")} {"is" if len(missing) == 1 else "are"} in no family '
              f'of the pedigree file and {"is" if len(missing) == 1 else "are"} left out '
              f'({", ".join(missing[:5])}{"..." if len(missing) > 5 else ""})', file=sys.stderr)


def _read_variants(args, people):
    path = str(args.variants).lower()
    if path.endswith(('.vcf', '.vcf.gz', '.vcf.bgz')):
        _note_strangers(vcf_samples(args.variants), people)
        variants = read_vcf(args.variants, samples=people, frequency_key=args.frequency_key,
                            passed_only=args.passed_only, gene_key=args.gene_key)
    else:
        variants = read_genotype_table(args.variants)
        _note_strangers({pid for v in variants for pid in v.genotypes}, people)
    if args.max_frequency is not None:
        kept = [v for v in variants if v.allele_frequency is None or v.allele_frequency <= args.max_frequency]
        if len(kept) < len(variants):
            n = len(variants) - len(kept)
            print(f'note: {_count(n, "variant")} with an allele frequency above {args.max_frequency} '
                  f'{"is" if n == 1 else "are"} left out', file=sys.stderr)
        variants = kept
    return variants


def _rank(args) -> int:
    families = _families(args)
    people = {pid for pedigree in families.values() for pid in pedigree.ids}
    variants = _read_variants(args, people)
    options = dict(modes=args.modes, penetrance=args.penetrance, phenocopy=args.phenocopy,
                   min_frequency=args.min_frequency, error_rate=args.error_rate, compound=not args.no_compound)
    if len(families) > 1:
        return _rank_across(args, families, variants, options)
    pedigree = next(iter(families.values()))
    scores = rank_variants(pedigree, variants, proband=args.proband, **options)
    if args.out:
        with open(args.out, 'w', newline='') as handle:
            _write_tsv([s.row() for s in scores], handle)
    shown = scores[:args.top] if args.top else scores
    pairs = sum(s.compound for s in scores)
    print(f'Family {pedigree.family}: {_count(len(scores) - pairs, "variant")}'
          + (f' and {_count(pairs, "pair")} of variants in one gene' if pairs else '') + ', the most likely cause first')
    header = ['rank', 'candidate', 'log10 odds', 'log10 BF', 'evidence', 'best mode', 'affected carriers',
              'unaffected carriers', 'note']
    table = [[_format(s.rank, 1), s.id, _format(s.log10_odds), _format(s.log10_bf), s.evidence or '-',
              (s.best_mode + ' (compound)' if s.compound and s.best_mode else s.best_mode) or '-',
              f'{s.affected_carriers}/{s.affected_carriers + s.affected_noncarriers}',
              f'{s.unaffected_carriers}/{s.unaffected_carriers + s.unaffected_noncarriers}', s.notes]
             for s in shown]
    _print_table(header, table)
    if args.top and len(scores) > args.top:
        print(f'... and {len(scores) - args.top} more' + (f' (all in {args.out})' if args.out else ''))
    return 0


def _rank_across(args, families, variants, options) -> int:
    combined = rank_variants_across(families, variants, **options)
    if args.out:
        with open(args.out, 'w', newline='') as handle:
            _write_tsv([c.row() for c in combined], handle)
    print(f'Families {", ".join(families)}: {_count(len(combined), "candidate")} carried by an affected person in at '
          'least one family, the most likely cause over the families first')
    shown = combined[:args.top] if args.top else combined
    header = ['rank', 'candidate', 'log10 odds', 'log10 BF', 'evidence', 'each family\'s own log10 BF']
    table = [[_format(c.rank, 1), c.id, _format(c.log10_odds), _format(c.log10_bf), c.evidence or '-',
              ', '.join(f'{name} {_format(s.log10_bf)}' for name, s in c.families.items())] for c in shown]
    _print_table(header, table)
    for c in shown:
        if c.note:
            print(f'note: {c.id}: {c.note}')
        elif c.evidence_withheld:
            print(f'note: no evidence is given for {c.id}: {c.evidence_withheld}')
    if args.top and len(combined) > args.top:
        print(f'... and {len(combined) - args.top} more' + (f' (all in {args.out})' if args.out else ''))
    return 0


def _check(args) -> int:
    for name, pedigree in _families(args).items():
        generations = pedigree.generations()
        print(f'Family {name}: {len([p for p in pedigree.people if not p.placeholder])} people, '
              f'{len(pedigree.affected())} affected, {max(generations.values()) + 1} generations')
        related = pedigree.consanguineous()
        if related:
            print(f'  children of related parents: {", ".join(sorted(related))}')
        for note in pedigree.notes + pedigree.problems():
            print(f'  note: {note}')
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog='pednet', description='Pedigrees as graphs: the structure of a family, '
                                     'the mode of inheritance of its condition, and the co-segregation of candidate '
                                     'variants with it.')
    parser.add_argument('--version', action='version', version=f'pednet {__version__}')
    sub = parser.add_subparsers(dest='command', required=True)

    graph = sub.add_parser('graph', help='the pedigree as a graph: its structure, loops, kinship and patterns')
    graph.add_argument('ped', help='the PED file, or a GA4GH Pedigree or Phenopackets Family (.json)')
    graph.add_argument('--family', help='only this family')
    _ga4gh(graph)
    graph.add_argument('--pairs', type=int, default=10, help='how many pairs of affected relatives to list (default 10)')
    graph.add_argument('--kinship', help='write the kinship coefficients of everyone to this file, separated by tabs')
    graph.add_argument('--x', action='store_true', help='with --kinship, the coefficients for the X chromosome')
    graph.add_argument('--graphml', help='write the graph as GraphML, for network tools such as Gephi or Cytoscape')
    graph.add_argument('--mating', action='store_true',
                       help='with --graphml, write the mating graph, with a node for each couple')
    graph.set_defaults(run=_graph)

    mode = sub.add_parser('mode', help='the probability of each mode of inheritance')
    _common(mode)
    mode.add_argument('--method', choices=('likelihood', 'patterns', 'metrics'), default='likelihood',
                      help='likelihood: the exact likelihood of the phenotypes under each mode, summed over '
                           'everyone\'s genotypes (the default); patterns: the classifier of the pattern of affected '
                           'people in the graph; metrics: the original PedNet\'s network metric classifier, AD or AR')
    mode.add_argument('--threshold', type=float, default=0.8,
                      help='the probability needed to call a mode (default: 0.8)')
    mode.add_argument('--together', action='store_true',
                      help='take the families as having the same condition, and give one answer for them all')
    mode.add_argument('--tsv', action='store_true', help='print a table separated by tabs')
    mode.set_defaults(run=_mode)

    rank = sub.add_parser('rank', help='candidate variants ranked by co-segregation with the condition',
                          description='Ranks candidate variants by how well they co-segregate with the condition. '
                          'With several families in the file (and no --family), the families are taken to have '
                          'the same condition, with one mode of inheritance, and each candidate is ranked by its '
                          'evidence over the families in which an affected person carries it: the sum of their log10 '
                          'Bayes factors when the mode is given (--modes AD, say), and otherwise more than the sum if '
                          'the families agree on the mode, and less if they point to different modes.')
    _common(rank)
    rank.add_argument('variants', help='a VCF file (.vcf or .vcf.gz), or a table with a column per person')
    rank.add_argument('--frequency-key', default='AF', help='the INFO field with the allele frequency (default: AF)')
    rank.add_argument('--gene-key', help='the INFO field naming the gene (default: the first of CSQ, ANN, BCSQ, GENE, '
                                         'SYMBOL, Gene.refGene, Gene.ensGene and GENEINFO present)')
    rank.add_argument('--passed-only', action='store_true', help='keep only VCF sites that passed their filters')
    rank.add_argument('--max-frequency', type=float,
                      help='leave out variants with an allele frequency above this (by default none are left out)')
    rank.add_argument('--min-frequency', type=float, default=MIN_VARIANT_FREQUENCY,
                      help=f'treat rarer variants as having this frequency (default: {MIN_VARIANT_FREQUENCY})')
    rank.add_argument('--error-rate', type=float, default=DEFAULT_ERROR_RATE,
                      help=f'the chance that a genotype call is one copy out (default: {DEFAULT_ERROR_RATE})')
    rank.add_argument('--no-compound', action='store_true',
                      help='don\'t score pairs of variants in one gene as compound heterozygotes')
    rank.add_argument('--top', type=int, default=20, help='how many to show (default: 20; 0 for all)')
    rank.add_argument('--out', help='write every candidate\'s scores to this file, separated by tabs')
    rank.set_defaults(run=_rank)

    check = sub.add_parser('check', help='what PedNet makes of a pedigree file')
    check.add_argument('ped', help='the PED file, or a GA4GH Pedigree or Phenopackets Family (.json)')
    check.add_argument('--family', help='only this family')
    _ga4gh(check)
    check.set_defaults(run=_check)

    args = parser.parse_args(argv)
    try:
        status = args.run(args)
        sys.stdout.flush()      # here rather than as Python exits, so that a reader who has stopped is noticed below
        return status
    except BrokenPipeError:
        # whatever was reading the output (head, say) has stopped: stop quietly, sending what is left to nowhere so
        # that Python doesn't complain again as it exits
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 1
    except (PedigreeError, ValueError, OSError) as error:
        print(f'pednet: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
