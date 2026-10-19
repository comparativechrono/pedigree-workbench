"""Modes of inheritance, and the genotype probabilities they give.

Each person's genotype at the locus is a variable with a few states. For an autosomal locus these are the number of
copies of the alternate (disease) allele, 0, 1 or 2 (kind "A"). On the X chromosome a man has one copy, 0 or 1
(kind "M"), and a woman two (kind "F"). Someone of unknown sex who has no children has the man's two states and the
woman's three, each equally likely beforehand (kind "U"); a parent's sex is always known from their role.
"""
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Dict, Optional

import numpy as np

MODES = ('AD', 'AR', 'XLR', 'XLD')
MODE_NAMES = {'AD': 'autosomal dominant', 'AR': 'autosomal recessive',
              'XLR': 'X-linked recessive', 'XLD': 'X-linked dominant'}
X_LINKED = {'AD': False, 'AR': False, 'XLR': True, 'XLD': True}

# the number of copies of the alternate allele in each state, and whether the state is a man's
ALT_COPIES = {'A': (0, 1, 2), 'M': (0, 1), 'F': (0, 1, 2), 'U': (0, 1, 0, 1, 2)}
IS_MALE = {'A': (None, None, None), 'M': (True, True), 'F': (False, False, False),
           'U': (True, True, False, False, False)}

# Default disease allele frequencies. The mode of inheritance is judged given that the proband carries the disease
# genotype, which makes the results depend little on these, as long as the allele is rare.
DEFAULT_FREQUENCY = {'AD': 1e-4, 'AR': 1e-3, 'XLR': 5e-4, 'XLD': 1e-4}


def domain(kind: str) -> int:
    return len(ALT_COPIES[kind])


@dataclass(frozen=True)
class Model:
    """
    A mode of inheritance with its parameters:

    mode: 'AD', 'AR', 'XLR' or 'XLD'
    allele_frequency: the disease allele's frequency in the population
    penetrance: the chance that someone with the disease genotype is affected
    phenocopy: the chance that someone without it is affected all the same
    carrier_penetrance: for XLR only, the chance that a woman with one copy is affected (by default the phenocopy rate)
    """
    mode: str
    allele_frequency: Optional[float] = None
    penetrance: float = 0.95
    phenocopy: float = 0.001
    carrier_penetrance: Optional[float] = None

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(f'Unknown mode of inheritance {self.mode!r}: use one of {", ".join(MODES)}')
        if self.allele_frequency is None:
            object.__setattr__(self, 'allele_frequency', DEFAULT_FREQUENCY[self.mode])
        for name in ('allele_frequency', 'penetrance', 'phenocopy'):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f'{name} must be between 0 and 1, not {value}')

    def with_(self, **changes) -> 'Model':
        return replace(self, **changes)

    @property
    def x_linked(self) -> bool:
        return X_LINKED[self.mode]

    def kinds(self):
        return ('M', 'F', 'U') if self.x_linked else ('A',)

    def affected_probability(self, kind: str) -> np.ndarray:
        """P(affected) for each state of a genotype of this kind"""
        f, p = self.penetrance, self.phenocopy
        h = p if self.carrier_penetrance is None else self.carrier_penetrance
        if self.mode == 'AD':
            return np.array([p, f, f])
        if self.mode == 'AR':
            return np.array([p, p, f])
        male = np.array([p, f])
        female = np.array([p, h, f]) if self.mode == 'XLR' else np.array([p, f, f])
        return {'M': male, 'F': female, 'U': np.concatenate([male, female])}[kind]

    def causal(self, kind: str) -> np.ndarray:
        """Which states of a genotype of this kind are the disease genotype (as 1.0 or 0.0)"""
        if self.mode == 'AD':
            return np.array([0., 1., 1.])
        if self.mode == 'AR':
            return np.array([0., 0., 1.])
        male = np.array([0., 1.])
        female = np.array([0., 0., 1.]) if self.mode == 'XLR' else np.array([0., 1., 1.])
        return {'M': male, 'F': female, 'U': np.concatenate([male, female])}[kind]


def founder_prior(kind: str, q) -> np.ndarray:
    """
    The genotype probabilities of someone with no parents in the pedigree, in Hardy-Weinberg proportions.
    q may be a single allele frequency or an array of them (one per batch), giving shape (batch, states).
    """
    q = np.asarray(q, dtype=float)
    p = 1 - q
    diploid = np.stack([p * p, 2 * p * q, q * q], axis=-1)
    haploid = np.stack([p, q], axis=-1)
    if kind in ('A', 'F'):
        return diploid
    if kind == 'M':
        return haploid
    return np.concatenate([0.5 * haploid, 0.5 * diploid], axis=-1)


def phenotype_factor(model: Model, kind: str, phenotype: int) -> np.ndarray:
    """P(the person's phenotype) for each state: 2 affected, 1 unaffected, anything else unknown"""
    affected = model.affected_probability(kind)
    if phenotype == 2:
        return affected
    if phenotype == 1:
        return 1 - affected
    return np.ones(domain(kind))


def genotype_factor(kind: str, alt_copies: Optional[int], error_rate: float = 1e-4) -> np.ndarray:
    """
    P(the observed genotype) for each state, allowing for genotyping errors. alt_copies is the number of copies of the
    alternate allele called (0, 1 or 2), or None if the person wasn't genotyped.

    A call one copy out (a heterozygote called homozygous, or the other way) happens with probability error_rate,
    and one two copies out (a homozygote called the other homozygote) with probability error_rate squared, so that a
    rare variant called homozygous in two affected siblings isn't put down to two errors. A man's X-chromosome call
    counts as the alternate allele if it has any copy of it; calling his allele when he doesn't have it is a single
    error, and missing it when he does is a double one, since he has nothing else at that position.
    """
    states = ALT_COPIES[kind]
    if alt_copies is None:
        return np.ones(len(states))
    return np.array([call_probability(copies, male, alt_copies, error_rate)
                     for copies, male in zip(states, IS_MALE[kind])])


@lru_cache(maxsize=None)
def genotype_table(kind: str, error_rate: float) -> np.ndarray:
    """
    genotype_factor for every call, as rows: not genotyped, then 0, 1 and 2 copies called, to be indexed by
    call_codes. The table is shared, so it is read-only.
    """
    table = np.stack([genotype_factor(kind, called, error_rate) for called in (None, 0, 1, 2)])
    table.flags.writeable = False
    return table


def call_codes(variants, person_id: str) -> np.ndarray:
    """Each variant's genotype call in one person as a row of genotype_table: 0 if not genotyped, else copies + 1"""
    return np.array([0 if g is None else min(int(g), 2) + 1
                     for g in (v.genotypes.get(person_id) for v in variants)], dtype=np.intp)


def call_probability(copies: int, male: Optional[bool], called: int, error_rate: float) -> float:
    """
    The chance of a genotype call of called copies of the alternate allele from someone with copies of it, for a
    man's X chromosome (male True) or a pair of chromosomes (see genotype_factor)
    """
    e = error_rate
    if male:
        if called >= 1:
            return 1 - e * e if copies == 1 else e
        return 1 - e if copies == 0 else e * e
    off = abs(called - copies)
    if off == 0:
        return 1 - 2 * e if copies == 1 else 1 - e - e * e
    return e if off == 1 else e * e


def _passes(copies: int) -> float:
    """The chance that a parent with this many copies passes one on (a man passes his X to every daughter)"""
    return copies / 2


def transmission(kind: str) -> np.ndarray:
    """
    P(child's state | father's state, mother's state), as an array indexed [child, father, mother].
    For an autosomal locus all three are of kind A. On the X chromosome, the father is of kind M and the mother of
    kind F, and the child of the kind given (M a son, F a daughter, U unknown sex).
    """
    if kind == 'A':
        t = np.zeros((3, 3, 3))
        for f in range(3):
            for m in range(3):
                a, b = _passes(f), _passes(m)
                t[2, f, m] = a * b
                t[1, f, m] = a * (1 - b) + (1 - a) * b
                t[0, f, m] = (1 - a) * (1 - b)
        return t
    son = np.zeros((2, 2, 3))
    daughter = np.zeros((3, 2, 3))
    for h in range(2):
        for m in range(3):
            b = _passes(m)
            son[1, h, m], son[0, h, m] = b, 1 - b
            # a daughter has her father's only X, and one of her mother's two
            daughter[h + 1, h, m] += b
            daughter[h, h, m] += 1 - b
    if kind == 'M':
        return son
    if kind == 'F':
        return daughter
    return np.concatenate([0.5 * son, 0.5 * daughter], axis=0)


def default_models(modes=MODES, penetrance: float = 0.95, phenocopy: float = 0.001,
                   allele_frequency: Optional[Dict[str, float]] = None) -> Dict[str, Model]:
    allele_frequency = allele_frequency or {}
    return {m: Model(m, allele_frequency.get(m), penetrance, phenocopy) for m in modes}
