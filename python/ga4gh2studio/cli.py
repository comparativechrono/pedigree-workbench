"""Command line: ga4gh2studio FILE.json [-o OUTPUT.json] [--force]"""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .converter import LegacyFileError, convert_file


def default_output(path: str) -> str:
    """``okafor_ga4gh-pedigree.json`` -> ``okafor.studio.json``, beside the input."""
    base = path
    for ext in ("_ga4gh-pedigree.json", "_phenopackets-family.json", ".json"):
        if base.endswith(ext):
            base = base[: -len(ext)]
            break
    return base + ".studio.json"


def _same_file(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ga4gh2studio",
                                description="Draw a GA4GH Pedigree or Phenopackets Family in Pedigree Studio.")
    p.add_argument("input", nargs="?", help="a GA4GH Pedigree or Phenopackets Family .json file")
    p.add_argument("-g", "--ga4gh", default=None, help="a GA4GH Pedigree file (as in version 0.3)")
    p.add_argument("-p", "--phenopackets", default=None, help="a Phenopackets Family file (as in version 0.3)")
    p.add_argument("-o", "--output", default=None,
                   help="the Pedigree Studio file to write; a file named here is replaced (default: the input's "
                        "name with .studio.json, beside it, which is never replaced unless you give --force)")
    p.add_argument("--force", action="store_true",
                   help="replace the default output file if it already exists")
    p.add_argument("--version", action="version", version="ga4gh2studio " + __version__)
    a = p.parse_args(argv)
    ga4gh = a.ga4gh or a.input
    if not ga4gh and not a.phenopackets:
        p.error("give a GA4GH Pedigree or Phenopackets Family file")
    inputs = [f for f in (ga4gh, a.phenopackets) if f]
    for f in inputs:
        if not os.path.isfile(f):
            print("ga4gh2studio: cannot find {}".format(f), file=sys.stderr)
            return 1
    out = a.output or default_output(ga4gh or a.phenopackets)
    if any(_same_file(out, f) for f in inputs):
        print("ga4gh2studio: {} is the file being read; give the drawing another name with -o".format(out),
              file=sys.stderr)
        return 2
    if not a.output and os.path.exists(out) and not a.force:
        # okafor.studio.json, the default for okafor_ga4gh-pedigree.json, may well be the drawing the GA4GH
        # files were made from, with names and notes they do not hold: never replace it unasked
        print("ga4gh2studio: {} already exists (it may be the drawing the file came from); give -o to choose "
              "another name, or --force to replace it".format(out), file=sys.stderr)
        return 2
    try:
        result = convert_file(ga4gh, a.phenopackets, out)
    except LegacyFileError as exc:
        print("ga4gh2studio: {}".format(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print("ga4gh2studio: {}".format(exc), file=sys.stderr)
        return 1
    print(result.summary)
    print("  wrote {}".format(out))
    for w in result.warnings:
        print("  note: {}".format(w))
    return 0


if __name__ == "__main__":
    sys.exit(main())
