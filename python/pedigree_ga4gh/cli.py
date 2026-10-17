"""Command line: pedigree-ga4gh validate|upgrade|convert|kin ..."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__, kin
from .io import dumps, load
from .kindred import detect, from_document, to_ga4gh_pedigree, to_phenopackets_family
from .legacy import identify, upgrade
from .validate import KIND_NAMES, errors, render, validate


def _write(text: str, path) -> None:
    if path and path != "-":
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pedigree-ga4gh",
                                description="Check, upgrade and convert GA4GH Pedigree and Phenopackets files.")
    p.add_argument("--version", action="version", version="pedigree-ga4gh " + __version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("validate", help="check a file against the standard")
    sp.add_argument("input")
    sp.add_argument("--json", action="store_true", help="print the findings as JSON")
    sp = sub.add_parser("upgrade", help="rewrite an older or non-standard file in the standard form")
    sp.add_argument("input")
    sp.add_argument("-o", "--output", default=None)
    sp = sub.add_parser("convert", help="GA4GH Pedigree <-> Phenopackets Family")
    sp.add_argument("input")
    sp.add_argument("--to", choices=["pedigree", "family"], required=True)
    sp.add_argument("-o", "--output", default=None)
    sp.add_argument("--created-by", default="pedigree-ga4gh " + __version__)
    sp = sub.add_parser("kin", help="list the KIN relations")
    a = p.parse_args(argv)
    if a.cmd == "kin":
        for t in kin.TERMS.values():
            print("{}  {:<40} {}".format(t.id, t.label, "symmetric" if t.symmetric else ""))
        return 0
    try:
        doc = load(a.input)
    except (OSError, ValueError) as exc:
        print("pedigree-ga4gh: {}".format(exc), file=sys.stderr)
        return 1
    if a.cmd == "validate":
        found = validate(doc)
        if a.json:
            print(json.dumps([f.to_dict() for f in found], indent=2))
        else:
            print("{}: {}".format(a.input, KIND_NAMES.get(detect(doc), "unknown")))
            print(render(found))
        return 1 if errors(found) else 0
    if a.cmd == "upgrade":
        try:
            new, changes, todo = upgrade(doc)
        except ValueError as exc:
            print("pedigree-ga4gh: {}: {}".format(a.input, exc), file=sys.stderr)
            return 1
        _write(dumps(new), a.output)
        for c in changes:
            print("changed: " + c, file=sys.stderr)
        for t in todo:
            print("to do: " + t, file=sys.stderr)
        return 0
    old = identify(doc)
    if old is not None:
        print("pedigree-ga4gh: {}: {}{}".format(a.input, old.description, " Upgrade it first: pedigree-ga4gh "
                                                "upgrade {}".format(a.input) if old.upgradable else ""),
              file=sys.stderr)
        return 1
    try:
        k, warnings = from_document(doc)
    except ValueError as exc:
        print("pedigree-ga4gh: {}: {}".format(a.input, exc), file=sys.stderr)
        return 1
    if a.to == "pedigree":
        out, w = to_ga4gh_pedigree(k, created_by=a.created_by)
    else:
        out, w = to_phenopackets_family(k, created_by=a.created_by)
    _write(dumps(out), a.output)
    for x in warnings + w:
        print("note: " + x, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
