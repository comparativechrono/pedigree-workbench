"""Pairs of variants in one gene, as a compound heterozygote.

A recessive condition is often caused by two different variants in the same gene, one on each copy of the gene.
Neither variant then segregates as a recessive variant should (the affected people have one copy of each, not two
of either), so PedNet also scores the pairs of variants in a gene that an affected person carries both of.

The gene is then a locus with four haplotypes: a copy of the gene with neither variant (r), with the first only
(a), with the second only (b), or with both (c, the two variants in cis). Someone's genotype is a pair of
haplotypes, which gives ten states; on the X chromosome a man has a single haplotype, four states. Under a
recessive mode the disease genotype is two copies that each carry a variant (on the X, a man's one copy). In a
founder the haplotypes have the frequencies they would have in linkage equilibrium. Two rare variants on one copy
(cis) are then about as likely in a founder as one on each copy (trans), and the family's genotypes show which
they are: in cis, the two are passed on together.
"""
from functools import lru_cache
from typing import TYPE_CHECKING, Dict, Optional, Sequence, Tuple

import numpy as np

from .engine import Network
from .inheritance import _logsumexp
from .models import Model, call_codes, call_probability
from .pedigree import Pedigree

if TYPE_CHECKING:
    from .segregation import Variant

# the copies of the first and of the second variant on each haplotype: r, a, b and c
HAPLOTYPES = ((0, 0), (1, 0), (0, 1), (1, 1))
PAIRS = tuple((i, j) for i in range(4) for j in range(i, 4))
PAIR_MODES = ('AR', 'XLR')


@lru_cache(maxsize=None)
def _states(kind: str) -> Tuple[Tuple[Tuple[int, ...], bool], ...]:
    """Each state of a genotype of this kind, as its haplotypes and whether it is a man's"""
    men = tuple(((h,), True) for h in range(4))
    pairs = tuple((pair, False) for pair in PAIRS)
    return {'A': pairs, 'F': pairs, 'M': men, 'U': men + pairs}[kind]


class PairLocus:
    """The four haplotypes of a pair of variants in one gene, as a locus for Network"""

    @staticmethod
    def domain(kind: str) -> int:
        return len(_states(kind))

    @staticmethod
    def transmission(kind: str) -> np.ndarray:
        return _transmission(kind)


@lru_cache(maxsize=None)
def _transmission(kind: str) -> np.ndarray:
    """P(child's state | father's state, mother's state), indexed [child, father, mother], as in models.transmission"""
    n = len(PAIRS)
    position = {pair: k for k, pair in enumerate(PAIRS)}
    if kind == 'A':
        t = np.zeros((n, n, n))
        for f, father in enumerate(PAIRS):
            for m, mother in enumerate(PAIRS):
                for a in father:
                    for b in mother:
                        t[position[tuple(sorted((a, b)))], f, m] += 0.25
        return t
    son = np.zeros((4, 4, n))
    daughter = np.zeros((n, 4, n))
    for h in range(4):
        for m, mother in enumerate(PAIRS):
            for b in mother:
                # a son has one of his mother's copies; a daughter her father's only copy and one of her mother's
                son[b, h, m] += 0.5
                daughter[position[tuple(sorted((h, b)))], h, m] += 0.5
    if kind == 'M':
        return son
    if kind == 'F':
        return daughter
    return np.concatenate([0.5 * son, 0.5 * daughter], axis=0)


def founder_prior(kind: str, q1, q2) -> np.ndarray:
    """The founder genotype probabilities, for variant frequencies q1 and q2 (single values, or one per batch)"""
    q1, q2 = np.asarray(q1, dtype=float), np.asarray(q2, dtype=float)
    hap = np.stack([(1 - q1) * (1 - q2), q1 * (1 - q2), (1 - q1) * q2, q1 * q2], axis=-1)
    diploid = np.stack([hap[..., i] * hap[..., j] * (1.0 if i == j else 2.0) for i, j in PAIRS], axis=-1)
    if kind in ('A', 'F'):
        return diploid
    if kind == 'M':
        return hap
    return np.concatenate([0.5 * hap, 0.5 * diploid], axis=-1)


@lru_cache(maxsize=None)
def genotype_table(kind: str, error_rate: float) -> np.ndarray:
    """genotype_factor for every pair of calls, indexed by the codes of models.call_codes; read-only"""
    calls = (None, 0, 1, 2)
    table = np.stack([np.stack([genotype_factor(kind, a, b, error_rate) for b in calls]) for a in calls])
    table.flags.writeable = False
    return table


def genotype_factor(kind: str, called1: Optional[int], called2: Optional[int], error_rate: float) -> np.ndarray:
    """P(the two genotype calls) for each state, with the error model of models.genotype_factor for each call"""
    out = np.ones(len(_states(kind)))
    for k, (haps, male) in enumerate(_states(kind)):
        if called1 is not None:
            out[k] *= call_probability(sum(HAPLOTYPES[h][0] for h in haps), male, called1, error_rate)
        if called2 is not None:
            out[k] *= call_probability(sum(HAPLOTYPES[h][1] for h in haps), male, called2, error_rate)
    return out


def _damaged(haps) -> int:
    """How many of the copies carry a variant"""
    return sum(1 for h in haps if h != 0)


def affected_probability(model: Model, kind: str) -> np.ndarray:
    """P(affected) for each state, under a recessive mode (AR, or XLR with its carrier penetrance for women)"""
    f, p = model.penetrance, model.phenocopy
    h = p if model.carrier_penetrance is None else model.carrier_penetrance
    out = []
    for haps, male in _states(kind):
        damaged = _damaged(haps)
        if male:
            out.append(f if damaged else p)
        elif model.mode == 'XLR':
            out.append(f if damaged == 2 else (h if damaged == 1 else p))
        else:
            out.append(f if damaged == 2 else p)
    return np.array(out)


def phenotype_factor(model: Model, kind: str, phenotype: int) -> np.ndarray:
    affected = affected_probability(model, kind)
    if phenotype == 2:
        return affected
    if phenotype == 1:
        return 1 - affected
    return np.ones(len(affected))


def has_disease_genotype(copies1: int, copies2: int, male: Optional[bool]) -> bool:
    """Whether genotype calls fit the disease genotype of a compound heterozygote (or a homozygote of either)"""
    if male:
        return copies1 >= 1 or copies2 >= 1
    return (copies1 >= 1 and copies2 >= 1) or copies1 == 2 or copies2 == 2


def pair_log_likelihoods(pedigree: Pedigree, net: Network, pairs: Sequence[Tuple['Variant', 'Variant']],
                         frequencies: Sequence[Tuple[float, float]], modes: Sequence[str], models: Dict[str, Model],
                         pens: Sequence[float], log_w: np.ndarray, error_rate: float) -> Dict[str, np.ndarray]:
    """
    For each mode, the natural log of P(phenotypes | both pairs' genotypes, the pair causes the condition) for each
    pair, averaged over the penetrances with weights exp(log_w). net must be a Network with a PairLocus.
    """
    V, F = len(pairs), len(pens)
    q1 = np.array([f[0] for f in frequencies])
    q2 = np.array([f[1] for f in frequencies])
    first, second = [a for a, _ in pairs], [b for _, b in pairs]
    evidence = []
    for i, (kind, person) in enumerate(zip(net.kinds, pedigree.people)):
        e = genotype_table(kind, error_rate)[call_codes(first, person.id), call_codes(second, person.id)]
        if net.parents[i] is None:
            e = e * founder_prior(kind, q1, q2)
        evidence.append(e)
    log_genotypes = net.log_likelihood(evidence)
    out = {}
    for mode in modes:
        model = models[mode]
        unary = []
        for i, (kind, person) in enumerate(zip(net.kinds, pedigree.people)):
            phen = np.stack([phenotype_factor(model.with_(penetrance=f), kind, person.phenotype) for f in pens])
            unary.append((phen[:, None, :] * evidence[i][None, :, :]).reshape(F * V, -1))
        joint = net.log_likelihood(unary).reshape(F, V)
        with np.errstate(invalid='ignore'):
            # NaN where the genotypes have no probability at all, which the caller reports
            out[mode] = _logsumexp(joint + log_w[:, None], axis=0) - log_genotypes
    return out
