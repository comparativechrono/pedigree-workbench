"""Command-line interface for mpedtools."""

from __future__ import annotations

import argparse
import sys

from .core import read, write, validate, format_output
from .ops import (
    extract_phenotype, extract_all_phenotypes, merge,
    split_families, filter_family, to_ped, to_mped,
    summarise, add_phenotype, remove_phenotype,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mpedtools",
        description="Tools for working with PED and MPED pedigree files.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # ── info ──
    p_info = subparsers.add_parser("info", help="Show summary of a PED/MPED file")
    p_info.add_argument("input", help="Input PED or MPED file")

    # ── validate ──
    p_val = subparsers.add_parser("validate", help="Validate a PED/MPED file")
    p_val.add_argument("input", help="Input PED or MPED file")

    # ── extract ──
    p_ext = subparsers.add_parser("extract",
        help="Extract a single phenotype as a PED file from an MPED file")
    p_ext.add_argument("input", help="Input MPED file")
    p_ext.add_argument("phenotype", help="Phenotype column name to extract")
    p_ext.add_argument("-o", "--output", required=True, help="Output PED file path")

    # ── extract-all ──
    p_exa = subparsers.add_parser("extract-all",
        help="Extract all phenotypes as separate PED files")
    p_exa.add_argument("input", help="Input MPED file")
    p_exa.add_argument("-d", "--output-dir", default=".", help="Output directory")
    p_exa.add_argument("-p", "--prefix", default=None, help="Filename prefix")

    # ── merge ──
    p_merge = subparsers.add_parser("merge",
        help="Merge multiple PED files into one MPED file")
    p_merge.add_argument("inputs", nargs="+", help="Input PED files")
    p_merge.add_argument("-o", "--output", required=True, help="Output MPED file path")
    p_merge.add_argument("-n", "--names", nargs="*", default=None,
        help="Phenotype column names (one per input file)")

    # ── split ──
    p_split = subparsers.add_parser("split",
        help="Split a multi-family file into one file per family")
    p_split.add_argument("input", help="Input PED or MPED file")
    p_split.add_argument("-d", "--output-dir", default=".", help="Output directory")
    p_split.add_argument("-p", "--prefix", default=None, help="Filename prefix")

    # ── convert ──
    p_conv = subparsers.add_parser("convert",
        help="Convert between PED and MPED formats")
    p_conv.add_argument("input", help="Input file")
    p_conv.add_argument("-o", "--output", required=True, help="Output file path")
    p_conv.add_argument("-f", "--format", choices=["ped", "mped"], required=True,
        help="Output format")
    p_conv.add_argument("--phenotype", default=None,
        help="Phenotype to use when converting MPED to PED (required if multiple)")

    # ── add-phenotype ──
    p_add = subparsers.add_parser("add-phenotype",
        help="Add a new phenotype column to a file")
    p_add.add_argument("input", help="Input PED or MPED file")
    p_add.add_argument("name", help="Name for the new phenotype column")
    p_add.add_argument("-o", "--output", required=True, help="Output file path")
    p_add.add_argument("--default", type=int, default=0,
        help="Default value for all individuals (0=unknown, default)")

    # ── remove-phenotype ──
    p_rem = subparsers.add_parser("remove-phenotype",
        help="Remove a phenotype column from a file")
    p_rem.add_argument("input", help="Input MPED file")
    p_rem.add_argument("name", help="Phenotype column name to remove")
    p_rem.add_argument("-o", "--output", required=True, help="Output file path")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    try:
        if args.command == "info":
            ped = read(args.input)
            print(summarise(ped))

        elif args.command == "validate":
            ped = read(args.input)
            issues = validate(ped)
            if not issues:
                print("Validation: OK")
            else:
                errors = sum(1 for i in issues if i.level == "error")
                warnings = sum(1 for i in issues if i.level == "warning")
                print(f"Found {errors} error(s), {warnings} warning(s):")
                for issue in issues:
                    prefix = "ERROR" if issue.level == "error" else "WARN"
                    line_info = f" (line {issue.line})" if issue.line else ""
                    print(f"  [{prefix}]{line_info} {issue.message}")
                return 1 if errors > 0 else 0

        elif args.command == "extract":
            ped = read(args.input)
            extracted = extract_phenotype(ped, args.phenotype)
            write(extracted, args.output, force_format="ped")
            print(f"Extracted '{args.phenotype}' → {args.output}")

        elif args.command == "extract-all":
            ped = read(args.input)
            prefix = args.prefix or "pedigree"
            paths = extract_all_phenotypes(ped, args.output_dir, prefix)
            for p in paths:
                print(f"  Written: {p}")

        elif args.command == "merge":
            peds = [read(f) for f in args.inputs]
            merged = merge(peds, args.names)
            write(merged, args.output, force_format="mped")
            print(f"Merged {len(peds)} files → {args.output}")
            print(f"Phenotypes: {', '.join(merged.phenotype_names)}")

        elif args.command == "split":
            ped = read(args.input)
            families = split_families(ped)
            prefix = args.prefix or "family"
            ext = ".mped" if ped.is_mped else ".ped"
            for fam in families:
                filepath = f"{args.output_dir}/{prefix}_{fam.families[0]}{ext}"
                write(fam, filepath)
                print(f"  Written: {filepath} ({len(fam.individuals)} individuals)")

        elif args.command == "convert":
            ped = read(args.input)
            if args.format == "ped":
                result = to_ped(ped, args.phenotype)
                write(result, args.output, force_format="ped")
            else:
                result = to_mped(ped, args.phenotype)
                write(result, args.output, force_format="mped")
            print(f"Converted → {args.output}")

        elif args.command == "add-phenotype":
            ped = read(args.input)
            result = add_phenotype(ped, args.name, args.default)
            write(result, args.output)
            print(f"Added phenotype '{args.name}' → {args.output}")

        elif args.command == "remove-phenotype":
            ped = read(args.input)
            result = remove_phenotype(ped, args.name)
            write(result, args.output)
            print(f"Removed phenotype '{args.name}' → {args.output}")

        return 0

    except FileNotFoundError:
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
