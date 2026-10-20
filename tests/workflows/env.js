/* The Tools tab's tools (assets/js/tools.js), the workflow engine (assets/js/workflows.js) and the page's kinds of file
   (assets/js/page-wb.js: MG.app.pedKind) in Node, with a small stand-in for the page, and two file systems for them: one
   in memory, and one on disk, in which /home/user is a temporary folder and /data/examples the workbench's examples.

     const { load, MemFS, DiskFS } = require('./env.js');
     const MG = load(new MemFS());          // MG.workflowEngine, MG.toolsKit …
*/
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..', '..');
const HOME = '/home/user';
const EXAMPLES = '/data/examples';
const posixDir = (p) => p.replace(/\/[^/]*$/, '') || '/';

/** files in memory: {path: text} */
class MemFS {
  constructor(files = {}) {
    this.entries = new Map();
    this.mkdirp(HOME);
    for (const [p, text] of Object.entries(files)) this.writeText(p, text);
  }
  resolve(p) {
    return String(p).replace(/^~(?=\/|$)/, HOME);
  }
  pretty(p) {
    return p.startsWith(HOME) ? '~' + p.slice(HOME.length) : p;
  }
  exists(p) {
    return this.entries.has(this.resolve(p));
  }
  get(p) {
    return this.entries.get(this.resolve(p));
  }
  isDir(p) {
    const e = this.get(p);
    return !!(e && e.kind === 'dir');
  }
  mkdirp(p) {
    const parts = this.resolve(p).split('/').filter(Boolean);
    let cur = '';
    for (const x of parts) {
      cur += '/' + x;
      if (!this.entries.has(cur)) this.entries.set(cur, { kind: 'dir', mtime: Date.now() });
    }
  }
  writeText(p, text) {
    p = this.resolve(p);
    this.mkdirp(posixDir(p));
    this.entries.set(p, { kind: 'text', text: String(text), mtime: Date.now() });
  }
  async readText(p) {
    const e = this.get(p);
    if (!e || e.kind !== 'text') throw new Error('No such file: ' + p);
    return e.text;
  }
  remove(p) {
    p = this.resolve(p);
    for (const k of Array.from(this.entries.keys())) if (k === p || k.startsWith(p + '/')) this.entries.delete(k);
  }
  rename(a, b) {
    const e = this.get(a);
    this.remove(a);
    this.entries.set(this.resolve(b), e);
  }
}

/** files on disk: /home/user in a temporary folder, /data/examples the workbench's own (read-only) */
class DiskFS {
  constructor() {
    this.tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wf-'));
    fs.mkdirSync(path.join(this.tmp, 'home'), { recursive: true });
  }
  real(p) {
    p = this.resolve(p);
    if (p === HOME || p.startsWith(HOME + '/')) return path.join(this.tmp, 'home', p.slice(HOME.length));
    if (p === EXAMPLES || p.startsWith(EXAMPLES + '/')) return path.join(ROOT, 'data', 'examples', p.slice(EXAMPLES.length));
    return path.join(this.tmp, 'elsewhere', p);
  }
  virtual(real) {
    const home = path.join(this.tmp, 'home');
    if (real.startsWith(home)) return HOME + real.slice(home.length);
    const ex = path.join(ROOT, 'data', 'examples');
    if (real.startsWith(ex)) return EXAMPLES + real.slice(ex.length);
    return real;
  }
  resolve(p) {
    return String(p).replace(/^~(?=\/|$)/, HOME);
  }
  pretty(p) {
    return p.startsWith(HOME) ? '~' + p.slice(HOME.length) : p;
  }
  exists(p) {
    return fs.existsSync(this.real(p));
  }
  get(p) {
    const r = this.real(p);
    if (!fs.existsSync(r)) return undefined;
    if (fs.statSync(r).isDirectory()) return { kind: 'dir' };
    return { kind: 'text', text: fs.readFileSync(r, 'utf8'), mtime: fs.statSync(r).mtimeMs };
  }
  isDir(p) {
    const r = this.real(p);
    return fs.existsSync(r) && fs.statSync(r).isDirectory();
  }
  mkdirp(p) {
    fs.mkdirSync(this.real(p), { recursive: true });
  }
  writeText(p, text) {
    const r = this.real(p);
    fs.mkdirSync(path.dirname(r), { recursive: true });
    fs.writeFileSync(r, String(text));
  }
  async readText(p) {
    return fs.readFileSync(this.real(p), 'utf8');
  }
  remove(p) {
    fs.rmSync(this.real(p), { recursive: true, force: true });
  }
  rename(a, b) {
    fs.mkdirSync(path.dirname(this.real(b)), { recursive: true });
    fs.renameSync(this.real(a), this.real(b));
  }
  /** every file under /home/user: {virtual path: mtime and size} */
  snapshot() {
    const out = {};
    const walk = (d) => {
      for (const n of fs.readdirSync(d)) {
        const p = path.join(d, n);
        const st = fs.statSync(p);
        if (st.isDirectory()) walk(p);
        else out[this.virtual(p)] = st.mtimeMs + ':' + st.size + ':' + fs.readFileSync(p).length;
      }
    };
    walk(path.join(this.tmp, 'home'));
    return out;
  }
  /** a tool, as MG.toolsKit.runTool runs it, with the workbench's Python packages (python/): its commands one after
      another (or its call), with the paths in them on disk → {ok, code, stdout, stderr, files, result} */
  runner(MG) {
    const env = Object.assign({}, process.env, {
      PYTHONPATH: [path.join(ROOT, 'python')].concat(fs.readdirSync(path.join(ROOT, 'python', 'vendor')).filter((f) => f.endsWith('.whl')).map((f) => path.join(ROOT, 'python', 'vendor', f))).join(path.delimiter),
      HTTPS_PROXY: 'http://127.0.0.1:9', HTTP_PROXY: 'http://127.0.0.1:9', https_proxy: 'http://127.0.0.1:9', http_proxy: 'http://127.0.0.1:9'
    });
    const real = (x) => (typeof x === 'string' && (x.startsWith(HOME) || x.startsWith(EXAMPLES)) ? this.real(x) : x);
    const py = (code, args) => spawnSync('python3', ['-I', '-c', code].concat(args), { env, encoding: 'utf8', cwd: path.join(this.tmp, 'home'), maxBuffer: 64 * 1024 * 1024 });
    return async (tool, x) => {
      const before = this.snapshot();
      const res = { ok: true, code: 0, stdout: '', stderr: '', files: [] };
      if (tool.call) {
        const args = tool.call.args(x);
        const fn = tool.call.fn.replace(/^pedwb\.gui\./, '');
        const r = py('import sys, json\nsys.path[:0] = __import__("os").environ["PYTHONPATH"].split(__import__("os").pathsep)\nfrom pedwb import gui\nprint(json.dumps(getattr(gui, sys.argv[1])(**json.loads(sys.argv[2]))))', [fn, JSON.stringify(Object.fromEntries(Object.entries(args).map(([k, v]) => [k, real(v)])))]);
        if (r.status !== 0) Object.assign(res, { ok: false, code: 1, stderr: r.stderr, error: r.stderr.trim().split('\n').pop() });
        else res.result = JSON.parse(r.stdout);
      } else {
        const list = Array.isArray(tool.argv(x)[0]) ? tool.argv(x) : [tool.argv(x)];
        for (const argv of list) {
          const r = py('import sys, json\nsys.path[:0] = __import__("os").environ["PYTHONPATH"].split(__import__("os").pathsep)\nfrom pedwb import cli\nsys.exit(cli.run(json.loads(sys.argv[1])))', [JSON.stringify(argv.map(real))]);
          res.stdout += r.stdout || '';
          res.stderr += r.stderr || '';
          res.code = Math.max(res.code, r.status == null ? 1 : r.status);
        }
        res.ok = (tool.okCodes || [0]).includes(res.code);
      }
      const after = this.snapshot();
      res.files = Object.keys(after).filter((p) => before[p] !== after[p]);
      return res;
    };
  }
}

/** the tools and the engine, with fs as the page's files → MG */
function load(files) {
  for (const k of Object.keys(require.cache)) if (k.startsWith(path.join(ROOT, 'assets', 'js'))) delete require.cache[k];
  const store = new Map();
  const MG = {
    h: () => ({ appendChild() {}, append() {}, addEventListener() {}, classList: { add() {}, toggle() {} }, dataset: {}, style: {} }),
    esc: (s) => String(s),
    toast() {},
    icon: () => '',
    store: { get: (k, d) => (store.has(k) ? store.get(k) : d), set: (k, v) => store.set(k, v), remove: (k) => store.delete(k) },
    bus: { on() {}, emit() {} },
    path: { dirname: posixDir },
    kernels: {},
    config: {},
    actions: {},
    app: {}
  };
  global.window = { MG, matchMedia: () => ({ matches: false }), addEventListener() {}, WB_EXAMPLES: [], WB_STARTERS: [] };
  global.location = { href: 'http://localhost/' };
  global.CSS = { escape: (s) => String(s) };
  require(path.join(ROOT, 'assets', 'js', 'page-wb.js'));
  MG.app.fs = files;
  require(path.join(ROOT, 'assets', 'js', 'tools.js'));
  require(path.join(ROOT, 'assets', 'js', 'workflows.js'));
  return MG;
}

module.exports = { load, MemFS, DiskFS, ROOT, HOME, EXAMPLES };
