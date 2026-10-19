"""Exact pedigree likelihoods by variable elimination.

The pedigree is a Bayesian network: each person's genotype depends on their parents' genotypes (Mendel's laws),
and their phenotype and genotype calls depend on their own genotype. The likelihood of what's observed is the sum,
over every possible assignment of genotypes, of the product of these probabilities. Variable elimination sums the
genotypes out one at a time, in an order chosen to keep the intermediate tables small. Unlike the Elston-Stewart
peeling of a family tree, it is exact for pedigrees with loops too (consanguinity, or two families married into each
other twice), at a cost that grows with how tangled the loops are rather than with the size of the pedigree.

Many likelihoods are computed at once: each person's "unary" factor (their founder prior, phenotype probabilities,
genotype evidence) can carry a leading batch axis, so that one pass gives the likelihood for each of many
penetrances, probands or variants. A large batch is split up so that no table grows too large for memory.

The genotype at the locus is a variable whose states the locus defines: by default the number of copies of one
alternate allele (see models), and for a pair of variants in one gene, the pair of haplotypes a person carries
(see compound).
"""
import math
import string
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .models import domain, transmission
from .pedigree import FEMALE, MALE, Pedigree

_LETTERS = string.ascii_letters
# The most numbers a table may hold (batch included) before a batch is split up: 4 million, or 32 MB
MAX_TABLE = 4_000_000
# The largest table a pedigree may need for one likelihood: beyond it, the pedigree has too many loops
MAX_STATES = 50_000_000


class Plan:
    """
    The order in which to sum out the genotypes, and which tables each step combines. feasible is whether the
    largest table is small enough for exact likelihoods; if it isn't, a ValueError is raised, unless check is False.
    """

    def __init__(self, scopes: Sequence[Tuple[int, ...]], domains: Sequence[int], check: bool = True):
        n = len(domains)
        factor_vars: Dict[int, Tuple[int, ...]] = {f: tuple(s) for f, s in enumerate(scopes)}
        var_factors: Dict[int, set] = {v: set() for v in range(n)}
        neighbours: Dict[int, set] = {v: set() for v in range(n)}
        for f, s in factor_vars.items():
            for v in s:
                var_factors[v].add(f)
                neighbours[v].update(u for u in s if u != v)
        self.steps: List[Tuple[Tuple[int, ...], int, Tuple[int, ...], int]] = []
        self.width = 0      # the most genotypes in one step
        self.largest = 1    # the most states in one step's table
        next_factor = len(scopes)
        remaining = set(range(n))
        cache: Dict[int, Tuple[int, float]] = {}

        def score(v):
            # the fill-in a step would add (new pairs of neighbours), then the size of the table it would make
            if v not in cache:
                nb = sorted(neighbours[v])
                fill = sum(1 for i, a in enumerate(nb) for b in nb[i + 1:] if b not in neighbours[a])
                size = float(np.prod([domains[u] for u in nb])) if nb else 1.0
                cache[v] = (fill, size)
            return cache[v] + (v,)

        while remaining:
            v = min(remaining, key=score)
            involved = tuple(sorted(var_factors[v]))
            union = sorted(set().union(*(factor_vars[f] for f in involved)) | {v})
            out = tuple(u for u in union if u != v)
            self.width = max(self.width, len(union))
            # math.prod, whose whole numbers can't overflow as NumPy's 64-bit ones would for a very wide table
            self.largest = max(self.largest, math.prod(domains[u] for u in union))
            self.steps.append((involved, v, out, next_factor))
            for f in involved:
                for u in factor_vars.pop(f):
                    var_factors[u].discard(f)
            factor_vars[next_factor] = out
            for u in out:
                var_factors[u].add(next_factor)
            touched = set(neighbours[v])
            for u in out:
                neighbours[u].update(w for w in out if w != u)
                neighbours[u].discard(v)
            del neighbours[v]
            remaining.discard(v)
            for u in touched:
                cache.pop(u, None)
                for w in neighbours.get(u, ()):
                    cache.pop(w, None)
            next_factor += 1
        self.feasible = self.width <= len(_LETTERS) and self.largest <= MAX_STATES
        if check and not self.feasible:
            raise ValueError('This pedigree has too many loops for exact likelihoods: summing out its genotypes '
                             f'needs a table of {self.largest:,} states')


def _log(x):
    with np.errstate(divide='ignore'):
        return np.log(x)


class Network:
    """
    The genotype network of one pedigree, for an autosomal or an X-linked locus.

    people's genotype kinds: A (autosomal); on the X, M for men, F for women and U for anyone of unknown sex (who,
    having no children, can be summed over as either).

    locus, if given, defines the genotypes' states instead of the single biallelic variant of models: an object with
    domain(kind), the number of states, and transmission(kind), the [child, father, mother] table. check False makes
    a network whose plan can be looked at even when it is too large to work with (see Plan).
    """

    def __init__(self, pedigree: Pedigree, x_linked: bool, locus=None, check: bool = True):
        self.pedigree = pedigree
        self.x_linked = x_linked
        self.ids = pedigree.ids
        index = {pid: i for i, pid in enumerate(self.ids)}
        self.kinds: List[str] = []
        for p in pedigree.people:
            if not x_linked:
                self.kinds.append('A')
            elif p.sex == MALE:
                self.kinds.append('M')
            elif p.sex == FEMALE:
                self.kinds.append('F')
            else:
                self.kinds.append('U')
        size = domain if locus is None else locus.domain
        make = transmission if locus is None else locus.transmission
        self.domains = [size(k) for k in self.kinds]
        self.parents: List[Optional[Tuple[int, int]]] = []
        scopes: List[Tuple[int, ...]] = []
        self._transmission: Dict[int, np.ndarray] = {}
        for i, p in enumerate(pedigree.people):
            if p.father is None:
                self.parents.append(None)
                continue
            f, m = index[p.father], index[p.mother]
            self.parents.append((f, m))
            self._transmission[len(scopes)] = make(self.kinds[i])
            scopes.append((i, f, m))
        self._n_transmission = len(scopes)
        scopes.extend((i,) for i in range(len(self.ids)))
        self.scopes = scopes
        self.plan = Plan(scopes, self.domains, check)
        self.founders = [i for i, par in enumerate(self.parents) if par is None]

    def index(self, person_id: str) -> int:
        return self.ids.index(person_id)

    def log_likelihood(self, unary: Sequence[np.ndarray]) -> np.ndarray:
        """
        The natural log of the likelihood, given each person's unary factor: an array of shape (states,) or
        (batch, states), the product of whatever applies to that person alone (founder prior, phenotype
        probabilities, genotype evidence). Returns an array of shape (batch,).
        """
        unary = [np.asarray(u, dtype=float) for u in unary]
        batch = max((u.shape[0] for u in unary if u.ndim == 2), default=1)
        step = max(1, MAX_TABLE // self.plan.largest)
        if batch <= step:
            return self._log_likelihood(unary, batch)
        parts = []
        for start in range(0, batch, step):
            stop = min(start + step, batch)
            parts.append(self._log_likelihood([u[start:stop] if u.ndim == 2 and u.shape[0] == batch else u
                                               for u in unary], stop - start))
        return np.concatenate(parts)

    def _log_likelihood(self, unary: Sequence[np.ndarray], batch: int) -> np.ndarray:
        tables: Dict[int, np.ndarray] = dict(self._transmission)
        for i, u in enumerate(unary):
            u = np.broadcast_to(u.reshape(-1, u.shape[-1]), (batch, u.shape[-1]))
            tables[self._n_transmission + i] = u
        scopes = {f: s for f, s in enumerate(self.scopes)}
        is_batched = {f: f >= self._n_transmission for f in scopes}
        log_scale = np.zeros(batch)
        for involved, var, out, new in self.plan.steps:
            union = sorted(set().union(*(scopes[f] for f in involved)) | {var})
            letter = {v: _LETTERS[k] for k, v in enumerate(union)}
            operands, terms = [], []
            any_batched = False
            for f in involved:
                operands.append(tables.pop(f))
                prefix = '...' if is_batched[f] else ''
                any_batched |= is_batched[f]
                terms.append(prefix + ''.join(letter[v] for v in scopes.pop(f)))
                del is_batched[f]
            result = np.einsum(','.join(terms) + '->' + ('...' if any_batched else '') + ''.join(letter[v] for v in out),
                               *operands)
            if any_batched:
                flat = result.reshape(batch, -1) if out else result.reshape(batch, 1)
                peak = flat.max(axis=1)
                safe = np.where(peak > 0, peak, 1.0)
                result = result / safe.reshape((batch,) + (1,) * len(out))
                log_scale += _log(peak)
            tables[new] = result
            scopes[new] = out
            is_batched[new] = any_batched
        total = np.ones(batch)
        for f, t in tables.items():
            total = total * (t if is_batched[f] else float(t))
        return log_scale + _log(total)
