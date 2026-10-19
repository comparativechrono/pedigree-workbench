/* =====================================================================
   The workbench's Python ("kernel"): Pyodide in a Web Worker
   (py-worker.js). One Python serves the whole page: the notebooks, the
   terminal's python and pedigree programs, and the Tools tab, which
   calls the packages' functions by name (PyKernel.call). It starts the
   first time it is needed.

   Python keeps a copy of the home folder in its own file system: before
   code runs the files that changed are copied in, afterwards the files
   the code wrote are copied back (MG.pysync).

   Shell commands from notebooks (%%bash cells, and !commands that are
   not Python's own) run in a shell of their own on the page: the same
   commands as the terminal.
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const { bus } = MG;
  const CFG = MG.config;
  const abs = (u) => new URL(u, location.href).href;
  const HOME = () => (MG.app && MG.app.HOME) || '/home/user';

  /* the example data, which Python can read (read-only): set by page-wb.js */
  const examples = () => (MG.app && MG.app.exampleFiles) || [];

  /* ------------------------------------------------------------------
     a shell for notebooks: !commands and %%bash cells
     ------------------------------------------------------------------ */
  let nbShell = null;
  function shellFor(cwd) {
    if (!nbShell) {
      const view = Object.create(MG.app.fs);
      view.cwd = HOME();
      nbShell = new MG.Shell({ fs: view, term: null, env: { PS1: '$ ' } });
      nbShell._view = view;
    }
    const F = MG.app.fs;
    nbShell._view.cwd = cwd && F.isDir(cwd) ? cwd : HOME();
    return nbShell;
  }
  let shellQueue = Promise.resolve();
  /** run shell commands for a notebook. opts: {cwd, capture, onOutput(o)} → {code, out} */
  function runShell(cmd, opts = {}) {
    const job = shellQueue.then(async () => {
      const sh = shellFor(opts.cwd);
      let out = '';
      const emit = (name, text) => {
        if (!text) return;
        if (name === 'stdout' && opts.capture) out += text;
        else if (opts.onOutput) opts.onOutput({ type: 'stream', name, text });
      };
      const asText = (t) => (t instanceof Uint8Array ? `[${t.length.toLocaleString('en')} bytes of binary output, which you can send to a file with  > file]\n` : String(t));
      const io = {
        out: (t) => emit('stdout', asText(t)),
        err: (t) => emit('stderr', String(t)),
        colored: (t) => emit('stdout', String(t)),
        note: (t) => emit('stderr', String(t).endsWith('\n') ? String(t) : String(t) + '\n'),
        html: (h) => opts.onOutput && opts.onOutput({ type: 'display', mime: 'text/html', data: String(h) }),
        progress: () => {},
        clear: () => {}
      };
      let code = 1;
      try {
        code = await sh.exec(cmd, io, { command: true, name: 'bash' });
      } catch (e) {
        emit('stderr', String((e && e.message) || e) + '\n');
        code = 1;
      }
      bus.emit('nb:shell', { cmd, code });
      return { code: Number(code) || 0, out };
    });
    shellQueue = job.catch(() => {});
    return job;
  }

  /* ------------------------------------------------------------------
     Python
     ------------------------------------------------------------------ */
  class PyKernel {
    constructor(opts) {
      this.lang = 'python';
      this.label = 'Python';
      this.opts = opts;
      // (the Python of the IDE tab – pyide.js – is a PyKernel as well, with a file sync of its own and its own name in
      // the kernel:state and kernel:status events, so that the notebook does not take its news for its own)
      this.evLang = opts.evLang || 'python';
      this.seq = 0;
      this.pending = new Map();
      this.state = 'off';
      this.versions = null;
      this.readyPromise = null;
    }
    /** start Python (if it is not running) → a promise that resolves when it is ready */
    ensure() {
      if (this.state === 'off' || this.state === 'failed') this.start();
      return this.readyPromise;
    }
    /** the copy of the home folder that this Python keeps in step with the page's (pysync.js) */
    get files() {
      return this.opts.sync || MG.pysync;
    }
    start() {
      this.state = 'loading';
      this._status('Starting Python…');
      bus.emit('kernel:state', { lang: this.evLang, state: 'loading' });
      this.worker = new Worker(this.opts.workerUrl);
      let resolveReady, rejectReady;
      this.readyPromise = new Promise((res, rej) => {
        resolveReady = res;
        rejectReady = rej;
      });
      this.readyPromise.catch(() => {});
      this._rejectReady = rejectReady;
      this.files.reset();
      this.worker.onmessage = (ev) => {
        const m = ev.data;
        if (m.type === 'status') {
          if (!m.id) this._status(m.text);
          const p = this.pending.get(m.id);
          if (p && p.onStatus) p.onStatus(m.text);
        } else if (m.type === 'ready') {
          this.state = 'ready';
          this.versions = m.versions;
          this._status(null);
          resolveReady(m.versions);
          bus.emit('kernel:state', { lang: this.evLang, state: 'ready', versions: m.versions });
        } else if (m.type === 'background') {
          bus.emit('kernel:state', { lang: this.evLang, state: 'packages' });
        } else if (m.type === 'output') {
          const p = this.pending.get(m.id);
          if (p && p.onOutput) p.onOutput(JSON.parse(m.payload));
        } else if (m.type === 'done' || m.type === 'vars' || m.type === 'scanned' || m.type === 'called') {
          if (m.changes) this.files.apply(m.changes);
          if (m.type === 'done' && m.where) this.where = m.where;
          const p = this.pending.get(m.id);
          if (p) {
            this.pending.delete(m.id);
            p.resolve(m.type === 'vars' ? m.value : m);
          }
        } else if (m.type === 'nb-shell') {
          this._nbShell(m);
        } else if (m.type === 'fs-changes' && this.opts.sync) {
          this.files.apply(m.changes);
        } else if (['term-out', 'term-done', 'smk-shell', 'fs-changes', 'pushed'].includes(m.type)) {
          MG.py.onExtra(m, this);
        } else if (m.type === 'fatal') {
          if (m.stage === 'init') {
            this.state = 'failed';
            this._status('Python couldn’t start: ' + m.message, true);
            rejectReady(new Error(m.message));
            bus.emit('kernel:state', { lang: this.evLang, state: 'failed', message: m.message });
          } else {
            const p = this.pending.get(m.id);
            if (p) {
              this.pending.delete(m.id);
              p.reject(new Error(m.message));
            }
          }
        } else if (this.onMessage) {
          // (the other messages of a worker that does more than the notebook's: see pyide.js)
          this.onMessage(m);
        }
      };
      this.worker.onerror = (e) => {
        this.state = 'failed';
        this._status('Python stopped unexpectedly: ' + (e.message || 'error'), true);
        rejectReady(new Error(e.message || 'worker error'));
        for (const p of this.pending.values()) p.reject(new Error('Python stopped unexpectedly'));
        this.pending.clear();
        bus.emit('kernel:state', { lang: this.evLang, state: 'failed', message: e.message || '' });
      };
      this.worker.postMessage(
        Object.assign(
          {
            type: 'init',
            indexURL: this.opts.indexURL,
            preload: this.opts.preload,
            background: this.opts.background,
            files: this.opts.files,
            bundle: this.opts.bundle || null,
            analysis: this.opts.analysis || null,
            home: HOME(),
            user: MG.user.login()
          },
          // (what a worker that does more than the notebook's needs to know as well)
          typeof this.opts.init === 'function' ? this.opts.init() : this.opts.init || {}
        )
      );
    }
    _status(text, bad) {
      this.statusText = text;
      bus.emit('kernel:status', { lang: this.evLang, text, bad: !!bad });
    }
    ready() {
      return this.ensure();
    }
    _send(msg, handlers) {
      const id = ++this.seq;
      return new Promise((resolve, reject) => {
        this.pending.set(id, Object.assign({ resolve, reject }, handlers || {}));
        this.worker.postMessage(Object.assign({ id }, msg));
      });
    }
    /** run a cell. handlers: {onOutput(o), onStatus(text)}; cwd: the notebook's folder → {ok, secs} */
    async run(code, handlers, cwd) {
      await this.ensure();
      await this.files.push(this);
      // (while a cell runs, a shell command it starts must not ask this Python for anything: see MG.py.term)
      this.cellRunning = (this.cellRunning || 0) + 1;
      try {
        return await this._send({ type: 'run', code, cwd: cwd || HOME(), user: MG.user.login() }, handlers);
      } finally {
        this.cellRunning--;
      }
    }
    /** call a function of the packages by name with keyword arguments (JSON values), as the Tools tab does:
        call('pedwb.gui.inspect', {path: '~/x.json'}) → {ok, result, stdout, stderr, changes} or {ok: false, error, …}.
        Files the function wrote are in the page's files when the promise resolves. */
    async call(fn, args, opts = {}) {
      await this.ensure();
      await this.files.push(this);
      return this._send({ type: 'call', fn, args: JSON.stringify(args || {}), cwd: opts.cwd || HOME(), user: MG.user.login() }, opts.handlers);
    }
    async vars() {
      if (this.state !== 'ready') return [];
      return this._send({ type: 'vars' });
    }
    /** the files Python wrote → the page (before a shell command looks at them) */
    async sync() {
      if (this.state !== 'ready') return;
      await this._send({ type: 'scan' });
    }
    async _nbShell(m) {
      const p = this.pending.get(m.id);
      this.files.apply(m.changes);
      const r = await runShell(m.cmd, { cwd: m.cwd, capture: m.capture, onOutput: p && p.onOutput });
      const { changes, transfer } = await this.files.collect();
      this.worker.postMessage({ type: 'smk-shell-result', sid: m.sid, code: r.code, out: r.out, changes }, transfer);
    }
    restart() {
      if (this.state === 'off') return;
      try {
        this.worker.terminate();
      } catch (e) {
        /* already gone */
      }
      for (const p of this.pending.values()) p.reject(new Error('Python was restarted'));
      this.pending.clear();
      if (this._rejectReady) this._rejectReady(new Error('Python was restarted'));
      this.start();
      bus.emit('kernel:state', { lang: this.evLang, state: 'restarted' });
    }
    describe() {
      const v = this.versions || {};
      return `Python ${v.python || ''} (Pyodide ${v.pyodide || ''}) in your browser, with the pedigree packages`;
    }
  }

  /* ------------------------------------------------------------------
     the registry
     ------------------------------------------------------------------ */
  const made = {};
  /** the archives of the pedigree packages (python/build_bundle.py writes them, and their checksums into the page):
      the one Python unpacks when it starts, and the second (PedNet, PedGen, PedInterp), which it loads when first used */
  const bundleUrl = (which) => {
    const all = window.WB_BUNDLE || {};
    const b = which ? all[which] : all;
    if (which && !(b && b.archive)) return null;
    return abs('assets/py/' + (b.archive || 'pedigree-tools.zip')) + '?v=' + encodeURIComponent((b.sha256 || CFG.buildId || '1').slice(0, 16));
  };
  const kernels = {
    LANGS: {
      python: { label: 'Python', ext: '.py', cm: 'python', kernelspec: { name: 'python3', display_name: 'Python 3 (ipykernel)', language: 'python' }, language_info: { name: 'python', file_extension: '.py', mimetype: 'text/x-python' } }
    },
    /** the Python kernel, made (not started) the first time */
    get() {
      if (!made.python)
        made.python = new PyKernel({
          workerUrl: 'assets/js/py-worker.js?v=' + encodeURIComponent((window.WB_BUNDLE && window.WB_BUNDLE.sha256 ? window.WB_BUNDLE.sha256.slice(0, 8) : '') + (CFG.buildId || '1')),
          indexURL: abs(CFG.pyodideBase || 'https://cdn.jsdelivr.net/pyodide/v0.29.5/full/'),
          preload: CFG.pythonPreload || [],
          background: CFG.pythonBackground || [],
          files: examples().map((f) => ({ path: f.path, url: f.url, mtime: f.mtime, readonly: true })),
          bundle: bundleUrl(),
          analysis: bundleUrl('analysis')
        });
      return made.python;
    },
    /** the kernel if it was made, else null */
    peek() {
      return made.python || null;
    },
    /** what Python wrote: into the page's files (before a shell command runs) */
    async syncAll() {
      if (made.python && made.python.state === 'ready') await made.python.sync().catch(() => {});
    },
    runShell
  };
  MG.kernels = kernels;
  MG.PyKernel = PyKernel;
})();
