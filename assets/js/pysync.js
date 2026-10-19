/* =====================================================================
   The page's files and Python's files.

   The page's virtual file system (MG.app.fs) is the master copy: the
   terminal, the editor, the Studio tab and the Tools tab use it. Python
   (in its Web Worker) keeps a mirror of the home folder. Before Python
   runs, the files that changed are pushed to it; afterwards the files
   Python changed come back, with their modification times.

   MG.py.term('python' | 'pip', argv, ctx) runs a terminal command in
   Python (the pedigree programs are  python -m pedwb PROGRAM …).
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const HOME = () => (MG.app && MG.app.HOME) || '/home/user';
  const MAX_SYNC = 300 * 1024 * 1024; // larger files stay out of Python's copy

  const under = (p) => p === HOME() || p.startsWith(HOME() + '/');
  const fs = () => MG.app.fs;

  const pysync = {
    sent: new Map(),
    reset() {
      this.sent.clear();
    },
    /** files that changed since Python last saw them -> {changes, transfer} */
    async collect() {
      const F = fs();
      const files = [], dirs = [], removed = [], transfer = [];
      for (const [p, e] of F.entries) {
        if (!under(p)) continue;
        const s = this.sent.get(p);
        if (e.kind === 'dir') {
          if (!s || s.e !== 'dir') {
            dirs.push(p);
            this.sent.set(p, { e: 'dir' });
          }
          continue;
        }
        if (e.kind === 'virtual' || F.size(e) > MAX_SYNC) continue;
        if (s && s.e === e && s.m === e.mtime) continue;
        let bytes;
        try {
          bytes = await F.readBytes(p);
        } catch (err) {
          continue;
        }
        const copy = bytes.slice();
        transfer.push(copy.buffer);
        files.push({ path: p, bytes: copy.buffer, mtime: e.mtime || Date.now(), readonly: !!e.readonly });
        this.sent.set(p, { e, m: e.mtime });
      }
      for (const p of Array.from(this.sent.keys())) {
        if (!F.entries.has(p)) {
          removed.push(p);
          this.sent.delete(p);
        }
      }
      removed.sort((a, b) => b.length - a.length);
      dirs.sort((a, b) => a.length - b.length);
      return { changes: { files, dirs, removed }, transfer };
    },
    /** the files that changed → Python (kernel: the notebook's Python unless another is given – the IDE tab's) */
    async push(kernel) {
      const K = kernel || MG.kernels.peek('python');
      if (!K || K.state !== 'ready') return;
      const { changes, transfer } = await this.collect();
      if (changes.files.length || changes.dirs.length || changes.removed.length) K.worker.postMessage({ type: 'push', changes }, transfer);
    },
    /** files Python changed -> the page's file system. F0: the file system of the terminal command that ran Python
        (for the AI agent's commands it notes which paths they reached – see _onFsChange in assistant.js) */
    apply(ch, F0) {
      if (!ch) return;
      const F = F0 || fs();
      for (const p of ch.removed || []) {
        if (F.exists(p)) F.remove(p);
        for (const k of Array.from(this.sent.keys())) if (k === p || k.startsWith(p + '/')) this.sent.delete(k);
      }
      for (const d of ch.dirs || []) {
        if (!F.isDir(d)) {
          if (F.exists(d)) F.remove(d);
          F.mkdirp(d);
        }
        this.sent.set(d, { e: 'dir' });
      }
      for (const f of ch.files || []) {
        const bytes = new Uint8Array(f.bytes);
        const text = MG.looksText(f.path, bytes);
        const entry = text != null ? { kind: 'text', text, mtime: f.mtime, fresh: true } : { kind: 'blob', blob: new Blob([bytes]), size: bytes.length, mtime: f.mtime, fresh: true };
        if (f.readonly) entry.readonly = true;
        const old = F.get(f.path);
        if (old && old.mode) entry.mode = old.mode;
        F.put(f.path, entry);
        const stored = F.get(f.path);
        this.sent.set(f.path, { e: stored, m: stored.mtime });
      }
      if ((ch.files || []).length || (ch.removed || []).length) MG.bus.emit('py:files', { files: (ch.files || []).map((f) => f.path), removed: ch.removed || [] });
    }
  };

  const py = {
    kernel() {
      return MG.kernels ? MG.kernels.get('python') : null;
    },
    get versions() {
      const K = this.kernel();
      return K && K.versions;
    },
    /** messages from the worker that are not about notebook cells */
    onExtra(m, K) {
      const p = K.pending.get(m.id);
      if (m.type === 'term-out') {
        if (p && p.onTermOut) p.onTermOut(m.chunks);
      } else if (m.type === 'smk-shell') {
        K.worker.postMessage({ type: 'smk-shell-result', sid: m.sid, code: 1, changes: null });
      } else if (m.type === 'term-done') {
        pysync.apply(m.changes, p && p.fs);
        if (p) {
          K.pending.delete(m.id);
          p.resolve(m.code);
        }
      } else if (m.type === 'fs-changes') pysync.apply(m.changes);
      else if (m.type === 'pushed') {
        if (p) {
          K.pending.delete(m.id);
          p.resolve();
        }
      }
    },
    /** run `python ARGS` or `pip ARGS` from the terminal; returns the exit status. ctx.progName: the name to use in
        messages (the pedigree programs run as python -m pedwb PROGRAM) */
    async term(type, argv, ctx) {
      const K = this.kernel();
      const name = ctx.progName || type;
      if (!K) throw MG.shellUtil.userErr(`${name}: Python is not available on this page`);
      // A notebook cell's shell command (!… | …, a %%bash cell) that needs Python would wait for ever: Python is busy
      // running that cell. (A plain  !studio2ped …  line runs in the cell's Python instead: see _wb_inproc.)
      if (K.cellRunning && !ctx.term)
        throw MG.shellUtil.userErr(
          `${name}: this needs Python, which is busy running the notebook cell that asked for it. ` +
            `In a cell, put the command on a line of its own without | or >  (!${name} …), or call it from Python – or run it in the Terminal tab.`
        );
      // (in the terminal a second Ctrl+C – while Python starts, or while it runs – ends the command and restarts Python:
      // see inKernel in terminal.js)
      return ctx.term && ctx.term.inKernel ? ctx.term.inKernel(K, this._term(K, type, name, argv, ctx)) : this._term(K, type, name, argv, ctx);
    },
    async _term(K, type, name, argv, ctx) {
      if (K.state !== 'ready') {
        ctx.io.note('Starting Python in your browser (the first time this downloads about 10 MB, then your browser keeps it)…');
        if (ctx.term && ctx.term.statusEl) ctx.term.statusEl.innerHTML = '<span class="spinner small"></span> starting Python…';
      }
      try {
        await K.ensure();
      } catch (e) {
        throw MG.shellUtil.userErr('Python couldn’t start: ' + e.message);
      }
      // (Ctrl+C while Python was starting: the command does not run)
      if (ctx.term && ctx.term.cancelled) return 130;
      await pysync.push();
      const id = ++K.seq;
      const out = (text, stream, color) => {
        if (stream === 'out') ctx.out(text);
        else if (ctx.errc) ctx.errc(text, color);
        else ctx.err(text);
      };
      const cancelTimer = setInterval(() => {
        if (ctx.term && ctx.term.cancelled) K.worker.postMessage({ type: 'cancel', id });
      }, 200);
      if (ctx.term && ctx.term.statusEl) ctx.term.statusEl.innerHTML = `<span class="spinner small"></span> ${name} is running…`;
      const t0 = performance.now();
      try {
        const work = new Promise((resolve, reject) => {
          K.pending.set(id, {
            resolve,
            reject,
            fs: ctx.fs,
            onTermOut: (chunks) => chunks.forEach((c) => out(c.text, c.stream, c.color)),
            // (what Python is loading for the command: PedNet and NumPy, say, the first time pednet runs)
            onStatus: (text) => {
              ctx.io.note(text);
              if (ctx.term && ctx.term.statusEl) ctx.term.statusEl.innerHTML = `<span class="spinner small"></span> ${MG.esc(text.replace(/ \(.*$/, '…'))}`;
            }
          });
          K.worker.postMessage({ type, id, argv, cwd: ctx.fs.cwd, user: MG.user.login() });
        });
        const code = await work;
        MG.bus.emit('py:script', { argv, prog: ctx.progName || null, code, ok: code === 0, secs: (performance.now() - t0) / 1000, cwd: ctx.fs.cwd });
        return code;
      } catch (e) {
        // (stopped by force with Ctrl+C: the terminal has said so already – see stop in terminal.js)
        if (!(ctx.term && ctx.term.cancelled && /restarted/.test(e.message))) ctx.err(`${name}: ${e.message}\n`);
        return 1;
      } finally {
        clearInterval(cancelTimer);
      }
    }
  };

  MG.pysync = pysync;
  MG.py = py;
})();
