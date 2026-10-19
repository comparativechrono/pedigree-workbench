try:
    from ._version import version as __version__
except ImportError:
    #_version.py is written when the package is built, so it is missing from a copy of the source
    __version__ = 'unknown'
from .core import (pedigree_generator, gen_PED_export, gen_GA4GH_export, gen_genotype_export, construct_pedigree_graph,
                   plot_pedigree_tree)

__all__ = [
    "pedigree_generator",
    "construct_pedigree_graph",
    "plot_pedigree_tree",
    "gen_PED_export",
    "gen_GA4GH_export",
    "gen_genotype_export",
]
