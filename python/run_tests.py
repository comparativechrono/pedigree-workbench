"""Run the tests without pytest: python run_tests.py [tests/test_x.py ...]

Every function whose name starts with ``test_`` in tests/test_*.py is run.
pytest runs the same files too. A test that raises unittest.SkipTest is
skipped, with its reason: the tests of PedNet, PedGen and PedInterp, when
NumPy, pandas or OpenCV isn't installed.
"""
import glob
import importlib.util
import os
import sys
import traceback
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def main(paths):
    paths = paths or sorted(glob.glob(os.path.join(HERE, "tests", "test_*.py")))
    passed = failed = skipped = 0
    for path in paths:
        spec = importlib.util.spec_from_file_location(os.path.splitext(os.path.basename(path))[0], path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for name in sorted(n for n in dir(mod) if n.startswith("test_")):
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            try:
                fn()
                passed += 1
                print("ok    {}::{}".format(os.path.basename(path), name))
            except unittest.SkipTest as reason:
                skipped += 1
                print("skip  {}::{} ({})".format(os.path.basename(path), name, reason))
            except Exception:
                failed += 1
                print("FAIL  {}::{}".format(os.path.basename(path), name))
                traceback.print_exc()
    print("\n{} passed, {} failed{}".format(passed, failed, ", {} skipped".format(skipped) if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
