"""Command-line interface for ped2studio."""

from __future__ import annotations

import argparse
import sys

from .converter import convert_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ped2studio",
        description="Convert PED pedigree files to Pedigree Studio session JSON.",
    )
    parser.add_argument(
        "input",
        help="Path to the input .ped file",
    )
    parser.add_argument(
        "output",
        help="Path to the output .json file",
    )
    parser.add_argument(
        "--color", "--colour",
        default="#1a2332",
        dest="color",
        help="Hex colour for affected individuals (default: #1a2332)",
    )
    parser.add_argument(
        "--shading",
        action="store_true",
        help="Use shading pattern instead of solid colour for affected individuals",
    )
    parser.add_argument(
        "--pattern",
        choices=["stripes", "dots"],
        default="stripes",
        help="Shading pattern type (default: stripes). Only used with --shading.",
    )
    parser.add_argument(
        "--fill",
        choices=["full", "half"],
        default="full",
        help="Fill coverage for affected individuals: 'full' for entire shape, 'half' for left half only (default: full).",
    )

    args = parser.parse_args(argv)

    try:
        session = convert_file(
            args.input,
            args.output,
            affected_color=args.color,
            use_shading=args.shading,
            shading_pattern=args.pattern,
            fill_type=args.fill,
        )
        n_persons = len(session["persons"])
        n_pships = len(session["partnerships"])
        n_clinks = len(session["childLinks"])
        print(
            f"Converted: {n_persons} individuals, "
            f"{n_pships} partnerships, "
            f"{n_clinks} child links → {args.output}"
        )
        return 0
    except FileNotFoundError:
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
