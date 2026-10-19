"""Graph features of who is affected, and what they say about the mode of inheritance.

Before any genotypes are known, the way the affected people sit in the pedigree graph says much about how a
condition is inherited: whether it passes from parent to child down the generations, from father to son, through
unaffected women, or appears in the children of unaffected or related parents. This module measures that on the
graph, in two ways, each with a classifier of the mode of inheritance built on it:

- network_metrics: the four network metrics of the original PedNet (Nick Taylor's): how often an affected person has
  an affected parent, how often an affected person's siblings are affected, how many generations are affected, and
  how central unaffected people are among the affected. classify_by_metrics is the original classifier, which sets
  a threshold on each metric from simulated families (by Youden's J) and lets the metrics vote, AD against AR.
- pattern_features: the patterns clinical geneticists read from a pedigree, as features of the graph: transmission
  down the generations, father to son, father to daughters, mother to sons, skipped generations, the share of men
  among the affected, affected children of related parents, and how much of the affected people's kinship is on
  the X. classify_by_patterns is a multinomial logistic regression on them, for all four modes.

segregation_network_score is the original PedNet's network score of a candidate variant, from how its genotypes sit
in the graph (see the module legacy/SegScoreMain.py).

The likelihood methods (inheritance and segregation) use the same graph as a Bayesian network of genotypes. They
need no training, and what they assume about the condition (its penetrance and phenocopy rate) can be set to suit it,
where the classifiers have only what they learnt from simulated families. benchmarks/RESULTS.md compares them.
"""
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

import networkx as nx
import numpy as np

from .graph import kinship_matrix, pedigree_graph
from .models import MODE_NAMES, MODES
from .pedigree import FEMALE, MALE, Pedigree

# -- the original PedNet's network metrics --------------------------------------------------------------------------
METRICS = ('ratio_aff_parent', 'sibling_aff_ratio', 'gen_cov', 'avg_bet_unaff')


def metric_graph(pedigree: Pedigree) -> nx.DiGraph:
    """
    The graph the original PedNet measured: the pedigree DAG without the unknown parents PedNet adds for someone with
    only one parent (who had one parent edge in the original), and without people who have no parents or children
    in the pedigree
    """
    graph = pedigree_graph(pedigree)
    graph.remove_nodes_from([n for n in list(graph) if graph.degree(n) == 0])
    return graph


def graph_generations(graph: nx.DiGraph) -> Dict[str, int]:
    """
    Each person's generation in a pedigree graph, 0 for the oldest, as Pedigree.generations works it out: a child
    one generation below its parents, partners in one generation; where that can't hold throughout, a child one
    below its lower parent, and someone with no parents one above their highest child
    """
    level_of: Dict[str, int] = {}
    order = list(nx.topological_sort(graph))
    for component in nx.weakly_connected_components(graph):
        people = [n for n in order if n in component]
        level = {people[0]: 0}
        queue = deque([people[0]])
        consistent = True
        while queue:
            n = queue.popleft()
            for other, step in [(c, 1) for c in graph.successors(n)] + [(p, -1) for p in graph.predecessors(n)]:
                if other not in level:
                    level[other] = level[n] + step
                    queue.append(other)
                elif level[other] != level[n] + step:
                    consistent = False
        if not consistent:
            level = {}
            for n in people:
                parents = list(graph.predecessors(n))
                level[n] = max(level[p] for p in parents) + 1 if parents else 0
            for n in people:
                children = list(graph.successors(n))
                if not list(graph.predecessors(n)) and children:
                    level[n] = min(level[c] for c in children) - 1
        oldest = min(level.values())
        for n, value in level.items():
            level_of[n] = value - oldest
    return level_of


def _affected(graph) -> List[str]:
    return [n for n in graph if graph.nodes[n]['phenotype'] == 2]


def _unaffected(graph) -> List[str]:
    return [n for n in graph if graph.nodes[n]['phenotype'] == 1]


def _siblings(graph, n) -> set:
    sibs = set()
    for parent in graph.predecessors(n):
        sibs.update(graph.successors(parent))
    sibs.discard(n)
    return sibs


def network_metrics(pedigree: Pedigree) -> Dict[str, float]:
    """
    The original PedNet's four network metrics, each between 0 and 1 except the last:

    - ratio_aff_parent: the share of affected people with an affected parent
    - sibling_aff_ratio: of the siblings of affected people (counted once for each affected sibling), the share
      affected
    - gen_cov: the share of the generations with someone affected in them
    - avg_bet_unaff: for each unaffected person, their betweenness (not normalised) in the graph of the affected
      people and them alone, averaged over the unaffected people
    """
    graph = metric_graph(pedigree)
    affected, unaffected = _affected(graph), _unaffected(graph)
    affected_set = set(affected)
    with_affected_parent = sum(1 for n in affected
                               if any(graph.nodes[p]['phenotype'] == 2 for p in graph.predecessors(n)))
    pairs = both = 0
    for n in affected:
        for sib in _siblings(graph, n):
            pairs += 1
            both += sib in affected_set
    generations = graph_generations(graph) if len(graph) else {}
    covered = len({generations[n] for n in affected}) / (max(generations.values()) + 1) if generations else 0.0
    betweenness = []
    for n in unaffected:
        sub = graph.subgraph(affected + [n])
        betweenness.append(nx.betweenness_centrality(sub, normalized=False)[n])
    return {'ratio_aff_parent': with_affected_parent / len(affected) if affected else 0.0,
            'sibling_aff_ratio': both / pairs if pairs else 0.0,
            'gen_cov': covered,
            'avg_bet_unaff': float(np.mean(betweenness)) if betweenness else 0.0}


@dataclass
class MetricThreshold:
    """A metric's threshold, the mode above it ('AD' or 'AR'), and the area under its ROC curve in training"""
    threshold: float
    high: str
    auc: float


def _roc(scores: np.ndarray, positive: np.ndarray):
    """The ROC curve as scikit-learn's roc_curve makes it (dropping points that aren't corners): fpr, tpr, thresholds"""
    order = np.argsort(-scores, kind='mergesort')
    scores, positive = scores[order], positive[order]
    last = np.r_[np.where(np.diff(scores))[0], len(scores) - 1]
    tps = np.cumsum(positive)[last].astype(float)
    fps = 1 + last - tps
    thresholds = scores[last]
    if len(tps) > 2:
        keep = np.where(np.r_[True, np.logical_or(np.diff(fps, 2), np.diff(tps, 2)), True])[0]
        fps, tps, thresholds = fps[keep], tps[keep], thresholds[keep]
    tps, fps = np.r_[0, tps], np.r_[0, fps]
    thresholds = np.r_[np.inf, thresholds]
    return fps / max(fps[-1], 1), tps / max(tps[-1], 1), thresholds


def _auc(fpr, tpr) -> float:
    return float(np.sum(np.diff(fpr) * (tpr[1:] + tpr[:-1]) / 2))


def train_metric_classifier(families: Iterable[Tuple[Pedigree, str]],
                            min_auc: float = 0.7) -> Dict[str, MetricThreshold]:
    """
    The original PedNet's training: for each metric, the threshold with the largest Youden's J (true positive rate
    less false positive rate) on the ROC curve of AD against AR families, keeping the metrics whose area under the
    curve is at least min_auc. families are (pedigree, mode) pairs, with modes 'AD' and 'AR'.
    """
    rows, modes = [], []
    for pedigree, mode in families:
        rows.append(network_metrics(pedigree))
        modes.append(mode)
    modes = np.array(modes)
    if not {'AD', 'AR'} <= set(modes):
        raise ValueError('Training needs both AD and AR families')
    found = {}
    for metric in METRICS:
        values = np.array([r[metric] for r in rows], dtype=float)
        high = 'AD' if values[modes == 'AD'].mean() > values[modes == 'AR'].mean() else 'AR'
        fpr, tpr, thresholds = _roc(values, modes == high)
        area = _auc(fpr, tpr)
        if area >= min_auc:
            found[metric] = MetricThreshold(float(thresholds[int(np.argmax(tpr - fpr))]), high, area)
    return found


def affected_child_of_unaffected_parents(pedigree: Pedigree) -> bool:
    """Whether some affected child has two parents in the pedigree, neither of them affected"""
    graph = metric_graph(pedigree)
    for n in _affected(graph):
        parents = list(graph.predecessors(n))
        if len(parents) == 2 and not any(graph.nodes[p]['phenotype'] == 2 for p in parents):
            return True
    return False


def classify_by_metrics(pedigree: Pedigree, thresholds: Optional[Dict[str, MetricThreshold]] = None,
                        confidence: float = 0.75) -> str:
    """
    The original PedNet's classifier: 'AD', 'AR' or 'uncertain'. An affected child of unaffected parents gives two
    votes for AR, and otherwise there is one for AD; each metric with a threshold votes for the mode on its side of
    it. A mode is called if its votes are at least confidence times the number of voters. thresholds are by default
    those trained on simulated families (see benchmarks/train_classifiers.py).
    """
    if thresholds is None:
        from ._trained import METRIC_THRESHOLDS
        thresholds = {k: MetricThreshold(*v) for k, v in METRIC_THRESHOLDS.items()}
    ad = ar = 0
    total = 1
    if affected_child_of_unaffected_parents(pedigree):
        ar += 2
    else:
        ad += 1
    values = network_metrics(pedigree)
    for metric, t in thresholds.items():
        total += 1
        above = values[metric] >= t.threshold
        if (t.high == 'AD') == above:
            ad += 1
        else:
            ar += 1
    if ad / total >= confidence:
        return 'AD'
    if ar / total >= confidence:
        return 'AR'
    return 'uncertain'


# -- the patterns of inheritance, as graph features ------------------------------------------------------------------
PATTERN_FEATURES = (
    'affected_share', 'affected_generations', 'vertical', 'skipped', 'male_to_male', 'father_daughters',
    'father_sons', 'mother_sons', 'mother_daughters', 'male_share', 'sibship_share', 'consanguineous',
    'x_kinship_ratio', 'log_affected', 'generations')


def _rate(hits: int, total: int) -> float:
    """A share, pulled towards a half when there are few to go on (with half a hit and half a miss added)"""
    return (hits + 0.5) / (total + 1)


def pattern_features(pedigree: Pedigree) -> Dict[str, float]:
    """
    Features of the pattern of affected people in the pedigree graph, each read off the DAG:

    - affected_share: the share of the people with a known phenotype who are affected
    - affected_generations: the share of the generations with someone affected in them
    - vertical: of the affected people with parents in the pedigree, the share with an affected parent
    - skipped: of the same people, the share whose parents are both unaffected
    - male_to_male: whether an affected father has an affected son (1 or 0), which rules out the X
    - father_daughters, father_sons: the shares of the daughters and the sons of affected fathers who are affected
    - mother_sons, mother_daughters: the same for affected mothers
    - male_share: the share of the affected people who are men
    - sibship_share: of the brothers and sisters of affected people, the share affected
    - consanguineous: whether an affected person is the child of related parents (1 or 0)
    - x_kinship_ratio: over the pairs of affected relatives, their kinship on the X over their kinship on an
      autosome, which is above 1 for men related through women and 0 for a father and son
    - log_affected: the log of 1 + the number of affected people, and generations: the number of generations

    The shares are pulled towards a half when there are few people to count (see _rate), so that every family has a
    value for each.
    """
    people = [p for p in pedigree.people if not p.placeholder]
    known = [p for p in people if p.phenotype in (1, 2)]
    affected = [p for p in people if p.affected]
    generations = pedigree.generations()
    gens_all = {generations[p.id] for p in people}
    with_parents = [p for p in affected if p.father is not None]
    vertical = sum(1 for p in with_parents if pedigree[p.father].affected or pedigree[p.mother].affected)
    skipped = sum(1 for p in with_parents if pedigree[p.father].unaffected and pedigree[p.mother].unaffected)
    counts = {key: [0, 0] for key in ('fd', 'fs', 'ms', 'md')}
    male_to_male = 0
    for p in people:
        if p.father is None or p.phenotype not in (1, 2):
            continue
        for parent, prefix in ((pedigree[p.father], 'f'), (pedigree[p.mother], 'm')):
            if not parent.affected or p.sex not in (MALE, FEMALE):
                continue
            key = prefix + ('s' if p.sex == MALE else 'd')
            counts[key][0] += p.affected
            counts[key][1] += 1
            if prefix == 'f' and p.sex == MALE and p.affected:
                male_to_male += 1
    sexed = [p for p in affected if p.sex in (MALE, FEMALE)]
    sibs = both = 0
    for p in affected:
        if p.father is None:
            continue
        for q in set(pedigree.children(p.father)) | set(pedigree.children(p.mother)):
            if q != p.id and pedigree[q].phenotype in (1, 2):
                sibs += 1
                both += pedigree[q].affected
    ids, phi = kinship_matrix(pedigree)
    _, phi_x = kinship_matrix(pedigree, x_linked=True)
    position = {pid: k for k, pid in enumerate(ids)}
    index = [position[p.id] for p in affected]
    upper = np.triu_indices(len(index), 1)
    autosomal = phi[np.ix_(index, index)][upper]
    on_x = phi_x[np.ix_(index, index)][upper]
    related = autosomal > 0
    x_ratio = float(np.mean(on_x[related] / autosomal[related])) if related.any() else 1.0
    inbred = any(p.father is not None and phi[position[p.father], position[p.mother]] > 0 for p in affected)
    return {
        'affected_share': _rate(len(affected), len(known)),
        'affected_generations': len({generations[p.id] for p in affected}) / max(len(gens_all), 1),
        'vertical': _rate(vertical, len(with_parents)),
        'skipped': _rate(skipped, len(with_parents)),
        'male_to_male': float(male_to_male > 0),
        'father_daughters': _rate(*counts['fd']),
        'father_sons': _rate(*counts['fs']),
        'mother_sons': _rate(*counts['ms']),
        'mother_daughters': _rate(*counts['md']),
        'male_share': _rate(sum(1 for p in sexed if p.sex == MALE), len(sexed)),
        'sibship_share': _rate(both, sibs),
        'consanguineous': float(inbred),
        'x_kinship_ratio': x_ratio,
        'log_affected': float(np.log1p(len(affected))),
        'generations': float(len(gens_all)),
    }


@dataclass
class PatternClassifier:
    """
    A multinomial logistic regression of the mode of inheritance on the pattern features: P(mode) is proportional to
    exp(weights[mode] . (1, standardised features)), the features standardised by mean and scale
    """
    modes: Tuple[str, ...]
    features: Tuple[str, ...]
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray

    def probabilities(self, values: Dict[str, float]) -> Dict[str, float]:
        x = (np.array([values[f] for f in self.features]) - self.mean) / self.scale
        z = self.weights @ np.r_[1.0, x]
        p = np.exp(z - z.max())
        p /= p.sum()
        return {m: float(v) for m, v in zip(self.modes, p)}


def train_pattern_classifier(families: Iterable[Tuple[Pedigree, str]], l2: float = 1.0,
                             iterations: int = 50) -> PatternClassifier:
    """
    Fits the pattern classifier to (pedigree, mode) pairs by maximum likelihood with an L2 penalty of l2 on the
    weights of the standardised features (not the intercepts), by Newton's method
    """
    rows, labels = [], []
    for pedigree, mode in families:
        values = pattern_features(pedigree)
        rows.append([values[f] for f in PATTERN_FEATURES])
        labels.append(mode)
    modes = tuple(m for m in MODES if m in set(labels))
    X = np.array(rows, dtype=float)
    mean = X.mean(axis=0)
    scale = X.std(axis=0)
    scale[scale == 0] = 1.0
    Z = np.c_[np.ones(len(X)), (X - mean) / scale]
    Y = np.array([[label == m for m in modes] for label in labels], dtype=float)
    K, D = len(modes), Z.shape[1]
    W = np.zeros((K, D))
    penalty = np.full(D, l2)
    penalty[0] = 1e-6

    def objective(W):
        logits = Z @ W.T
        logits -= logits.max(axis=1, keepdims=True)
        log_p = logits - np.log(np.exp(logits).sum(axis=1, keepdims=True))
        return -(Y * log_p).sum() + 0.5 * (penalty * W ** 2).sum(), np.exp(log_p)

    value, P = objective(W)
    for _ in range(iterations):
        gradient = ((P - Y).T @ Z) + penalty * W
        H = np.zeros((K * D, K * D))
        for a in range(K):
            for b in range(K):
                w = P[:, a] * ((a == b) - P[:, b])
                H[a * D:(a + 1) * D, b * D:(b + 1) * D] = (Z * w[:, None]).T @ Z
        H += np.diag(np.tile(penalty, K))
        step = np.linalg.solve(H, gradient.ravel()).reshape(K, D)
        t, improved = 1.0, False
        while t > 1e-8:
            new_value, new_P = objective(W - t * step)
            if new_value <= value:
                improved = True
                break
            t /= 2
        if not improved:
            break
        W, change = W - t * step, value - new_value
        value, P = new_value, new_P
        if change < 1e-10 * max(1.0, abs(value)):
            break
    return PatternClassifier(modes, PATTERN_FEATURES, mean, scale, W)


@dataclass
class PatternResult:
    """The pattern classifier's answer: each mode's probability, most probable first, the call and the features"""
    family: str
    probabilities: Dict[str, float]
    call: str
    threshold: float
    features: Dict[str, float] = field(default_factory=dict)

    @property
    def dominant(self) -> float:
        return self.probabilities.get('AD', 0) + self.probabilities.get('XLD', 0)

    @property
    def recessive(self) -> float:
        return self.probabilities.get('AR', 0) + self.probabilities.get('XLR', 0)

    @property
    def x_linked(self) -> float:
        return self.probabilities.get('XLR', 0) + self.probabilities.get('XLD', 0)

    def __str__(self):
        lines = [f'Family {self.family}, from the pattern of affected people: '
                 f'{self.call if self.call == "uncertain" else MODE_NAMES[self.call]}']
        for mode, p in self.probabilities.items():
            lines.append(f'  {mode:4s} {p:6.3f}   ({MODE_NAMES[mode]})')
        lines.append(f'  dominant {self.dominant:.3f}, recessive {self.recessive:.3f}')
        lines.append(f'  X-linked {self.x_linked:.3f}, autosomal {1 - self.x_linked:.3f}')
        return '\n'.join(lines)


def classify_by_patterns(pedigree: Pedigree, classifier: Optional[PatternClassifier] = None,
                         threshold: float = 0.8) -> PatternResult:
    """
    The probability of each mode of inheritance from the pattern features alone, by the pattern classifier: by
    default the one trained on simulated families of two to five generations, with penetrances from 0.4 to 1 (see
    benchmarks/train_classifiers.py), whose probabilities are less to be trusted for families far from those. The
    call is the most probable mode if its probability reaches threshold, and 'uncertain' otherwise.
    """
    if classifier is None:
        from ._trained import pattern_classifier
        classifier = pattern_classifier()
    values = pattern_features(pedigree)
    probabilities = dict(sorted(classifier.probabilities(values).items(), key=lambda item: -item[1]))
    best, p = next(iter(probabilities.items()))
    call = best if p >= threshold and pedigree.affected() else 'uncertain'
    return PatternResult(pedigree.family, probabilities, call, threshold, values)


# -- the original PedNet's network score of a variant --------------------------------------------------------------
NETWORK_WEIGHTS = {'w_edge': 0.6, 'w_gen': 0.2, 'w_bet': 0.2}
EXTENDED_WEIGHTS = {'w_edge': 0.6, 'w_gen': 0.1, 'w_bet': 0.1, 'w_found': 0.1, 'w_depth': 0.1}
_BOTH_PARENTS = {(0, 0): {0}, (1, 0): {0, 1}, (1, 1): {0, 1, 2}, (2, 1): {1, 2}, (2, 0): {1}, (2, 2): {2}}
_ONE_PARENT = {0: {0, 1}, 1: {0, 1, 2}, 2: {1, 2}}


def network_parts(pedigree: Pedigree, genotypes: Dict[str, Optional[int]]) -> Dict[str, float]:
    """
    The parts of the original network score of a variant, from its genotypes (copies of the variant, for the people
    genotyped):

    - edge_consistency: the share of the parent-child edges between genotyped people whose genotypes Mendel's laws
      allow (a child with both parents genotyped counts twice)
    - generation_continuity: of the generations with someone genotyped, the share with a carrier
    - carrier_betweenness: the average betweenness (not normalised) of the unaffected heterozygous carriers in the
      graph of them and the affected people
    - founder_influence: the average founder influence of the founders who carry it (see graph.founder_influence)
    - alt_depth: the longest of the shortest paths from a founder who carries it down to another carrier, over the
      length of the longest path in the pedigree
    """
    from .graph import founder_influence
    graph = metric_graph(pedigree)
    gt = {pid: int(g) for pid, g in genotypes.items() if g is not None and pid in graph}
    good = total = 0
    for child in graph:
        if child not in gt:
            continue
        typed = [p for p in graph.predecessors(child) if p in gt]
        if len(typed) == 1:
            good += gt[child] in _ONE_PARENT.get(gt[typed[0]], set())
            total += 1
        elif len(typed) == 2:
            pair = (gt[typed[0]], gt[typed[1]])
            pair = pair if pair in _BOTH_PARENTS else pair[::-1]
            good += 2 * (gt[child] in _BOTH_PARENTS.get(pair, set()))
            total += 2
    generations = graph_generations(graph) if len(graph) else {}
    typed_gens = {generations[n] for n in gt}
    carrier_gens = {generations[n] for n in gt if gt[n] > 0}
    affected = _affected(graph)
    carriers = [n for n in _unaffected(graph) if gt.get(n) == 1]
    betweenness = nx.betweenness_centrality(graph.subgraph(affected + carriers), normalized=False)
    founders = [n for n in graph if graph.in_degree(n) == 0 and gt.get(n, 0) > 0]
    influence = founder_influence(pedigree)
    depth = nx.dag_longest_path_length(graph) if len(graph) else 0
    reach = 0
    for f in founders:
        lengths = nx.single_source_shortest_path_length(graph, f)
        reach = max([reach] + [lengths[n] for n in gt if gt[n] > 0 and n in lengths])
    return {
        'edge_consistency': good / total if total else 0.0,
        'generation_continuity': len(carrier_gens) / len(typed_gens) if typed_gens else 0.0,
        'carrier_betweenness': sum(betweenness[n] for n in carriers) / len(carriers) if carriers else 0.0,
        'founder_influence': float(np.mean([influence.get(f, 0.0) for f in founders])) if founders else 0.0,
        'alt_depth': reach / depth if depth else 0.0,
    }


def segregation_network_score(pedigree: Pedigree, genotypes: Dict[str, Optional[int]], mode: str = 'AD',
                              extended: bool = False, weights: Optional[Dict[str, float]] = None) -> float:
    """
    The original PedNet's network score of a variant, between 0 and 1: a weighted sum of its edge consistency,
    generation continuity and carrier betweenness (taken away from 1 except for AR), with founder influence and
    depth too if extended. genotypes maps people to their copies of the variant.
    """
    parts = network_parts(pedigree, genotypes)
    weights = dict(weights or (EXTENDED_WEIGHTS if extended else NETWORK_WEIGHTS))
    if extended and len(weights) < 5:
        weights = dict(EXTENDED_WEIGHTS)
    betweenness = parts['carrier_betweenness'] if mode == 'AR' else 1 - parts['carrier_betweenness']
    score = (weights['w_edge'] * parts['edge_consistency']
             + weights['w_gen'] * min(max(parts['generation_continuity'], 0), 1)
             + weights['w_bet'] * min(max(betweenness, 0), 1))
    if extended:
        score += weights['w_found'] * parts['founder_influence'] + weights['w_depth'] * parts['alt_depth']
    return float(score)
