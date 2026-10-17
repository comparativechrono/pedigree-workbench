/* =====================================================================
   Python in a Web Worker (Pyodide = CPython compiled to WebAssembly).

   One Python serves the whole workbench:
   · notebook cells (run one at a time, output streamed back);
     !command lines and %pip / %cd / %%writefile … work as in Jupyter:
     the pedigree programs (studio2ped, phenotk …) and python run here,
     in this Python; other shell commands are sent to the page, which
     runs them in its shell and answers with 'smk-shell-result';
   · the terminal's  python  command, and the pedigree programs, which
     the terminal runs as  python -m pedwb PROGRAM …;
   · the Tools tab, which calls functions of the packages ('call').

   The packages (python/ in the repository) come as one archive,
   assets/py/pedigree-tools.zip, unpacked into /lib/pedwb at the start.

   Files: the page's file system is the master copy. Before Python runs,
   the page pushes changed files here ('push'); afterwards this worker
   reports the files Python changed ('changes' in the 'done' message).
   Files keep their modification times on both sides.
   ===================================================================== */
/* global loadPyodide, importScripts */
'use strict';

let pyodide = null;
let runId = null;
let queue = Promise.resolve();

const post = (m, transfer) => self.postMessage(m, transfer || []);
const status = (text) => post({ type: 'status', text });

let HOME = '/home/user';
// the name of the person at the workbench: USER and LOGNAME (see setUser)
const NAME_OK = /^[A-Za-z_][A-Za-z0-9_.-]{0,31}$/;
let USER = 'user';
let ROOTS = [HOME];

/* ------------------------------------------------------------------
   output of notebook cells
   ------------------------------------------------------------------ */
const OUT_CAP = 400000;
let outChars = 0;
let outCut = false;
let sbuf = { name: null, text: '' };
function flushStream() {
  if (sbuf.text) post({ type: 'output', id: runId, payload: JSON.stringify({ type: 'stream', name: sbuf.name, text: sbuf.text }) });
  sbuf.text = '';
}
function resetOutput() {
  outChars = 0;
  outCut = false;
  sbuf = { name: null, text: '' };
}
self.nb_stream = (name, text) => {
  if (outCut || !text) return;
  if (outChars + text.length > OUT_CAP) {
    text = text.slice(0, Math.max(0, OUT_CAP - outChars)) + '\n… output cut after ' + OUT_CAP.toLocaleString('en') + ' characters (the cell carries on running; Restart stops it).\n';
    outCut = true;
  }
  outChars += text.length;
  if (sbuf.name !== name) flushStream();
  sbuf.name = name;
  sbuf.text += text;
  const nl = sbuf.text.lastIndexOf('\n');
  if (outCut || sbuf.text.length > 8192) flushStream();
  else if (nl >= 0) {
    const rest = sbuf.text.slice(nl + 1);
    sbuf.text = sbuf.text.slice(0, nl + 1);
    flushStream();
    sbuf.text = rest;
  }
};
self.nb_post_output = (json) => {
  flushStream();
  post({ type: 'output', id: runId, payload: json });
};

/* ------------------------------------------------------------------
   output of terminal commands (python and the pedigree programs)
   ------------------------------------------------------------------ */
let termId = null;
let tbuf = [];
let tTimer = null;
function termFlush() {
  if (tTimer) {
    clearTimeout(tTimer);
    tTimer = null;
  }
  if (tbuf.length) post({ type: 'term-out', id: termId, chunks: tbuf });
  tbuf = [];
}
self.term_emit = (text, stream, color) => {
  if (!text) return;
  const last = tbuf[tbuf.length - 1];
  if (last && last.stream === stream && last.color === (color || null)) last.text += text;
  else tbuf.push({ text, stream, color: color || null });
  if (tbuf.length > 40 || (last && last.text.length > 16000)) termFlush();
  else if (!tTimer) tTimer = setTimeout(termFlush, 30);
};

/* ------------------------------------------------------------------
   the bridge: Python asks the page to run a shell command
   (the !commands of notebook cells that are not Python's own)
   ------------------------------------------------------------------ */
const shellWaits = new Map();
let shellSeq = 0;
const cancelled = new Set();
/* a notebook cell's  !command  → {code, out} as JSON (out: the command's output when it is captured: x = !ls) */
self.nb_shell = (cmd, capture) =>
  new Promise((resolve) => {
    flushStream();
    const sid = ++shellSeq;
    shellWaits.set(sid, (m) => {
      applyChanges(m.changes);
      resolve(JSON.stringify({ code: m.code, out: m.out || '' }));
    });
    const ch = scan();
    post({ type: 'nb-shell', id: runId, sid, cmd, capture: !!capture, cwd: pyodide.FS.cwd(), changes: ch }, transferOf(ch));
  });

/* ------------------------------------------------------------------
   file sync
   ------------------------------------------------------------------ */
const known = new Map(); // path -> 'dir' | 'size:mtime'
const sigOf = (st) => st.size + ':' + (st.mtime instanceof Date ? st.mtime.getTime() : +st.mtime);
function dirnameOf(p) {
  const i = p.lastIndexOf('/');
  return i <= 0 ? '/' : p.slice(0, i);
}
function mkdirp(p) {
  try {
    pyodide.FS.mkdirTree(p);
  } catch (e) {
    /* exists */
  }
}
function removeTree(p) {
  const FS = pyodide.FS;
  let st;
  try {
    st = FS.lstat(p);
  } catch (e) {
    return;
  }
  if (FS.isDir(st.mode)) {
    for (const n of FS.readdir(p)) if (n !== '.' && n !== '..') removeTree(p + '/' + n);
    try {
      FS.rmdir(p);
    } catch (e) {}
  } else {
    try {
      FS.unlink(p);
    } catch (e) {}
  }
  for (const k of Array.from(known.keys())) if (k === p || k.startsWith(p + '/')) known.delete(k);
}
function applyChanges(ch) {
  if (!ch) return;
  const FS = pyodide.FS;
  for (const p of ch.removed || []) removeTree(p);
  for (const d of ch.dirs || []) {
    mkdirp(d);
    known.set(d, 'dir');
  }
  for (const f of ch.files || []) {
    mkdirp(dirnameOf(f.path));
    try {
      FS.chmod(f.path, 0o644);
    } catch (e) {}
    FS.writeFile(f.path, new Uint8Array(f.bytes));
    if (f.mtime) FS.utime(f.path, f.mtime, f.mtime);
    if (f.readonly) FS.chmod(f.path, 0o444);
    known.set(f.path, sigOf(FS.stat(f.path)));
  }
}
const SKIP_DIRS = new Set(['__pycache__', '.ipynb_checkpoints', '.cache']);
function scan() {
  const FS = pyodide.FS;
  const files = [];
  const dirs = [];
  const seen = new Set();
  const walk = (dir) => {
    let names;
    try {
      names = FS.readdir(dir);
    } catch (e) {
      return;
    }
    for (const n of names) {
      if (n === '.' || n === '..' || SKIP_DIRS.has(n)) continue;
      const p = dir + '/' + n;
      let st;
      try {
        st = FS.stat(p);
      } catch (e) {
        continue;
      }
      if (FS.isDir(st.mode)) {
        seen.add(p);
        if (known.get(p) !== 'dir') {
          known.set(p, 'dir');
          dirs.push(p);
        }
        walk(p);
      } else if (FS.isFile(st.mode)) {
        seen.add(p);
        const s = sigOf(st);
        if (known.get(p) !== s) {
          known.set(p, s);
          files.push({ path: p, bytes: FS.readFile(p).buffer, mtime: st.mtime instanceof Date ? st.mtime.getTime() : +st.mtime, readonly: (st.mode & 0o200) === 0 });
        }
      }
    }
  };
  for (const r of ROOTS) {
    try {
      FS.stat(r);
    } catch (e) {
      continue;
    }
    seen.add(r);
    walk(r);
  }
  const removed = [];
  for (const p of Array.from(known.keys())) {
    if (ROOTS.some((r) => p === r || p.startsWith(r + '/')) && !seen.has(p)) {
      removed.push(p);
      known.delete(p);
    }
  }
  removed.sort((a, b) => b.length - a.length);
  return { files, dirs, removed };
}
function transferOf(ch) {
  return (ch && ch.files ? ch.files.map((f) => f.bytes) : []).filter((b) => b instanceof ArrayBuffer);
}

/* ------------------------------------------------------------------
   Python set-up
   ------------------------------------------------------------------ */
const PY_SETUP = String.raw`
import sys, io, os, re, json, base64, ast, inspect, linecache, traceback, difflib, warnings, runpy, asyncio, time, shlex, builtins
os.environ.setdefault('MPLBACKEND', 'Agg')
from js import nb_post_output, nb_stream, term_emit, nb_shell

def _emit(obj):
    nb_post_output(json.dumps(obj))

class _Stream(io.TextIOBase):
    def __init__(self, name):
        self.name = name
    def writable(self):
        return True
    def write(self, s):
        if s:
            nb_stream(self.name, s)
        return len(s)
    def flush(self):
        pass
    def isatty(self):
        return False

class _TermStream(io.TextIOBase):
    def __init__(self, name):
        self.name = name
    def writable(self):
        return True
    def write(self, s):
        if s:
            term_emit(s, 'out' if self.name == 'stdout' else 'err', None)
        return len(s)
    def flush(self):
        pass
    def isatty(self):
        return False

_NB_OUT, _NB_ERR = _Stream('stdout'), _Stream('stderr')
sys.stdout, sys.stderr = _NB_OUT, _NB_ERR
warnings.simplefilter('once')
warnings.filterwarnings('ignore', category=ResourceWarning)
warnings.filterwarnings('ignore', message='.*non-interactive.*')
warnings.filterwarnings('ignore', message='.*FigureCanvasAgg.*')

# ---------------------------------------------------------------- modules that would start threads
# Python in a web page cannot start threads. SciPy's reader and writer of Matrix Market files (scipy.io.mmread and
# mmwrite – and what calls them, as scanpy.read_mtx) start them unless told to work alone ("thread constructor
# failed"): tell them so, as SciPy loads the module.
import importlib.abc, importlib.machinery
class _OneThread(importlib.abc.MetaPathFinder):
    SETTINGS = {'scipy.io._fast_matrix_market': ('PARALLELISM', 1)}
    def find_spec(self, name, path=None, target=None):
        if name not in self.SETTINGS:
            return None
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        if spec is None or spec.loader is None:
            return spec
        spec.loader = _OneThreadLoader(spec.loader, *self.SETTINGS[name])
        return spec
class _OneThreadLoader(importlib.abc.Loader):
    def __init__(self, inner, attr, value):
        self.inner, self.attr, self.value = inner, attr, value
    def __getattr__(self, k):
        return getattr(self.inner, k)
    def create_module(self, spec):
        return self.inner.create_module(spec)
    def exec_module(self, module):
        self.inner.exec_module(module)
        setattr(module, self.attr, self.value)
sys.meta_path.insert(0, _OneThread())

# ---------------------------------------------------------------- plots (matplotlib, when a cell uses it)
_MPL = [False]
def _mpl_setup():
    if _MPL[0] or 'matplotlib' not in sys.modules:
        return
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.figure import Figure
    except Exception:
        return
    _MPL[0] = True
    plt.rcParams.update({'figure.figsize': (6.4, 4.2), 'figure.dpi': 100, 'axes.spines.top': False,
                         'axes.spines.right': False, 'font.size': 10, 'axes.titlesize': 11})
    plt.show = lambda *a, **k: _flush_figures()
    Figure.show = lambda self, *a, **k: display(self)

def _png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=110, bbox_inches='tight')
    return base64.b64encode(buf.getvalue()).decode('ascii')

def _flush_figures():
    if 'matplotlib.pyplot' not in sys.modules:
        return
    plt = sys.modules['matplotlib.pyplot']
    for num in plt.get_fignums():
        fig = plt.figure(num)
        if fig.axes:
            _emit({'type': 'display', 'mime': 'image/png', 'data': _png(fig)})
    plt.close('all')

def _is_mpl(v):
    if 'matplotlib' not in sys.modules:
        return False
    from matplotlib.artist import Artist
    from matplotlib.container import Container
    if isinstance(v, (Artist, Container)):
        return True
    if 'numpy' in sys.modules:
        np = sys.modules['numpy']
        if isinstance(v, np.ndarray) and v.dtype == object and v.size and all(isinstance(x, Artist) for x in v.ravel()):
            return True
    if isinstance(v, (list, tuple)) and v and any(_is_mpl(x) for x in v):
        return True
    if isinstance(v, dict) and v and all(isinstance(x, list) and all(isinstance(y, Artist) for y in x) for x in v.values()):
        return True
    return False

# ---------------------------------------------------------------- rich output, display()
def _rich(o, result=False):
    if 'matplotlib' in sys.modules:
        from matplotlib.figure import Figure
        if isinstance(o, Figure):
            data = _png(o)
            sys.modules['matplotlib.pyplot'].close(o)
            return {'type': 'display', 'mime': 'image/png', 'data': data}
    for meth, mime in (('_repr_png_', 'image/png'), ('_repr_svg_', 'image/svg+xml'), ('_repr_html_', 'text/html'), ('_repr_markdown_', 'text/markdown')):
        f = getattr(o, meth, None)
        if callable(f) and not isinstance(o, type):
            try:
                d = f()
                if isinstance(d, tuple):
                    d = d[0]
                if d:
                    if mime == 'image/png':
                        d = base64.b64encode(d).decode('ascii') if isinstance(d, (bytes, bytearray)) else d
                    return {'type': 'display', 'mime': mime, 'data': d, 'result': result}
            except Exception:
                pass
    r = repr(o)
    if len(r) > 20000:
        r = r[:20000] + '\n… (output truncated)'
    return {'type': 'display', 'mime': 'text/plain', 'data': r, 'result': result}

def display(*objs, **kwargs):
    for o in objs:
        _emit(_rich(o))

# a small IPython.display, so that notebooks written for Jupyter run here
def _ipython_shim():
    import types
    ip = types.ModuleType('IPython')
    disp = types.ModuleType('IPython.display')
    class HTML:
        def __init__(self, data=None, url=None, filename=None):
            self.data = data if data is not None else (open(filename).read() if filename else '')
        def _repr_html_(self):
            return self.data
    class Markdown:
        def __init__(self, data=None, url=None, filename=None):
            self.data = data if data is not None else (open(filename).read() if filename else '')
        def _repr_markdown_(self):
            return self.data
    class SVG:
        def __init__(self, data=None, url=None, filename=None):
            self.data = data if data is not None else (open(filename).read() if filename else '')
        def _repr_svg_(self):
            return self.data
    class Image:
        def __init__(self, data=None, url=None, filename=None, format=None, width=None, height=None, embed=None):
            if filename or (isinstance(data, str) and os.path.exists(data)):
                with open(filename or data, 'rb') as fh:
                    data = fh.read()
            self.data = data
        def _repr_png_(self):
            return self.data
    class JSON:
        def __init__(self, data=None, **k):
            self.data = data
        def __repr__(self):
            return json.dumps(self.data, indent=2, default=str)
    def clear_output(wait=False):
        pass
    for k, v in dict(display=display, HTML=HTML, Markdown=Markdown, SVG=SVG, Image=Image, JSON=JSON, clear_output=clear_output).items():
        setattr(disp, k, v)
    ip.display = disp
    ip.get_ipython = lambda: None
    ip.__version__ = '0 (workbench shim)'
    sys.modules['IPython'] = ip
    sys.modules['IPython.display'] = disp
_ipython_shim()

def _no_input(prompt=''):
    raise RuntimeError("input() cannot ask for typing here. Put the value in the code instead, e.g.  name = 'TP53'")
builtins.input = _no_input

_G = {'__name__': '__main__', '__builtins__': __builtins__, 'display': display}

# ---------------------------------------------------------------- hints under errors
_DNAish = re.compile(r'^[ACGTUNacgtun]{2,}$')
def _user_names():
    return [k for k in _G if not k.startswith('_') and k not in ('display',)]

def _hints(e, code):
    """short, rule-based explanations of common mistakes (shown under the error)"""
    hints = []
    name = type(e).__name__
    msg = str(e)
    try:
        if name == 'NameError':
            m = re.search(r"name '([^']+)' is not defined", msg)
            if m:
                n = m.group(1)
                imports = {'pd': 'import pandas as pd', 'np': 'import numpy as np', 'plt': 'import matplotlib.pyplot as plt',
                           'sns': 'import seaborn as sns', 'nx': 'import networkx as nx', 'numpy': 'import numpy', 'pandas': 'import pandas',
                           'math': 'import math', 're': 'import re', 'os': 'import os', 'json': 'import json', 'requests': 'import requests',
                           'deque': 'from collections import deque', 'Counter': 'from collections import Counter',
                           'defaultdict': 'from collections import defaultdict', 'Phylo': 'from Bio import Phylo',
                           'AlignIO': 'from Bio import AlignIO', 'Seq': 'from Bio.Seq import Seq', 'SeqIO': 'from Bio import SeqIO',
                           'stats': 'from scipy import stats'}
                if n in ('true', 'false', 'none', 'TRUE', 'FALSE', 'NULL', 'null'):
                    hints.append(f"Python writes {'None' if n.lower() in ('none', 'null') else n.capitalize()} with a capital letter.")
                elif n in imports:
                    hints.append(f"'{n}' has to be imported first:  {imports[n]}")
                elif n in ('display',):
                    hints.append("display() is available here without importing it.")
                elif _DNAish.match(n):
                    hints.append(f"If {n} is a sequence, put it in quotes so that Python treats it as text:  '{n}'")
                else:
                    known = _user_names() + [k for k in dir(builtins) if not k.startswith('_')]
                    same = [k for k in known if k.lower() == n.lower() and k != n]
                    close = difflib.get_close_matches(n, known, n=3, cutoff=0.7)
                    if same:
                        hints.append(f"Names are case-sensitive: {n} is not the same as {same[0]}.")
                    elif 'Did you mean' in msg:
                        hints.append("Python suggests a similar name above: check the spelling – names are case-sensitive.")
                    elif close:
                        hints.append(f"Did you mean {', '.join(close)}?  (Names are case-sensitive.)")
                    else:
                        hints.append(f"'{n}' has not been created yet. Run the cell that defines it first – after a restart Python forgets everything. If it is meant to be text, put it in quotes: '{n}'")
        elif name == 'TypeError':
            if 'can only concatenate str' in msg or ("unsupported operand type(s) for +" in msg and 'str' in msg):
                hints.append("You are adding text and a number with +. Use an f-string instead:  f'GC: {gc}'  – or convert the number with str().")
            elif "unsupported operand type(s)" in msg and 'NoneType' in msg:
                hints.append("One of the values is None – often the result of a function that has no return line.")
            elif 'does not support item assignment' in msg and "'str'" in msg:
                hints.append("Text (a string) cannot be changed in place. Make a new string instead, e.g. with + or .replace().")
            elif "has no len()" in msg:
                hints.append("len() counts the items of a string, list, dictionary or table – not a number.")
            elif "'NoneType' object is not" in msg:
                hints.append("The value is None. A function without a return line gives None – did you forget  return …  in your function?")
            elif 'is not subscriptable' in msg:
                hints.append("Square brackets [ ] pick items out of strings, lists, dictionaries and tables – this value is not one of those.")
            elif 'is not callable' in msg:
                hints.append("Something you call with ( ) is not a function. Did you use the name of a function (len, str, list, max, print …) for a variable of your own? Rename it, then Restart and run the cells again.")
            elif 'missing' in msg and 'required positional argument' in msg:
                hints.append("The function needs more values between its brackets – check its definition for how many it takes.")
            elif 'list indices must be integers' in msg or 'string indices must be integers' in msg:
                hints.append("Lists and strings are numbered 0, 1, 2 …; use a whole number in the [ ]. To look things up by name, use a dictionary.")
            elif "'int' object is not iterable" in msg:
                hints.append("A for loop needs a collection to go through. To repeat n times use  for i in range(n):")
        elif name == 'IndexError':
            hints.append("Positions count from 0, so the last of n items is at n − 1 (or use -1). Check the length with len().")
        elif name == 'KeyError':
            key = str(e.args[0]) if e.args else ''
            found = False
            if 'pandas' in sys.modules:
                pd = sys.modules['pandas']
                for vn in _user_names():
                    v = _G.get(vn)
                    if isinstance(v, pd.DataFrame):
                        close = difflib.get_close_matches(key, [str(c) for c in v.columns], n=3, cutoff=0.5)
                        if close:
                            hints.append(f"'{key}' is not a column of {vn}. Did you mean: {', '.join(repr(c) for c in close)}?")
                            found = True
                            break
            if not found:
                for vn in _user_names():
                    v = _G.get(vn)
                    if isinstance(v, dict) and v:
                        close = difflib.get_close_matches(key, [str(k) for k in list(v.keys())[:2000]], n=3, cutoff=0.6)
                        if close:
                            hints.append(f"{key!r} is not a key of {vn}. Did you mean {', '.join(repr(c) for c in close)}? Keys must match exactly, including capitals.")
                            found = True
                            break
            if not found:
                hints.append(f"{key!r} was not found. Names are case-sensitive: check the spelling (for a table:  df.columns; for a dictionary:  d.keys()).")
        elif name == 'AttributeError':
            if "'str' object has no attribute 'append'" in msg:
                hints.append("Strings have no .append() – lists do. To add to a string, make a new one:  s = s + 'A'")
            elif "'NoneType' object has no attribute 'group'" in msg or "'NoneType' object has no attribute 'start'" in msg:
                hints.append("re.search() found nothing and returned None. Test it first:  if match:  …  before using match.group().")
            elif "'NoneType' object has no attribute" in msg:
                hints.append("The value is None – often the result of a function without a return line.")
            elif "has no attribute 'info'" in msg and 'networkx' in msg:
                hints.append("nx.info() was removed in NetworkX 3. Use  print(G)  or  G.number_of_nodes()  and  G.number_of_edges()")
            elif "'DataFrame' object has no attribute 'append'" in msg:
                hints.append("DataFrame.append() was removed in pandas 2. Use  pd.concat([df, other])  instead.")
        elif name in ('SyntaxError', 'IndentationError', 'TabError'):
            if 'expected an indented block' in msg:
                hints.append("The lines that belong to an if, for, while or def must be indented underneath it (4 spaces, or press Tab).")
            elif 'unexpected indent' in msg:
                hints.append("This line is indented but does not belong to a block – remove the spaces at its start.")
            elif 'unindent does not match' in msg or name == 'TabError':
                hints.append("The indentation does not line up. Use 4 spaces for each level, and the same number for lines in the same block.")
            elif "expected ':'" in msg:
                hints.append("Lines that start a block – if, elif, else, for, while, def – end with a colon  :")
            elif 'unterminated string' in msg or 'unterminated triple-quoted' in msg:
                hints.append("A quote is missing: text needs a quote mark at both ends, 'like this'.")
            elif 'was never closed' in msg or "unmatched ')'" in msg or "unmatched ']'" in msg or 'does not match opening' in msg:
                hints.append("Brackets must come in pairs: check that every ( [ { has its ) ] }.")
            elif "Maybe you meant '==' or ':=' instead of '='" in msg:
                hints.append("A single = stores a value; to compare two values use ==  (e.g.  if base == 'A':)")
            elif 'invalid character' in msg and any(q in msg for q in ('‘', '’', '“', '”')):
                hints.append("Curly quotes (copied from Word, a PDF or a web page) do not work in Python – type straight quotes ' or \" instead.")
            elif "'await' outside" in msg:
                hints.append("!commands and %magics only work at the top level of a cell, not inside a def. Call the program in its own cell, or use subprocess-free code.")
            elif 'Missing parentheses in call to' in msg:
                hints.append("In Python 3, print is a function:  print('hello')")
            elif 'invalid decimal literal' in msg:
                hints.append("A name cannot start with a number, and multiplication needs a *, e.g. 2*n not 2n.")
            elif '<-' in code and re.search(r'\w\s*<-', code):
                hints.append("<- is R. In Python a value is stored with =  (x = 5). Is this an R notebook's code? R code needs an R notebook.")
            else:
                hints.append("Python could not read this line. Check brackets, quotes, colons and the spelling near the ^ mark (the mistake is sometimes on the line before).")
        elif name == 'ZeroDivisionError':
            hints.append("Something was divided by zero – for example a percentage of an empty sequence (its len() is 0).")
        elif name == 'ValueError' and 'invalid literal for int()' in msg:
            hints.append("int() can only turn text made of digits into a number.")
        elif name in ('ModuleNotFoundError', 'ImportError'):
            m = re.search(r"No module named '([^'.]+)", msg)
            mod = m.group(1) if m else ''
            if mod in ('phenopackets', 'google', 'protobuf'):
                hints.append("The Phenopackets Python library (phenopackets, built on protobuf) is not part of the workbench. Read and write the files as JSON, or with phenopacket_toolkit and pedigree_ga4gh, which are here:  import pedigree_ga4gh as pg")
            elif mod in ('pysam', 'tensorflow', 'torch'):
                hints.append(f"{mod} cannot run in a web browser.")
            elif mod:
                hints.append(f"Packages that are part of Pyodide load by themselves when imported. {mod} is not one of them: try  %pip install {mod}  (it works for pure-Python packages), then run this cell again.")
        elif name == 'FileNotFoundError':
            hints.append(f"The notebook runs in {os.getcwd()}; relative paths start there. Your files are in {os.path.expanduser('~')} (~), the example pedigrees in /data/examples. Check the name in the Files tab.")
        elif name == 'UnboundLocalError':
            hints.append("Inside a function, this variable is both used and given a new value with =, so Python treats it as a new local variable. Give the new value another name.")
        elif name == 'RecursionError':
            hints.append("A function keeps calling itself without stopping.")
        elif name in ('ConnectionError', 'JsException', 'OSError') and ('Failed to fetch' in msg or 'NetworkError' in msg or 'XMLHttpRequest' in msg):
            hints.append("The request did not get through. Web services can only be called from a browser if they allow it (CORS) – EBI's Ontology Lookup Service and raw.githubusercontent.com do. Also check the internet connection.")
    except Exception:
        pass
    return hints

def _emit_error(e, code):
    tb = traceback.TracebackException.from_exception(e)
    frames = [f for f in tb.stack if f.filename == '<cell>']
    lines = []
    if frames:
        lines.append('Traceback (most recent call last):')
        shown = frames if len(frames) <= 12 else frames[:5] + [None] + frames[-5:]
        for f in shown:
            if f is None:
                lines.append(f'  … {len(frames) - 10} more lines like these …')
                continue
            lines.append(f'  Cell line {f.lineno}' + (f', in {f.name}' if f.name != '<module>' else ''))
            if f.line:
                lines.append('    ' + f.line.strip())
    if isinstance(e, SyntaxError):
        lines.append(f'  Cell line {e.lineno}')
        if e.text:
            lines.append('    ' + e.text.rstrip('\n'))
            if e.offset:
                lines.append('    ' + ' ' * (max(e.offset, 1) - 1) + '^')
    only = [l for l in ''.join(tb.format_exception_only()).strip().split('\n') if l.strip()]
    msg = only[-1].strip() if isinstance(e, SyntaxError) else '\n'.join(l.rstrip() for l in only)
    if len(msg) > 3000:
        msg = msg[:3000] + ' …'
    lines.append(msg)
    hints = _hints(e, code)
    if 'Did you mean' in msg:
        hints = [h for h in hints if not h.startswith('Did you mean')]
    _emit({'type': 'error', 'ename': type(e).__name__, 'evalue': str(e)[:2000], 'traceback': '\n'.join(lines),
           'lineno': (frames[-1].lineno if frames else getattr(e, 'lineno', None)), 'hints': hints})

# ---------------------------------------------------------------- Jupyter's ! and % commands
class _SList(list):
    """what  x = !ls  gives in Jupyter: a list of lines, with .s (one string) and .n (lines joined by newlines)"""
    @property
    def s(self):
        return ' '.join(self)
    @property
    def n(self):
        return '\n'.join(self)
    def grep(self, pattern):
        return _SList([l for l in self if re.search(pattern, l)])

def _wb_expand(cmd):
    """{expression} and $name are Python values, as in Jupyter ($$ is a $)"""
    def brace(m):
        try:
            return str(eval(m.group(1), _G))
        except Exception:
            return m.group(0)
    cmd = re.sub(r'(?<!\{)\{([^{}\n]+)\}(?!\})', brace, cmd)
    def dollar(m):
        n = m.group(1)
        return str(_G[n]) if n in _G else m.group(0)
    cmd = re.sub(r'(?<!\$)\$([A-Za-z_]\w*)', dollar, cmd)
    return cmd.replace('$$', '$')

# The pedigree programs and python itself run in this Python: the page's shell would have to ask this Python to run
# them while it is busy with the cell that asked, and wait for ever. A command with pipes or redirections goes to the
# page's shell, which refuses such commands with a note instead of waiting (see MG.py.term in pysync.js).
_WB_SHELLY = re.compile(r'[|;&<>\`]|\$\(')

def _wb_progs():
    try:
        from pedwb.cli import PROGRAMS
        return set(PROGRAMS)
    except Exception:
        return set()

def _wb_words(cmd):
    import glob as _glob
    out = []
    for w in shlex.split(cmd):
        if w.startswith('~'):
            w = os.path.expanduser(w)
        if any(c in w for c in '*?[') and _glob.glob(w):
            out.extend(sorted(_glob.glob(w)))
        else:
            out.append(w)
    return out

def _wb_python(args):
    """python ARGS in a cell's ! line: -c CODE, -m MODULE or a script, run here (it prints into the cell)"""
    old = sys.argv[:]
    try:
        if not args:
            print('python: give a script, -c "code" or -m module (or type the Python into a cell).', file=sys.stderr)
            return 2
        if args[0] in ('-V', '--version'):
            print('Python ' + sys.version.split()[0])
            return 0
        if args[0] == '-c':
            sys.argv[:] = ['-c'] + args[2:]
            exec(compile(args[1] if len(args) > 1 else '', '<string>', 'exec'), {'__name__': '__main__'})
        elif args[0] == '-m':
            sys.argv[:] = [args[1] if len(args) > 1 else ''] + args[2:]
            runpy.run_module(args[1], run_name='__main__', alter_sys=True)
        else:
            sys.argv[:] = list(args)
            runpy.run_path(args[0], run_name='__main__')
        return 0
    except SystemExit as e:
        c = e.code
        if c is None or isinstance(c, int):
            return c or 0
        print(c, file=sys.stderr)
        return 1
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        sys.argv[:] = old

def _wb_inproc(cmd, capture):
    """a ! line that is one of the pedigree programs, or python, with no pipes or redirections → its exit status, or
    None if the page's shell must run it"""
    if _WB_SHELLY.search(cmd):
        return None
    try:
        words = _wb_words(cmd)
    except ValueError:
        return None
    if not words:
        return None
    prog = words[0]
    if prog not in _wb_progs() and prog not in ('python', 'python3'):
        return None
    buf = io.StringIO()
    ctx = __import__('contextlib').redirect_stdout(buf) if capture else __import__('contextlib').nullcontext()
    with ctx:
        if prog in ('python', 'python3'):
            code = _wb_python(words[1:])
        else:
            from pedwb.cli import run as _run
            code = _run(words)
    return code, buf.getvalue()

async def _wb_sh(cmd, capture=False):
    cmd = _wb_expand(cmd)
    if re.match(r'^\s*(pip3?|python3? -m pip)\s+install\b', cmd):
        return await _wb_pip(re.sub(r'^\s*(pip3?|python3? -m pip)\s+install\b', '', cmd))
    here = _wb_inproc(cmd, capture)
    if here is not None:
        _G['_exit_code'] = here[0]
        return _SList(here[1].splitlines()) if capture else None
    r = json.loads(await nb_shell(cmd, bool(capture)))
    _G['_exit_code'] = r['code']
    if capture:
        return _SList(r['out'].splitlines())
    return None

async def _wb_pip(args):
    args = shlex.split(args)
    pkgs = [a for a in args if not a.startswith('-')]
    if not pkgs:
        print('Usage: %pip install PACKAGE …', file=sys.stderr)
        return
    import micropip
    for p in pkgs:
        print(f'Installing {p} …')
        try:
            await micropip.install(p)
        except Exception as e:
            print(f"Could not install {p}: {str(e).splitlines()[0][:300]}\n(Only packages that are pure Python, or that Pyodide has built for the browser, can be installed.)", file=sys.stderr)
            continue
    print('Done. (Packages are installed for this visit of the page; after a reload, install them again.)')

async def _wb_magic(name, args):
    if name == 'pip':
        parts = args.split(None, 1)
        if parts and parts[0] == 'install':
            return await _wb_pip(parts[1] if len(parts) > 1 else '')
        if parts and parts[0] in ('list', 'freeze'):
            import micropip
            for n, p in sorted(micropip.list().items()):
                print(f'{n}=={p.version}' if parts[0] == 'freeze' else f'{n:30} {p.version}')
            return
        print('This notebook supports  %pip install …  and  %pip list.', file=sys.stderr)
    elif name == 'cd':
        target = os.path.expanduser(args.strip() or '~')
        os.chdir(target)
        print(os.getcwd())
    elif name == 'pwd':
        return os.getcwd()
    elif name in ('ls', 'cat', 'mkdir', 'rm', 'cp', 'mv', 'less', 'head', 'tail'):
        return await _wb_sh(name + ' ' + args)
    elif name in ('matplotlib', 'config', 'load_ext', 'reload_ext', 'autoreload', 'xmode', 'precision'):
        return None
    elif name in ('time', 'timeit'):
        t0 = time.perf_counter()
        r = eval(compile(args, '<cell>', 'eval', flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT), _G) if args.strip() else None
        if inspect.iscoroutine(r):
            r = await r
        dt = time.perf_counter() - t0
        print(f'Wall time: {dt * 1000:.3g} ms' if dt < 1 else f'Wall time: {dt:.3g} s')
        return r
    elif name in ('who', 'whos'):
        names = sorted(_user_names())
        print('  '.join(names) if names else 'Interactive namespace is empty.')
    elif name == 'env':
        if '=' in args:
            k, v = args.split('=', 1)
            os.environ[k.strip()] = v.strip()
        elif args.strip():
            return os.environ.get(args.strip())
        else:
            return dict(os.environ)
    elif name == 'run':
        a = shlex.split(args)
        if not a:
            print('Usage: %run script.py', file=sys.stderr)
            return
        old = sys.argv[:]
        sys.argv[:] = a
        try:
            g = runpy.run_path(a[0], run_name='__main__')
            _G.update({k: v for k, v in g.items() if not k.startswith('__')})
        finally:
            sys.argv[:] = old
    else:
        print(f'%{name} is a Jupyter command this notebook does not have (it was skipped).', file=sys.stderr)

_TRIPLE = re.compile(r'"""|' + r"'''")
def _wb_transform(code):
    """Jupyter's ! and % lines → Python (await _wb_sh(…), await _wb_magic(…)); %%writefile / %%time / %%html cells"""
    lines = code.split('\n')
    first = lines[0].strip() if lines else ''
    if first.startswith('%%'):
        m = re.match(r'%%(\w+)\s*(.*)$', first)
        name, args = (m.group(1), m.group(2)) if m else ('', '')
        body = '\n'.join(lines[1:])
        if name == 'writefile':
            a = shlex.split(args)
            append = '-a' in a or '--append' in a
            path = [x for x in a if not x.startswith('-')]
            if not path:
                return "print('Usage: %%writefile FILE', file=__import__('sys').stderr)"
            p = path[0]
            word = 'Appending to' if append else ('Overwriting' if os.path.exists(p) else 'Writing')
            return f"with open({p!r}, {'a' if append else 'w'!r}) as _wb_fh:\n    _wb_fh.write({body + chr(10)!r})\nprint({word + ' ' + p!r})"
        if name == 'time':
            return "_wb_t0 = __import__('time').perf_counter()\n" + _wb_transform(body) + "\nprint(f\"Wall time: {__import__('time').perf_counter() - _wb_t0:.3g} s\")"
        if name == 'capture':
            # what the cell prints goes into a variable (%%capture out → out.stdout, out.stderr, out.show()), not under
            # the cell. (Plots and the output of !commands are still shown.)
            a = shlex.split(args)
            var = next((x for x in a if not x.startswith('-')), None)
            inner = _wb_transform(body) or 'pass'
            lines = ['_wb_co, _wb_ce = __import__("io").StringIO(), __import__("io").StringIO()',
                     'with __import__("contextlib").ExitStack() as _wb_stack:',
                     '    _wb_stack.enter_context(__import__("contextlib").redirect_stdout(_wb_co))' if '--no-stdout' not in a else '    pass',
                     '    _wb_stack.enter_context(__import__("contextlib").redirect_stderr(_wb_ce))' if '--no-stderr' not in a else '    pass']
            lines += ['    ' + l for l in inner.split('\n')]
            if var and var.isidentifier():
                lines.append(f'{var} = _WbCaptured(_wb_co.getvalue(), _wb_ce.getvalue())')
            return '\n'.join(lines)
        if name in ('html', 'HTML'):
            return f"display(__import__('sys').modules['IPython.display'].HTML({body!r}))"
        if name in ('markdown',):
            return f"display(__import__('sys').modules['IPython.display'].Markdown({body!r}))"
        if name in ('bash', 'sh', 'script', 'system'):
            return f"await _wb_sh({body!r})"
        return f"print({'%%' + name + ' is a Jupyter cell command this notebook does not have.'!r}, file=__import__('sys').stderr)"
    out = []
    in_str = False
    depth = 0  # open brackets: a line inside ( … ) that starts with % is the modulo operator, not a magic
    for line in lines:
        if not in_str and depth == 0:
            m = re.match(r'^(\s*)(?:([A-Za-z_][\w.]*)\s*=\s*)?([!%])(.*)$', line)
            if m and not (m.group(3) == '!' and m.group(4).startswith('=')):
                ind, var, kind, rest = m.group(1), m.group(2), m.group(3), m.group(4)
                call = None
                if kind == '!':
                    call = f"await _wb_sh({rest!r}, capture={bool(var)})"
                else:
                    mm = re.match(r'(\w+)\s*(.*)$', rest)
                    if mm:
                        call = f"await _wb_magic({mm.group(1)!r}, {mm.group(2)!r})"
                if call:
                    out.append(f"{ind}{var} = {call}" if var else f"{ind}{call}")
                    continue
        out.append(line)
        if len(_TRIPLE.findall(line)) % 2 == 1:
            in_str = not in_str
        if not in_str:
            bare = re.sub(r'#.*$', '', re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'|\"[^\"\\]*(?:\\.[^\"\\]*)*\"", '', line))
            depth = max(0, depth + sum(bare.count(c) for c in '([{') - sum(bare.count(c) for c in ')]}'))
    return '\n'.join(out)

_NB_CWD = [None]
class _WbCaptured:
    """what a %%capture cell printed"""
    def __init__(self, out, err):
        self.stdout, self.stderr, self.outputs = out, err, []
    def show(self):
        if self.stdout:
            print(self.stdout, end='')
        if self.stderr:
            print(self.stderr, end='', file=sys.stderr)
    def __call__(self):
        self.show()
    def __repr__(self):
        return f'<captured output: {len(self.stdout)} characters printed, {len(self.stderr)} as messages>'

_G.update({'_wb_sh': _wb_sh, '_wb_magic': _wb_magic, '_WbCaptured': _WbCaptured})

async def _nb_run(code, cwd=None):
    # a notebook starts in its own folder (as in Jupyter); %cd inside it is kept until another notebook runs
    if cwd and cwd != _NB_CWD[0]:
        _NB_CWD[0] = cwd
        if os.path.isdir(cwd):
            os.chdir(cwd)
    src = code
    try:
        if re.search(r'^\s*[!%]|^\s*[A-Za-z_][\w.]*\s*=\s*!', code, re.M):
            code = _wb_transform(code)
    except Exception as e:
        print(f'(The ! and % lines of this cell could not be read: {e})', file=sys.stderr)
    linecache.cache['<cell>'] = (len(code), None, code.splitlines(True), '<cell>')
    try:
        tree = ast.parse(code, filename='<cell>', mode='exec')
    except SyntaxError as e:
        _emit_error(e, src)
        return False
    last = None
    if tree.body and isinstance(tree.body[-1], ast.Expr) and not src.rstrip().endswith(';'):
        last = ast.Expression(tree.body.pop().value)
    flags = ast.PyCF_ALLOW_TOP_LEVEL_AWAIT
    try:
        r = eval(compile(tree, '<cell>', 'exec', flags=flags), _G)
        if inspect.iscoroutine(r):
            await r
        val = None
        if last is not None:
            val = eval(compile(last, '<cell>', 'eval', flags=flags), _G)
            if inspect.iscoroutine(val):
                val = await val
        _mpl_setup()
        _flush_figures()
        if val is not None and not _is_mpl(val):
            _G['_'] = val
            _emit(_rich(val, True))
        return True
    except BaseException as e:
        try:
            _mpl_setup()
            _flush_figures()
        except Exception:
            pass
        _emit_error(e, src)
        return False

def _nb_vars():
    out = []
    pd = sys.modules.get('pandas')
    np = sys.modules.get('numpy')
    for k, v in list(_G.items()):
        if k.startswith('_') or k in ('display',) or inspect.ismodule(v):
            continue
        if callable(v) and not (pd and isinstance(v, (pd.DataFrame, pd.Series))):
            continue
        t = type(v).__name__
        if pd and isinstance(v, pd.DataFrame):
            d = f'{v.shape[0]} rows × {v.shape[1]} columns'
        elif pd and isinstance(v, pd.Series):
            d = f'{len(v)} values'
        elif np and isinstance(v, np.ndarray):
            d = 'shape ' + ' × '.join(str(x) for x in v.shape)
        elif isinstance(v, (int, float, str, bool)):
            d = repr(v)[:60]
        elif isinstance(v, (list, tuple, dict, set)):
            d = f'{len(v)} items'
        else:
            d = type(v).__module__.split('.')[0]
        out.append({'name': k, 'type': t, 'desc': d})
    return json.dumps(out)

# ---------------------------------------------------------------- terminal commands
class _TermContext:
    """run a terminal command: its own cwd, output to the terminal, notebook state untouched"""
    def __init__(self, cwd):
        self.cwd = cwd
    def __enter__(self):
        self.old_cwd = os.getcwd()
        self.old = (sys.stdout, sys.stderr, sys.argv[:])
        sys.stdout, sys.stderr = _TermStream('stdout'), _TermStream('stderr')
        if self.cwd:
            os.chdir(self.cwd)
        return self
    def __exit__(self, *exc):
        sys.stdout, sys.stderr, sys.argv[:] = self.old[0], self.old[1], self.old[2]
        try:
            if 'matplotlib.pyplot' in sys.modules:
                sys.modules['matplotlib.pyplot'].close('all')
        except Exception:
            pass
        try:
            os.chdir(self.old_cwd)
        except OSError:
            os.chdir(os.environ.get('HOME', '/'))
        return False

def _term_traceback(e, path):
    tbe = traceback.TracebackException.from_exception(e)
    lines = ['Traceback (most recent call last):']
    home = os.environ.get('HOME', '/home')
    for fr in tbe.stack:
        if not (fr.filename == path or fr.filename.startswith(home)):
            continue
        lines.append(f'  File "{fr.filename}", line {fr.lineno}, in {fr.name}')
        if fr.line:
            lines.append('    ' + fr.line.strip())
    if isinstance(e, SyntaxError):
        lines = [f'  File "{e.filename}", line {e.lineno}']
        if e.text:
            lines.append('    ' + e.text.rstrip('\n'))
            if e.offset:
                lines.append('    ' + ' ' * (max(e.offset, 1) - 1) + '^')
    lines += [l.rstrip('\n') for l in tbe.format_exception_only()]
    return '\n'.join(l for l in lines if l.strip() or l == '') + '\n'

async def _py_script(argv, cwd):
    """python ARGS... ; returns the exit status"""
    with _TermContext(cwd):
        code_text, path = None, None
        args = list(argv)
        if not args:
            term_emit("Python 3 is here, but an interactive Python prompt (>>>) is not available in this terminal.\n"
                      "Use the Notebook tab to type Python line by line, or run a script:  python my_script.py\n", 'err', None)
            return 2
        if args[0] == '-c':
            if len(args) < 2:
                term_emit("Argument expected for the -c option\n", 'err', None)
                return 2
            code_text, path = args[1], '<string>'
            sys.argv[:] = ['-c'] + args[2:]
        elif args[0] == '-m':
            mod = args[1] if len(args) > 1 else ''
            if mod in ('pip',):
                term_emit("Use  pip install PACKAGE  (or %pip install in a notebook cell).\n", 'err', None)
                return 2
            sys.argv[:] = [mod] + args[2:]
            try:
                runpy.run_module(mod, run_name='__main__', alter_sys=True)
                return 0
            except SystemExit as e:
                return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
            except BaseException as e:
                term_emit(_term_traceback(e, '<module>'), 'err', None)
                return 1
        else:
            path = args[0]
            if not os.path.exists(path):
                term_emit(f"python: can't open file '{os.path.abspath(path)}': [Errno 2] No such file or directory\n", 'err', None)
                return 2
            if os.path.isdir(path):
                term_emit(f"python: '{path}' is a directory, cannot run it\n", 'err', None)
                return 2
            sys.argv[:] = args
            with open(path) as fh:
                code_text = fh.read()
            path = os.path.abspath(path)
        g = {'__name__': '__main__', '__file__': path, '__builtins__': __builtins__}
        try:
            code = compile(code_text, path, 'exec', flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            r = eval(code, g)
            if inspect.iscoroutine(r):
                await r
            return 0
        except SystemExit as e:
            c = e.code
            if c is None:
                return 0
            if isinstance(c, int):
                return c
            term_emit(str(c) + '\n', 'err', None)
            return 1
        except BaseException as e:
            term_emit(_term_traceback(e, path), 'err', None)
            return 1

async def _pip_term(argv):
    """the terminal's  pip  command: install (micropip), list, show"""
    with _TermContext(None):
        args = list(argv)
        if not args or args[0] in ('-h', '--help', 'help'):
            print('Usage:\n  pip install PACKAGE …   install pure-Python packages (or those Pyodide has built) for this visit\n  pip list                 the packages Python has now\n  pip show PACKAGE         about one package')
            return 0
        import micropip
        if args[0] == 'install':
            pkgs = [a for a in args[1:] if not a.startswith('-')]
            if not pkgs:
                print('ERROR: You must give at least one requirement to install', file=sys.stderr)
                return 1
            ok = 0
            for p in pkgs:
                try:
                    await micropip.install(p)
                    print(f'Successfully installed {p}')
                except Exception as e:
                    print(f'ERROR: Could not install {p}: {str(e).splitlines()[0][:300]}', file=sys.stderr)
                    ok = 1
            return ok
        if args[0] in ('list', 'freeze'):
            for n, p in sorted(micropip.list().items()):
                print(f'{n}=={p.version}' if args[0] == 'freeze' else f'{n:30} {p.version}')
            return 0
        if args[0] == 'show' and len(args) > 1:
            pk = micropip.list().get(args[1])
            if not pk:
                print(f'WARNING: Package(s) not found: {args[1]}', file=sys.stderr)
                return 1
            print(f'Name: {pk.name}\nVersion: {pk.version}\nLocation: {pk.source}')
            return 0
        print(f'pip {args[0]}: not available here (install, list, freeze and show are).', file=sys.stderr)
        return 1

# ---------------------------------------------------------------- the Tools tab: a function of the packages, called by name
async def _wb_call(fn, args_json, cwd):
    """fn: 'module.function'; args: a JSON object of keyword arguments → JSON {ok, result | error, stdout, stderr}"""
    import importlib, contextlib
    out, err = io.StringIO(), io.StringIO()
    old = os.getcwd()
    try:
        mod, _, name = fn.rpartition('.')
        f = getattr(importlib.import_module(mod), name)
        args = json.loads(args_json or '{}')
        if cwd and os.path.isdir(cwd):
            os.chdir(cwd)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            r = f(**args)
            if inspect.iscoroutine(r):
                r = await r
        return json.dumps({'ok': True, 'result': r, 'stdout': out.getvalue(), 'stderr': err.getvalue()}, default=str)
    except BaseException as e:
        return json.dumps({'ok': False, 'error': f'{type(e).__name__}: {e}', 'kind': type(e).__name__, 'message': str(e),
                           'traceback': traceback.format_exc()[-6000:], 'stdout': out.getvalue(), 'stderr': err.getvalue()})
    finally:
        try:
            os.chdir(old)
        except OSError:
            os.chdir(os.environ.get('HOME', '/'))
`;

const URLLIB_SETUP = `
def _wb_urllib():
    import io, email.message, urllib.request, urllib.response, urllib.error
    from js import XMLHttpRequest, Uint8Array
    from pyodide.ffi import to_js
    SKIP_OUT = {'user-agent', 'host', 'connection', 'content-length', 'accept-encoding'}
    SKIP_IN = {'content-encoding', 'content-length', 'transfer-encoding'}

    class _BrowserHTTP(urllib.request.BaseHandler):
        handler_order = 100

        def _open(self, req):
            xhr = XMLHttpRequest.new()
            xhr.open(req.get_method(), req.full_url, False)
            xhr.responseType = 'arraybuffer'
            for k, v in req.header_items():
                if k.lower() not in SKIP_OUT:
                    xhr.setRequestHeader(k, v)
            data = req.data
            if isinstance(data, str):
                data = data.encode()
            try:
                xhr.send(to_js(bytes(data)) if data is not None else None)
            except Exception as e:
                raise urllib.error.URLError(f'no answer from {req.host}: the site may not allow requests from web pages (CORS), or the internet connection is off') from None
            body = Uint8Array.new(xhr.response).to_bytes() if xhr.response else b''
            msg = email.message.Message()
            for line in str(xhr.getAllResponseHeaders() or '').strip().split('\\r\\n'):
                if ':' in line:
                    k, v = line.split(':', 1)
                    if k.strip().lower() not in SKIP_IN:
                        msg[k.strip()] = v.strip()
            if xhr.status == 0:
                raise urllib.error.URLError(f'no answer from {req.host}')
            if xhr.status >= 400:
                raise urllib.error.HTTPError(req.full_url, xhr.status, str(xhr.statusText), msg, io.BytesIO(body))
            resp = urllib.response.addinfourl(io.BytesIO(body), msg, str(xhr.responseURL or req.full_url), xhr.status)
            resp.msg = str(xhr.statusText)
            return resp

        http_open = https_open = _open

    urllib.request.install_opener(urllib.request.build_opener(_BrowserHTTP))

_wb_urllib()
del _wb_urllib
`;

async function init(m) {
  status('Downloading Python (Pyodide)…');
  try {
    importScripts(m.indexURL + 'pyodide.js');
  } catch (e) {
    throw new Error('Could not download Python from ' + m.indexURL + ' – check the internet connection.');
  }
  HOME = m.home || HOME;
  ROOTS = [HOME];
  USER = NAME_OK.test(m.user || '') ? m.user : 'user';
  pyodide = await loadPyodide({ indexURL: m.indexURL, env: { HOME, USER, LOGNAME: USER, MPLBACKEND: 'Agg' } });
  const pre = (m.preload || []).concat(['micropip']);
  status('Loading ' + pre.filter((x) => x !== 'micropip').join(', ') + '…');
  await pyodide.loadPackage(pre, { messageCallback: () => {}, errorCallback: () => {} });
  status('Setting up the files…');
  mkdirp(HOME);
  // (the home folder was /home/student before: a path written with that name still leads home)
  if (HOME !== '/home/student') {
    try {
      pyodide.FS.symlink(HOME, '/home/student');
    } catch (e) {
      /* there already */
    }
  }
  for (const f of m.files || []) {
    try {
      const r = await fetch(f.url);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const buf = new Uint8Array(await r.arrayBuffer());
      mkdirp(dirnameOf(f.path));
      pyodide.FS.writeFile(f.path, buf);
      if (f.mtime) pyodide.FS.utime(f.path, f.mtime, f.mtime);
      if (f.readonly) pyodide.FS.chmod(f.path, 0o444);
    } catch (e) {
      /* an example file that could not be fetched is simply not there */
    }
  }
  // the folders of the example data are read-only too: nothing new can be written into them (PermissionError)
  const lock = (d) => {
    let names;
    try {
      names = pyodide.FS.readdir(d);
    } catch (e) {
      return;
    }
    for (const n of names) {
      if (n === '.' || n === '..') continue;
      try {
        if (pyodide.FS.isDir(pyodide.FS.stat(d + '/' + n).mode)) lock(d + '/' + n);
      } catch (e) {}
    }
    try {
      pyodide.FS.chmod(d, 0o555);
    } catch (e) {}
  };
  if ((m.files || []).some((f) => f.readonly && f.path.startsWith('/data/'))) lock('/data');
  // the pedigree packages: one archive (python/build_bundle.py), unpacked where Python finds them
  const lib = '/lib/pedwb';
  mkdirp(lib);
  if (m.bundle) {
    status('Loading the pedigree packages…');
    const r = await fetch(m.bundle);
    if (!r.ok) throw new Error('Could not load the pedigree packages (' + m.bundle + ': HTTP ' + r.status + ')');
    pyodide.unpackArchive(await r.arrayBuffer(), 'zip', { extractDir: lib });
  }
  pyodide.FS.chdir(HOME);
  await pyodide.runPythonAsync(PY_SETUP);
  await pyodide.runPythonAsync(`import sys\nif '${lib}' not in sys.path: sys.path.insert(0, '${lib}')\nimport importlib\nimportlib.invalidate_caches()`);
  await pyodide.runPythonAsync('_mpl_setup()');
  // urllib.request (and what uses it: Bio.Entrez, pandas.read_csv(URL) …) has no HTTPS in the browser: it is given
  // one that asks the browser (a synchronous XMLHttpRequest – this is a worker). requests works without it.
  try {
    await pyodide.runPythonAsync(URLLIB_SETUP);
  } catch (e) {
    /* urllib stays as it is */
  }
  const versions = JSON.parse(
    await pyodide.runPythonAsync(
      "import sys, json, importlib\n" +
        "def _v(m):\n" +
        "    try:\n" +
        "        return importlib.import_module(m).__version__\n" +
        "    except Exception:\n" +
        "        return None\n" +
        "def _pk():\n" +
        "    try:\n" +
        "        from pedwb.gui import versions\n" +
        "        return versions()\n" +
        "    except Exception as e:\n" +
        "        return {'error': str(e)}\n" +
        "json.dumps({'python': sys.version.split()[0], 'pyodide': " + JSON.stringify(m.pyodideVersion || '') + ", 'packages': _pk()})"
    )
  );
  try {
    versions.pyodide = pyodide.version;
  } catch (e) {
    /* older Pyodide */
  }
  // (a worker that builds on this one – py-ide-worker.js, the Python of the IDE tab – finishes setting up here)
  if (typeof self.wbAfterInit === 'function') await self.wbAfterInit(m, versions);
  post({ type: 'ready', versions });
  if (m.background && m.background.length) {
    pyodide.loadPackage(m.background, { messageCallback: () => {}, errorCallback: () => {} }).then(() => post({ type: 'background', done: true })).catch(() => {});
  }
}

async function loadImports(code, id) {
  try {
    await pyodide.loadPackagesFromImports(code, {
      messageCallback: (msg) => {
        const mm = /Loading (.+)/.exec(msg);
        if (mm) post({ type: 'status', text: 'Loading ' + mm[1].slice(0, 80) + '…', id });
      },
      errorCallback: () => {}
    });
  } catch (e) {
    /* a missing package is reported by Python itself when the import runs */
  }
}

function doneWithChanges(msg) {
  let ch = { files: [], dirs: [], removed: [] };
  try {
    ch = scan();
  } catch (e) {
    console.error(e);
  }
  msg.changes = ch;
  post(msg, transferOf(ch));
}

/** USER and LOGNAME of Python: the name of the person at the workbench (or "user" for the AI agent's commands) */
function setUser(name) {
  if (!name || name === USER || !NAME_OK.test(name) || !pyodide) return;
  try {
    pyodide.runPython(`import os\nos.environ['USER'] = os.environ['LOGNAME'] = ${JSON.stringify(name)}`);
    USER = name;
  } catch (e) {
    /* (Python keeps the name it had) */
  }
}

async function run(m) {
  setUser(m.user);
  runId = m.id;
  resetOutput();
  const t0 = performance.now();
  // packages of the imports in the cell (and of  %pip install  lines, which micropip does itself)
  await loadImports(m.code.replace(/^\s*[!%].*$/gm, ''), m.id);
  const runner = pyodide.globals.get('_nb_run');
  let ok = false;
  try {
    ok = await runner(m.code, m.cwd || null);
  } finally {
    runner.destroy();
    flushStream();
  }
  // (where Python is now – %cd moves it – for the %%bash cells of this notebook, which run in the page)
  let where = null;
  try {
    where = { folder: m.cwd || null, cwd: pyodide.FS.cwd() };
  } catch (e) {
    where = null;
  }
  doneWithChanges({ type: 'done', id: m.id, ok: !!ok, secs: (performance.now() - t0) / 1000, where });
  runId = null;
}

async function termRun(m) {
  setUser(m.user);
  termId = m.id;
  tbuf = [];
  let code = 1;
  try {
    if (m.type === 'python') {
      const path = m.argv[0] && m.argv[0] !== '-c' && m.argv[0] !== '-m' ? m.argv[0] : null;
      let src = m.argv[0] === '-c' ? m.argv[1] || '' : '';
      if (path) {
        try {
          src = new TextDecoder().decode(pyodide.FS.readFile(m.cwd && !path.startsWith('/') ? m.cwd + '/' + path : path));
        } catch (e) {
          src = '';
        }
      }
      if (src) await loadImports(src, m.id);
      const f = pyodide.globals.get('_py_script');
      try {
        code = await f(pyodide.toPy(m.argv), m.cwd);
      } finally {
        f.destroy();
      }
    } else if (m.type === 'pip') {
      const f = pyodide.globals.get('_pip_term');
      try {
        code = await f(pyodide.toPy(m.argv));
      } finally {
        f.destroy();
      }
    }
  } catch (e) {
    self.term_emit(String((e && e.message) || e) + '\n', 'err', 'red');
    code = 1;
  }
  termFlush();
  cancelled.delete(m.id);
  doneWithChanges({ type: 'term-done', id: m.id, code: Number(code) || 0 });
  termId = null;
}

/** the Tools tab calls a function of the packages: {fn: 'pedwb.gui.inspect', args: {...}} → 'called' */
async function call(m) {
  setUser(m.user);
  const f = pyodide.globals.get('_wb_call');
  let r;
  try {
    r = JSON.parse(await f(m.fn, m.args || '{}', m.cwd || HOME));
  } finally {
    f.destroy();
  }
  doneWithChanges(Object.assign({ type: 'called', id: m.id }, r));
}

async function vars(m) {
  const f = pyodide.globals.get('_nb_vars');
  let v = '[]';
  try {
    v = f();
  } finally {
    f.destroy();
  }
  post({ type: 'vars', id: m.id, value: JSON.parse(v) });
}

async function handle(m) {
  try {
    if (m.type === 'init') await init(m);
    else if (m.type === 'push') {
      applyChanges(m.changes);
      if (m.id) post({ type: 'pushed', id: m.id });
    } else if (m.type === 'scan') doneWithChanges({ type: 'scanned', id: m.id });
    else if (m.type === 'run') await run(m);
    else if (m.type === 'python' || m.type === 'pip') await termRun(m);
    else if (m.type === 'call') await call(m);
    else if (m.type === 'vars') await vars(m);
    else if (typeof self.wbHandle === 'function') await self.wbHandle(m);
  } catch (e) {
    post({ type: 'fatal', id: m.id, stage: m.type, message: String((e && e.message) || e) });
  }
}

self.onmessage = (ev) => {
  const m = ev.data;
  if (m.type === 'smk-shell-result') {
    const w = shellWaits.get(m.sid);
    if (w) {
      shellWaits.delete(m.sid);
      w(m);
    }
    return;
  }
  if (m.type === 'cancel') {
    cancelled.add(m.id);
    return;
  }
  queue = queue.then(() => handle(m));
};
