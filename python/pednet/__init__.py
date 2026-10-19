"""PedNet: pedigrees as graphs. A pedigree is a directed acyclic graph, and PedNet analyses its structure (graph),
the pattern of affected people in it (features), and, with the graph as a Bayesian network of genotypes, the mode
of inheritance (inheritance) and the co-segregation of candidate variants (segregation)."""
from .features import (classify_by_metrics, classify_by_patterns, network_metrics, pattern_features,
                       segregation_network_score)
from .genotypes import read_genotype_table, read_vcf
from .graph import (inbreeding, kinship, kinship_matrix, loops, mating_graph, moral_graph, pedigree_graph,
                    relationship)
from .inheritance import InheritanceResult, ModeEvidence, infer_mode, infer_shared_mode
from .models import MODE_NAMES, MODES, Model
from .ga4gh import read_ga4gh
from .pedigree import Pedigree, PedigreeError, Person, pedigree_from_rows, read_ped, read_pedigree, write_ped
from .segregation import (CombinedScore, Variant, VariantScore, evidence_strength, rank_variants,
                          rank_variants_across)

__version__ = '2.1.0'

__all__ = [
    'pedigree_graph', 'mating_graph', 'moral_graph', 'loops', 'kinship', 'kinship_matrix', 'inbreeding',
    'relationship', 'network_metrics', 'pattern_features', 'classify_by_metrics', 'classify_by_patterns',
    'segregation_network_score', 'infer_mode', 'infer_shared_mode', 'rank_variants', 'rank_variants_across',
    'evidence_strength', 'read_ped', 'read_pedigree', 'read_ga4gh', 'write_ped', 'pedigree_from_rows', 'read_vcf', 'read_genotype_table', 'Pedigree',
    'Person', 'PedigreeError', 'Variant', 'VariantScore', 'CombinedScore', 'InheritanceResult', 'ModeEvidence',
    'Model', 'MODES', 'MODE_NAMES', '__version__',
]
