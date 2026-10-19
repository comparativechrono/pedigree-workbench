"""Simulated families, for testing and benchmarking PedNet.

A family is a pedigree, the genotypes of a disease locus passed down it by Mendel's laws, phenotypes drawn from those
genotypes, and a set of candidate variants: the causal one (or for a compound heterozygote, two in one gene), and
rare background variants passed down the same pedigree independently of it, as a family's other rare variants are.
Some people are sequenced; the proband always is.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .models import X_LINKED
from .pedigree import FEMALE, MALE, Pedigree, Person
from .segregation import Variant

Row = Tuple[str, Optional[str], Optional[str], int]


@dataclass
class SimulatedFamily:
    pedigree: Pedigree
    mode: str
    proband: str
    disease: Dict[str, int]                  # each person's copies of the disease allele (of a compound
                                             # heterozygote's two, the copies of the gene carrying either)
    variants: List[Variant]                  # the causal variants first: see causal
    sequenced: List[str] = field(default_factory=list)
    penetrance: float = 0.9
    phenocopy: float = 0.001
    causal: Tuple[str, ...] = ('causal',)    # the ids of the causal variant, or of a compound heterozygote's two


def _tree(rng: np.random.Generator, generations: int, children: Tuple[int, int], partner: float) -> List[Row]:
    rows: List[Row] = [('1', None, None, MALE), ('2', None, None, FEMALE)]
    next_id = 3
    couples = [('1', '2')]
    for g in range(1, generations):
        new_couples = []
        for father, mother in couples:
            kids = []
            for _ in range(int(rng.integers(children[0], children[1] + 1))):
                sex = MALE if rng.random() < 0.5 else FEMALE
                rows.append((str(next_id), father, mother, sex))
                kids.append((str(next_id), sex))
                next_id += 1
            if g == generations - 1:
                continue
            for k, (kid, sex) in enumerate(kids):
                # the first child always has a family of their own, so that every generation is there
                if k == 0 or rng.random() < partner:
                    spouse = str(next_id)
                    next_id += 1
                    rows.append((spouse, None, None, FEMALE if sex == MALE else MALE))
                    new_couples.append((kid, spouse) if sex == MALE else (spouse, kid))
        couples = new_couples
    return rows


def _cousins(rng: np.random.Generator, children: Tuple[int, int]) -> List[Row]:
    """Four generations: two siblings' children, first cousins, have children of their own"""
    rows: List[Row] = [('1', None, None, MALE), ('2', None, None, FEMALE),
                       ('3', '1', '2', MALE), ('4', '1', '2', FEMALE), ('5', None, None, FEMALE), ('6', None, None, MALE),
                       ('7', '3', '5', MALE), ('8', '6', '4', FEMALE)]
    next_id = 9

    def add_children(father, mother, n):
        nonlocal next_id
        for _ in range(n):
            rows.append((str(next_id), father, mother, MALE if rng.random() < 0.5 else FEMALE))
            next_id += 1

    add_children('1', '2', int(rng.integers(0, 3)))
    add_children('3', '5', int(rng.integers(0, 3)))
    add_children('6', '4', int(rng.integers(0, 3)))
    # the related couple usually has a larger family, as such families often do
    add_children('7', '8', int(rng.integers(max(children[0], 3), max(children[1], 3) + 3)))
    return rows


def _drop(rows: Sequence[Row], x_linked: bool, founder_copies: Dict[str, int], q: float,
          rng: np.random.Generator) -> Dict[str, int]:
    """Copies of an allele passed down the pedigree, founders given in founder_copies or drawn from the population"""
    copies: Dict[str, int] = {}
    for pid, father, mother, s in rows:
        if father is None:
            if pid in founder_copies:
                copies[pid] = founder_copies[pid]
            elif x_linked and s == MALE:
                copies[pid] = int(rng.random() < q)
            else:
                copies[pid] = int(rng.random() < q) + int(rng.random() < q)
            continue
        from_mother = int(rng.random() < copies[mother] / 2)
        if x_linked:
            copies[pid] = from_mother if s == MALE else copies[father] + from_mother
        else:
            copies[pid] = int(rng.random() < copies[father] / 2) + from_mother
    return copies


def _drop_haplotypes(rows: Sequence[Row], x_linked: bool, founders: Dict[str, Tuple[int, ...]],
                     rng: np.random.Generator) -> Dict[str, Tuple[int, ...]]:
    """
    Each person's copies of a gene, as haplotype labels (0 for a copy with no variant), passed down the pedigree from
    the founders given in founders; other founders have no variants. A man has one copy on the X.
    """
    haplotypes: Dict[str, Tuple[int, ...]] = {}
    for pid, father, mother, s in rows:
        if father is None:
            haplotypes[pid] = founders.get(pid, (0,) if x_linked and s == MALE else (0, 0))
            continue
        from_mother = haplotypes[mother][int(rng.integers(2))]
        if x_linked:
            haplotypes[pid] = (from_mother,) if s == MALE else (haplotypes[father][0], from_mother)
        else:
            haplotypes[pid] = (haplotypes[father][int(rng.integers(2))], from_mother)
    return haplotypes


# haplotype labels for a pair of variants: 1 the first, 2 the second, 3 both (in cis)
_FIRST, _SECOND = {1, 3}, {2, 3}


def _affected(mode: str, copies: int, male: bool, penetrance: float, phenocopy: float, rng) -> bool:
    if mode in ('AD', 'XLD'):
        disease = copies >= 1
    elif mode == 'AR':
        disease = copies == 2
    else:
        disease = copies >= 1 if male else copies == 2
    return bool(rng.random() < (penetrance if disease else phenocopy))


def _has_disease_genotype(mode: str, copies: int, male: bool) -> bool:
    if mode in ('AD', 'XLD'):
        return copies >= 1
    if mode == 'AR':
        return copies == 2
    return copies >= 1 if male else copies == 2


def simulate_family(mode: str, rng: Optional[np.random.Generator] = None, generations: int = 3,
                    children: Tuple[int, int] = (1, 4), partner: float = 0.6, consanguineous: bool = False,
                    penetrance: float = 0.9, phenocopy: float = 0.001, allele_frequency: float = 1e-3,
                    min_affected: int = 2, unknown_phenotype: float = 0.0, background: int = 20,
                    background_frequency: Tuple[float, float] = (1e-4, 1e-2), sequenced: float = 0.5,
                    error_rate: float = 0.0, compound: bool = False, background_pairs: int = 0,
                    max_tries: int = 5000) -> SimulatedFamily:
    """
    One simulated family with a disease of the given mode, found through an affected proband who has the disease
    genotype (one of the affected people in the youngest generation that has any, where possible).

    generations, children (the range of a couple's children) and partner (the chance that a later child has a family)
    shape the pedigree; consanguineous makes it the four-generation family of a first-cousin marriage instead.
    penetrance, phenocopy and allele_frequency set the disease; min_affected is the fewest affected people the
    family must have. unknown_phenotype is the share of people (besides the proband) whose phenotype is unknown.
    background is the number of other rare variants the proband carries, with frequencies drawn evenly on a log scale
    from background_frequency, each in a gene of its own. sequenced is the chance that each person besides the
    proband is sequenced, and error_rate the chance that a genotype call is wrong.

    compound makes an autosomal recessive condition a compound heterozygote's: two variants in one gene, 'causal a'
    and 'causal b', brought into the family by two founders. background_pairs is the number of other pairs of rare
    variants in one gene that the proband carries both of (as the gene's two copies, or both on one copy).
    """
    rng = np.random.default_rng() if rng is None else rng
    x = X_LINKED[mode]
    if compound and mode != 'AR':
        raise ValueError('compound heterozygotes are simulated for autosomal recessive conditions only')
    haplotypes: Dict[str, Tuple[int, ...]] = {}
    for _ in range(max_tries):
        rows = _cousins(rng, children) if consanguineous else _tree(rng, generations, children, partner)
        sex = {r[0]: r[3] for r in rows}
        founders = [r[0] for r in rows if r[1] is None]
        # the disease allele comes into the family through one of the first couple, and for a recessive
        # condition without consanguinity also through someone who married in
        seed: Dict[str, int] = {}
        if mode == 'XLR':
            seed['2'] = 1
        else:
            seed[str(rng.choice(['1', '2']))] = 1
        if mode == 'AR' and (compound or not consanguineous):
            spouses = [f for f in founders if f not in ('1', '2')]
            if spouses:
                seed[str(rng.choice(spouses))] = 1
            else:
                seed['1'] = seed['2'] = 1
        if compound:
            # the first variant from one founder, the second from the other
            first, second = list(seed) if len(seed) == 2 else ('1', '2')
            haplotypes = _drop_haplotypes(rows, x, {first: (1, 0), second: (2, 0)}, rng)
            disease = {pid: sum(1 for h in hs if h) for pid, hs in haplotypes.items()}
        else:
            disease = _drop(rows, x, seed, allele_frequency, rng)
        phenotype = {pid: 2 if _affected(mode, disease[pid], sex[pid] == MALE, penetrance, phenocopy, rng) else 1
                     for pid in disease}
        affected = [pid for pid in disease if phenotype[pid] == 2]
        if len(affected) < min_affected:
            continue
        candidates = [pid for pid in affected if _has_disease_genotype(mode, disease[pid], sex[pid] == MALE)]
        if not candidates:
            continue
        generation_of = Pedigree([Person(r[0], r[1], r[2], r[3], phenotype[r[0]]) for r in rows]).generations()
        youngest = max(generation_of[pid] for pid in candidates)
        proband = str(rng.choice([pid for pid in candidates if generation_of[pid] == youngest]))
        break
    else:
        raise RuntimeError(f'No family with {min_affected} or more affected people in {max_tries} tries')

    for pid in phenotype:
        if pid != proband and rng.random() < unknown_phenotype:
            phenotype[pid] = 0
    people = [Person(r[0], r[1], r[2], r[3], phenotype[r[0]]) for r in rows]
    pedigree = Pedigree(people, f'SIM-{mode}')
    seq = [pid for pid in disease if pid == proband or rng.random() < sequenced]

    def call(true_copies, male):
        if error_rate and rng.random() < error_rate:
            options = [c for c in ((0, 1) if (x and male) else (0, 1, 2)) if c != true_copies]
            return int(rng.choice(options))
        return true_copies

    chrom = 'X' if x else '1'

    def variant(name, copies, frequency, gene):
        genotypes = {pid: call(copies[pid], sex[pid] == MALE) for pid in seq}
        return Variant(name, genotypes, chrom, None, None, None, frequency, gene)

    def counts(labels):
        return {pid: sum(1 for h in hs if h in labels) for pid, hs in haplotypes.items()}

    low, high = np.log10(background_frequency[0]), np.log10(background_frequency[1])

    def frequency():
        return float(10 ** rng.uniform(low, high))

    # the causal variants' recorded frequencies are drawn like the background variants', so that they give nothing away
    if compound:
        variants = [variant('causal a', counts(_FIRST), frequency(), 'GENE0'),
                    variant('causal b', counts(_SECOND), frequency(), 'GENE0')]
        causal: Tuple[str, ...] = ('causal a', 'causal b')
    else:
        variants = [variant('causal', disease, frequency(), 'GENE0')]
        causal = ('causal',)
    # a rare variant the proband carries came into the family through one of the proband's founder ancestors
    ancestors = pedigree.ancestors(proband) | {proband}
    roots = [f for f in founders if f in ancestors]
    made = 0
    while made < background:
        q = frequency()
        copies = _drop(rows, x, {str(rng.choice(roots)): 1}, q, rng)
        if copies[proband] == 0:
            continue
        made += 1
        variants.append(variant(f'background {made}', copies, q, f'GENE{made}'))
    made = 0
    def founder_copies(pid, label):
        return (label,) if x and sex[pid] == MALE else (label, 0)

    while made < background_pairs:
        one, other = str(rng.choice(roots)), str(rng.choice(roots))
        if one != other:
            start = {one: founder_copies(one, 1), other: founder_copies(other, 2)}
        elif x and sex[one] == MALE:
            start = {one: (3,)}
        else:
            # one founder with both: one on each copy of the gene, or both on one copy
            start = {one: (1, 2) if rng.random() < 0.5 else (3, 0)}
        haplotypes = _drop_haplotypes(rows, x, start, rng)
        first, second = counts(_FIRST), counts(_SECOND)
        if first[proband] == 0 or second[proband] == 0:
            continue
        made += 1
        gene = f'PAIR{made}'
        variants.append(variant(f'pair {made} a', first, frequency(), gene))
        variants.append(variant(f'pair {made} b', second, frequency(), gene))
    return SimulatedFamily(pedigree, mode, proband, disease, variants, seq, penetrance, phenocopy, causal)
