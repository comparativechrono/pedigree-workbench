"""Interactive command-line tool to validate and normalise the phenotypic
feature terms in GA4GH phenopacket / family JSON files against the HPO ontology.

Run:  python -m hponorm FILE.json [FILE2.json ...]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from . import phenopackets as pp
from .hpo import HpoIndex, normalise_curie
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

    def candidates(self, cands: list[Candidate], error: str | None = None) -> None:
        if error and not cands:
            self.warn(f"{error}, so there are no suggestions. Try again with 's <search words>', "
                      "enter an id with 'h <HP:id>', or run hponorm with --backend local.")
            return
        if error:
            self.warn(f"{error}; these suggestions are from the local copy of the HPO.")
        if not cands:
            self.warn("No suggestions found. Try 's <better search words>' or 'h <HP:id>'.")
            return
        if self.rich:
            t = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
            t.add_column("#", justify="right")
            t.add_column("HPO id", style="magenta", no_wrap=True)
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
  <number>      select that suggestion
  s <words>     search again with different words
  h <HP:id>     enter an HPO id manually (e.g. h HP:0001657) - it is validated
  r             reuse the decision remembered for this label (earlier, or from --mapping)
  k             keep the current term unchanged
  x             skip this label (leave it unmapped)
  ?             show this help
  q             finish now: apply decisions made so far and save
"""


def build_suggester(args, ui: UI) -> Suggester:
    backend = args.backend
    if backend == "ols":
        ui.say("Backend: EBI OLS (online).")
        return Suggester(OlsClient(), name="ols")
    if backend == "local":
        idx = HpoIndex.load(
            args.hpo_file,
            allow_download=not args.no_download,
            update=args.update,
            cache_dir=args.cache_dir,
            log=ui.say,
        )
        ui.say(f"Backend: local HPO ({len(idx)} terms from {idx.source}).")
        return Suggester(idx, name="hpo-local")
    # auto
    ols = OlsClient()
    if not args.no_online and ols.available():
        ui.say("Backend: EBI OLS (online).")
        # Local is used as a silent fallback only if it is already cheap to load.
        fb = None
        try:
            if args.hpo_file or (Path(args.cache_dir or _default_cache()) / "hp.obo").exists():
                fb = HpoIndex.load(
                    args.hpo_file, allow_download=False,
                    cache_dir=args.cache_dir, log=lambda *a, **k: None,
                )
        except Exception:
            fb = None
        return Suggester(ols, fallback=fb, name="ols")
    ui.warn("OLS not reachable; using local HPO.")
    idx = HpoIndex.load(
        args.hpo_file,
        allow_download=not args.no_download,
        update=args.update,
        cache_dir=args.cache_dir,
        log=ui.say,
    )
    ui.say(f"Backend: local HPO ({len(idx)} terms from {idx.source}).")
    return Suggester(idx, name="hpo-local")


def _default_cache():
    from .hpo import default_cache_dir

    return default_cache_dir()


# ------------------------------------------------------------------ mapping
# The --mapping file: names matched to terms, kept between runs. Names are
# matched without regard to case. The same file can serve studio2ga4gh, phenotk
# and mondonorm: values may be hponorm's {"id": ..., "label": ...} or a bare
# id ("HP:0001657"), a phenotk decision log's {"resolved": {...}} is read too,
# and entries for other ontologies are kept as they are.

def _is_ours(curie: str) -> bool:
    c = (curie or "").strip().upper()
    return (c.startswith("HP:") or c.startswith("HP_") or "/HP_" in c) and normalise_curie(curie) is not None


def _entries(data) -> dict:
    """The name -> term part of a mapping file's JSON."""
    if isinstance(data, dict) and isinstance(data.get("resolved"), dict):
        return data["resolved"]
    if isinstance(data, dict):
        return data
    raise ValueError("a mapping file holds a JSON object of names and terms")


def _entry_term(value) -> tuple[str, str]:
    """(id, label) of one entry's value; the label is '' when the file gives only the id."""
    if isinstance(value, str):
        return value.strip(), ""
    if isinstance(value, dict):
        return str(value.get("id") or value.get("curie") or "").strip(), str(value.get("label") or "").strip()
    return "", ""


def read_mapping(data) -> tuple[dict[str, dict], int]:
    """The remembered decisions in a mapping file's JSON: ``({lower-case name: {"id", "label"}}, n)``,
    where ``n`` counts the entries left alone because they are not HPO terms."""
    remembered: dict[str, dict] = {}
    others = 0
    for name, value in _entries(data).items():
        cid, label = _entry_term(value)
        if not _is_ours(cid):
            others += 1
            continue
        key = str(name).strip().lower()
        if key and key not in remembered:
            remembered[key] = {"id": normalise_curie(cid), "label": label}
    return remembered, others


def update_mapping(data, decided: dict[str, dict]) -> tuple[dict, list[str]]:
    """``data`` (a mapping file's JSON, or None) with this run's decisions put in.

    An entry for the same name (in any case) is updated in its own form; a new
    name is added in lower case, as ``{"id": ..., "label": ...}``. An entry for
    another ontology's term is left alone, with a note."""
    data = {} if data is None else data
    entries = _entries(data)
    keys = {}
    for k in entries:
        keys.setdefault(str(k).strip().lower(), k)
    notes = []
    for name, term in decided.items():
        key = keys.get(name)
        if key is None:
            entries[name] = {"id": term["id"], "label": term["label"]}
            continue
        old = entries[key]
        old_id, _ = _entry_term(old)
        if old_id and not _is_ours(old_id):
            notes.append(f"{key!r} is matched to {old_id} in the mapping file, which was left as it is "
                         f"(the HPO term chosen for it, {term['id']}, is in the decision log)")
            continue
        if isinstance(old, dict):
            if normalise_curie(old_id or "") != term["id"]:
                old.pop("version", None)  # the release it came from is not known for the new term
            old.pop("curie", None)
            old["id"], old["label"] = term["id"], term["label"]
        elif isinstance(old, str):
            entries[key] = term["id"]
        else:
            entries[key] = {"id": term["id"], "label": term["label"]}
    return data, notes


def _with_label(suggester: Suggester, mem: dict, fallback: str) -> dict:
    """A remembered decision with its label: a mapping file may give only the id,
    and then the label is looked up (or the file's own label kept)."""
    if not mem.get("label"):
        found = suggester.resolve(mem["id"])
        mem["label"] = found.label if found else ""
    return {"id": mem["id"], "label": mem["label"] or fallback}


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
    ui.rule(f"[{index}/{total}] phenotype label: {label!r}   ({count} occurrence(s))")

    if existing_id:
        existing = suggester.resolve(existing_id)
        if existing and existing.label.lower() == label.lower():
            ui.ok(f"Already a valid HPO term: {existing.id}  {existing.label}")
        elif existing:
            ui.warn(
                f"Existing id {existing_id} resolves to {existing.id} '{existing.label}', "
                f"which differs from the label '{label}'."
            )
        elif suggester.last_error:
            ui.warn(f"Existing id {existing_id!r} could not be checked: {suggester.last_error}.")
        else:
            ui.warn(f"Existing id {existing_id!r} could not be validated against HPO.")

    query = label
    cands = suggester.suggest(query, limit=limit)
    error = suggester.last_error

    # Float a remembered decision for this label to the very top.
    mem = remembered.get(label.lower())
    if mem:
        shown = f"  {mem['label']}" if mem.get("label") else ""
        ui.ok(f"Remembered from earlier: {mem['id']}{shown}  (enter 'r' to reuse)")

    while True:
        ui.candidates(cands, error)
        raw = ui.prompt("Select [#, s words, h HP:id, r, k, x, ?, q]: ").strip()

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
            return {"action": "map", **_with_label(suggester, mem, label)}

        # search again
        if raw.startswith("s ") or raw == "s":
            query = raw[2:].strip() or ui.prompt("Search words: ").strip()
            if query:
                cands = suggester.suggest(query, limit=limit)
                error = suggester.last_error
            continue

        # explicit manual id  (h HP:0001657)  or a bare curie
        manual = None
        if raw.startswith("h "):
            manual = raw[2:].strip()
        elif normalise_curie(raw):
            # Only treat as a curie if it is NOT a small selection index.
            if not (raw.isdigit() and 1 <= int(raw) <= len(cands)):
                manual = raw
        if manual is not None:
            c = normalise_curie(manual)
            if not c:
                ui.err(f"{manual!r} is not a valid HPO id (expected HP:0000000).")
                continue
            resolved = suggester.resolve(c)
            if resolved:
                ui.ok(f"{resolved.id}  {resolved.label}")
                if _confirm(ui, "Use this term?"):
                    return {"action": "map", "id": resolved.id, "label": resolved.label}
                continue
            if suggester.last_error:
                ui.warn(f"Could not check {c}: {suggester.last_error}.")
            else:
                ui.warn(f"Could not validate {c} against HPO.")
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
    refs = pp.find_phenotypic_features(data)
    if not refs:
        ui.warn("No phenotypic features found in this file.")
        return {"file": str(path), "mapped": 0, "kept": 0, "skipped": 0, "total": 0}

    groups = pp.group_by_label(refs)
    ui.say(f"Found {len(refs)} phenotypic feature(s) across {len(groups)} distinct label(s).")

    decisions: list[dict] = []
    stop = False
    items = list(groups.items())
    for index, ((label, existing_id), group_refs) in enumerate(items, 1):
        if stop:
            break
        if args.auto_remembered and label.lower() in remembered:
            mem = _with_label(suggester, remembered[label.lower()], label)
            for r in group_refs:
                r.apply(mem["id"], mem["label"])
            ui.ok(f"[auto] {label!r} -> {mem['id']} {mem['label']}")
            decisions.append({"label": label, "id": mem["id"], "label_hpo": mem["label"],
                              "action": "map", "count": len(group_refs)})
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
        decisions.append({"label": label, "id": cid, "label_hpo": clabel,
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
        prog="hponorm",
        description="Interactively map free-text phenopacket phenotype labels to HPO terms.",
    )
    p.add_argument("files", nargs="+", help="Phenopacket / family JSON file(s).")
    p.add_argument("-o", "--out", help="Output path (only valid with a single input file).")
    p.add_argument("--in-place", action="store_true", help="Overwrite the input file(s).")
    p.add_argument("--backend", choices=["auto", "ols", "local"], default="auto",
                   help="Suggestion source (default: auto -> OLS online, else local).")
    p.add_argument("--hpo-file", help="Path to a local hp.obo or hp.json.")
    p.add_argument("--cache-dir", help="Where to cache the downloaded HPO file.")
    p.add_argument("--update", action="store_true", help="Re-download / re-parse HPO.")
    p.add_argument("--no-download", action="store_true",
                   help="Never download HPO (local backend must find a file).")
    p.add_argument("--no-online", action="store_true",
                   help="Do not use OLS even in auto mode.")
    p.add_argument("--limit", type=int, default=8, help="Suggestions shown per label.")
    p.add_argument("--mapping", help="JSON file of remembered label->term decisions to "
                                     "load and update across runs (labels in any case).")
    p.add_argument("--auto-remembered", action="store_true",
                   help="Auto-apply remembered labels without prompting.")
    p.add_argument("--no-color", action="store_true", help="Disable rich/colour output.")
    p.add_argument("--version", action="version", version="hponorm " + __version__)
    args = p.parse_args(argv)
    args._files = args.files

    ui = UI(color=not args.no_color)

    if args.out and len(args.files) > 1:
        ui.err("--out can only be used with a single input file.")
        return 2

    # Load remembered decisions, if any.
    remembered: dict[str, dict] = {}
    mapping_data = None
    mapping_ok = True
    if args.mapping and Path(args.mapping).exists():
        try:
            mapping_data = json.loads(Path(args.mapping).read_text(encoding="utf-8-sig"))
            remembered, others = read_mapping(mapping_data)
            ui.say(f"Loaded {len(remembered)} remembered mapping(s) from {args.mapping}."
                   + (f" ({others} entr{'y' if others == 1 else 'ies'} for other ontologies left as "
                      f"they are.)" if others else ""))
        except Exception as exc:
            mapping_ok = False
            ui.warn(f"Could not read mapping file {args.mapping} ({exc}); starting fresh, "
                    "and it will not be overwritten.")
    loaded = {k: dict(v) for k, v in remembered.items()}

    try:
        suggester = build_suggester(args, ui)
    except Exception as exc:
        ui.err(f"Could not initialise an HPO backend: {exc}")
        return 1

    summaries = []
    for f in args.files:
        path = Path(f)
        if not path.exists():
            ui.err(f"File not found: {path}")
            continue
        summaries.append(process_file(path, args, ui, suggester, remembered))

    # Persist remembered decisions for next time.
    if args.mapping and mapping_ok:
        decided = {k: v for k, v in remembered.items() if loaded.get(k) != v and v.get("label")}
        try:
            data, notes = update_mapping(mapping_data, decided)
            Path(args.mapping).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
            for note in notes:
                ui.warn(note)
            ui.say(f"Saved {len(remembered)} remembered mapping(s) to {args.mapping}.")
        except Exception as exc:
            ui.warn(f"Could not write mapping file: {exc}")

    ui.rule("Summary")
    for s in summaries:
        ui.say(f"{Path(s['file']).name}: {s['mapped']} mapped, {s['kept']} kept, "
               f"{s['skipped']} skipped (of {s['total']} feature(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
