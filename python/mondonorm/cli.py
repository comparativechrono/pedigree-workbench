"""Interactive command-line tool to validate and normalise the disease terms
in GA4GH phenopacket / family JSON files against the MONDO ontology.

Run:  python -m mondonorm FILE.json [FILE2.json ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import phenopackets as pp
from .mondo import MondoIndex, normalise_curie
from .ols import OlsClient
from .suggest import Candidate, Suggester

# --------------------------------------------------------------------- pretty
try:
    from rich.console import Console
    from rich.table import Table

    _console = Console()
    _HAVE_RICH = True
except Exception:  # pragma: no cover
    _console = None
    _HAVE_RICH = False


class UI:
    def __init__(self, color: bool = True):
        self.rich = _HAVE_RICH and color

    def rule(self, text: str = "") -> None:
        if self.rich:
            _console.rule(f"[bold]{text}")
        else:
            print("\n" + "=" * 70)
            if text:
                print(text)
                print("-" * 70)

    def say(self, text: str = "") -> None:
        (_console.print if self.rich else print)(text)

    def warn(self, text: str) -> None:
        self.say(f"[yellow]! {text}[/yellow]" if self.rich else f"! {text}")

    def ok(self, text: str) -> None:
        self.say(f"[green]\u2713 {text}[/green]" if self.rich else f"\u2713 {text}")

    def err(self, text: str) -> None:
        self.say(f"[red]\u2717 {text}[/red]" if self.rich else f"\u2717 {text}")

    def candidates(self, cands: list[Candidate]) -> None:
        if not cands:
            self.warn("No suggestions found. Try 's <better search words>' or 'm <MONDO:id>'.")
            return
        if self.rich:
            t = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
            t.add_column("#", justify="right")
            t.add_column("MONDO id", style="magenta", no_wrap=True)
            t.add_column("Label", style="white")
            t.add_column("Score", justify="right")
            t.add_column("Matched on", style="dim")
            t.add_column("Definition", style="dim")
            for i, c in enumerate(cands, 1):
                t.add_row(str(i), c.id, c.label, f"{c.score:g}", c.matched_on, c.short_def(70))
            _console.print(t)
        else:
            for i, c in enumerate(cands, 1):
                print(f"  {i:>2}. {c.id}  {c.label}  (score {c.score:g}, {c.matched_on})")
                if c.short_def(80):
                    print(f"      {c.short_def(80)}")

    def prompt(self, text: str) -> str:
        try:
            return input(text)
        except EOFError:
            return "q"


HELP = """\
Choices:
  <number>        select that suggestion
  s <words>       search again with different words
  m <MONDO:id>    enter a MONDO id manually (e.g. m MONDO:0005015) - it is validated
  k               keep the current term unchanged
  x               skip this label (leave it unmapped)
  ?               show this help
  q               finish now: apply decisions made so far and save
"""


def build_suggester(args, ui: UI) -> Suggester:
    backend = args.backend
    if backend == "ols":
        ui.say("Backend: EBI OLS (online).")
        return Suggester(OlsClient(), name="ols")
    if backend == "local":
        idx = MondoIndex.load(
            args.mondo_file,
            allow_download=not args.no_download,
            update=args.update,
            cache_dir=args.cache_dir,
            log=ui.say,
        )
        ui.say(f"Backend: local MONDO ({len(idx)} terms from {idx.source}).")
        return Suggester(idx, name="mondo-local")
    # auto
    ols = OlsClient()
    if not args.no_online and ols.available():
        ui.say("Backend: EBI OLS (online).")
        # Local is used as a silent fallback only if it is already cheap to load.
        fb = None
        try:
            if args.mondo_file or (Path(args.cache_dir or _default_cache()) / "mondo.obo").exists():
                fb = MondoIndex.load(
                    args.mondo_file, allow_download=False,
                    cache_dir=args.cache_dir, log=lambda *a, **k: None,
                )
        except Exception:
            fb = None
        return Suggester(ols, fallback=fb, name="ols")
    ui.warn("OLS not reachable; using local MONDO.")
    idx = MondoIndex.load(
        args.mondo_file,
        allow_download=not args.no_download,
        update=args.update,
        cache_dir=args.cache_dir,
        log=ui.say,
    )
    ui.say(f"Backend: local MONDO ({len(idx)} terms from {idx.source}).")
    return Suggester(idx, name="mondo-local")


def _default_cache():
    from .mondo import default_cache_dir

    return default_cache_dir()


def review_group(
    ui: UI,
    suggester: Suggester,
    label: str,
    existing_id: str,
    count: int,
    index: int,
    total: int,
    remembered: dict[str, dict],
    limit: int,
) -> dict | None:
    """Drive the interactive review of one label group.

    Returns a decision dict {id,label,action} or None to abort/quit.
    The special action 'quit' tells the caller to stop and save.
    """
    ui.rule(f"[{index}/{total}] disease label: {label!r}   ({count} occurrence(s))")

    if existing_id:
        existing = suggester.resolve(existing_id)
        if existing and existing.label.lower() == label.lower():
            ui.ok(f"Already a valid MONDO term: {existing.id}  {existing.label}")
        elif existing:
            ui.warn(
                f"Existing id {existing_id} resolves to {existing.id} '{existing.label}', "
                f"which differs from the label '{label}'."
            )
        else:
            ui.warn(f"Existing id {existing_id!r} could not be validated against MONDO.")

    query = label
    cands = suggester.suggest(query, limit=limit)

    # Float a remembered decision for this label to the very top.
    mem = remembered.get(label.lower())
    if mem:
        ui.ok(f"Remembered from earlier: {mem['id']}  {mem['label']}  (enter 'r' to reuse)")

    while True:
        ui.candidates(cands)
        raw = ui.prompt("Select [#, s words, m MONDO:id, r, k, x, ?, q]: ").strip()

        if raw == "":
            continue
        if raw in ("?", "help"):
            ui.say(HELP)
            continue
        if raw in ("q", "quit"):
            return {"action": "quit"}
        if raw in ("k", "keep"):
            return {"action": "keep"}
        if raw in ("x", "skip"):
            return {"action": "skip"}
        if raw in ("r", "reuse") and mem:
            return {"action": "map", "id": mem["id"], "label": mem["label"]}

        # search again
        if raw.startswith("s ") or raw == "s":
            query = raw[2:].strip() or ui.prompt("Search words: ").strip()
            if query:
                cands = suggester.suggest(query, limit=limit)
            continue

        # explicit manual id  (m MONDO:0005015)  or a bare curie
        manual = None
        if raw.startswith("m "):
            manual = raw[2:].strip()
        elif normalise_curie(raw):
            # Only treat as a curie if it is NOT a small selection index.
            if not (raw.isdigit() and 1 <= int(raw) <= len(cands)):
                manual = raw
        if manual is not None:
            c = normalise_curie(manual)
            if not c:
                ui.err(f"{manual!r} is not a valid MONDO id (expected MONDO:0000000).")
                continue
            resolved = suggester.resolve(c)
            if resolved:
                ui.ok(f"{resolved.id}  {resolved.label}")
                if _confirm(ui, "Use this term?"):
                    return {"action": "map", "id": resolved.id, "label": resolved.label}
                continue
            ui.warn(f"Could not validate {c} against MONDO.")
            if _confirm(ui, f"Use {c} anyway with label {label!r}?"):
                return {"action": "map", "id": c, "label": label}
            continue

        # numeric selection
        if raw.isdigit():
            i = int(raw)
            if 1 <= i <= len(cands):
                chosen = cands[i - 1]
                return {"action": "map", "id": chosen.id, "label": chosen.label}
            ui.err(f"Pick a number between 1 and {len(cands)}.")
            continue

        ui.err("Unrecognised input. Type ? for help.")


def _confirm(ui: UI, text: str) -> bool:
    ans = ui.prompt(f"{text} [Y/n]: ").strip().lower()
    return ans in ("", "y", "yes")


def process_file(path: Path, args, ui: UI, suggester: Suggester, remembered: dict) -> dict:
    ui.rule(f"FILE: {path.name}")
    data = pp.load(path)
    refs = pp.find_disease_terms(data)
    if not refs:
        ui.warn("No disease terms found in this file.")
        return {"file": str(path), "mapped": 0, "kept": 0, "skipped": 0, "total": 0}

    groups = pp.group_by_label(refs)
    ui.say(f"Found {len(refs)} disease term(s) across {len(groups)} distinct label(s).")

    decisions: list[dict] = []
    stop = False
    items = list(groups.items())
    for index, ((label, existing_id), group_refs) in enumerate(items, 1):
        if stop:
            break
        if args.auto_remembered and label.lower() in remembered:
            mem = remembered[label.lower()]
            for r in group_refs:
                r.apply(mem["id"], mem["label"])
            ui.ok(f"[auto] {label!r} -> {mem['id']} {mem['label']}")
            decisions.append({"label": label, **mem, "action": "map", "count": len(group_refs)})
            continue

        decision = review_group(
            ui, suggester, label, existing_id, len(group_refs),
            index, len(items), remembered, args.limit,
        )
        action = decision.get("action")
        if action == "quit":
            stop = True
            ui.warn("Finishing early - remaining labels left unchanged.")
            break
        if action == "keep":
            ui.say(f"Kept {label!r} unchanged.")
            decisions.append({"label": label, "action": "keep", "count": len(group_refs)})
            continue
        if action == "skip":
            ui.say(f"Skipped {label!r}.")
            decisions.append({"label": label, "action": "skip", "count": len(group_refs)})
            continue
        # map
        cid, clabel = decision["id"], decision["label"]
        for r in group_refs:
            r.apply(cid, clabel)
        remembered[label.lower()] = {"id": cid, "label": clabel}
        ui.ok(f"Mapped {label!r} -> {cid} {clabel} ({len(group_refs)} occurrence(s)).")
        decisions.append({"label": label, "id": cid, "label_mondo": clabel,
                          "action": "map", "count": len(group_refs)})

    # ---- write output
    if args.out and len(args._files) == 1:
        out_path = Path(args.out)
    elif args.in_place:
        out_path = path
    else:
        out_path = path.with_name(path.stem + ".normalized.json")
    pp.save(data, out_path)
    ui.ok(f"Wrote normalised file: {out_path}")

    # ---- write a mapping sidecar
    sidecar = out_path.with_suffix(out_path.suffix + ".mapping.json")
    pp.save({"file": str(path), "decisions": decisions}, sidecar)
    ui.say(f"Wrote decision log: {sidecar}")

    mapped = sum(d["count"] for d in decisions if d["action"] == "map")
    kept = sum(d["count"] for d in decisions if d["action"] == "keep")
    skipped = sum(d["count"] for d in decisions if d["action"] == "skip")
    return {"file": str(path), "mapped": mapped, "kept": kept,
            "skipped": skipped, "total": len(refs)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="mondonorm",
        description="Interactively map free-text phenopacket disease labels to MONDO terms.",
    )
    p.add_argument("files", nargs="+", help="Phenopacket / family JSON file(s).")
    p.add_argument("-o", "--out", help="Output path (only valid with a single input file).")
    p.add_argument("--in-place", action="store_true", help="Overwrite the input file(s).")
    p.add_argument("--backend", choices=["auto", "ols", "local"], default="auto",
                   help="Suggestion source (default: auto -> OLS online, else local).")
    p.add_argument("--mondo-file", help="Path to a local mondo.obo or mondo.json.")
    p.add_argument("--cache-dir", help="Where to cache the downloaded MONDO file.")
    p.add_argument("--update", action="store_true", help="Re-download / re-parse MONDO.")
    p.add_argument("--no-download", action="store_true",
                   help="Never download MONDO (local backend must find a file).")
    p.add_argument("--no-online", action="store_true",
                   help="Do not use OLS even in auto mode.")
    p.add_argument("--limit", type=int, default=8, help="Suggestions shown per label.")
    p.add_argument("--mapping", help="JSON file of remembered label->term decisions to "
                                     "load and update across runs.")
    p.add_argument("--auto-remembered", action="store_true",
                   help="Auto-apply remembered labels without prompting.")
    p.add_argument("--no-color", action="store_true", help="Disable rich/colour output.")
    args = p.parse_args(argv)
    args._files = args.files

    ui = UI(color=not args.no_color)

    if args.out and len(args.files) > 1:
        ui.err("--out can only be used with a single input file.")
        return 2

    # Load remembered decisions, if any.
    remembered: dict[str, dict] = {}
    if args.mapping and Path(args.mapping).exists():
        try:
            remembered = json.loads(Path(args.mapping).read_text())
            ui.say(f"Loaded {len(remembered)} remembered mapping(s) from {args.mapping}.")
        except Exception:
            ui.warn(f"Could not read mapping file {args.mapping}; starting fresh.")

    try:
        suggester = build_suggester(args, ui)
    except Exception as exc:
        ui.err(f"Could not initialise a MONDO backend: {exc}")
        return 1

    summaries = []
    for f in args.files:
        path = Path(f)
        if not path.exists():
            ui.err(f"File not found: {path}")
            continue
        summaries.append(process_file(path, args, ui, suggester, remembered))

    # Persist remembered decisions for next time.
    if args.mapping:
        try:
            Path(args.mapping).write_text(json.dumps(remembered, indent=2, ensure_ascii=False))
            ui.say(f"Saved {len(remembered)} remembered mapping(s) to {args.mapping}.")
        except Exception as exc:
            ui.warn(f"Could not write mapping file: {exc}")

    ui.rule("Summary")
    for s in summaries:
        ui.say(f"{Path(s['file']).name}: {s['mapped']} mapped, {s['kept']} kept, "
               f"{s['skipped']} skipped (of {s['total']} term(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
