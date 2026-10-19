"""The pedigree as a graph.

PedNet starts from the view that a pedigree is a directed acyclic graph (DAG): a node for each person, and an edge
from each parent to each child. This module builds that graph, and the graphs derived from it, with networkx, and
answers questions about the family's structure from them:

- pedigree_graph: the DAG itself, with each person's sex, phenotype and generation on their node
- mating_graph: the DAG with a node for each couple between the parents and their children, the form in which
  loops in a pedigree are counted
- moral_graph: the undirected graph in which each child's parents are joined, on which the genotypes are summed out
  for exact likelihoods (see elimination)
- loops: the pedigree's loops, from consanguinity or from two families married into each other twice
- kinship and inbreeding: Malécot's coefficients, the probability that genes drawn from two people (or from one
  person's two copies) are identical by descent, for an autosome or the X chromosome
- relationship: how two people are related, by the paths through their closest common ancestors
- centrality, founder_influence, pedigree_width, founder_cover: network measures of the people and the pedigree

Placeholders (the unknown parents PedNet adds for someone with only one parent in the file) are left out of the
graphs unless asked for, so that the graphs show the pedigree as it was given.
"""
from dataclasses import dataclass
from itertools import combinations
from typing import Dict, List, Optional, Tuple

import networkx as nx
import numpy as np

from .pedigree import FEMALE, MALE, Pedigree

_SEX_NAMES = {MALE: 'male', FEMALE: 'female'}


def pedigree_graph(pedigree: Pedigree, placeholders: bool = False) -> nx.DiGraph:
    """
    The pedigree as a DAG: a node for each person and an edge from each parent to each child. Each node has the
    person's sex (1 male, 2 female, 0 unknown), phenotype (2 affected, 1 unaffected, 0 unknown), affected (a bool),
    generation (0 for the oldest), and founder (no parents in the pedigree); each edge has parent, 'father' or
    'mother'. People PedNet added as unknown parents (placeholders) are left out unless placeholders is True.
    """
    generations = pedigree.generations()
    graph = nx.DiGraph(family=pedigree.family)
    for p in pedigree.people:
        if p.placeholder and not placeholders:
            continue
        graph.add_node(p.id, sex=p.sex, phenotype=p.phenotype, affected=p.affected, generation=generations[p.id],
                       founder=p.father is None, added=p.added)
    for p in pedigree.people:
        for role, parent in (('father', p.father), ('mother', p.mother)):
            if parent is not None and parent in graph and p.id in graph:
                graph.add_edge(parent, p.id, parent=role)
    return graph


def mating_graph(pedigree: Pedigree, placeholders: bool = False) -> nx.DiGraph:
    """
    The pedigree with a node for each couple who have children, between them and their children: an edge from each
    partner to the couple's node, and from it to each child. People's nodes have kind 'person' and the attributes of
    pedigree_graph; couples' nodes are ('mating', father, mother), with kind 'mating'. Unlike pedigree_graph, this
    graph has a loop (in its undirected form) exactly where the pedigree does.
    """
    people = pedigree_graph(pedigree, placeholders)
    graph = nx.DiGraph(family=pedigree.family)
    for n, data in people.nodes(data=True):
        graph.add_node(n, kind='person', **data)
    for p in pedigree.people:
        if p.father is None or p.id not in people:
            continue
        parents = [q for q in (p.father, p.mother) if q in people]
        mating = ('mating', p.father, p.mother)
        if mating not in graph:
            graph.add_node(mating, kind='mating')
            for q in parents:
                graph.add_edge(q, mating)
        graph.add_edge(mating, p.id)
    return graph


def moral_graph(pedigree: Pedigree, placeholders: bool = True) -> nx.Graph:
    """
    The moral graph of the pedigree's genotypes: the pedigree's edges without their directions, and an edge between
    the two parents of each child. A child's genotype depends on both parents' together, so this is the graph on
    which the genotypes are summed out for exact likelihoods (see elimination). Placeholders are kept by default,
    since the likelihoods include them.
    """
    graph = pedigree_graph(pedigree, placeholders).to_undirected()
    for p in pedigree.people:
        if p.father is not None and p.father in graph and p.mother in graph:
            graph.add_edge(p.father, p.mother)
    return graph


@dataclass
class Loop:
    """
    One of a pedigree's independent loops. people is the people on it in order, and couples the couples on it, as
    (father, mother); an unknown partner PedNet added has an ID such as '1~partner'. kind is 'consanguinity' for a
    loop through a related couple (one with a common ancestor in the pedigree), and 'marriage' for one through no
    related couple: two families married into each other more than once.
    """
    people: List[str]
    couples: List[Tuple[str, str]]
    kind: str


def _node_order(node):
    return (1, node[1], node[2]) if isinstance(node, tuple) else (0, node, '')


def _undirected_mating_graph(pedigree: Pedigree) -> nx.Graph:
    """
    The mating graph without its directions, with its nodes and edges in a fixed order, so that the loops found
    don't depend on the order of the lines in the PED file
    """
    directed = mating_graph(pedigree)
    graph = nx.Graph(family=pedigree.family)
    for n in sorted(directed, key=_node_order):
        graph.add_node(n, **directed.nodes[n])
    edges = [tuple(sorted(e, key=_node_order)) for e in directed.edges]
    graph.add_edges_from(sorted(edges, key=lambda e: (_node_order(e[0]), _node_order(e[1]))))
    return graph


def _related(pedigree: Pedigree, a: str, b: str) -> bool:
    """Whether two people share an ancestor in the pedigree (or one is the other's)"""
    return bool((pedigree.ancestors(a) | {a}) & (pedigree.ancestors(b) | {b}))


def loops(pedigree: Pedigree) -> List[Loop]:
    """
    The independent loops of the pedigree: a cycle basis of the mating graph without its directions (by Paton's
    algorithm, as networkx finds it), the loops from consanguinity first. Their number is the cyclomatic number of
    that graph, its edges less its nodes plus the number of its connected parts (see loop_count).

    Which loops make up a basis is a matter of choice, but how many of them come from consanguinity is not: the
    marriage loops are a basis of the graph without the related couples' nodes, and the rest of the basis, which
    must pass through a related couple, are the loops from consanguinity.
    """
    graph = _undirected_mating_graph(pedigree)
    related = {n for n, data in graph.nodes(data=True)
               if data.get('kind') == 'mating' and _related(pedigree, n[1], n[2])}
    # each cycle as a set of edges, a vector over GF(2), so as to keep only cycles independent of those kept already
    edge_index: Dict[frozenset, int] = {}
    kept: Dict[int, int] = {}

    def independent(cycle) -> bool:
        vector = 0
        for k, node in enumerate(cycle):
            edge = frozenset((node, cycle[(k + 1) % len(cycle)]))
            vector ^= 1 << edge_index.setdefault(edge, len(edge_index))
        while vector:
            top = vector.bit_length() - 1
            if top not in kept:
                kept[top] = vector
                return True
            vector ^= kept[top]
        return False

    found = []
    unrelated = graph.subgraph([n for n in graph if n not in related])
    for kind, cycles in (('marriage', nx.cycle_basis(unrelated)), ('consanguinity', nx.cycle_basis(graph))):
        for cycle in cycles:
            if independent(cycle):
                people = [n for n in cycle if graph.nodes[n].get('kind') == 'person']
                couples = [(n[1], n[2]) for n in cycle if graph.nodes[n].get('kind') == 'mating']
                found.append(Loop(people, couples, kind))
    found.sort(key=lambda loop: loop.kind != 'consanguinity')
    return found


def loop_count(pedigree: Pedigree) -> int:
    """The number of independent loops in the pedigree (see loops)"""
    graph = mating_graph(pedigree).to_undirected()
    return graph.number_of_edges() - graph.number_of_nodes() + nx.number_connected_components(graph)


# -- kinship ----------------------------------------------------------------------------------------------------
def kinship_matrix(pedigree: Pedigree, x_linked: bool = False) -> Tuple[List[str], np.ndarray]:
    """
    Malécot's kinship coefficients of every pair of people: the probability that a gene drawn at random from one
    and a gene drawn from the other, at the same place, are identical by descent. On the diagonal is each person's
    own coefficient, (1 + F) / 2 for inbreeding coefficient F (on the X, 1 for a man, who has one copy). Founders
    are taken as unrelated and not inbred.

    The coefficients are worked out in the order of the DAG, parents before children, by the recursion that sums
    Wright's path coefficients over every path through a common ancestor: a person's kinship with anyone not their
    descendant is the average of their parents' kinships with that person.

    For the X chromosome (x_linked), a man has one copy, his mother's: his own coefficient is 1, and his kinship with
    anyone is his mother's. A woman has her father's copy and one of her mother's. Someone of unknown sex (who has no
    children) is taken as equally likely to be either.

    Returns the people's IDs, in the order of the matrix's rows, and the matrix.
    """
    order = pedigree.order()
    ids = pedigree.ids
    position = {pid: k for k, pid in enumerate(ids)}
    n = len(ids)
    phi = np.zeros((n, n))
    done = np.zeros(n, dtype=bool)      # the people worked out so far, none of them descended from the next
    for pid in order:
        p = pedigree[pid]
        i = position[pid]
        if p.father is None:
            self_kinship = 0.5
            row = np.zeros(n)
            if x_linked and p.sex == MALE:
                self_kinship = 1.0
            elif x_linked and p.sex not in (MALE, FEMALE):
                self_kinship = 0.75
        else:
            f, m = position[p.father], position[p.mother]
            if not x_linked:
                row = 0.5 * (phi[f] + phi[m])
                self_kinship = 0.5 * (1 + phi[f, m])
            elif p.sex == MALE:
                row = phi[m].copy()
                self_kinship = 1.0
            elif p.sex == FEMALE:
                row = 0.5 * (phi[f] + phi[m])
                self_kinship = 0.5 * (1 + phi[f, m])
            else:
                row = 0.5 * (phi[m] + 0.5 * (phi[f] + phi[m]))
                self_kinship = 0.5 * (1.0 + 0.5 * (1 + phi[f, m]))
        phi[i, done] = row[done]
        phi[done, i] = row[done]
        phi[i, i] = self_kinship
        done[i] = True
    return ids, phi


def kinship(pedigree: Pedigree, a: str, b: str, x_linked: bool = False) -> float:
    """The kinship coefficient of two people (see kinship_matrix)"""
    ids, phi = kinship_matrix(pedigree, x_linked)
    return float(phi[ids.index(a), ids.index(b)])


def inbreeding(pedigree: Pedigree, x_linked: bool = False) -> Dict[str, float]:
    """
    Each person's inbreeding coefficient: the kinship coefficient of their parents, the probability that their two
    copies are identical by descent (0 for a founder, and on the X for a man, who has one copy). On the X, someone
    of unknown sex has half their parents' kinship, being a woman, with two copies, with probability one half.
    """
    ids, phi = kinship_matrix(pedigree, x_linked)
    position = {pid: k for k, pid in enumerate(ids)}
    out = {}
    for p in pedigree.people:
        if p.father is None or (x_linked and p.sex == MALE):
            out[p.id] = 0.0
        else:
            value = float(phi[position[p.father], position[p.mother]])
            out[p.id] = 0.5 * value if x_linked and p.sex not in (MALE, FEMALE) else value
    return out


# -- relationships ----------------------------------------------------------------------------------------------
@dataclass
class Relationship:
    """
    How two people are related. name describes the second person relative to the first ('father', 'half-sister',
    'first cousin once removed' and so on). up and down are the steps from the first person up to their closest
    common ancestor and from there down to the second, and via the closest common ancestors. degree is the degree
    of that relationship: 1 for parents, children and full siblings, 2 for grandparents, half-siblings, aunts and
    uncles, 3 for first cousins, and so on (the steps of the path, less one for a full relationship). kinship is the
    kinship coefficient and coefficient (2 x kinship) the coefficient of relationship, over every path between the
    two, so they show a closer relationship than the name when there is more than one: double first cousins, whose
    coefficient is a half-sibling's, or relatives whose parents were related.
    """
    name: str
    degree: Optional[int]
    kinship: float
    coefficient: float
    up: Optional[int]
    down: Optional[int]
    via: List[str]


def _steps_up(pedigree: Pedigree, person: str) -> Dict[str, int]:
    """Each ancestor of a person (and the person), with the fewest generations up to them"""
    found = {person: 0}
    frontier = [person]
    while frontier:
        following = []
        for n in frontier:
            for parent in pedigree.parents(n):
                if parent is not None and parent not in found:
                    found[parent] = found[n] + 1
                    following.append(parent)
        frontier = following
    return found


def _ordinal(n: int) -> str:
    words = {1: 'first', 2: 'second', 3: 'third', 4: 'fourth', 5: 'fifth', 6: 'sixth', 7: 'seventh', 8: 'eighth'}
    return words.get(n, f'{n}th')


def _removed(n: int) -> str:
    return {0: '', 1: ' once removed', 2: ' twice removed', 3: ' three times removed'}.get(n, f' {n} times removed')


def _greats(n: int) -> str:
    return 'great-' * n


def _name(up: int, down: int, sex: int, full: bool) -> str:
    """The name of the second person, up generations to the common ancestor from the first and down from it to them"""
    male, female = sex == MALE, sex == FEMALE

    def pick(m, f, either):
        return m if male else (f if female else either)

    if full == 'double' and up >= 2 and down >= 2:
        return 'double ' + _ordinal(min(up, down) - 1) + ' cousin' + _removed(abs(up - down))

    if up == 0 and down == 0:
        return 'self'
    if down == 0:
        base = pick('father', 'mother', 'parent')
        return base if up == 1 else _greats(up - 2) + 'grand' + base
    if up == 0:
        base = pick('son', 'daughter', 'child')
        return base if down == 1 else _greats(down - 2) + 'grand' + base
    half = '' if full else 'half-'
    if up == 1 and down == 1:
        return half + pick('brother', 'sister', 'sibling')
    if down == 1:
        return half + _greats(up - 2) + pick('uncle', 'aunt', 'aunt or uncle')
    if up == 1:
        return half + _greats(down - 2) + pick('nephew', 'niece', 'niece or nephew')
    return half + _ordinal(min(up, down) - 1) + ' cousin' + _removed(abs(up - down))


def relationship(pedigree: Pedigree, a: str, b: str,
                 matrix: Optional[Tuple[List[str], np.ndarray]] = None) -> Relationship:
    """
    How b is related to a, by the shortest path up from a to a common ancestor and down to b. The relationship is
    full (sister rather than half-sister) when the closest common ancestors include a couple, both of whom are at
    that distance, and double (double first cousin) when they include two couples. Partners who aren't related by
    descent are 'unrelated'. via can include the unknown partners PedNet adds, with IDs such as '1~partner'.
    matrix is the pedigree's kinship_matrix, if it has been worked out already, which saves working it out again
    for each pair of a large family.
    """
    ids, phi = kinship_matrix(pedigree) if matrix is None else matrix
    position = {pid: k for k, pid in enumerate(ids)}
    value = float(phi[position[a], position[b]])
    above_a, above_b = _steps_up(pedigree, a), _steps_up(pedigree, b)
    common = set(above_a) & set(above_b)
    if a == b:
        return Relationship('self', 0, value, 2 * value, 0, 0, [a])
    if not common:
        return Relationship('unrelated', None, value, 2 * value, None, None, [])
    distance = {c: above_a[c] + above_b[c] for c in common}
    shortest = min(distance.values())
    closest = sorted(c for c in common if distance[c] == shortest)
    # the steps for the closest ancestor, preferring the most even split (cousins rather than aunts, for a tie)
    best = min(closest, key=lambda c: (abs(above_a[c] - above_b[c]), c))
    up, down = above_a[best], above_b[best]
    # full (siblings, cousins) when two of the closest common ancestors are a couple with a child together, and
    # double when two such couples are (as for the children of two brothers who married two sisters)
    couples = sum(1 for c, d in combinations(closest, 2) if set(pedigree.children(c)) & set(pedigree.children(d)))
    lineal = up == 0 or down == 0
    full = not lineal and couples >= 1
    degree = up + down - (1 if full else 0)
    name = _name(up, down, pedigree[b].sex, 'double' if not lineal and couples >= 2 else full)
    return Relationship(name, degree, value, 2 * value, up, down, closest)


# -- network measures ---------------------------------------------------------------------------------------------
def centrality(pedigree: Pedigree, measure: str = 'betweenness', directed: bool = False) -> Dict[str, float]:
    """
    Each person's centrality in the pedigree graph, 'degree', 'betweenness' or 'closeness', as networkx works them
    out (normalised), on the graph without its directions unless directed is True
    """
    graph = pedigree_graph(pedigree)
    if not directed:
        graph = graph.to_undirected()
    if measure == 'degree':
        return nx.degree_centrality(graph)
    if measure == 'betweenness':
        return nx.betweenness_centrality(graph)
    if measure == 'closeness':
        return nx.closeness_centrality(graph)
    raise ValueError(f"measure must be 'degree', 'betweenness' or 'closeness', not {measure!r}")


def founder_influence(pedigree: Pedigree) -> Dict[str, float]:
    """
    Nick Taylor's founder influence: for each founder with descendants, the share of the paths down the DAG from the
    founder (counting the path of no steps, to the founder) that end at an affected person
    """
    graph = pedigree_graph(pedigree)
    affected = {n for n, d in graph.nodes(data=True) if d['affected']}
    paths_all: Dict[str, int] = {}
    paths_affected: Dict[str, int] = {}
    for n in reversed(list(nx.topological_sort(graph))):
        paths_all[n] = 1 + sum(paths_all[c] for c in graph.successors(n))
        paths_affected[n] = (n in affected) + sum(paths_affected[c] for c in graph.successors(n))
    return {n: paths_affected[n] / paths_all[n] for n in graph if graph.in_degree(n) == 0 and graph.out_degree(n)}


def pedigree_width(pedigree: Pedigree) -> int:
    """
    The width of the pedigree as a partial order: the most people no one of whom is another's ancestor. By
    Dilworth's theorem it is the number of people less a maximum matching of the transitive closure, which is how it
    is found.
    """
    graph = pedigree_graph(pedigree)
    closure = nx.transitive_closure_dag(graph)
    bipartite = nx.Graph()
    left = [('L', n) for n in graph]
    bipartite.add_nodes_from(left)
    bipartite.add_nodes_from(('R', n) for n in graph)
    bipartite.add_edges_from((('L', u), ('R', v)) for u, v in closure.edges)
    matching = nx.bipartite.hopcroft_karp_matching(bipartite, top_nodes=left)
    return graph.number_of_nodes() - len(matching) // 2


def founder_cover(pedigree: Pedigree) -> List[str]:
    """
    A small set of founders between whom everyone in the pedigree descends (or is one), chosen greedily, each time
    the founder who covers most of the people not yet covered: Nick Taylor's minimal founder cover
    """
    graph = pedigree_graph(pedigree)
    founders = sorted(n for n in graph if graph.in_degree(n) == 0)
    reach = {f: nx.descendants(graph, f) | {f} for f in founders}
    uncovered, cover = set(graph), []
    while uncovered:
        best = max(founders, key=lambda f: (len(reach[f] & uncovered), -founders.index(f)))
        if not reach[best] & uncovered:
            break
        cover.append(best)
        uncovered -= reach[best]
    return cover


@dataclass
class Elimination:
    """
    The order in which the genotypes are summed out for exact likelihoods, from the moral graph. width is the most
    people in one step's table, so width - 1 bounds the treewidth of the moral graph from above, and the cost of a
    likelihood grows as the number of genotype states to the power of width. exact is whether the largest table is
    small enough for PedNet to work out exact likelihoods at all.
    """
    order: List[str]
    width: int
    largest_table: int
    exact: bool = True


def elimination(pedigree: Pedigree, x_linked: bool = False) -> Elimination:
    """The elimination order PedNet's likelihood engine uses for the pedigree (see engine.Plan), however large"""
    from .engine import Network
    net = Network(pedigree, x_linked, check=False)
    order = [net.ids[var] for _, var, _, _ in net.plan.steps]
    return Elimination(order, net.plan.width, net.plan.largest, net.plan.feasible)


def write_graph(pedigree: Pedigree, path, mating: bool = False):
    """
    Writes the pedigree graph (or the mating graph) as GraphML, for network tools such as Gephi or Cytoscape. The
    couples' nodes of the mating graph are named 'mating:father:mother', where an unknown partner PedNet added has
    an ID such as '1~partner'.
    """
    graph = mating_graph(pedigree) if mating else pedigree_graph(pedigree)
    if mating:
        graph = nx.relabel_nodes(graph, {n: f'mating:{n[1]}:{n[2]}' for n in graph if isinstance(n, tuple)})
    for _, data in graph.nodes(data=True):
        for key, value in list(data.items()):
            if isinstance(value, (bool, np.bool_)):
                data[key] = bool(value)
            elif value is None:
                data[key] = ''
    nx.write_graphml(graph, path)
