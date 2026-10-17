"""Run the packages' command-line programs by name.

    python -m pedwb studio2ped okafor.studio.json -d results

is the same as typing ``studio2ped okafor.studio.json -d results`` on a
computer where the packages are installed with pip. The workbench's terminal
uses this for its commands, and notebooks use it for ``!studio2ped …`` lines.

Two of the programs, hponorm and mondonorm, ask questions as they go
(``input()``). A web page cannot answer those from the terminal, so here they
stop asking: what has been decided so far is saved, and the rest is left as it
was. Give them the answers in a file instead (``--mapping FILE
--auto-remembered``), or use the Tools tab's *Match conditions to terms*.
"""
from __future__ import annotations

import builtins
import importlib
import os
import sys
from typing import Callable, Dict, List, Optional

# program name -> "module:function" (the console scripts of the packages)
PROGRAMS: Dict[str, str] = {
    "studio2ped": "studio2ped.cli:main",
    "ped2studio": "ped2studio.cli:main",
    "studio2ga4gh": "studio2ga4gh.cli:main",
    "ga4gh2studio": "ga4gh2studio.cli:main",
    "mpedtools": "mpedtools.cli:main",
    "hponorm": "hponorm.cli:main",
    "mondonorm": "mondonorm.cli:main",
    "phenotk": "phenopacket_toolkit.cli.main:main",
    "pedigree-ga4gh": "pedigree_ga4gh.cli:main",
}

# what each program is for, in a few words (for help and man in the terminal)
ABOUT: Dict[str, str] = {
    "studio2ped": "Pedigree Studio drawing -> PED or MPED file(s)",
    "ped2studio": "PED file -> Pedigree Studio drawing",
    "studio2ga4gh": "Pedigree Studio drawing -> GA4GH Pedigree and Phenopackets Family",
    "ga4gh2studio": "GA4GH Pedigree or Phenopackets Family -> Pedigree Studio drawing",
    "mpedtools": "PED and multi-phenotype PED (MPED) files: check, extract, merge, split, convert",
    "hponorm": "match phenotype names in Phenopackets to HPO terms (asks as it goes)",
    "mondonorm": "match disease names in Phenopackets to Mondo terms (asks as it goes)",
    "phenotk": "the phenopacket toolkit: validate, view, normalise, filter, de-identify, convert ...",
    "pedigree-ga4gh": "the GA4GH implementation the others share: validate, upgrade, convert",
}

# the programs that ask questions with input()
_ASKS = {"hponorm", "mondonorm"}

_NO_TYPING = (
    "\n{prog}: this terminal cannot answer {prog}'s questions, so it stops here: the choices made so far "
    "are saved and the rest are left as they were.\n"
    "  To match names with the mouse, use the Tools tab (Match conditions to terms).\n"
    "  To give the answers in a file:  {prog} FILE.json --mapping terms.json --auto-remembered\n"
)


def entry_point(name: str) -> Callable[[Optional[List[str]]], int]:
    """The main() of a program, imported when it is first used."""
    if name not in PROGRAMS:
        raise KeyError(name)
    mod, func = PROGRAMS[name].split(":")
    return getattr(importlib.import_module(mod), func)


def _exit_status(code) -> int:
    if code is None:
        return 0
    if isinstance(code, bool):
        return int(code)
    if isinstance(code, int):
        return code
    print(code, file=sys.stderr)
    return 1


def run(argv: List[str]) -> int:
    """Run ``argv[0]`` (a program name) with the arguments ``argv[1:]`` and
    return its exit status, as a shell would. Nothing is raised: an error in
    the program is printed, as Python would print it, and gives status 1."""
    if not argv:
        print("usage: python -m pedwb PROGRAM [ARGUMENTS ...]\nprograms: " + ", ".join(PROGRAMS),
              file=sys.stderr)
        return 2
    name, args = argv[0], list(argv[1:])
    if name not in PROGRAMS:
        print("pedwb: no program called {!r} (there are: {})".format(name, ", ".join(PROGRAMS)), file=sys.stderr)
        return 127
    main = entry_point(name)
    old_input, old_argv = builtins.input, sys.argv[:]
    told = []

    def no_input(prompt=""):
        if prompt:
            sys.stdout.write(str(prompt))
        if not told:
            told.append(True)
            sys.stderr.write(_NO_TYPING.format(prog=name))
        raise EOFError

    if name in _ASKS:
        builtins.input = no_input
    sys.argv[:] = [name] + args
    try:
        return _exit_status(main(args))
    except SystemExit as e:
        return _exit_status(e.code)
    except KeyboardInterrupt:
        return 130
    except Exception:  # noqa: BLE001 - show it as Python would, and carry on
        import traceback
        traceback.print_exc()
        return 1
    finally:
        builtins.input = old_input
        sys.argv[:] = old_argv
        try:
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
