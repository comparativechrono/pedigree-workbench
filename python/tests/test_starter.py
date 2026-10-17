"""The notebook new users start from (data/starter/pedigree-tools.ipynb) runs from top to bottom."""
import contextlib
import io
import json
import os
import shlex
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
NOTEBOOK = os.path.join(REPO, "data", "starter", "pedigree-tools.ipynb")
EXAMPLES = os.path.join(REPO, "data", "examples")


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
