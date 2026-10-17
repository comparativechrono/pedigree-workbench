"""Check documents the way phenopacket-tools (the GA4GH reference validator) does.

phenopacket-tools reads a JSON file into protobuf (rejecting unknown fields,
accepting proto or JSON field names), prints it back as JSON with enum and bool
defaults included, validates that against its v2 JSON schemas, and checks that
every ontology prefix used is declared in the top-level metaData.

This script repeats those steps in Python, using phenopacket-tools' own schema
files, which are not shipped with the workbench. Get them from
https://github.com/phenopackets/phenopacket-tools (the folder
phenopacket-tools-validator-jsonschema/src/main/resources/org/phenopackets/phenopackettools/validator/jsonschema/v2)
and install the Python packages jsonschema and referencing. Usage:

    python python/tools/official_check.py SCHEMA_DIR file.json [file.json ...]

For a GA4GH Pedigree, every individual is checked as a Phenopacket.
"""
import json
import sys
from pathlib import Path

from jsonschema import Draft201909Validator
from referencing import Registry, Resource

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CP = "classpath:/org/phenopackets/phenopackettools/validator/jsonschema/v2/"


def registry(schema_dir: Path) -> Registry:
    """the v2 schemas, and those beside the v2 folder that they refer to (vrsatile.json, for variants)"""
    reg = Registry()
    for folder, prefix in ((schema_dir, CP), (schema_dir.parent, CP.rsplit("v2/", 1)[0])):
        for f in folder.glob("*.json"):
            doc = json.loads(f.read_text())
            res = Resource.from_contents(doc)
            reg = reg.with_resource(prefix + f.name, res)
            if "$id" in doc:
                reg = reg.with_resource(doc["$id"], res)
    return reg


def proto_roundtrip(obj, message, schema_mod, problems, path=""):
    """Mimic JsonFormat.parser() then the phenopacket-tools printer."""
    if not isinstance(obj, dict):
        return obj
    out = {}
    for key, value in obj.items():
        f = schema_mod.field(message, key)
        if f is None:
            problems.append("parse error: unknown field '{}' at {}".format(key, path or "(top)"))
            continue
        t = f.type
        if schema_mod.is_message(t):
            if f.repeated:
                value = [proto_roundtrip(v, t, schema_mod, problems, "{}.{}[{}]".format(path, f.json, i))
                         for i, v in enumerate(value or [])]
                if not value:
                    continue
            elif value is None:
                continue
            else:
                value = proto_roundtrip(value, t, schema_mod, problems, "{}.{}".format(path, f.json))
        else:
            if f.repeated:
                if not value:
                    continue
            elif t == "string" and value == "":
                continue
            elif t in ("int32", "uint32", "uint64", "double") and value in (0, 0.0):
                continue
            elif t == "map" and not value:
                continue
        out[f.json] = value
    # the printer adds enum and bool fields at their default values
    for f in schema_mod.MESSAGES[message]:
        if f.json in out or f.repeated or f.oneof:
            continue
        if f.type == "bool":
            out[f.json] = False
        elif f.type.startswith("enum:"):
            out[f.json] = schema_mod.enum_values(f.type)[0]
    return out


def metadata_check(doc, message, schema_mod, problems):
    md = doc.get("metaData")
    if not md:
        return
    declared = {r.get("namespacePrefix") for r in md.get("resources", [])}
    import re
    for path, oc in schema_mod.ontology_classes(doc, message):
        curie = oc.get("id", "")
        fields = [x for x in re.split(r"[:_]", curie)]
        if len(fields) != 2:
            problems.append("MetaData: malformed ontology class ID '{}' at {}".format(curie, path))
        elif fields[0] not in declared:
            problems.append("MetaData: no ontology for '{}' in MetaData ({})".format(curie, path))


def check(doc, schema_dir: Path, reg: Registry):
    from pedigree_ga4gh import schema as S
    from pedigree_ga4gh.kindred import detect
    kind = detect(doc)
    targets = []
    if kind == "pedigree":
        for i, ind in enumerate(doc.get("individuals") or []):
            targets.append(("individuals[{}]".format(i), ind, "Phenopacket", "phenopacket-schema.json"))
    elif kind == "family":
        targets.append(("family", doc, "Family", "family-schema.json"))
    elif kind == "cohort":
        targets.append(("cohort", doc, "Cohort", "cohort-schema.json"))
    else:
        targets.append(("phenopacket", doc, "Phenopacket", "phenopacket-schema.json"))
    problems = []
    for label, obj, message, schema_file in targets:
        p = []
        printed = proto_roundtrip(obj, message, S, p)
        schema = json.loads((schema_dir / schema_file).read_text())
        v = Draft201909Validator(schema, registry=reg, format_checker=Draft201909Validator.FORMAT_CHECKER)
        for err in v.iter_errors(printed):
            p.append("schema: {} at {}".format(err.message, "/".join(str(x) for x in err.absolute_path)))
        metadata_check(printed, message, S, p)
        problems.extend("{}: {}".format(label, x) for x in p)
    return kind, problems


def main():
    schema_dir = Path(sys.argv[1])
    reg = registry(schema_dir)
    bad = 0
    for f in sys.argv[2:]:
        doc = json.loads(Path(f).read_text())
        kind, problems = check(doc, schema_dir, reg)
        status = "PASS" if not problems else "FAIL ({})".format(len(problems))
        print("{}  {}  [{}]".format(status, f, kind))
        for p in problems[:12]:
            print("    " + p)
        if len(problems) > 12:
            print("    ... {} more".format(len(problems) - 12))
        bad += bool(problems)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
