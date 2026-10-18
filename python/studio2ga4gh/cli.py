"""Command line: studio2ga4gh SESSION.json [options]"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .converter import convert_file


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="studio2ga4gh",
        description="Convert a Pedigree Studio drawing to a GA4GH Pedigree and a Phenopackets Family.")
    p.add_argument("input", help="the Pedigree Studio .json file")
    p.add_argument("-o", "--output-prefix", default=None,
                   help="start of the output file names (default: the input file's name)")
    p.add_argument("-d", "--output-dir", default=None,
                   help="folder for the output, made if it does not exist (default: beside the input)")
    p.add_argument("-t", "--terms", default=None,
                   help="JSON file matching the colour key's condition names to ontology terms, "
                        'e.g. {"Breast cancer": "MONDO:0007254"}; conditions without a term are left out')
    p.add_argument("--phenotypes", action="store_true",
                   help="kept for version 0.3's commands: it changed how conditions without a term were written, and they are now left out, so it changes nothing")
    p.add_argument("--ids", choices=["numbers", "drawing", "studio"], default="numbers",
                   help="identifiers for people: pedigree numbers such as II-3 (default), the labels shown "
                        "in the drawing (which may be names), or Pedigree Studio's internal ids; a label "
                        "becomes an id as in studio2ped (J. Mensah -> J_Mensah), and one that would be "
                        "empty, 0 or shared falls back to the pedigree number")
    p.add_argument("--include-names", action="store_true",
                   help="kept for version 0.3's commands: the same as --ids drawing, whose ids are the "
                        "drawing's labels and so may be names; no other names are written")
    p.add_argument("--family-id", default="FAM", help="family id (default FAM1, FAM2 ...)")
    p.add_argument("--created-by", default=None, help="who made the files, for metaData.createdBy")
    p.add_argument("--only", choices=["pedigree", "family"], default=None, help="write only one of the two files")
    p.add_argument("--version", action="version", version="studio2ga4gh " + __version__)
    a = p.parse_args(argv)
    terms = None
    if a.terms:
        try:
            with open(a.terms, encoding="utf-8-sig") as fh:
                terms = json.load(fh)
        except FileNotFoundError:
            print("studio2ga4gh: cannot find the terms file {}".format(a.terms), file=sys.stderr)
            return 1
        except (OSError, ValueError) as exc:
            print("studio2ga4gh: could not read the terms file {}: {}".format(a.terms, exc), file=sys.stderr)
            return 1
    options = dict(terms=terms, use_phenotypic_features=a.phenotypes,
                   ids="drawing" if a.include_names else a.ids, family_id=a.family_id,
                   outputs=(a.only,) if a.only else ("pedigree", "family"))
    if a.created_by:
        options["created_by"] = a.created_by
    if not os.path.isfile(a.input):
        print("studio2ga4gh: cannot find {}".format(a.input), file=sys.stderr)
        return 1
    try:
        result = convert_file(a.input, a.output_prefix, a.output_dir, **options)
    except OSError as exc:
        print("studio2ga4gh: {}".format(exc), file=sys.stderr)
        return 1
    except (ValueError, KeyError) as exc:
        print("studio2ga4gh: {}".format(exc), file=sys.stderr)
        return 1
    print(result.summary)
    for path, _ in result.files:
        print("  wrote {}".format(path))
    for w in result.warnings:
        print("  note: {}".format(w))
    return 0


if __name__ == "__main__":
    sys.exit(main())
