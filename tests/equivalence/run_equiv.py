"""The Tools tab shows, under each tool, the same work as a command and as Python. For each case that gen.js prints,
run the command (as the Tools tab and the terminal do) in one home folder and the Python in another, and compare the
files they write: they must be the same, apart from the time they were made. Both must succeed (the command with exit
status 0, or 1 for the tools whose 1 is an answer), unless the case says that both must fail. For the tools whose
result is what they print, the two must print the same.

    node tests/equivalence/gen.js assets/js/tools.js > cases.jsonl
    python3 tests/equivalence/run_equiv.py cases.jsonl
"""
import contextlib, io, json, os, shutil, sys, tempfile, traceback
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# (networkx, which PedNet needs, is kept as its wheel: Python imports it from there)
sys.path[:0] = [REPO + '/python'] + [os.path.join(REPO, 'python', 'vendor', f) for f in sorted(os.listdir(REPO + '/python/vendor')) if f.endswith('.whl')]
from pedwb import cli
CASES = sys.argv[1] if len(sys.argv) > 1 else 'cases.jsonl'
TMP = tempfile.mkdtemp(prefix='equiv-')
HA, HB = os.path.join(TMP, 'homeA'), os.path.join(TMP, 'homeB')
for d in (HA, HB):
    for sub in ('results', 'pedigrees', 'terms', 'pictures'):
        os.makedirs(os.path.join(d, sub))
EX = REPO + '/data/examples'
def sub(s, home):
    return s.replace('/home/user', home).replace('/data/examples', EX)
def snapshot(home):
    out = {}
    for dp, dn, fn in os.walk(home):
        for f in fn:
            p = os.path.join(dp, f)
            out[os.path.relpath(p, home)] = open(p, 'rb').read()
    return out
def norm(rel, data):
    if rel.endswith('.json'):
        try:
            doc = json.loads(data)
        except ValueError:
            return data
        def walk(o):
            if isinstance(o, dict):
                return {k: walk(v) for k, v in o.items() if k not in ('created',)}
            if isinstance(o, list):
                return [walk(v) for v in o]
            return o
        return json.dumps(walk(doc), sort_keys=True)
    return data
# the exit status 1 of these is an answer (the files differ; the MPED file has something to note), not a failure
ANSWER_CODES = {'diff', 'mped-info'}
# what these print is their result, and the Python prints the same as the command, apart from the home folder
SAME_OUTPUT = {'pednet-mode', 'pedinterp'}
def printed_as(out, home):
    return sub(out, home).replace(home, '~').rstrip()
ok = bad = 0
for line in open(CASES):
    c = json.loads(line)
    for f in c.get('files') or []:
        for h in (HA, HB):
            p = sub(f['path'], h)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, 'w').write(f['text'])
    before = {h: snapshot(h) for h in (HA, HB)}
    if c.get('idfile'):
        for h in (HA, HB):
            p = sub(c['idfile']['path'], h)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, 'w').write(c['idfile']['text'])
    for o in c['outputs']:
        for h in (HA, HB):
            os.makedirs(os.path.dirname(sub(o, h)), exist_ok=True)
    # the command
    codes = []
    out_a, err_a = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out_a), contextlib.redirect_stderr(err_a):
        for argv in c['argv']:
            codes.append(cli.run([sub(a, HA) for a in argv]))
    # the Python
    err_b = ''
    out_b = io.StringIO()
    try:
        with contextlib.redirect_stdout(out_b):
            exec(compile(sub(c['python'], HB), '<py>', 'exec'), {'__name__': '__main__'})
    except Exception:
        err_b = traceback.format_exc()
    after = {h: snapshot(h) for h in (HA, HB)}
    new_a = {k: v for k, v in after[HA].items() if before[HA].get(k) != v}
    new_b = {k: v for k, v in after[HB].items() if before[HB].get(k) != v}
    if c['id'] == 'filter':  # (the id list is the command's own input file)
        new_a = {k: v for k, v in new_a.items() if not k.endswith('-ids.txt')}
        new_b = {k: v for k, v in new_b.items() if not k.endswith('-ids.txt')}
    same_names = set(new_a) == set(new_b)
    diffs = [k for k in new_a if k in new_b and norm(k, new_a[k]) != norm(k, new_b[k])]
    allowed = (0, 1) if c['id'] in ANSWER_CODES else (0,)
    printed = c['id'] not in SAME_OUTPUT or printed_as(out_a.getvalue(), HA) == printed_as(out_b.getvalue(), HB)
    if c.get('fails'):
        good = any(x != 0 for x in codes) and bool(err_b) and not new_a and not new_b
    else:
        good = same_names and not diffs and not err_b and all(x in allowed for x in codes) and printed
    status = 'ok' if good else 'DIFF'
    if not printed:
        print('   printed differently:\n   command: %r\n   Python:  %r' % (out_a.getvalue()[:300], out_b.getvalue()[:300]))
    if status == 'ok':
        ok += 1
    else:
        bad += 1
    print(f"{status:4} {c['id']:14} codes={codes} files A={sorted(new_a)} B={sorted(new_b) if not same_names else '='} {('diffs=' + str(diffs)) if diffs else ''}")
    if err_b and (status != 'ok' or not c.get('fails')):
        print('   python error:', err_b.strip().splitlines()[-1])
    if c.get('fails') and status == 'ok':
        print('   (both stopped, as they should:', err_b.strip().splitlines()[-1][:120] + ')')
    if not c.get('fails') and any(x not in allowed for x in codes):
        print('   command stderr:', err_a.getvalue().strip()[-400:])
print(f'\n{ok} the same, {bad} different')
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if bad else 0)
