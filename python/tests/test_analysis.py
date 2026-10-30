"""Tests for the workbench's second archive: PedNet, PedGen and PedInterp, run as the terminal runs them.

They need NumPy (all three), pandas (PedGen and PedInterp) and OpenCV and Pillow (PedInterp), which the browser loads
from Pyodide; here they must be installed (pip install numpy pandas opencv-python-headless pillow). A test whose
packages aren't there is skipped, and says what it needs. networkx is imported from its wheel in vendor/.
"""
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.dirname(HERE)
REPO = os.path.dirname(PY)
DATA = os.path.join(HERE, "data")
EXAMPLES = os.path.join(REPO, "data", "examples")
SOURCES = json.load(open(os.path.join(PY, "vendor", "SOURCES.json"), encoding="utf-8"))
for _f in sorted(os.listdir(os.path.join(PY, "vendor"))):
    if _f.endswith(".whl") and os.path.join(PY, "vendor", _f) not in sys.path:
        sys.path.append(os.path.join(PY, "vendor", _f))

from pedwb import cli, gui  # noqa: E402

sys.path.insert(0, os.path.join(PY, "tools"))
from vendor_wheels import tree_digest  # noqa: E402


def needs(*modules):
    missing = [m for m in modules if importlib.util.find_spec(m) is None]
    if missing:
        raise unittest.SkipTest("needs " + ", ".join(missing))


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.run(argv)
    return code, out.getvalue(), err.getvalue()


def read_ped(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        if line.strip() and not line.startswith("#"):
            rows.append(line.split())
    return rows


def test_programs_and_what_they_need():
    # each program of the second archive says which packages of Pyodide's it needs, and each package names its program
    for prog in ("pednet", "pedgen", "pedinterp"):
        assert prog in cli.PROGRAMS and prog in cli.ABOUT and prog in cli.NEEDS
        assert "numpy" in cli.NEEDS[prog]
    assert sorted(cli.MODULES.values()) == ["pedgen", "pedinterp", "pednet"]
    for module, prog in cli.MODULES.items():
        assert cli.PROGRAMS[prog].split(".")[0] == module


def test_needs_cover_the_imports():
    # what a package imports as it is imported (at the top of its modules) must be loaded with it: one of the packages
    # of Pyodide's that pedwb.cli.NEEDS names for its program, networkx (in the archive), or the standard library
    if not hasattr(sys, "stdlib_module_names"):
        raise unittest.SkipTest("needs Python 3.10 or later")
    pyodide = {"numpy": "numpy", "pandas": "pandas", "cv2": "opencv-python", "PIL": "pillow"}
    for module, prog in cli.MODULES.items():
        for dirpath, _, files in os.walk(os.path.join(PY, module)):
            for name in (f for f in files if f.endswith(".py")):
                tree = ast.parse(open(os.path.join(dirpath, name), encoding="utf-8").read())
                for node in tree.body:
                    if isinstance(node, ast.Import):
                        tops = [a.name.split(".")[0] for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                        tops = [node.module.split(".")[0]]
                    else:
                        continue
                    for top in tops:
                        if top in sys.stdlib_module_names or top in (module, "networkx", "__future__"):
                            continue
                        assert pyodide.get(top) in cli.NEEDS[prog], f"{module}/{name} imports {top}, which NEEDS doesn't load for {prog}"


def test_copies_are_the_wheels():
    # the copies here are the wheels SOURCES.json names: networkx is its wheel, and each of the others is the files
    # that vendor_wheels.py copied from its wheel, unchanged since (their digest is recorded)
    for project, record in SOURCES.items():
        if record["folder"] == "vendor":
            path = os.path.join(PY, "vendor", record["wheel"])
            assert hashlib.sha256(open(path, "rb").read()).hexdigest() == record["sha256"], project
            continue
        assert os.path.exists(os.path.join(PY, record["folder"], "LICENSE")), project
        assert tree_digest(os.path.join(PY, record["folder"])) == record["files_sha256"], \
            f"python/{record['folder']} isn't what vendor_wheels.py copied from {record['wheel']}"
    versions = {"pednet": "pednet/__init__.py", "pedgen": "PedGen/_version.py", "pedinterp": "PedInterp/_version.py"}
    for project, path in versions.items():
        text = open(os.path.join(PY, path), encoding="utf-8").read()
        assert repr(SOURCES[project]["version"]) in text, project


def test_archive_holds_what_it_should():
    # (the archive is built by build_bundle.py: this checks the one in assets/py, when there is one)
    path = os.path.join(REPO, "assets", "py", "pedigree-analysis.zip")
    if not os.path.exists(path):
        raise unittest.SkipTest("no assets/py/pedigree-analysis.zip (python/ on its own)")
    names = zipfile.ZipFile(path).namelist()
    for package in ("pednet", "PedGen", "PedInterp", "networkx"):
        assert package + "/__init__.py" in names, package
    assert not [n for n in names if "/tests/" in n], "networkx's tests are left out"
    assert {"pednet/LICENSE", "PedGen/LICENSE", "PedInterp/LICENSE", "networkx/LICENSE.txt"} <= set(names)
    manifest = json.load(open(os.path.join(REPO, "assets", "py", "pedigree-tools.json"), encoding="utf-8"))
    assert manifest["analysis"]["sha256"] == hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_pednet_on_the_examples():
    needs("numpy")
    code, out, err = run(["pednet", "graph", os.path.join(EXAMPLES, "okafor.mped")])
    assert code == 0, err
    # the twins' parents are first cousins: a loop, and the children are inbred (F = 1/16)
    assert "a loop, from consanguinity: III-2, II-2, II-3, III-3" in out
    assert "IV-3 (F = 0.0625)" in out and "IV-4 is the brother of IV-3" in out
    code, out, err = run(["pednet", "mode", os.path.join(EXAMPLES, "lynch.ped")])
    assert code == 0 and out.startswith("Family FAM1: autosomal dominant"), out + err
    code, out, err = run(["pednet", "rank", os.path.join(EXAMPLES, "pednet", "dominant.ped"),
                          os.path.join(EXAMPLES, "pednet", "dominant.vcf")])
    assert code == 0, err
    first = [l for l in out.splitlines() if l.startswith("1.0")][0].split()
    assert first[1] == "var1" and first[4] == "PP1_Strong"


def test_pednet_kinship_table():
    needs("numpy")
    with tempfile.TemporaryDirectory() as tmp:
        table = os.path.join(tmp, "kinship.tsv")
        code, out, err = run(["pednet", "graph", os.path.join(EXAMPLES, "pednet", "consanguineous.ped"),
                              "--kinship", table])
        assert code == 0, err
        rows = [l.rstrip("\n").split("\t") for l in open(table, encoding="utf-8")]
        people = rows[0][1:]
        assert len(people) == 12 and [r[0] for r in rows[1:]] == people
        # a child of first cousins: kinship with themself (1 + F)/2 = 17/32
        assert float(rows[1 + people.index("IV-1")][1 + people.index("IV-1")]) == 0.53125


def test_pedgen_then_pednet():
    needs("numpy", "pandas")
    with tempfile.TemporaryDirectory() as tmp:
        code, out, err = run(["pedgen", "-m", "AR", "-g", "4", "-s", "7", "-d", tmp,
                              "--genotypes", os.path.join(tmp, "FAM1-genotypes.tsv")])
        assert code == 0 and out.startswith("Family FAM1: "), out + err
        # the same seed, the same family
        again = os.path.join(tmp, "again")
        run(["pedgen", "-m", "AR", "-g", "4", "-s", "7", "-d", again])
        assert read_ped(os.path.join(tmp, "FAM1.ped")) == read_ped(os.path.join(again, "FAM1.ped"))
        code, out, err = run(["pednet", "rank", os.path.join(tmp, "FAM1.ped"), os.path.join(tmp, "FAM1-genotypes.tsv")])
        assert code == 0 and "causal" in out, out + err
        # a family ID with a space would break the PED file
        code, out, err = run(["pedgen", "-f", "FAM 2", "-d", tmp])
        assert code == 1 and "no spaces" in err


def test_pedinterp_reads_the_example_picture():
    # the Lynch family's picture, read with the people numbered (as in the browser, where Tesseract can't run), is
    # the PED file studio2ped wrote from its drawing, apart from the family ID
    needs("numpy", "pandas", "cv2", "PIL")
    with tempfile.TemporaryDirectory() as tmp:
        code, out, err = run(["pedinterp", os.path.join(EXAMPLES, "lynch.png"), "--labels", "none", "-d", tmp, "-q"])
        assert code == 0, err
        assert [r[1:] for r in read_ped(os.path.join(tmp, "lynch.ped"))] == \
               [r[1:] for r in read_ped(os.path.join(EXAMPLES, "lynch.ped"))]
        # without Tesseract, the labels can't be read: the people are numbered, with a warning that says how to avoid it
        if importlib.util.find_spec("pytesseract") is None:
            code, out, err = run(["pedinterp", os.path.join(EXAMPLES, "lynch.png"), "-d", tmp, "-q"])
            assert code == 0 and "--labels none" in err


def test_pedinterp_reads_the_okafor_pictures_and_their_twins():
    # the Okafor family as Pedigree Studio saves it, and sketched roughly with its Draw tool (read --hand-drawn): the
    # people, parents and sexes of its MPED file, with those who have either condition affected. What is printed is
    # the PED file's table, and nothing more. The identical twins, which a PED file can't hold, are in the Pedigree
    # Studio drawing (--studio), which studio2ped reads back as the same family
    needs("numpy", "pandas", "cv2", "PIL")
    import studio2ped
    want = [r[1:5] + ["2" if "2" in r[5:] else "1"] for r in read_ped(os.path.join(EXAMPLES, "okafor.mped"))]
    for picture, options in (("okafor.png", []), ("okafor-sketch.png", ["--hand-drawn"])):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run(["pedinterp", os.path.join(EXAMPLES, picture), "--labels", "none", "-f", "OKAFOR",
                                  "-d", tmp, "--studio"] + options)
            assert code == 0, err
            assert [r[1:] for r in read_ped(os.path.join(tmp, "OKAFOR.ped"))] == want, picture
            assert "twin" not in out.lower() and "identical" not in out, out
            # (the drawing's people are the table's, in its order)
            read = read_ped(os.path.join(tmp, "OKAFOR.ped"))
            drawing = json.load(open(os.path.join(tmp, "OKAFOR.studio.json"), encoding="utf-8"))
            who = {p["id"]: read[k][1] for k, p in enumerate(drawing["persons"])}
            (twins,) = drawing["twinLinks"]
            assert (who[twins["child1Id"]], who[twins["child2Id"]], twins["type"]) == ("IV-3", "IV-4", "identical")
            (_, content), = studio2ped.convert(drawing, "BACK").files
            rows = [line.split("\t")[1:] for line in content.splitlines() if line and not line.startswith("#")]
            assert rows == [r[1:] for r in read], picture


def test_pedinterp_reads_who_has_died_and_the_proband():
    # with --marks, the Okafor family's five who have died and its proband (Chidi, IV-3), from the picture the Studio
    # saves, among the names and ages written under its symbols, and from the sketch (--hand-drawn). A PED file can't
    # hold them, so none is written, and --studio or --ga4gh must be given: the drawing and the GA4GH Pedigree have them
    needs("numpy", "pandas", "cv2", "PIL")
    died = {"I-1", "I-2", "II-2", "II-4", "III-4"}
    for picture, options in (("okafor.png", []), ("okafor-sketch.png", ["--hand-drawn"])):
        with tempfile.TemporaryDirectory() as tmp:
            args = ["pedinterp", os.path.join(EXAMPLES, picture), "--labels", "none", "-f", "OKAFOR", "-d", tmp,
                    "--marks"] + options
            code, out, err = run(args)
            assert code == 1 and "can't hold the marks" in err, picture
            code, out, err = run(args + ["--studio", "--ga4gh"])
            assert code == 0, err
            assert out.splitlines()[0].split()[-3:] == ["Deceased", "Proband", "Carrier"], out
            assert not os.path.exists(os.path.join(tmp, "OKAFOR.ped")), picture
            doc = json.load(open(os.path.join(tmp, "OKAFOR_ga4gh-pedigree.json"), encoding="utf-8"))
            status = {p["subject"]["id"]: p["subject"]["vitalStatus"]["status"] for p in doc["individuals"]}
            assert {who for who, s in status.items() if s == "DECEASED"} == died, picture
            assert doc["indexPatients"] == ["IV-3"], picture
            assert "is a carrier" not in doc["narrative"], picture
            drawing = json.load(open(os.path.join(tmp, "OKAFOR.studio.json"), encoding="utf-8"))
            assert sum(p["deceased"] for p in drawing["persons"]) == len(died), picture
            assert sum(p["proband"] for p in drawing["persons"]) == 1, picture


def test_pednet_reads_what_pedgen_and_pedinterp_make():
    # in Python, their tables go straight to PedNet
    needs("numpy", "pandas", "cv2", "PIL")
    import pednet
    from PedGen import pedigree_generator
    from PedInterp import pedigree_processing
    sim = pednet.pedigree_from_rows(pedigree_generator(max_children=3, FamilyID="SIM", mode="AD", generation_count=3,
                                                       seed=5))
    assert sim.family == "SIM" and sim.affected()
    read = pednet.pedigree_from_rows(pedigree_processing("LYNCH", image_path=os.path.join(EXAMPLES, "lynch.png"),
                                                         ocr=None))
    assert pednet.infer_mode(read).call == "AD"


def test_what_the_tools_tab_says_a_file_is():
    # (pedwb.gui.inspect, for a file's page in the Tools tab: no NumPy needed)
    vcf = gui.inspect(os.path.join(EXAMPLES, "pednet", "dominant.vcf"))
    assert (vcf["kind"], vcf["variants"], vcf["samples"]) == ("vcf", 6, 12) and "X" in vcf["chromosomes"]
    assert gui.inspect(os.path.join(EXAMPLES, "lynch.png"))["kind"] == "image"
    with tempfile.TemporaryDirectory() as tmp:
        table = os.path.join(tmp, "FAM1-genotypes.tsv")
        with open(table, "w", encoding="utf-8") as fh:
            fh.write("variant\tchrom\tpos\tref\talt\taf\t1\t2\t3\ncausal\t1\t1000\tA\tG\t0.1\t1\t0\t2\n")
        info = gui.inspect(table)
        assert (info["kind"], info["variants"], info["people"]) == ("variants", 1, 3)
    assert gui.inspect(os.path.join(EXAMPLES, "lynch.ped"))["kind"] == "ped"
