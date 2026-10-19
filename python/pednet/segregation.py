"""How strongly each candidate variant co-segregates with the condition.

For each variant, PedNet compares two explanations of the family's phenotypes:

- the variant causes the condition: the genotypes at the disease locus are the variant's genotypes, so the people
  who were sequenced fix part of the picture, and the genotypes of the rest are summed over
- it doesn't: the condition comes from some other, unseen locus, which the proband carries (the family having come
  to notice through the proband), and whose genotypes in everyone else are summed over

The ratio of the two probabilities is the variant's co-segregation likelihood ratio (a Bayes factor). It is 2 to
the power of the number of informative meioses for a variant that follows the condition exactly with full
penetrance, the measure used for the co-segregation criteria of variant classification. Above 1, the variant
follows the condition through the family better than an unseen locus would be expected to; below 1, worse. Both
explanations average over the same penetrances, and over the modes of inheritance that suit the variant's
chromosome (autosomal dominant and recessive for an autosomal variant, X-linked recessive and dominant for one on
the X), each weighted by how well it explains the phenotypes.

Candidates are ranked by their odds against an unseen locus: the Bayes factor times the probability that the mode
is one that suits the candidate's chromosome, so that an X-linked variant ranks low in a family whose condition is
clearly autosomal, and the other way round.

Pairs of variants in the same gene are scored in the same way as compound heterozygotes, under the recessive modes
(see compound), and rank alongside the single variants.

The Bayes factor is the full-likelihood Bayes factor for co-segregation of Thompson et al. (2003), as segregatr
computes it, except that PedNet conditions on the proband having the disease genotype rather than on the proband's
genotype call: the same condition for every variant, so that their Bayes factors can be compared. Its strength as
evidence for the PP1 criterion of the ACMG/AMP guidelines (or against, BS4) is given by the Bayes factor thresholds
of Tavtigian et al. (2018), as Belman et al. (2020) apply them to co-segregation: 2.08 for supporting evidence, 4.33
moderate and 18.7 strong, and their reciprocals against.
"""
import warnings
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .engine import Network
from .inheritance import (DEFAULT_PENETRANCE, DEFAULT_PHENOCOPY, LN10, _logsumexp, _modes, _prior, _weights,
                          mode_log_likelihoods)
from .models import MODES, X_LINKED, Model, call_codes, founder_prior, genotype_table, phenotype_factor
from .pedigree import MALE, Pedigree
from .compound import PAIR_MODES, PairLocus, has_disease_genotype, pair_log_likelihoods

DEFAULT_VARIANT_FREQUENCY = 0.001
# Rarer variants are treated as having this frequency. Below it, the frequency hardly changes how the variant can
# pass through the family, and a variant seen in the family is there, however rare it is in the population.
MIN_VARIANT_FREQUENCY = 0.001
DEFAULT_ERROR_RATE = 1e-4
_X_NAMES = {'x', 'chrx', '23', 'chr23'}
# PLINK numbers the Y 24, the pseudoautosomal regions 25 (inherited like an autosome) and the mitochondria 26
_Y_NAMES = {'y', 'chry', '24', 'chr24'}
_MT_NAMES = {'mt', 'm', 'chrm', 'chrmt', '26', 'chr26'}

# The strengths of evidence for co-segregation (PP1) or against it (BS4), by the log10 Bayes factor: the thresholds of
# Tavtigian et al. (2018) for the ACMG/AMP criteria, 18.7 strong, 4.33 moderate and 2.08 supporting
EVIDENCE = ((np.log10(18.7), 'Strong'), (np.log10(4.33), 'Moderate'), (np.log10(2.08), 'Supporting'))


def evidence_strength(log10_bf: Optional[float]) -> str:
    """PP1_Strong, PP1_Moderate or PP1_Supporting for co-segregation, BS4_ likewise against it, or '' for neither"""
    if log10_bf is None:
        return ''
    for threshold, strength in EVIDENCE:
        if log10_bf >= threshold - 1e-12:
            return f'PP1_{strength}'
        if log10_bf <= -threshold + 1e-12:
            return f'BS4_{strength}'
    return ''


@dataclass
class Variant:
    """
    A candidate variant: its genotypes, as the number of copies of the alternate allele each person carries (0, 1 or 2;
    None, or no entry, if not genotyped), with where it is if known, its allele frequency in the population, and
    the gene it is in (which pairs variants up as compound heterozygotes).
    """
    id: str
    genotypes: Dict[str, Optional[int]]
    chrom: Optional[str] = None
    pos: Optional[int] = None
    ref: Optional[str] = None
    alt: Optional[str] = None
    allele_frequency: Optional[float] = None
    gene: Optional[str] = None

    @property
    def x_linked(self) -> Optional[bool]:
        """True on the X chromosome, False on another, None if the chromosome isn't known"""
        if self.chrom is None:
            return None
        return str(self.chrom).strip().lower() in _X_NAMES

    @property
    def unmodelled(self) -> bool:
        """Whether the variant is on the Y chromosome or in the mitochondria, whose inheritance PedNet doesn't model"""
        return self.chrom is not None and str(self.chrom).strip().lower() in _Y_NAMES | _MT_NAMES


@dataclass
class VariantScore:
    """
    One candidate's evidence: a variant, or with a partner, a pair of variants in one gene as a compound
    heterozygote.

    log10_lr is the log10 likelihood ratio for co-segregation under each mode that suits the candidate's chromosome
    on its own (only AR, or XLR, for a pair), and log_likelihood the natural log of the probability of the
    phenotypes, given the genotypes, with the candidate as the cause, under each of those modes. log10_bf, the log10
    co-segregation Bayes factor, combines the modes, each weighted by how probable the family's phenotypes make it:
    it is near 0 for a variant whose genotypes say nothing, and evidence is its strength as evidence for
    co-segregation (PP1) or against it (BS4). evidence is left blank, and evidence_withheld says why, for a variant
    that may be new in an affected person and is otherwise consistent with the family (for PS2 or PM6 to judge,
    not PP1 or BS4), and for one that is part of a pair which is evidence for co-segregation (PP1, a log10 BF of
    0.318 or more) and better evidence than the variant alone. best_mode is the most probable mode of inheritance if
    the candidate is the cause. log10_bf is None, and note says why, for a candidate that can't be scored.
    impossible_modes lists the modes under which its genotypes can't have been passed down at all, which happens
    only with an error rate of 0: they are left out, and if no mode is left, the candidate isn't scored.

    mode_probability is the probability, from the phenotypes, that the mode is one that suits the candidate
    (autosomal or X-linked, or recessive for a pair), and log10_odds = log10_bf + log10(mode_probability): the
    log10 odds that this candidate, rather than some other locus, causes the condition, with even odds beforehand.
    The candidates are ranked by it, so that an X-linked variant in a family whose condition is clearly autosomal
    doesn't rank highly. rank is 1 for the candidate with the most evidence, and tied candidates share the average
    of their ranks.

    The rest describes the genotypes. A carrier has the variant (for a pair, the genotype of a compound heterozygote:
    both variants, or two copies of either). concordance is the share of the genotyped people with a known phenotype
    whose genotype fits it under the best mode, as a plain check. mendelian_errors counts the genotyped children whose
    genotype their genotyped parents can't have given them, which suggests calling errors: the Bayes factor allows
    for errors, but such a variant is worth checking. de_novo lists the genotyped children who carry the variant
    though both their parents were genotyped without it (on the X, a son whose mother was): the Bayes factor counts
    such a variant against itself, since PedNet doesn't model new mutations, and it needs judging on its own.
    """
    variant: Variant
    log10_bf: Optional[float]
    log10_lr: Dict[str, float] = field(default_factory=dict)
    log_likelihood: Dict[str, float] = field(default_factory=dict)
    rank: Optional[float] = None
    log10_odds: Optional[float] = None
    mode_probability: Optional[float] = None
    genotyped: int = 0
    affected_carriers: int = 0
    affected_noncarriers: int = 0
    unaffected_carriers: int = 0
    unaffected_noncarriers: int = 0
    best_mode: Optional[str] = None
    concordance: Optional[float] = None
    mendelian_errors: int = 0
    note: str = ''
    partner: Optional[Variant] = None
    de_novo: List[str] = field(default_factory=list)
    evidence_withheld: str = ''
    impossible_modes: List[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.variant.id if self.partner is None else f'{self.variant.id} + {self.partner.id}'

    @property
    def compound(self) -> bool:
        return self.partner is not None

    @property
    def evidence(self) -> str:
        """The strength of the evidence, or '' when there is none or evidence_withheld says why it isn't given"""
        return '' if self.evidence_withheld else evidence_strength(self.log10_bf)

    @property
    def notes(self) -> str:
        """The note, with the Mendelian errors, possible new mutations and why any evidence is withheld"""
        parts = [self.note] if self.note else []
        if self.mendelian_errors:
            parts.append(f'{self.mendelian_errors} Mendelian error{"s" if self.mendelian_errors > 1 else ""}')
        if self.de_novo:
            parts.append(f'possibly de novo in {", ".join(self.de_novo)}')
        if self.evidence_withheld:
            parts.append(self.evidence_withheld)
        return '; '.join(parts)

    def row(self) -> dict:
        v, w = self.variant, self.partner

        def both(name):
            if w is None:
                return getattr(v, name)
            return ','.join('' if x is None else str(x) for x in (getattr(v, name), getattr(w, name)))

        row = {'rank': self.rank, 'candidate': self.id, 'kind': 'compound heterozygote' if w else 'variant',
               'gene': v.gene, 'chrom': v.chrom, 'pos': both('pos'), 'ref': both('ref'), 'alt': both('alt'),
               'allele_frequency': both('allele_frequency'), 'log10_bf': self.log10_bf, 'evidence': self.evidence,
               'log10_odds': self.log10_odds, 'mode_probability': self.mode_probability, 'best_mode': self.best_mode}
        for mode in MODES:
            row[f'log10_lr_{mode}'] = self.log10_lr.get(mode)
        row.update(genotyped=self.genotyped, affected_carriers=self.affected_carriers,
                   affected_noncarriers=self.affected_noncarriers, unaffected_carriers=self.unaffected_carriers,
                   unaffected_noncarriers=self.unaffected_noncarriers, concordance=self.concordance,
                   mendelian_errors=self.mendelian_errors, de_novo=','.join(self.de_novo), note=self.note,
                   evidence_withheld=self.evidence_withheld)
        return row


def _fits(mode: str, copies: int, male: Optional[bool], affected: bool) -> bool:
    """Whether a genotype fits a phenotype under a mode with full penetrance and no phenocopies"""
    if mode == 'AD':
        disease = copies >= 1
    elif mode == 'AR':
        disease = copies == 2
    elif mode == 'XLD':
        disease = copies >= 1
    else:
        disease = copies >= 1 if male else copies == 2
    return disease == affected


def fair_ranks(values: Sequence[Optional[float]], decimals: int = 9) -> List[Optional[float]]:
    """
    Ranks, highest first, with tied values sharing the average of their ranks, and None for a missing value. Values
    equal to the given number of decimal places are tied, so that likelihood ratios that are equal in theory but differ
    in the last digits of the arithmetic share their rank.
    """
    rounded = [None if v is None or v != v else round(v, decimals) for v in values]
    count = Counter(v for v in rounded if v is not None)
    higher, above = {}, 0
    for v in sorted(count, reverse=True):
        higher[v] = above
        above += count[v]
    return [None if v is None else 1 + higher[v] + (count[v] - 1) / 2 for v in rounded]


def _frequency(v: Variant, default: float, lowest: float) -> float:
    q = v.allele_frequency if v.allele_frequency is not None else default
    return float(np.clip(q, max(lowest, 1e-8), 0.5))


def rank_variants(pedigree: Pedigree, variants: Iterable[Variant], modes: Sequence[str] = MODES,
                  penetrance=DEFAULT_PENETRANCE, penetrance_weights=None, phenocopy: float = DEFAULT_PHENOCOPY,
                  allele_frequency: Optional[Dict[str, float]] = None, carrier_penetrance: Optional[float] = None,
                  variant_frequency: float = DEFAULT_VARIANT_FREQUENCY, min_frequency: float = MIN_VARIANT_FREQUENCY,
                  error_rate: float = DEFAULT_ERROR_RATE, prior: Optional[Dict[str, float]] = None,
                  proband: Optional[str] = None, compound: bool = True, chunk: int = 2000) -> List[VariantScore]:
    """
    Scores candidate variants for co-segregation with the condition in one family, and ranks them, the strongest
    evidence first.

    variants: Variant objects (see read_vcf and read_genotype_table); people not in the pedigree are ignored
    modes: the modes of inheritance to allow (by default all four); give one if the mode is known
    penetrance, penetrance_weights, phenocopy, allele_frequency, carrier_penetrance, prior, proband: as for
        infer_mode; allele_frequency is that of the unseen locus in the explanation without the variant, and proband
        the person that locus is taken to be carried by (by default, each affected person in turn)
    variant_frequency: the allele frequency to use for a variant that doesn't give its own
    min_frequency: the lowest frequency used; rarer variants are treated as having this one. If it were far below
        error_rate, a genotype call in one person would be put down to an error rather than to the variant
    error_rate: the chance that a genotype call is one copy out (see models.genotype_factor)
    compound: whether to score pairs of variants in one gene (see Variant.gene) as compound heterozygotes too, when a
        recessive mode is allowed: the pairs that an affected person (the proband, if given) carries both of
    """
    modes = _modes(modes)
    priors = _prior(modes, prior)
    pens = (float(penetrance),) if np.isscalar(penetrance) else tuple(float(f) for f in penetrance)
    with np.errstate(divide='ignore'):
        log_w = np.log(_weights(pens, penetrance_weights))
    allele_frequency = allele_frequency or {}
    variants = list(variants)
    networks: Dict[bool, Network] = {}
    if proband is not None and proband not in pedigree:
        raise ValueError(f'{proband} is not in family {pedigree.family}')
    if proband is not None and not pedigree[proband].affected:
        raise ValueError(f'The proband, {proband}, is not recorded as affected: the Bayes factors take the family to '
                         'have come to notice through an affected person')
    models = {m: Model(m, allele_frequency.get(m), pens[0], phenocopy, carrier_penetrance) for m in modes}

    # the explanation without the variant: P(phenotypes | the proband carries the disease genotype, mode), averaged
    # over the penetrances and the probands, as for the mode of inheritance
    log_without = mode_log_likelihoods(pedigree, modes, pens, penetrance_weights, phenocopy, allele_frequency,
                                       carrier_penetrance, [proband] if proband else None, networks)
    log_priors = {m: float(np.log(priors[m])) for m in modes if priors[m] > 0}

    scores = [VariantScore(v, None) for v in variants]
    errors = [mendelian_errors(pedigree, v) for v in variants]
    for k, v in enumerate(variants):
        _describe(pedigree, v, scores[k])
        scores[k].mendelian_errors = errors[k]
        scores[k].de_novo = de_novo(pedigree, v)

    # the explanation with the variant as the cause, for each mode that suits its chromosome
    for x in (False, True):
        chosen = [k for k, v in enumerate(variants)
                  if v.x_linked in (x, None) and not v.unmodelled and scores[k].genotyped]
        suited = [m for m in modes if X_LINKED[m] == x and priors[m] > 0]
        if not chosen or not suited:
            continue
        if x not in networks:
            networks[x] = Network(pedigree, x)
        for start in range(0, len(chosen), chunk):
            batch = chosen[start:start + chunk]
            _score_batch(pedigree, networks[x], [variants[k] for k in batch], [scores[k] for k in batch], suited,
                         models, pens, log_w, variant_frequency, min_frequency, error_rate, log_without)

    # pairs of variants in one gene, as compound heterozygotes
    pairs = []
    if compound:
        allowed = {x: [m for m in PAIR_MODES if m in modes and priors[m] > 0 and x in (X_LINKED[m], None)]
                   for x in (False, True, None)}
        pairs = [(i, j) for i, j in candidate_pairs(pedigree, variants, proband) if allowed[variants[i].x_linked]]
    pair_scores = []
    for i, j in pairs:
        score = VariantScore(variants[i], None, partner=variants[j], mendelian_errors=errors[i] + errors[j],
                             de_novo=sorted(set(scores[i].de_novo) | set(scores[j].de_novo)))
        _describe_pair(pedigree, variants[i], variants[j], score)
        pair_scores.append(score)
    left_out = set()
    for x in (False, True):
        chosen = [k for k, (i, j) in enumerate(pairs) if variants[i].x_linked in (x, None)]
        suited = [m for m in PAIR_MODES if m in modes and X_LINKED[m] == x and priors[m] > 0]
        if not chosen or not suited:
            continue
        try:
            net = Network(pedigree, x, PairLocus())
        except ValueError as error:
            warnings.warn(f'Pairs of variants in one gene are left out: {error} for a pair (single variants are '
                          'still scored)')
            left_out.update(chosen)
            continue
        for start in range(0, len(chosen), chunk):
            batch = chosen[start:start + chunk]
            both = [(variants[pairs[k][0]], variants[pairs[k][1]]) for k in batch]
            frequencies = [(_frequency(a, variant_frequency, min_frequency), _frequency(b, variant_frequency, min_frequency))
                           for a, b in both]
            logs = pair_log_likelihoods(pedigree, net, both, frequencies, suited, models, pens, log_w, error_rate)
            for mode, values in logs.items():
                for k, value in zip(batch, values):
                    _set_mode(pair_scores[k], mode, float(value), log_without[mode])
    pair_scores = [p for k, p in enumerate(pair_scores) if k not in left_out]

    groups: Dict[Tuple[str, ...], List[VariantScore]] = {}
    for s in scores + pair_scores:
        if s.variant.unmodelled:
            s.note = 'Y-linked and mitochondrial inheritance aren\'t modelled'
        elif not s.genotyped:
            s.note = 'no one in the family was genotyped for it'
        elif s.impossible_modes and not s.log10_lr:
            s.note = _IMPOSSIBLE
        elif not s.log10_lr:
            s.note = 'none of the modes allowed suits its chromosome'
        else:
            if s.impossible_modes:
                # a variant of unknown chromosome whose genotypes rule out the X, say: the other modes remain
                s.note = (f'{" and ".join(s.impossible_modes)} {"is" if len(s.impossible_modes) == 1 else "are"} '
                          'left out, since its genotypes can\'t have been passed down that way without a genotyping '
                          'error, and the error rate is 0')
            groups.setdefault(tuple(s.log10_lr), []).append(s)
    for suited, group in groups.items():
        _combine_modes(group, suited, log_priors, log_without)
        for s in group:
            if s.best_mode is None:
                continue
            if s.partner is None:
                s.concordance = _concordance(pedigree, s.variant, s.best_mode)
            else:
                s.concordance = _pair_concordance(pedigree, s.variant, s.partner)
    _withhold_evidence(pedigree, scores, pair_scores)
    scores = scores + pair_scores
    for s, r in zip(scores, fair_ranks([s.log10_odds for s in scores])):
        s.rank = r
    scores.sort(key=lambda s: (s.rank is None, s.rank if s.rank is not None else 0))
    return scores


def _set_mode(score: 'VariantScore', mode: str, log_with: float, log_without: float):
    """
    Records the log likelihood of the phenotypes under a mode with the candidate as the cause, and the ratio. A
    likelihood of NaN comes from genotypes that have no probability at all under the mode (0 / 0), which only an error
    rate of 0 and a Mendelian error can give: the mode is then left out for the candidate (see impossible_modes).
    """
    if log_with != log_with:
        if mode not in score.impossible_modes:
            score.impossible_modes.append(mode)
        return
    score.log_likelihood[mode] = log_with
    with np.errstate(invalid='ignore'):
        ratio = (log_with - log_without) / LN10
    score.log10_lr[mode] = float(ratio) if ratio == ratio else float('-inf')


def _combine_modes(group: List['VariantScore'], suited: Sequence[str], log_priors: Dict[str, float],
                   log_without: Dict[str, float]):
    """
    The Bayes factor and odds of candidates whose likelihoods are for the modes suited: the probability of the
    phenotypes with the candidate as the cause, averaged over those modes by their priors, over the same without it.
    A mode that can't explain the phenotypes without the candidate adds nothing to the second, rather than making the
    likelihood ratio infinite.
    """
    suited = [m for m in suited if m in log_priors]
    log_all = _logsumexp([log_priors[m] + log_without[m] for m in log_priors])
    log_suited = _logsumexp([log_priors[m] + log_without[m] for m in suited]) if suited else -np.inf
    if not np.isfinite(log_suited) or not np.isfinite(log_all):
        for s in group:
            s.note = s.note or 'the phenotypes rule out every mode that suits its chromosome'
        return
    priors = np.array([log_priors[m] for m in suited])
    for s in group:
        with_modes = priors + np.array([s.log_likelihood[m] for m in suited])
        value = _logsumexp(with_modes)
        if not np.isfinite(value):
            s.note = s.note or 'its genotypes can\'t give these phenotypes under any mode that suits it'
            s.log10_bf = s.log10_odds = float('-inf')
            s.mode_probability = float(np.exp(log_suited - log_all))
            s.best_mode = suited[int(np.argmax(with_modes))]
            continue
        s.log10_bf = float((value - log_suited) / LN10)
        s.mode_probability = float(np.exp(log_suited - log_all))
        s.log10_odds = float((value - log_all) / LN10)
        s.best_mode = suited[int(np.argmax(with_modes))]


def _withhold_evidence(pedigree: Pedigree, scores: List['VariantScore'], pair_scores: List['VariantScore']):
    """Leaves out the strength of evidence where it would mislead (see VariantScore)"""
    best_pair: Dict[int, 'VariantScore'] = {}
    for p in pair_scores:
        if p.log10_bf is None:
            continue
        for member in (p.variant, p.partner):
            known = best_pair.get(id(member))
            if known is None or p.log10_bf > known.log10_bf:
                best_pair[id(member)] = p
    for s in scores:
        if s.log10_bf is None:
            continue
        pair = best_pair.get(id(s.variant))
        if _new_in_affected(pedigree, s):
            s.evidence_withheld = _NEW
        elif pair is not None and evidence_strength(pair.log10_bf).startswith('PP1') and pair.log10_bf > s.log10_bf:
            # the pair is evidence for co-segregation, and better evidence than the variant alone
            s.evidence_withheld = f'judge it with its pair, {pair.id} (log10 BF {pair.log10_bf:.2f})'
    for p in pair_scores:
        if p.log10_bf is not None and _new_in_affected(pedigree, p):
            p.evidence_withheld = _NEW


_NEW = 'co-segregation can\'t judge a variant new in an affected person: see PS2 and PM6 instead'
_IMPOSSIBLE = ('its genotypes can\'t have been passed down without a genotyping error, and the error rate is 0, so it '
               'isn\'t scored')


def _new_in_affected(pedigree: Pedigree, s: 'VariantScore') -> bool:
    """
    Whether the candidate may be new in an affected person, and its genotypes are otherwise consistent: no other
    Mendelian errors, and no affected person genotyped without it. Then the Bayes factor, which counts the new
    mutation against it, says nothing about whether it causes the condition. An affected relative without it is
    evidence against it whatever its origin.
    """
    return (any(pedigree[pid].affected for pid in s.de_novo) and s.mendelian_errors <= len(s.de_novo)
            and s.affected_noncarriers == 0)


def candidate_pairs(pedigree: Pedigree, variants: Sequence[Variant],
                    proband: Optional[str] = None) -> List[Tuple[int, int]]:
    """
    The pairs of variants in one gene, as pairs of positions in variants, that an affected person (the proband, if
    given) carries both of; on the X, an affected person who isn't a man, since a man has only one copy
    """
    who = [proband] if proband else pedigree.affected()
    by_gene: Dict[str, List[int]] = {}
    for k, v in enumerate(variants):
        if v.gene:
            by_gene.setdefault(v.gene, []).append(k)
    pairs = []
    for ks in by_gene.values():
        for a in range(len(ks)):
            for b in range(a + 1, len(ks)):
                v, w = variants[ks[a]], variants[ks[b]]
                if v.x_linked != w.x_linked or v.unmodelled or w.unmodelled:
                    continue
                for pid in who:
                    if pid not in pedigree or (v.x_linked and pedigree[pid].sex == MALE):
                        continue
                    if (v.genotypes.get(pid) or 0) >= 1 and (w.genotypes.get(pid) or 0) >= 1:
                        pairs.append((ks[a], ks[b]))
                        break
    return pairs


def _describe(pedigree: Pedigree, v: Variant, s: VariantScore):
    for pid, copies in v.genotypes.items():
        if copies is None or pid not in pedigree:
            continue
        person = pedigree[pid]
        s.genotyped += 1
        carrier = copies >= 1
        if person.affected:
            if carrier:
                s.affected_carriers += 1
            else:
                s.affected_noncarriers += 1
        elif person.unaffected:
            if carrier:
                s.unaffected_carriers += 1
            else:
                s.unaffected_noncarriers += 1


def _describe_pair(pedigree: Pedigree, v: Variant, w: Variant, s: VariantScore):
    for pid in pedigree.ids:
        a, b = v.genotypes.get(pid), w.genotypes.get(pid)
        if a is None and b is None:
            continue
        s.genotyped += 1
        if a is None or b is None:
            continue
        person = pedigree[pid]
        carrier = has_disease_genotype(a, b, v.x_linked and person.sex == MALE)
        if person.affected:
            if carrier:
                s.affected_carriers += 1
            else:
                s.affected_noncarriers += 1
        elif person.unaffected:
            if carrier:
                s.unaffected_carriers += 1
            else:
                s.unaffected_noncarriers += 1


def _pair_concordance(pedigree: Pedigree, v: Variant, w: Variant) -> Optional[float]:
    fits = total = 0
    for pid in pedigree.ids:
        a, b = v.genotypes.get(pid), w.genotypes.get(pid)
        person = pedigree[pid]
        if a is None or b is None or person.phenotype not in (1, 2):
            continue
        total += 1
        fits += has_disease_genotype(a, b, v.x_linked and person.sex == MALE) == person.affected
    return fits / total if total else None


def de_novo(pedigree: Pedigree, v: Variant) -> List[str]:
    """
    The genotyped children who carry the variant though both their parents were genotyped without it; on the X, a
    son who carries it though his mother was genotyped without it
    """
    found = []
    x = v.x_linked
    if v.unmodelled:
        return found
    for p in pedigree.people:
        child = v.genotypes.get(p.id)
        if not child or p.father is None:
            continue
        father, mother = v.genotypes.get(p.father), v.genotypes.get(p.mother)
        if x and p.sex == MALE:
            if mother == 0:
                found.append(p.id)
        elif father == 0 and mother == 0:
            found.append(p.id)
    return found


def mendelian_errors(pedigree: Pedigree, v: Variant) -> int:
    """The genotyped children whose genotype can't have come from their genotyped parents"""
    if v.unmodelled:
        return 0
    x = v.x_linked
    errors = 0
    for p in pedigree.people:
        child = v.genotypes.get(p.id)
        if child is None or p.father is None:
            continue
        father, mother = v.genotypes.get(p.father), v.genotypes.get(p.mother)
        if x:
            # a son has only his mother's X; a daughter has her father's (all of it) and one of her mother's
            if p.sex == 1:
                if mother is not None and ((mother == 0 and child >= 1) or (mother == 2 and child == 0)):
                    errors += 1
                continue
            if p.sex != 2:
                continue
            low = (1 if father is not None and father >= 1 else 0) + (1 if mother == 2 else 0)
            high = (0 if father == 0 else 1) + (0 if mother == 0 else 1)
        else:
            low = (1 if father == 2 else 0) + (1 if mother == 2 else 0)
            high = (0 if father == 0 else 1) + (0 if mother == 0 else 1)
        if not low <= child <= high:
            errors += 1
    return errors


def _concordance(pedigree: Pedigree, v: Variant, mode: str) -> Optional[float]:
    fits = total = 0
    for pid, copies in v.genotypes.items():
        if copies is None or pid not in pedigree:
            continue
        person = pedigree[pid]
        if person.phenotype not in (1, 2):
            continue
        male = person.sex == 1 if person.sex in (1, 2) else None
        total += 1
        fits += _fits(mode, copies, male, person.affected)
    return fits / total if total else None


def _score_batch(pedigree, net, variants, scores, modes, models, pens, log_w, variant_frequency, min_frequency,
                 error_rate, log_without):
    V, F = len(variants), len(pens)
    q = np.array([_frequency(v, variant_frequency, min_frequency) for v in variants])
    evidence = []
    for i, (kind, person) in enumerate(zip(net.kinds, pedigree.people)):
        e = genotype_table(kind, error_rate)[call_codes(variants, person.id)]
        if net.parents[i] is None:
            e = e * founder_prior(kind, q)
        evidence.append(e)
    # P(genotypes), which doesn't depend on the mode except through the chromosome
    log_genotypes = net.log_likelihood(evidence)
    for mode in modes:
        model = models[mode]
        unary = []
        for i, (kind, person) in enumerate(zip(net.kinds, pedigree.people)):
            phen = np.stack([phenotype_factor(model.with_(penetrance=f), kind, person.phenotype) for f in pens])
            unary.append((phen[:, None, :] * evidence[i][None, :, :]).reshape(F * V, -1))
        joint = net.log_likelihood(unary).reshape(F, V)
        with np.errstate(invalid='ignore'):
            # NaN where the genotypes have no probability at all (see _set_mode)
            with_variant = _logsumexp(joint + log_w[:, None], axis=0) - log_genotypes
        for s, value in zip(scores, with_variant):
            _set_mode(s, mode, float(value), log_without[mode])


@dataclass
class CombinedScore:
    """
    A candidate's evidence from several families with the same condition, over the families in which an affected
    person (the family's proband, if given) carries it, whose scores are in families. A family in which no affected
    person carries it counts only towards the mode of inheritance, since the condition may have another cause there.

    log10_bf is the log10 Bayes factor over those families together, with the mode of inheritance shared between
    them. With one mode allowed it is the sum of the families' log10 Bayes factors. With several, each mode is
    weighted by how well it explains all the families together, so the evidence can be more than the sum when the
    families agree on the mode and less when they point to different modes, and each family's own log10_bf (in
    families) is for the modes weighted by that family alone. A mode under which the candidate's genotypes are
    impossible in one family (with an error rate of 0) is left out for all of them. mode_probability is the
    probability, from all the families' phenotypes, that the mode is one that suits the candidate, and log10_odds is
    log10_bf + log10(mode_probability), as for VariantScore. log10_bf is None, and note says why, when the candidate
    can't be scored.
    """
    id: str
    log10_bf: Optional[float]
    families: Dict[str, VariantScore]
    rank: Optional[float] = None
    log10_odds: Optional[float] = None
    mode_probability: Optional[float] = None
    evidence_withheld: str = ''
    note: str = ''

    @property
    def evidence(self) -> str:
        if self.evidence_withheld or self.log10_bf != self.log10_bf:
            return ''
        return evidence_strength(self.log10_bf)

    @property
    def compound(self) -> bool:
        return next(iter(self.families.values())).compound

    def row(self) -> dict:
        first = next(iter(self.families.values()))
        row = {'rank': self.rank, 'candidate': self.id, 'kind': 'compound heterozygote' if self.compound else 'variant',
               'gene': first.variant.gene, 'log10_bf': self.log10_bf, 'evidence': self.evidence,
               'log10_odds': self.log10_odds, 'mode_probability': self.mode_probability,
               'families': ','.join(self.families)}
        for name, s in self.families.items():
            row[f'log10_bf_{name}'] = s.log10_bf
        row.update(evidence_withheld=self.evidence_withheld, note=self.note)
        return row


def rank_variants_across(pedigrees, variants: Iterable[Variant], probands: Optional[Dict[str, str]] = None,
                         **options) -> List[CombinedScore]:
    """
    Ranks candidates over several families with the same condition (see CombinedScore). The families are taken to
    share one mode of inheritance: for each mode, the families' likelihoods are multiplied, and the modes are then
    weighed as for a single family, by how well they explain all the families' phenotypes.

    pedigrees: a dict of family to Pedigree, as read_ped gives, or a list of pedigrees
    variants: the candidates, whose genotypes can cover the people of every family
    probands: the proband of each family, if known (a dict of family to person)
    options: passed on to rank_variants
    """
    if not isinstance(pedigrees, dict):
        pedigrees = {p.family: p for p in pedigrees}
    variants = list(variants)
    probands = probands or {}
    modes = _modes(options.get('modes', MODES))
    priors = _prior(modes, options.get('prior'))
    log_priors = {m: float(np.log(priors[m])) for m in modes if priors[m] > 0}
    # each family's likelihood of its phenotypes under each mode without the candidate, and its candidates' scores
    without: Dict[str, Dict[str, float]] = {}
    found: Dict[Tuple[int, int], Dict[str, VariantScore]] = {}
    for name, pedigree in pedigrees.items():
        proband = probands.get(name)
        without[name] = mode_log_likelihoods(pedigree, modes, options.get('penetrance', DEFAULT_PENETRANCE),
                                             options.get('penetrance_weights'), options.get('phenocopy', DEFAULT_PHENOCOPY),
                                             options.get('allele_frequency'), options.get('carrier_penetrance'),
                                             [proband] if proband else None)
        who = [proband] if proband else pedigree.affected()
        for s in rank_variants(pedigree, variants, proband=proband, **options):
            if s.partner is None and not any((s.variant.genotypes.get(p) or 0) >= 1 for p in who):
                continue
            if s.note != _IMPOSSIBLE and (s.log10_bf is None or not s.log_likelihood):
                continue
            found.setdefault((id(s.variant), id(s.partner)), {})[name] = s
    log_all = _logsumexp([log_priors[m] + sum(without[f][m] for f in pedigrees) for m in log_priors])
    combined = []
    for by_family in found.values():
        first = next(iter(by_family.values()))
        c = CombinedScore(first.id, None, by_family)
        combined.append(c)
        unscored = [f for f, s in by_family.items() if s.note == _IMPOSSIBLE]
        if unscored:
            c.note = (f'its genotypes in {", ".join(unscored)} can\'t have been passed down without a genotyping '
                      'error, and the error rate is 0, so it isn\'t scored')
            continue
        # the modes that suit the candidate in every family where it is scored: a mode under which its genotypes
        # are impossible in one family (with an error rate of 0) is ruled out for them all
        suited = [m for m in log_priors if all(m in s.log_likelihood for s in by_family.values())]
        if not suited:
            c.note = (f'its genotypes in {", ".join(by_family)} can\'t have been passed down under any one mode '
                      'without a genotyping error, and the error rate is 0, so it isn\'t scored')
            continue
        ruled_out = [m for m in log_priors if any(m in s.impossible_modes for s in by_family.values())]
        if ruled_out:
            where = [f for f, s in by_family.items() if s.impossible_modes]
            c.note = (f'{" and ".join(ruled_out)} {"is" if len(ruled_out) == 1 else "are"} left out for every '
                      f'family, since its genotypes in {", ".join(where)} can\'t have been passed down that way '
                      'without a genotyping error, and the error rate is 0')
        with_modes = [log_priors[m] + sum(by_family[f].log_likelihood[m] if f in by_family else without[f][m]
                                          for f in pedigrees) for m in suited]
        suited_without = [log_priors[m] + sum(without[f][m] for f in pedigrees) for m in suited]
        log_with, log_suited = _logsumexp(with_modes), _logsumexp(suited_without)
        if not (np.isfinite(log_suited) and np.isfinite(log_all)):
            c.note = 'the families\' phenotypes rule out every mode that suits its chromosome'
        else:
            c.log10_bf = float((log_with - log_suited) / LN10)
            c.mode_probability = float(np.exp(log_suited - log_all))
            c.log10_odds = float((log_with - log_all) / LN10)
        if any(s.evidence_withheld for s in by_family.values()):
            c.evidence_withheld = next(s.evidence_withheld for s in by_family.values() if s.evidence_withheld)
    for c, r in zip(combined, fair_ranks([c.log10_odds for c in combined])):
        c.rank = r
    combined.sort(key=lambda c: (c.rank is None, c.rank if c.rank is not None else 0))
    return combined
