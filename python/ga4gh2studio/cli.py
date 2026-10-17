"""Command line: ga4gh2studio FILE.json [-o OUTPUT.json]"""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .converter import LegacyFileError, convert_file


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ga4gh2studio",
                                description="Draw a GA4GH Pedigree or Phenopackets Family in Pedigree Studio.")
    p.add_argument("input", nargs="?", help="a GA4GH Pedigree or Phenopackets Family .json file")
    p.add_argument("-g", "--ga4gh", default=None, help="a GA4GH Pedigree file (as in version 0.3)")
    p.add_argument("-p", "--phenopackets", default=None, help="a Phenopackets Family file (as in version 0.3)")
    p.add_argument("-o", "--output", default=None, help="the Pedigree Studio file to write "
                                                        "(default: the input's name with .studio.json)")
    p.add_argument("--version", action="version", version="ga4gh2studio " + __version__)
    a = p.parse_args(argv)
    ga4gh = a.ga4gh or a.input
    if not ga4gh and not a.phenopackets:
        p.error("give a GA4GH Pedigree or Phenopackets Family file")
    out = a.output
    if not out:
        base = (ga4gh or a.phenopackets)
        for ext in ("_ga4gh-pedigree.json", "_phenopackets-family.json", ".json"):
            if base.endswith(ext):
                base = base[: -len(ext)]
                break
        out = base + ".studio.json"
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
