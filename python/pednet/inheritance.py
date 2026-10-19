"""The mode of inheritance that best explains a family's phenotypes.

For each mode (autosomal dominant or recessive, X-linked recessive or dominant), PedNet works out the probability of
everyone's phenotype given that the proband has the disease genotype for that mode, summing over every genotype the
rest of the family could have. Conditioning on the proband takes account of how the family came to be seen, and
makes the answer depend little on how common the disease allele is. The penetrance isn't known, so the probability
is averaged over a range of penetrances, and if no proband is given it is averaged over each affected person as the
proband. With the modes' prior probabilities, Bayes' theorem then gives each mode's posterior probability.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from .engine import Network
from .models import MODE_NAMES, MODES, X_LINKED, Model, founder_prior, phenotype_factor
from .pedigree import Pedigree

# The penetrances averaged over, equally weighted, when it isn't known
DEFAULT_PENETRANCE = (0.6, 0.8, 0.95, 0.99)
DEFAULT_PHENOCOPY = 0.001
LN10 = np.log(10)


def _logsumexp(x, axis=None):
    x = np.asarray(x, dtype=float)
    peak = np.max(x, axis=axis, keepdims=True)
    peak = np.where(np.isfinite(peak), peak, 0.0)
    with np.errstate(divide='ignore'):
        out = np.log(np.sum(np.exp(x - peak), axis=axis, keepdims=True)) + peak
    return np.squeeze(out, axis=axis) if axis is not None else float(out.reshape(()))


def _weights(penetrance, weights) -> np.ndarray:
    if np.isscalar(penetrance):
        penetrance = (float(penetrance),)
    w = np.ones(len(penetrance)) if weights is None else np.asarray(weights, dtype=float)
    if len(w) != len(penetrance) or np.any(w < 0) or w.sum() == 0:
        raise ValueError('penetrance_weights must be one non-negative weight for each penetrance')
    return w / w.sum()


def _prior(modes, prior) -> Dict[str, float]:
    if prior is None:
        return {m: 1 / len(modes) for m in modes}
    total = sum(prior.get(m, 0) for m in modes)
    if total <= 0:
        raise ValueError('The prior must give some probability to one of the modes')
    return {m: prior.get(m, 0) / total for m in modes}


def _modes(modes) -> List[str]:
    if isinstance(modes, str):
        modes = [m.strip() for m in modes.replace(',', ' ').split()]
    modes = [m.upper() for m in modes]
    for m in modes:
        if m not in MODES:
            raise ValueError(f'Unknown mode of inheritance {m!r}: use one of {", ".join(MODES)}')
    return modes


@dataclass
class ModeEvidence:
    mode: str
    posterior: float
    log10_likelihood: float

    @property
    def name(self) -> str:
        return MODE_NAMES[self.mode]


@dataclass
class InheritanceResult:
    """
    The modes, most probable first. call is the most probable mode if its posterior probability reaches threshold,
    and 'uncertain' otherwise. log10_likelihood is the log10 probability of the phenotypes under each mode (given
    the proband), whose differences are log10 likelihood ratios.
    """
    family: str
    modes: List[ModeEvidence]
    call: str
    threshold: float
    probands: List[str]
    notes: List[str] = field(default_factory=list)

    def posterior(self, mode: str) -> float:
        return next((m.posterior for m in self.modes if m.mode == mode), 0.0)

    @property
    def dominant(self) -> float:
        """The probability that the condition is dominant (AD or XLD), among the modes weighed up"""
        return self.posterior('AD') + self.posterior('XLD')

    @property
    def recessive(self) -> float:
        """The probability that it is recessive (AR or XLR)"""
        return self.posterior('AR') + self.posterior('XLR')

    @property
    def x_linked(self) -> float:
        """The probability that it is X-linked (XLR or XLD)"""
        return self.posterior('XLR') + self.posterior('XLD')

    def table(self) -> List[dict]:
        return [{'family': self.family, 'mode': m.mode, 'posterior': m.posterior, 'log10_likelihood': m.log10_likelihood}
                for m in self.modes]

    def __str__(self):
        lines = [f'Family {self.family}: {self.call if self.call == "uncertain" else MODE_NAMES[self.call]}']
        for m in self.modes:
            lines.append(f'  {m.mode:4s} {m.posterior:6.3f}   ({m.name})')
        names = {m.mode for m in self.modes}
        if names & {'AD', 'XLD'} and names & {'AR', 'XLR'}:
            lines.append(f'  dominant {self.dominant:.3f}, recessive {self.recessive:.3f}')
        if names & {'XLR', 'XLD'} and names & {'AD', 'AR'}:
            lines.append(f'  X-linked {self.x_linked:.3f}, autosomal {1 - self.x_linked:.3f}')
        lines.extend(f'  note: {n}' for n in self.notes)
        return '\n'.join(lines)


def mode_log_likelihoods(pedigree: Pedigree, modes: Sequence[str] = MODES,
                         penetrance=DEFAULT_PENETRANCE, penetrance_weights=None,
                         phenocopy: float = DEFAULT_PHENOCOPY, allele_frequency: Optional[Dict[str, float]] = None,
                         carrier_penetrance: Optional[float] = None, probands: Optional[Sequence[str]] = None,
                         networks: Optional[Dict[bool, Network]] = None) -> Dict[str, float]:
    """
    The natural log of P(phenotypes | proband has the disease genotype, mode) for each mode, averaged over the
    penetrances (with penetrance_weights) and over the probands (by default everyone affected).
    """
    modes = _modes(modes)
    pens = (float(penetrance),) if np.isscalar(penetrance) else tuple(float(f) for f in penetrance)
    with np.errstate(divide='ignore'):
        log_w = np.log(_weights(pens, penetrance_weights))
    probands = list(probands) if probands else pedigree.affected()
    if not probands:
        return {m: 0.0 for m in modes}
    networks = {} if networks is None else networks
    allele_frequency = allele_frequency or {}
    result = {}
    for mode in modes:
        x = X_LINKED[mode]
        if x not in networks:
            networks[x] = Network(pedigree, x)
        net = networks[x]
        model = Model(mode, allele_frequency.get(mode), pens[0], phenocopy, carrier_penetrance)
        F, A = len(pens), len(probands)
        positions = [net.index(p) for p in probands]
        with_phenotypes, without = [], []
        for i, (kind, person) in enumerate(zip(net.kinds, pedigree.people)):
            base = founder_prior(kind, model.allele_frequency) if net.parents[i] is None else np.ones(len(model.causal(kind)))
            u = np.tile(base, (F * A, 1))
            for fi, f in enumerate(pens):
                u[fi * A:(fi + 1) * A] *= phenotype_factor(model.with_(penetrance=f), kind, person.phenotype)
            u0 = np.tile(base, (A, 1))
            for ai, pos in enumerate(positions):
                if pos == i:
                    u[ai::A] *= model.causal(kind)
                    u0[ai] *= model.causal(kind)
            with_phenotypes.append(u)
            without.append(u0)
        joint = net.log_likelihood(with_phenotypes).reshape(F, A)
        proband_causal = net.log_likelihood(without)
        with np.errstate(invalid='ignore'):
            conditional = np.where(np.isfinite(proband_causal)[None, :], joint - proband_causal[None, :], -np.inf)
        result[mode] = _logsumexp(conditional + log_w[:, None] - np.log(A))
    return result


def infer_mode(pedigree: Pedigree, modes: Sequence[str] = MODES, penetrance=DEFAULT_PENETRANCE,
               penetrance_weights=None, phenocopy: float = DEFAULT_PHENOCOPY,
               allele_frequency: Optional[Dict[str, float]] = None, carrier_penetrance: Optional[float] = None,
               prior: Optional[Dict[str, float]] = None, proband: Optional[str] = None,
               threshold: float = 0.8) -> InheritanceResult:
    """
    The posterior probability of each mode of inheritance for a pedigree.

    pedigree: a Pedigree (see read_ped)
    modes: the modes to weigh up, from 'AD', 'AR', 'XLR' and 'XLD'
    penetrance: the penetrance, or several to average over (by default 0.6, 0.8, 0.95 and 0.99, equally weighted)
    penetrance_weights: the weight of each penetrance, if not equal
    phenocopy: the chance that someone without the disease genotype is affected
    allele_frequency: the disease allele frequency for each mode, if not the defaults
    carrier_penetrance: for X-linked recessive, the chance that a woman with one copy is affected
    prior: the prior probability of each mode (equal by default)
    proband: the person through whom the family was found; by default each affected person in turn
    threshold: the posterior probability the most probable mode needs for the call not to be 'uncertain'
    """
    modes = _modes(modes)
    priors = _prior(modes, prior)
    notes = list(pedigree.notes)
    affected = pedigree.affected()
    if proband is not None:
        if proband not in pedigree:
            raise ValueError(f'{proband} is not in family {pedigree.family}')
        if not pedigree[proband].affected:
            notes.append(f'the proband, {proband}, is not recorded as affected')
        probands = [proband]
    else:
        probands = affected
    if not affected:
        notes.append('no one is affected, so the phenotypes say nothing about the mode of inheritance')
    elif len(affected) == 1:
        notes.append('only one person is affected: a new dominant mutation, which PedNet doesn\'t model, would '
                     'explain that as well as a recessive condition does')
    x_needed = any(X_LINKED[m] for m in modes)
    unknown_sex = [p.id for p in pedigree.people if p.sex == 0 and not p.placeholder]
    if x_needed and unknown_sex:
        notes.append(f'the sex of {", ".join(unknown_sex[:5])}{" and others" if len(unknown_sex) > 5 else ""} '
                     'is unknown, and is taken as equally likely to be either for the X-linked modes')
    if probands:
        logs = mode_log_likelihoods(pedigree, modes, penetrance, penetrance_weights, phenocopy, allele_frequency,
                                    carrier_penetrance, probands)
    else:
        logs = {m: 0.0 for m in modes}
    log_post = np.array([np.log(priors[m]) + logs[m] if priors[m] > 0 else -np.inf for m in modes])
    total = _logsumexp(log_post)
    possible = bool(np.isfinite(total))
    post = np.exp(log_post - total) if possible else np.array([priors[m] for m in modes])
    if probands and not possible:
        notes.append('none of the modes allowed can give these phenotypes with this penetrance and phenocopy rate, '
                     'so the probabilities shown are the priors')
    evidence = [ModeEvidence(m, float(post[k]), float(logs[m] / LN10)) for k, m in enumerate(modes)]
    evidence.sort(key=lambda e: -e.posterior)
    call = evidence[0].mode if probands and possible and evidence[0].posterior >= threshold else 'uncertain'
    return InheritanceResult(pedigree.family, evidence, call, threshold, probands, notes)


def infer_shared_mode(pedigrees, modes: Sequence[str] = MODES, penetrance=DEFAULT_PENETRANCE,
                      penetrance_weights=None, phenocopy: float = DEFAULT_PHENOCOPY,
                      allele_frequency: Optional[Dict[str, float]] = None, carrier_penetrance: Optional[float] = None,
                      prior: Optional[Dict[str, float]] = None, threshold: float = 0.8) -> InheritanceResult:
    """
    The posterior probability of each mode of inheritance for a condition that several families share, from the
    product of the families' likelihoods (they are taken to be unrelated, with the same mode of inheritance, though
    not necessarily the same gene). pedigrees is a dict of family to Pedigree, as read_ped gives, or a list of
    pedigrees; the other arguments are as for infer_mode.
    """
    if isinstance(pedigrees, dict):
        pedigrees = list(pedigrees.values())
    modes = _modes(modes)
    priors = _prior(modes, prior)
    totals = {m: 0.0 for m in modes}
    notes, probands = [], []
    for pedigree in pedigrees:
        result = infer_mode(pedigree, modes, penetrance, penetrance_weights, phenocopy, allele_frequency,
                            carrier_penetrance, None, None, threshold)
        for m in result.modes:
            totals[m.mode] += m.log10_likelihood * LN10
        notes.extend(f'family {pedigree.family}: {n}' for n in result.notes)
        probands.extend(result.probands)
    log_post = np.array([np.log(priors[m]) + totals[m] if priors[m] > 0 else -np.inf for m in modes])
    total = _logsumexp(log_post)
    possible = bool(np.isfinite(total))
    post = np.exp(log_post - total) if possible else np.array([priors[m] for m in modes])
    if probands and not possible:
        notes.append('none of the modes allowed can give these phenotypes with this penetrance and phenocopy rate, '
                     'so the probabilities shown are the priors')
    evidence = [ModeEvidence(m, float(post[k]), float(totals[m] / LN10)) for k, m in enumerate(modes)]
    evidence.sort(key=lambda e: -e.posterior)
    call = evidence[0].mode if probands and possible and evidence[0].posterior >= threshold else 'uncertain'
    return InheritanceResult(', '.join(p.family for p in pedigrees), evidence, call, threshold, probands, notes)
