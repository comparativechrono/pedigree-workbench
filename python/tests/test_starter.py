"""The notebooks new users start from (data/starter/*.ipynb) run from top to bottom."""
import contextlib
import importlib.util
import io
import json
import os
import shlex
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
NOTEBOOK = os.path.join(REPO, "data", "starter", "pedigree-tools.ipynb")
ANALYSIS = os.path.join(REPO, "data", "starter", "pedigree-analysis.ipynb")
EXAMPLES = os.path.join(REPO, "data", "examples")
VENDOR = os.path.join(REPO, "python", "vendor")


def run_notebook(path):
    """runs the code cells in one namespace, with the paths of the workbench changed to these → what they printed"""
    from pedwb import cli
    nb = json.load(open(path, encoding="utf-8"))
    with tempfile.TemporaryDirectory() as home:
        fix = lambda s: s.replace("/data/examples", EXAMPLES).replace("/home/user", home).replace("~/", home + "/")
        g = {"__name__": "__main__"}
        out = io.StringIO()
        for cell in nb["cells"]:
            if cell["cell_type"] != "code":
                continue
            src = fix("".join(cell["source"]))
            with contextlib.redirect_stdout(out):
                py = []
                for line in src.split("\n"):
                    if line.startswith("!"):
                        if py:
                            exec(compile("\n".join(py), "<cell>", "exec"), g)
                            py = []
                        assert cli.run(shlex.split(line[1:])) == 0, line
                    else:
                        py.append(line)
                if py:
                    exec(compile("\n".join(py), "<cell>", "exec"), g)
        return out.getvalue(), {os.path.relpath(os.path.join(d, f), home) for d, _, fs in os.walk(home) for f in fs}


def test_analysis_notebook_runs():
    if not os.path.exists(ANALYSIS):
        raise unittest.SkipTest("no data/starter (python/ on its own, without the web page)")
    missing = [m for m in ("numpy", "pandas", "cv2", "PIL") if importlib.util.find_spec(m) is None]
    if missing:
        raise unittest.SkipTest("needs " + ", ".join(missing))
    for f in sorted(os.listdir(VENDOR)):
        if f.endswith(".whl") and os.path.join(VENDOR, f) not in sys.path:
            sys.path.append(os.path.join(VENDOR, f))
    text, files = run_notebook(ANALYSIS)
    assert "a loop, from consanguinity" in text
    assert "autosomal dominant" in text
    assert "the same as lynch.ped: True" in text
    assert "twins: [['IV-3', 'IV-4', 'MZ']]" in text
    assert "results/SIM1.ped" in files


def test_starter_notebook_runs():
    from pedwb import cli
    if not os.path.exists(NOTEBOOK):
        return  # (python/ on its own, without the web page)
    nb = json.load(open(NOTEBOOK, encoding="utf-8"))
    with tempfile.TemporaryDirectory() as home:
        fix = lambda s: s.replace("/data/examples", EXAMPLES).replace("/home/user", home).replace("~/", home + "/")
        g = {"__name__": "__main__"}
        out = io.StringIO()
        for cell in nb["cells"]:
            if cell["cell_type"] != "code":
                continue
            src = fix("".join(cell["source"]))
            with contextlib.redirect_stdout(out):
                py = []
                for line in src.split("\n"):
                    if line.startswith("!"):
                        if py:
                            exec(compile("\n".join(py), "<cell>", "exec"), g)
                            py = []
                        assert cli.run(shlex.split(line[1:])) == 0, line
                    else:
                        py.append(line)
                if py:
                    exec(compile("\n".join(py), "<cell>", "exec"), g)
        text = out.getvalue()
        assert "No problems found." in text
        assert "in a file from studio2ga4gh 0.3" in text
        assert os.path.exists(os.path.join(home, "results", "okafor-nb.mped"))
