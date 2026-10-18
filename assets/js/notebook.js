/* =====================================================================
   The Notebook tab: Jupyter-style notebooks in Python.

   · Each notebook is an .ipynb file among the user's files (normally in
     ~/notebooks), saved as it is edited and run – outputs included – so
     it is kept in the browser and can be downloaded and opened in
     Jupyter, JupyterLab, VS Code or Google Colab.
   · Code cells and text (Markdown) cells; Jupyter's keyboard keys.
   · Python runs in Pyodide (kernels.js), with the pedigree packages
     (studio2ped, phenopacket_toolkit, pedigree_ga4gh …) ready to import.
     A cell whose first line is %%bash runs in the workbench's shell (the
     terminal's commands); !command lines run the pedigree programs and
     python in the notebook's own Python, other commands in the shell.
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const { h, esc, bus, toast, store } = MG;
  const LANGS = () => MG.kernels.LANGS;

  /* ------------------------------------------------------------------
     small helpers
     ------------------------------------------------------------------ */
  const uid = () => Math.random().toString(36).slice(2, 10);
  const srcText = (x) => (Array.isArray(x) ? x.join('') : x == null ? '' : String(x));
  const toLines = (s) => {
    const a = String(s).split(/(?<=\n)/);
    return a.length === 1 && a[0] === '' ? [] : a;
  };
  const stripAnsi = (s) => String(s).replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '');
  /** \r and \b in what a program printed, as a terminal (and Jupyter) shows them – PLINK 2 counts 0% … 99% over itself:
      \r goes back to the start of the line, \b one character back, and what follows is written over what was there */
  const inPlace = (s) => {
    if (!/[\r\b]/.test(s)) return s;
    let done = '', line = [], at = 0;
    for (const ch of s) {
      if (ch === '\r') at = 0;
      else if (ch === '\b') at = Math.max(0, at - 1);
      else if (ch === '\n') { done += line.join('') + '\n'; line = []; at = 0; }
      else line[at++] = ch;
    }
    return done + line.join('');
  };
  const BASH = /^\s*%%(bash|sh|script\s+(ba)?sh)\b[^\n]*\n?/;

  /* HTML from cells (tables, rich output) and Markdown are cleaned before they are shown:
     code from the internet or an AI model could otherwise put scripts or look-alike page elements here. */
  const NUMERIC = /^[\s\-+−]*[\d.,]+(e[-+]?\d+)?\s*%?$|^(NaN|nan|NA|None|True|False|TRUE|FALSE|–|-|inf|-inf|Inf|-Inf)$/i;
  function cleanHtml(html, opts = {}) {
    if (!window.DOMPurify) return esc(html);
    return window.DOMPurify.sanitize(html, Object.assign({ FORBID_TAGS: ['style', 'form', 'input', 'button', 'textarea', 'select', 'iframe', 'script'], FORBID_ATTR: ['style'] }, opts));
  }
  function htmlOutput(html) {
    const box = h('div.nb-html', { html: cleanHtml(html) });
    box.querySelectorAll('td').forEach((td) => {
      if (!NUMERIC.test(td.textContent.trim())) td.classList.add('txt');
    });
    box.querySelectorAll('a[href]').forEach((a) => {
      a.target = '_blank';
      a.rel = 'noopener';
    });
    return box;
  }
  function renderMarkdown(src) {
    let html;
    try {
      html = window.marked ? window.marked.parse(src, { gfm: true, breaks: false }) : '<pre>' + esc(src) + '</pre>';
    } catch (e) {
      html = '<pre>' + esc(src) + '</pre>';
    }
    const box = h('div', { html: cleanHtml(html, { FORBID_TAGS: ['style', 'form', 'input', 'button', 'textarea', 'select', 'iframe', 'script'] }) });
    box.querySelectorAll('a[href]').forEach((a) => {
      if (/^https?:/.test(a.getAttribute('href'))) {
        a.target = '_blank';
        a.rel = 'noopener';
      }
    });
    return box.innerHTML;
  }
  MG.renderMarkdownSafe = renderMarkdown;

  /* ------------------------------------------------------------------
     .ipynb ⇄ the notebook's model
     cell: {id, type: 'code'|'markdown'|'raw', source, outputs[], count, meta}
     output: {type:'stream', name, text} | {type:'display', mime, data, result?, bundle?} | {type:'error', ename, evalue, traceback, hints}
     ------------------------------------------------------------------ */
  const MIME_ORDER = ['image/png', 'image/jpeg', 'image/svg+xml', 'text/html', 'text/markdown', 'text/latex', 'application/json', 'text/plain'];
  function outputFromJupyter(o) {
    if (o.output_type === 'stream') return { type: 'stream', name: o.name === 'stderr' ? 'stderr' : 'stdout', text: stripAnsi(srcText(o.text)) };
    if (o.output_type === 'error') return { type: 'error', ename: o.ename || 'Error', evalue: o.evalue || '', traceback: stripAnsi((o.traceback || []).join('\n')), hints: [] };
    if (o.output_type === 'display_data' || o.output_type === 'execute_result') {
      const data = o.data || {};
      const mime = MIME_ORDER.find((m) => data[m] != null) || Object.keys(data)[0];
      if (!mime) return null;
      let d = data[mime];
      if (mime === 'application/json') d = JSON.stringify(d, null, 2);
      else d = srcText(d);
      return { type: 'display', mime: mime === 'application/json' || mime === 'text/latex' ? 'text/plain' : mime, data: mime === 'image/png' || mime === 'image/jpeg' ? d.replace(/\s+/g, '') : d, result: o.output_type === 'execute_result', bundle: data };
    }
    return null;
  }
  function outputToJupyter(o, count) {
    if (o.type === 'stream') return { output_type: 'stream', name: o.name, text: toLines(o.text) };
    if (o.type === 'error') return { output_type: 'error', ename: o.ename || 'Error', evalue: o.evalue || '', traceback: String(o.traceback || '').split('\n') };
    if (o.type === 'display') {
      let data;
      if (o.bundle) data = o.bundle;
      else {
        data = {};
        data[o.mime] = o.mime === 'image/png' || o.mime === 'image/jpeg' ? o.data : toLines(o.data);
        if (o.mime !== 'text/plain') data['text/plain'] = [o.mime.startsWith('image/') ? '<Figure>' : o.mime === 'text/html' ? '<table>' : '<output>'];
      }
      const out = { output_type: o.result ? 'execute_result' : 'display_data', data, metadata: {} };
      if (o.result) out.execution_count = count == null ? null : count;
      return out;
    }
    return null;
  }
  /** an .ipynb text → {lang, meta, cells, warning} */
  function parseIpynb(text) {
    const nb = JSON.parse(text);
    if (!nb || !Array.isArray(nb.cells)) throw new Error('This file isn’t a Jupyter notebook, because it has no cells.');
    const meta = nb.metadata || {};
    const ks = meta.kernelspec || {};
    const li = meta.language_info || {};
    const langName = String(ks.language || li.name || ks.name || 'python').toLowerCase();
    let lang = 'python', warning = '';
    if (!/python/.test(langName)) warning = `This notebook was written for ${ks.display_name || langName}. The Pedigree workbench runs Python notebooks, so it has been opened as a Python notebook and code in other languages won’t run.`;
    const cells = nb.cells.map((c) => ({
      id: c.id || uid(),
      type: c.cell_type === 'markdown' ? 'markdown' : c.cell_type === 'raw' ? 'raw' : 'code',
      source: srcText(c.source),
      outputs: c.cell_type === 'code' ? (c.outputs || []).map(outputFromJupyter).filter(Boolean) : [],
      count: c.execution_count == null ? null : c.execution_count,
      meta: c.metadata || {},
      attachments: c.attachments
    }));
    return { lang, meta, cells, warning };
  }
  /** the model → an .ipynb object (nbformat 4.5) */
  function buildIpynb(lang, cells, meta) {
    const L = LANGS()[lang] || LANGS().python;
    const K = MG.kernels.peek(lang);
    const li = Object.assign({}, L.language_info);
    if (K && K.versions) li.version = lang === 'r' ? K.versions.r : K.versions.python;
    const m = Object.assign({}, meta || {}, { kernelspec: L.kernelspec, language_info: li });
    m.workbench = Object.assign({}, (meta && meta.workbench) || {}, { made_with: 'Pedigree workbench (in the browser)' });
    return {
      cells: cells.map((c) => {
        const base = { cell_type: c.type, id: c.id || uid(), metadata: c.meta || {}, source: toLines(c.source) };
        if (c.type === 'markdown' && c.attachments) base.attachments = c.attachments;
        if (c.type !== 'code') return base;
        return Object.assign(base, { execution_count: c.count == null ? null : c.count, outputs: (c.outputs || []).map((o) => outputToJupyter(o, c.count)).filter(Boolean) });
      }),
      metadata: m,
      nbformat: 4,
      nbformat_minor: 5
    };
  }
  /** for other tabs: make a notebook from a list of cells [{type, source, outputs?}] */
  function makeIpynb(lang, cells, meta) {
    return buildIpynb(lang, cells.map((c) => Object.assign({ id: uid(), type: 'code', source: '', outputs: [], count: null, meta: {} }, c)), meta);
  }
  MG.nbformat = { parse: parseIpynb, build: buildIpynb, make: makeIpynb, outputFromJupyter, outputToJupyter, renderMarkdown };

  /* ------------------------------------------------------------------
     one open notebook
     ------------------------------------------------------------------ */
  class NotebookView {
    constructor(app, path, doc) {
      this.app = app;
      this.path = path;
      this.lang = doc.lang;
      this.meta = doc.meta || {};
      this.cells = [];
      this.current = null;
      this.warning = doc.warning || '';
      this.el = h('div.nb-cells', { tabindex: '-1' });
      this.el.addEventListener('click', (e) => {
        const c = this.cells.find((x) => x.el.contains(e.target));
        if (c && !e.target.closest('button, a, .CodeMirror, input')) this.select(c, false, true);
      });
      this.endEl = h('div.nb-end');
      const addCode = h('button.tbtn', { type: 'button', html: MG.icon('plus') + '<span>Code</span>', title: 'Add a code cell at the end' });
      const addText = h('button.tbtn', { type: 'button', html: MG.icon('plus') + '<span>Text</span>', title: 'Add a text (Markdown) cell at the end' });
      addCode.addEventListener('click', () => this.addCell({ type: 'code' }, { after: this.cells[this.cells.length - 1], focus: true }));
      addText.addEventListener('click', () => this.addCell({ type: 'markdown' }, { after: this.cells[this.cells.length - 1], focus: true, edit: true }));
      this.endEl.append(addCode, addText);
      this.el.appendChild(this.endEl);
      doc.cells.forEach((c) => this.addCell(c, { noSave: true }));
      if (!this.cells.length) this.addCell({ type: 'code' }, { noSave: true });
      this.select(this.cells[0], false);
      this.dirty = false;
    }
    get kernel() {
      return MG.kernels.get(this.lang);
    }
    get folder() {
      return MG.path.dirname(this.path);
    }

    /* ---------------- cells ---------------- */
    addCell(data, opts = {}) {
      const c = {
        id: data.id || uid(),
        type: data.type || 'code',
        outputs: (data.outputs || []).slice(),
        count: data.count == null ? null : data.count,
        meta: data.meta || {},
        attachments: data.attachments,
        el: null,
        cm: null,
        rendered: data.type === 'markdown' && !opts.edit
      };
      const runBtn = h('button.nb-runbtn', { type: 'button', title: 'Run this cell (Shift+Enter)', 'aria-label': 'Run this cell', html: MG.icon('play') });
      runBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.select(c, false);
        this.runCell(c);
      });
      const countEl = h('span.nb-count', c.type === 'code' ? (c.count ? `[${c.count}]` : '[ ]') : '');
      const edBox = h('div.nb-editor');
      const mdView = h('div.nb-md', { title: 'Double-click to edit' });
      mdView.addEventListener('dblclick', () => this.editMarkdown(c));
      const tools = h('div.nb-tools');
      const tb = (icon, title, fn) => {
        const b = h('button.icon-btn', { type: 'button', title, 'aria-label': title, html: MG.icon(icon) });
        b.addEventListener('click', (e) => {
          e.stopPropagation();
          this.select(c, false);
          fn(e);
        });
        tools.appendChild(b);
        return b;
      };
      tb('dots', 'More: change, move, copy or delete this cell', (e) => {
        MG.popmenu(e.currentTarget, [
          c.type === 'code' ? ['text', 'Make it a text (Markdown) cell', () => this.setType(c, 'markdown')] : ['code', 'Make it a code cell', () => this.setType(c, 'code')],
          ['arrowUp', 'Move up', () => this.move(c, -1)],
          ['arrowDown', 'Move down', () => this.move(c, 1)],
          ['plus', 'Add a code cell below', () => this.addCell({ type: 'code' }, { after: c, focus: true })],
          ['plus', 'Add a text cell below', () => this.addCell({ type: 'markdown' }, { after: c, focus: true, edit: true })],
          ['copy', 'Duplicate', () => this.addCell({ type: c.type, source: c.cm.getValue() }, { after: c, focus: true })],
          ['trash', 'Clear the output', () => this.clearOutput(c, true)],
          ['trash', 'Delete the cell', () => this.deleteCell(c)]
        ]);
      });
      const out = h('div.nb-out', { 'aria-live': 'polite' });
      c.el = h('div.nb-cell', { dataset: { id: c.id, type: c.type }, tabindex: '-1' }, h('div.nb-gutter', runBtn, countEl), h('div.nb-main', h('div.nb-edrow', edBox, mdView, tools), out));
      c.countEl = countEl;
      c.outEl = out;
      c.runBtn = runBtn;
      c.edBox = edBox;
      c.mdView = mdView;
      const idx = opts.after ? this.cells.indexOf(opts.after) + 1 : opts.before ? this.cells.indexOf(opts.before) : this.cells.length;
      const ref = this.cells[idx];
      this.cells.splice(idx, 0, c);
      this.el.insertBefore(c.el, ref ? ref.el : this.endEl);
      c.cm = window.CodeMirror(edBox, {
        value: data.source || '',
        mode: this._mode(c),
        indentUnit: this.lang === 'r' ? 2 : 4,
        tabSize: 4,
        lineWrapping: true,
        viewportMargin: Infinity,
        matchBrackets: true,
        autoCloseBrackets: c.type === 'code',
        screenReaderLabel: c.type === 'code' ? `${LANGS()[this.lang].label} code cell` : 'Text cell (Markdown)',
        extraKeys: {
          Esc: () => this.commandMode(c),
          'Shift-Enter': () => this.runCell(c, { advance: true }),
          'Ctrl-Enter': () => this.runCell(c),
          'Cmd-Enter': () => this.runCell(c),
          'Alt-Enter': () => this.runCell(c, { insert: true }),
          'Ctrl-S': () => this.saveNow(true),
          'Cmd-S': () => this.saveNow(true),
          'Ctrl-/': 'toggleComment',
          'Cmd-/': 'toggleComment',
          Tab: (cm) => (cm.somethingSelected() ? cm.indentSelection('add') : cm.replaceSelection(this.lang === 'r' ? '  ' : '    ', 'end')),
          'Shift-Tab': (cm) => cm.indentSelection('subtract'),
          Up: (cm) => {
            const cur = cm.getCursor();
            if (cur.line === 0 && cur.ch === 0) return this.focusNeighbour(c, -1);
            return window.CodeMirror.Pass;
          },
          Down: (cm) => {
            const cur = cm.getCursor();
            if (cur.line === cm.lastLine() && cur.ch === cm.getLine(cur.line).length) return this.focusNeighbour(c, 1);
            return window.CodeMirror.Pass;
          }
        }
      });
      c.cm.on('focus', () => this.select(c, false));
      c.cm.on('change', () => this.changed());
      this._showType(c);
      c.outputs.forEach((o) => this._render(c, o));
      if (c.outputs.some((o) => o.type === 'error')) c.el.classList.add('has-error');
      c.el.addEventListener('keydown', (e) => this._cmdKey(e, c));
      if (opts.focus) setTimeout(() => this.select(c, true), 0);
      if (!opts.noSave) this.changed();
      return c;
    }
    _mode(c) {
      if (c.type === 'markdown') return 'markdown';
      if (c.type === 'raw') return null;
      const src = c.cm ? c.cm.getValue() : '';
      if (BASH.test(src)) return 'shell';
      return LANGS()[this.lang].cm;
    }
    _showType(c) {
      c.el.dataset.type = c.type;
      const md = c.type === 'markdown';
      c.runBtn.hidden = c.type === 'raw';
      c.countEl.textContent = c.type === 'code' ? (c.count ? `[${c.count}]` : '[ ]') : '';
      if (md && c.rendered) {
        const src = c.cm.getValue();
        c.mdView.innerHTML = src.trim() ? renderMarkdown(src) : '<p class="nb-md-empty">This text cell is empty. Double-click to write in it, using Markdown such as # heading, **bold** or - list.</p>';
        c.mdView.hidden = false;
        c.edBox.hidden = true;
      } else {
        c.mdView.hidden = true;
        c.edBox.hidden = false;
        const mode = this._mode(c);
        if (c.cm.getOption('mode') !== mode) c.cm.setOption('mode', mode);
        setTimeout(() => c.cm.refresh(), 0);
      }
    }
    setType(c, type) {
      if (c.type === type) return;
      c.type = type;
      c.rendered = false;
      this.clearOutput(c);
      c.count = null;
      c.cm.setOption('autoCloseBrackets', type === 'code');
      this._showType(c);
      c.cm.focus();
      this.changed();
    }
    editMarkdown(c) {
      if (c.type !== 'markdown') return;
      c.rendered = false;
      this._showType(c);
      this.select(c, true);
    }
    cellInfo(c) {
      const err = c.outputs.find((o) => o.type === 'error');
      const text = c.outputs
        .filter((o) => o.type === 'stream' || (o.type === 'display' && o.mime === 'text/plain'))
        .map((o) => o.text || o.data)
        .join('')
        .slice(0, 1500);
      return { id: c.id, lang: this.lang, path: this.path, code: c.cm.getValue(), count: c.count, error: err ? { ename: err.ename, evalue: err.evalue, traceback: err.traceback, hints: err.hints } : null, output: text, hasPlot: c.outputs.some((o) => o.mime === 'image/png'), hasTable: c.outputs.some((o) => o.mime === 'text/html') };
    }
    select(c, focus, keyboard) {
      if (!c) return;
      if (this.current && this.current !== c) this.current.el.classList.remove('sel');
      this.current = c;
      c.el.classList.add('sel');
      if (focus) {
        c.cm.focus();
        c.el.scrollIntoView({ block: 'nearest' });
      } else if (keyboard) c.el.focus({ preventScroll: true });
    }
    focusNeighbour(c, d) {
      const i = this.cells.indexOf(c) + d;
      const n = this.cells[i];
      if (!n) return window.CodeMirror.Pass;
      if (n.type === 'markdown' && n.rendered) {
        this.select(n, false, true);
        n.el.scrollIntoView({ block: 'nearest' });
        return;
      }
      this.select(n, true);
      n.cm.setCursor(d < 0 ? { line: n.cm.lastLine(), ch: 1e6 } : { line: 0, ch: 0 });
    }
    commandMode(c) {
      c.cm.getInputField().blur();
      if (c.type === 'markdown' && !c.rendered && c.cm.getValue().trim()) {
        c.rendered = true;
        this._showType(c);
      }
      this.select(c, false, true);
    }
    /* Jupyter's keys for a selected cell (not editing): Enter edit, A/B add above/below, D D delete, M text, Y code, ↑ ↓ move */
    _cmdKey(e, c) {
      if (e.target !== c.el || e.altKey) return;
      const k = e.key;
      // (⌘ on a Mac does what Ctrl does)
      if (e.ctrlKey || e.metaKey) {
        if (k === 'Enter') (e.preventDefault(), this.runCell(c));
        else if (k === 's') (e.preventDefault(), this.saveNow(true));
        return;
      }
      if (k === 'Enter' && e.shiftKey) (e.preventDefault(), this.runCell(c, { advance: true }));
      else if (k === 'Enter') {
        e.preventDefault();
        if (c.type === 'markdown') this.editMarkdown(c);
        else this.select(c, true);
      } else if (k === 'a' || k === 'A') (e.preventDefault(), this.addCell({ type: 'code' }, { before: c, focus: true }));
      else if (k === 'b' || k === 'B') (e.preventDefault(), this.addCell({ type: 'code' }, { after: c, focus: true }));
      else if (k === 'm' || k === 'M') (e.preventDefault(), this.setType(c, 'markdown'), this.commandMode(c));
      else if (k === 'y' || k === 'Y') (e.preventDefault(), this.setType(c, 'code'), this.commandMode(c));
      else if (k === 'ArrowUp' || k === 'k') {
        e.preventDefault();
        const p = this.cells[this.cells.indexOf(c) - 1];
        if (p) (this.select(p, false, true), p.el.scrollIntoView({ block: 'nearest' }));
      } else if (k === 'ArrowDown' || k === 'j') {
        e.preventDefault();
        const n = this.cells[this.cells.indexOf(c) + 1];
        if (n) (this.select(n, false, true), n.el.scrollIntoView({ block: 'nearest' }));
      } else if (k === 'd' || k === 'D') {
        e.preventDefault();
        if (this._dd && Date.now() - this._dd < 700) {
          this._dd = 0;
          this.deleteCell(c);
        } else this._dd = Date.now();
      }
    }
    move(c, d) {
      const i = this.cells.indexOf(c);
      const j = i + d;
      if (j < 0 || j >= this.cells.length) return;
      this.cells.splice(i, 1);
      this.cells.splice(j, 0, c);
      const ref = this.cells[j + 1];
      this.el.insertBefore(c.el, ref ? ref.el : this.endEl);
      c.cm.refresh();
      this.changed();
    }
    deleteCell(c) {
      const i = this.cells.indexOf(c);
      if (i < 0) return;
      const removed = { data: { type: c.type, source: c.cm.getValue(), outputs: c.outputs, count: c.count, meta: c.meta }, i };
      this.cells.splice(i, 1);
      c.el.remove();
      if (!this.cells.length) this.addCell({ type: 'code' });
      const next = this.cells[Math.min(i, this.cells.length - 1)];
      this.select(next, false, true);
      this.changed();
      // a deleted cell can come back (once)
      const t = h('span', { html: 'Cell deleted. ' });
      const undo = h('button.linkbtn', { type: 'button' }, 'Undo');
      undo.addEventListener('click', () => {
        const before = this.cells[removed.i];
        const nc = this.addCell(removed.data, before ? { before } : {});
        this.select(nc, false, true);
      });
      t.appendChild(undo);
      toastNode(t);
    }
    clearOutput(c, save) {
      c.outputs = [];
      c.outEl.innerHTML = '';
      c.el.classList.remove('has-error');
      if (save) this.changed();
    }
    clearAll() {
      this.cells.forEach((c) => {
        this.clearOutput(c);
        c.count = null;
        this._showType(c);
      });
      this.changed();
    }

    /* ---------------- running ---------------- */
    runCell(c, opts = {}) {
      if (opts.advance) {
        const i = this.cells.indexOf(c);
        const next = this.cells[i + 1] || this.addCell({ type: 'code' }, { after: c });
        setTimeout(() => (next.type === 'markdown' && next.rendered ? this.select(next, false, true) : this.select(next, true)), 0);
      } else if (opts.insert) {
        const n = this.addCell({ type: 'code' }, { after: c });
        setTimeout(() => this.select(n, true), 0);
      }
      if (c.type === 'markdown') {
        c.rendered = true;
        this._showType(c);
        this.changed();
        if (!opts.advance && !opts.insert) this.select(c, false, true);
        return Promise.resolve();
      }
      if (c.type === 'raw') return Promise.resolve();
      return this.app.enqueue(this, c);
    }
    runAll() {
      this.cells.forEach((c) => (c.type === 'markdown' ? ((c.rendered = true), this._showType(c)) : c.type === 'code' && this.app.enqueue(this, c)));
      return this.app.queue;
    }
    runAbove(c) {
      const i = this.cells.indexOf(c);
      this.cells.slice(0, i).forEach((x) => x.type === 'code' && this.app.enqueue(this, x));
      return this.app.queue;
    }
    /** run one cell (called by the app's queue) */
    async _run(c, gen) {
      c.queued = false;
      if (gen !== this.app.gen[this.lang] || !this.cells.includes(c)) {
        c.countEl.textContent = c.count ? `[${c.count}]` : '[ ]';
        return;
      }
      const code = c.cm.getValue();
      this.clearOutput(c);
      c.el.classList.add('running');
      c.countEl.textContent = '[*]';
      this.app.setRunning(this, c);
      const t0 = performance.now();
      let res = null;
      const handlers = {
        onOutput: (o) => this._append(c, o),
        onStatus: (t) => this.app.status(`<span class="spinner small"></span> ${esc(t)}`)
      };
      try {
        if (BASH.test(code)) {
          // a %%bash cell: the workbench's shell, in the folder where the notebook's language is – the notebook's
          // folder, unless %cd (Python) or setwd() (R) moved it, as in Jupyter (Python's and R's files first)
          await MG.kernels.syncAll();
          const K = MG.kernels.peek(this.lang);
          const w = K && K.state === 'ready' && K.where;
          const cwd = w && w.folder === this.folder && w.cwd && MG.app.fs.isDir(w.cwd) ? w.cwd : this.folder;
          const r = await MG.kernels.runShell(code.replace(BASH, ''), { cwd, onOutput: handlers.onOutput });
          if (r.code !== 0) this._append(c, { type: 'stream', name: 'stderr', text: `(the commands ended with exit status ${r.code})\n` });
          res = { ok: r.code === 0 };
        } else {
          res = await this.kernel.run(code, handlers, this.folder);
        }
      } catch (e) {
        this._append(c, { type: 'error', ename: 'Stopped', evalue: e.message, traceback: e.message, hints: [] });
      }
      c.el.classList.remove('running');
      c.count = this.app.nextCount(this.lang);
      c.countEl.textContent = `[${c.count}]`;
      const secs = (performance.now() - t0) / 1000;
      this.app.setRunning(this, null, secs);
      this.changed(true);
      const err = c.outputs.find((o) => o.type === 'error');
      bus.emit('nb:run', {
        id: c.id,
        lang: this.lang,
        path: this.path,
        code,
        ok: !!(res && res.ok),
        error: err ? err.ename : '',
        plot: c.outputs.some((o) => o.mime === 'image/png'),
        table: c.outputs.some((o) => o.mime === 'text/html'),
        secs,
        text: c.outputs.filter((o) => o.type === 'stream' || o.mime === 'text/plain').map((o) => o.text || o.data).join('').slice(0, 4000)
      });
    }

    /* ---------------- outputs ---------------- */
    _append(c, o) {
      if (o.type === 'stream') o = Object.assign({}, o, { text: stripAnsi(o.text) });
      const prev = c.outputs[c.outputs.length - 1];
      if (o.type === 'stream' && prev && prev.type === 'stream' && prev.name === o.name) {
        // (a \r or \b goes on from the line that the earlier output ended with)
        const edit = /[\r\b]/.test(o.text);
        prev.text = edit ? inPlace(prev.text + o.text) : prev.text + o.text;
        const last = c.outEl.lastElementChild;
        if (last && last.classList.contains('nb-stream') && last.dataset.name === o.name) {
          if (edit) last.textContent = prev.text;
          else last.appendChild(document.createTextNode(o.text));
          return;
        }
      } else {
        if (o.type === 'stream') o.text = inPlace(o.text);
        c.outputs.push(o);
      }
      this._render(c, o);
    }
    _render(c, o) {
      const box = c.outEl;
      if (o.type === 'stream') {
        box.appendChild(h('pre.nb-stream' + (o.name === 'stderr' ? '.err' : ''), { dataset: { name: o.name } }, o.text));
      } else if (o.type === 'display') {
        if (o.mime === 'image/png' || o.mime === 'image/jpeg') {
          const img = h('img.nb-img', { src: `data:${o.mime};base64,` + o.data, alt: 'Plot' });
          if (o.width) img.style.width = o.width + 'px';
          const dl = h('button.icon-btn.nb-imgdl', { type: 'button', title: 'Save this picture as a PNG file', html: MG.icon('download') });
          dl.addEventListener('click', () => {
            const a = h('a', { href: img.src, download: 'plot.' + (o.mime === 'image/jpeg' ? 'jpg' : 'png') });
            document.body.appendChild(a);
            a.click();
            a.remove();
          });
          box.appendChild(h('div.nb-figure', img, dl));
        } else if (o.mime === 'image/svg+xml') {
          box.appendChild(h('div.nb-svg', { html: window.DOMPurify ? window.DOMPurify.sanitize(o.data, { USE_PROFILES: { svg: true, svgFilters: true } }) : '' }));
        } else if (o.mime === 'text/html') box.appendChild(htmlOutput(o.data));
        else if (o.mime === 'text/markdown') box.appendChild(h('div.nb-md.nb-mdout', { html: renderMarkdown(o.data) }));
        else box.appendChild(h('pre.nb-text', o.data));
      } else if (o.type === 'error') {
        c.el.classList.add('has-error');
        const hints = (o.hints || []).map((t) => h('div.nb-hint', '💡 ' + t));
        box.appendChild(h('div.nb-error', h('pre', o.traceback || o.ename + ': ' + o.evalue), hints));
      }
    }

    /* ---------------- saving: the .ipynb file ---------------- */
    toIpynb() {
      return buildIpynb(
        this.lang,
        this.cells.map((c) => ({ id: c.id, type: c.type, source: c.cm.getValue(), outputs: c.outputs, count: c.count, meta: c.meta, attachments: c.attachments })),
        this.meta
      );
    }
    changed(now) {
      this.dirty = true;
      this.app.saveState(this, 'unsaved');
      clearTimeout(this._st);
      const big = this._lastSize > 1.5e6;
      this._st = setTimeout(() => this.saveNow(), now ? 150 : big ? 2500 : 800);
    }
    saveNow(user) {
      clearTimeout(this._st);
      const F = MG.app.fs;
      if (this.gone) return;
      const text = JSON.stringify(this.toIpynb(), null, 1);
      this._lastSize = text.length;
      try {
        this._saving = true;
        try {
          F.writeText(this.path, text);
        } finally {
          this._saving = false;
        }
        this.written = F.get(this.path);
        this.dirty = false;
        this.app.saveState(this, 'saved');
        if (user) toast(`Saved <b>${esc(F.pretty(this.path))}</b>. It’s kept in this browser, and you can download it with ⬇.`, 'ok', 2500);
        bus.emit('nb:saved', { path: this.path });
      } catch (e) {
        this.app.saveState(this, 'error');
        toast('The notebook couldn’t be saved: ' + esc(e.message), 'error');
      }
    }
    refresh() {
      this.cells.forEach((c) => c.cm.refresh());
    }
    insertCode(code, opts = {}) {
      const last = this.cells[this.cells.length - 1];
      let c;
      if (last && last.type === 'code' && !last.cm.getValue().trim() && !last.outputs.length) {
        c = last;
        c.cm.setValue(code);
      } else c = this.addCell({ type: opts.type || 'code', source: code }, { after: last });
      if (opts.type === 'markdown') {
        c.rendered = true;
        this._showType(c);
      }
      this.select(c, false);
      setTimeout(() => {
        c.el.scrollIntoView({ block: 'center', behavior: 'smooth' });
        c.el.classList.add('flash');
        setTimeout(() => c.el.classList.remove('flash'), 1400);
        c.cm.refresh();
      }, 50);
      this.changed();
      if (opts.run) return this.runCell(c).then(() => c);
      return Promise.resolve(c);
    }
    codeContext(maxChars = 5000) {
      const parts = this.cells
        .filter((c) => c.type === 'code')
        .map((c, i) => `# cell ${i + 1}${c.count ? ` [ran as ${c.count}]` : ''}\n${c.cm.getValue().trim()}`)
        .filter((s) => s.split('\n').length > 1 || s.length > 12);
      let s = parts.join('\n\n');
      if (s.length > maxChars) s = '…\n' + s.slice(-maxChars);
      return s;
    }
    destroy() {
      clearTimeout(this._st);
      this.el.remove();
    }
  }

  function toastNode(node) {
    const id = 'tn' + uid();
    MG.toast(`<span id="${id}"></span>`, null, 6000);
    setTimeout(() => {
      const slot = document.getElementById(id);
      if (slot) slot.replaceWith(node);
    }, 0);
  }

  /* ------------------------------------------------------------------
     the tab: notebooks, kernel, toolbar
     ------------------------------------------------------------------ */
  class NotebookApp {
    constructor(root, opts = {}) {
      this.root = root;
      this.fs = opts.fs || MG.app.fs;
      this.dir = opts.dir || MG.app.HOME + '/notebooks';
      this.views = new Map(); // path → NotebookView
      this.view = null;
      this.queue = Promise.resolve();
      this.gen = { python: 0, r: 0 };
      this.counts = { python: 0, r: 0 };
      this._build();
      this._watch();
      bus.on('kernel:state', (d) => {
        if (d.state === 'restarted') this.counts[d.lang] = 0;
        this._kernelPill();
      });
      bus.on('kernel:status', () => this._kernelPill());
    }

    _build() {
      const R = this.root;
      R.classList.add('nb');
      const btn = (icon, label, title, fn, cls) => {
        const b = h('button.tbtn' + (cls || ''), { type: 'button', title, 'aria-label': label ? null : title, html: MG.icon(icon) + (label ? '<span>' + esc(label) + '</span>' : '') });
        b.addEventListener('click', fn);
        return b;
      };
      this.listBtn = btn('notebook', 'Notebooks', 'Open another notebook, or start a new one', (e) => this.notebookMenu(e.currentTarget), '.nb-listbtn');
      this.titleEl = h('input.nb-name', { type: 'text', spellcheck: 'false', 'aria-label': 'Notebook name', title: 'The notebook\'s file name – click to rename' });
      this.titleEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') this.titleEl.blur();
        if (e.key === 'Escape') {
          this.titleEl.value = this.view ? MG.path.basename(this.view.path) : '';
          this.titleEl.blur();
        }
      });
      this.titleEl.addEventListener('change', () => this.rename(this.titleEl.value));
      this.saveEl = h('span.nb-save');
      this.kernelEl = h('button.nb-kernel', { type: 'button', title: 'The language that runs this notebook – click for options' });
      this.kernelEl.addEventListener('click', (e) => this.kernelMenu(e.currentTarget));
      this.statusEl = h('span.nb-status');
      this.runBtn = btn('play', 'Run', 'Run the selected cell and go to the next one (Shift+Enter)', () => this.view && this.view.current && this.view.runCell(this.view.current, { advance: true }));
      this.stopBtn = btn('stop', 'Stop', 'Stop the code that’s running. This restarts the language, so its variables are forgotten.', () => this.stop(), '.nb-stopbtn');
      this.stopBtn.hidden = true;
      const bar = h(
        'div.nb-bar',
        this.listBtn,
        h('div.nb-namebox', this.titleEl, this.saveEl),
        h('span.grow'),
        this.statusEl,
        this.kernelEl
      );
      const bar2 = h(
        'div.nb-bar.nb-bar2',
        btn('plus', 'Code', 'Add a code cell below the selected one (B)', () => this.view && this.view.addCell({ type: 'code' }, { after: this.view.current, focus: true }), '.nb-add'),
        btn('plus', 'Text', 'Add a text (Markdown) cell below the selected one', () => this.view && this.view.addCell({ type: 'markdown' }, { after: this.view.current, focus: true, edit: true }), '.nb-add'),
        h('span.nb-sep'),
        this.runBtn,
        btn('fastforward', 'Run all', 'Run every cell from the top', () => this.view && this.view.runAll()),
        this.stopBtn,
        btn('reset', 'Restart', 'Restart the language, which forgets all variables and stops anything still running', () => this.restart()),
        h('span.grow'),
        btn('list', '', 'Show the variables that the notebook\'s language remembers now', () => this.showVars()),
        btn('download', 'Download', 'Download this notebook (.ipynb, script or web page)', (e) => this.downloadMenu(e.currentTarget)),
        btn('help', '', 'Help for notebooks', () => MG.app.showHelp && MG.app.showHelp('h-notebook'))
      );
      this.banner = h('div.nb-banner', { hidden: true });
      this.body = h('div.nb-body');
      R.append(bar, bar2, this.banner, this.body);
      // drop .ipynb files onto the notebook to open them
      R.addEventListener('dragover', (e) => {
        if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) {
          e.preventDefault();
          R.classList.add('dropping');
        }
      });
      R.addEventListener('dragleave', (e) => {
        if (!R.contains(e.relatedTarget)) R.classList.remove('dropping');
      });
      R.addEventListener('drop', async (e) => {
        R.classList.remove('dropping');
        const files = Array.from((e.dataTransfer && e.dataTransfer.files) || []);
        if (!files.length) return;
        e.preventDefault();
        const nbs = files.filter((f) => /\.ipynb$/i.test(f.name));
        if (!nbs.length) {
          const paths = await MG.project.addFiles(this.fs, this.view ? this.view.folder : MG.app.HOME, files);
          if (paths.length) toast(`Added ${paths.length} file${paths.length === 1 ? '' : 's'} next to the notebook (${esc(this.fs.pretty(MG.path.dirname(paths[0])))}).`, 'ok');
          return;
        }
        for (const f of nbs) await this.importFile(f);
      });
    }

    /* ---------------- the notebook files ---------------- */
    list() {
      const out = [];
      for (const [p, e] of this.fs.entries) if (e.kind !== 'dir' && /\.ipynb$/i.test(p) && p.startsWith(MG.app.HOME + '/') && !/\/\.ipynb_checkpoints\//.test(p)) out.push({ path: p, mtime: e.mtime || 0 });
      return out.sort((a, b) => b.mtime - a.mtime);
    }
    async open(path, opts = {}) {
      path = this.fs.resolve(path);
      if (this.view && this.view.path === path) return this.view;
      let v = this.views.get(path);
      if (!v || v.gone) {
        let doc;
        try {
          doc = parseIpynb(await this.fs.readText(path));
        } catch (e) {
          toast(`<b>${esc(this.fs.pretty(path))}</b> couldn’t be opened as a notebook: ${esc(e.message)}`, 'error', 8000);
          return null;
        }
        v = new NotebookView(this, path, doc);
        v.written = this.fs.get(path);
        this.views.set(path, v);
      }
      if (this.view) {
        this.view.el.remove();
        if (this.view.dirty) this.view.saveNow();
      }
      this.view = v;
      this.body.appendChild(v.el);
      this.titleEl.value = MG.path.basename(path);
      this.titleEl.title = this.fs.pretty(path) + ' – click to rename';
      this.saveState(v, v.dirty ? 'unsaved' : 'saved');
      this._banner();
      this._kernelPill();
      setTimeout(() => v.refresh(), 0);
      store.set('nbOpen', path);
      bus.emit('nb:open', { path, lang: v.lang });
      // Python or R starts in the background the first time a notebook of that language is open
      if (!opts.noStart) setTimeout(() => v.kernel.ensure().catch(() => {}), opts.delay || 400);
      return v;
    }
    _banner() {
      const v = this.view;
      if (v && v.warning) {
        this.banner.hidden = false;
        this.banner.innerHTML = `${MG.icon('warning')}<span>${esc(v.warning)}</span>`;
      } else if (v && v.gone) {
        this.banner.hidden = false;
        this.banner.innerHTML = `${MG.icon('warning')}<span>This notebook's file was deleted or moved. </span>`;
        const again = h('button.btn.small', { type: 'button' }, 'Save it again');
        again.addEventListener('click', () => {
          v.gone = false;
          v.saveNow(true);
          this._banner();
        });
        this.banner.appendChild(again);
      } else this.banner.hidden = true;
    }
    /** a free name in a folder: Untitled.ipynb, Untitled1.ipynb … */
    freeName(folder, stem, ext = '.ipynb') {
      let p = `${folder}/${stem}${ext}`;
      for (let i = 1; this.fs.exists(p); i++) p = `${folder}/${stem}${i}${ext}`;
      return p;
    }
    async newNotebook(lang, opts = {}) {
      this.fs.mkdirp(this.dir);
      const path = opts.path || this.freeName(this.dir, opts.stem || (lang === 'r' ? 'Untitled-R' : 'Untitled'));
      const cells = opts.cells || [{ type: 'code', source: '' }];
      this.fs.writeText(path, JSON.stringify(makeIpynb(lang, cells), null, 1));
      const v = await this.open(path);
      if (v && !opts.cells) v.select(v.cells[0], true);
      return v;
    }
    async importFile(file) {
      this.fs.mkdirp(this.dir);
      const text = await file.text();
      try {
        parseIpynb(text);
      } catch (e) {
        toast(`<b>${esc(file.name)}</b> isn’t a notebook that this page can read.`, 'error');
        return null;
      }
      const stem = file.name.replace(/\.ipynb$/i, '').replace(/[\/\\]/g, '_');
      const path = this.freeName(this.dir, stem);
      this.fs.writeText(path, text);
      toast(`Opened <b>${esc(file.name)}</b> and saved it as ${esc(this.fs.pretty(path))}. Run its cells to recreate the results.`, 'ok', 6000);
      return this.open(path);
    }
    openFromComputer() {
      const inp = h('input', { type: 'file', accept: '.ipynb,application/x-ipynb+json,application/json', multiple: true, style: { display: 'none' } });
      document.body.appendChild(inp);
      inp.addEventListener('change', async () => {
        const files = Array.from(inp.files || []);
        inp.remove();
        for (const f of files) await this.importFile(f);
      });
      inp.click();
    }
    rename(name) {
      const v = this.view;
      if (!v) return;
      name = String(name || '').trim().replace(/[\/\\]/g, '_');
      if (!name) {
        this.titleEl.value = MG.path.basename(v.path);
        return;
      }
      if (!/\.ipynb$/i.test(name)) name += '.ipynb';
      const to = MG.path.dirname(v.path) + '/' + name;
      if (to === v.path) return;
      if (this.fs.exists(to)) {
        toast(`There’s already a file called <b>${esc(name)}</b> here.`, 'warn');
        this.titleEl.value = MG.path.basename(v.path);
        return;
      }
      if (v.dirty) v.saveNow();
      this._renaming = true;
      try {
        this.fs.rename(v.path, to);
      } finally {
        this._renaming = false;
      }
      this.views.delete(v.path);
      v.path = to;
      v.written = this.fs.get(to);
      this.views.set(to, v);
      this.titleEl.value = name;
      store.set('nbOpen', to);
      toast(`Renamed to <b>${esc(name)}</b>.`, 'ok', 2000);
    }
    /** files changed by other tabs (an upload, the terminal, the AI): an open notebook follows its file */
    _watch() {
      this.fs.onChange((path, what) => {
        if (this._renaming || !/\.ipynb$/i.test(path)) return;
        const v = this.views.get(path);
        if (what === 'rename' && !v) {
          // a notebook moved (mv in the terminal, rename in Files): follow it
          const e = this.fs.get(path);
          for (const [p, x] of this.views) {
            if (x.written === e && p !== path) {
              this.views.delete(p);
              x.path = path;
              x.gone = false;
              this.views.set(path, x);
              if (x === this.view) {
                this.titleEl.value = MG.path.basename(path);
                store.set('nbOpen', path);
                this._banner();
              }
            }
          }
          return;
        }
        if (!v) return;
        if (what === 'remove') {
          setTimeout(() => {
            if (!this.fs.exists(v.path)) {
              v.gone = true;
              if (v === this.view) this._banner();
            }
          }, 30);
          return;
        }
        if (what === 'write' && !v._saving && this.fs.get(path) !== v.written) this._external(v);
      });
    }
    async _external(v) {
      const e = this.fs.get(v.path);
      if (!e || e === v.written) return;
      if (v.dirty) {
        toast(`<b>${esc(this.fs.pretty(v.path))}</b> was changed elsewhere while you were editing it here. Your version has been kept. If you want both, click this notebook’s name and rename it.`, 'warn', 9000);
        v.written = e;
        return;
      }
      let doc;
      try {
        doc = parseIpynb(await this.fs.readText(v.path));
      } catch (err) {
        return;
      }
      const nv = new NotebookView(this, v.path, doc);
      nv.written = this.fs.get(v.path);
      this.views.set(v.path, nv);
      if (v === this.view) {
        v.destroy();
        this.view = null;
        await this.open(nv.path, { noStart: true });
        toast('The notebook was changed in another tab of the workbench, so you’re now looking at the new version.', null, 4000);
      } else v.destroy();
    }

    /* ---------------- menus ---------------- */
    notebookMenu(anchor) {
      const items = [
        ['plus', 'New Python notebook', () => this.newNotebook('python')],
        ['upload', 'Open a notebook from my computer…', () => this.openFromComputer()]
      ];
      const nbs = this.list().slice(0, 14);
      nbs.forEach((n) => items.push(['notebook', (this.view && this.view.path === n.path ? '● ' : '') + this.fs.pretty(n.path), () => this.open(n.path)]));
      if (this.list().length > 14) items.push(['folder', 'All my files…', () => MG.app.showWorkbench('editor')]);
      if (this.view) {
        items.push(['copy', 'Make a copy of this notebook', () => this.duplicate()]);
        items.push(['folder', 'Show this notebook in Files', () => MG.app.revealFile && MG.app.revealFile(this.view.path)]);
        items.push(['trash', 'Delete this notebook…', () => this.deleteNotebook()]);
      }
      MG.popmenu(anchor, items);
    }
    downloadMenu(anchor) {
      const v = this.view;
      if (!v) return;
      const L = LANGS()[v.lang];
      MG.popmenu(anchor, [
        ['download', 'Jupyter notebook (.ipynb)', () => this.downloadIpynb()],
        ['code', `${L.label} script (${L.ext})`, () => this.downloadScript()],
        ['globe', 'Web page with the results (.html)', () => this.downloadHtml()],
        ['trash', 'Clear all outputs', () => v.clearAll()]
      ]);
    }
    kernelMenu(anchor) {
      const v = this.view;
      if (!v) return;
      const K = v.kernel;
      const items = [];
      if (K.state === 'off' || K.state === 'failed') items.push(['play', `Start ${K.label}`, () => K.ensure().catch(() => {})]);
      items.push(['reset', `Restart ${K.label} (forget all variables)`, () => this.restart()]);
      items.push(['fastforward', `Restart ${K.label} and run all cells`, () => this.restart(true)]);
      items.push(['list', 'Variables', () => this.showVars()]);
      items.push(['info', `About ${K.label} in the workbench`, () => MG.app.showHelp && MG.app.showHelp('h-notebook')]);
      MG.popmenu(anchor, items);
    }
    _kernelPill() {
      const v = this.view;
      if (!v) return;
      const K = MG.kernels.peek(v.lang);
      const label = LANGS()[v.lang].label;
      let dot = 'off', text = `${label} · not started yet`;
      if (K) {
        if (K.state === 'ready') {
          dot = this.running && this.running.view.lang === v.lang ? 'busy' : 'ok';
          text = v.lang === 'r' ? `R ${(K.versions && K.versions.r) || ''}` : `Python ${(K.versions && K.versions.python) || ''}`;
        } else if (K.state === 'loading') {
          dot = 'busy';
          text = `${label} · ${K.statusText || 'starting…'}`;
        } else if (K.state === 'failed') {
          dot = 'bad';
          text = `${label} couldn’t start`;
        }
      }
      this.kernelEl.innerHTML = `<span class="nb-lang nb-lang-${v.lang}">${esc(label)}</span><span class="kdot ${dot}"></span><span class="nb-ktext">${esc(text)}</span>`;
      this.kernelEl.title = K && K.state === 'ready' ? K.describe() + ' – click for options' : 'Click for options';
    }
    saveState(v, state) {
      if (v !== this.view) return;
      this.saveEl.dataset.state = state;
      this.saveEl.textContent = state === 'saved' ? 'Saved' : state === 'unsaved' ? 'Editing…' : 'Not saved';
      this.saveEl.title = state === 'saved' ? 'Saved with your files, which are kept in this browser' : '';
    }
    status(html) {
      this.statusEl.innerHTML = html || '';
    }

    /* ---------------- running ---------------- */
    nextCount(lang) {
      return ++this.counts[lang];
    }
    enqueue(view, c) {
      const gen = this.gen[view.lang];
      c.queued = true;
      if (!c.el.classList.contains('running')) c.countEl.textContent = '[…]';
      this.queue = this.queue.then(() => view._run(c, gen)).catch((e) => console.error(e));
      return this.queue;
    }
    setRunning(view, c, secs) {
      this.running = c ? { view, c } : null;
      this.stopBtn.hidden = !c;
      this.runBtn.hidden = !!c;
      clearInterval(this._timer);
      if (c) {
        const t0 = performance.now();
        const K = MG.kernels.peek(view.lang);
        const waiting = () => K && K.state !== 'ready' && !BASH.test(c.cm.getValue());
        this.status(waiting() ? `<span class="spinner small"></span> waiting for ${esc(LANGS()[view.lang].label)} to start…` : '');
        this._timer = setInterval(() => {
          const s = Math.round((performance.now() - t0) / 1000);
          if (waiting()) this.status(`<span class="spinner small"></span> starting ${esc(LANGS()[view.lang].label)}… ${s} s`);
          else if (s >= 2) this.status(`<span class="spinner small"></span> running… ${s} s`);
        }, 500);
      } else this.status(secs > 3 ? `last cell: ${secs.toFixed(1)} s` : '');
      this._kernelPill();
    }
    stop() {
      const r = this.running;
      if (!r) return;
      const lang = r.view.lang;
      const label = LANGS()[lang].label;
      const m = MG.modal(
        'Stop the running code?',
        `<p>${esc(label)} in the browser can only be stopped by restarting it. Its variables will be forgotten, so run your cells again afterwards. Run all does that for you.</p><div class="prompt-actions"><button class="btn" data-x="no" type="button">Let it run</button><button class="btn primary" data-x="yes" type="button">Stop and restart ${esc(label)}</button></div>`
      );
      m.box.querySelector('[data-x="no"]').addEventListener('click', () => m.close());
      m.box.querySelector('[data-x="yes"]').addEventListener('click', () => {
        m.close();
        this.restart(false, lang);
      });
    }
    restart(runAll, lang) {
      const v = this.view;
      lang = lang || (v && v.lang);
      if (!lang) return;
      this.gen[lang]++;
      this.counts[lang] = 0;
      const K = MG.kernels.get(lang);
      // cells waiting in the queue are dropped; the one running is stopped
      for (const x of this.views.values()) {
        if (x.lang !== lang) continue;
        x.cells.forEach((c) => {
          if (c.queued || c.el.classList.contains('running')) {
            c.queued = false;
            c.el.classList.remove('running');
            c.countEl.textContent = c.count ? `[${c.count}]` : '[ ]';
          }
        });
      }
      if (this.running && this.running.view.lang === lang) this.setRunning(this.running.view, null, 0);
      if (K.state === 'off') K.ensure().catch(() => {});
      else K.restart();
      this.queue = Promise.resolve();
      K.ensure().then(
        () => {
          if (runAll && v) v.runAll();
          else toast(`${esc(K.label)} has restarted, so its variables are forgotten. Run your cells again from the top, which Run all does for you.`, null, 4000);
        },
        () => {}
      );
    }
    async showVars() {
      const v = this.view;
      if (!v) return;
      const K = MG.kernels.peek(v.lang);
      let vars = [];
      try {
        vars = K ? await K.vars() : [];
      } catch (e) {
        vars = [];
      }
      const rows = vars.length
        ? vars.filter((x) => x.desc !== '' || x.type).map((x) => `<tr><td><code>${esc(x.name)}</code></td><td>${esc(x.type)}</td><td>${esc(x.desc)}</td></tr>`).join('')
        : `<tr><td colspan="3" class="muted">There’s nothing here yet. Run a cell that makes a variable, such as <code>${v.lang === 'r' ? 'df &lt;- read.csv(…)' : 'df = pd.read_csv(…)'}</code>.</td></tr>`;
      MG.modal(`What ${esc(LANGS()[v.lang].label)} remembers`, `<p class="muted small">These are the variables made by the cells you’ve run since ${esc(LANGS()[v.lang].label)} started. They’re shared by all your ${esc(LANGS()[v.lang].label)} notebooks.</p><div class="table-scroll"><table class="table small"><tr><th>Name</th><th>Type</th><th>Contents</th></tr>${rows}</table></div>`);
    }

    /* ---------------- downloads ---------------- */
    downloadIpynb() {
      const v = this.view;
      if (!v) return;
      if (v.dirty) v.saveNow();
      MG.downloadText(JSON.stringify(v.toIpynb(), null, 1), MG.path.basename(v.path), 'application/x-ipynb+json');
      toast('Downloaded the notebook. It opens in Jupyter, JupyterLab, VS Code or Google Colab. If it reads data files, download those too from the Files tab, and keep them in the same folders.', null, 7000);
      bus.emit('nb:download', { path: v.path, format: 'ipynb' });
    }
    downloadScript() {
      const v = this.view;
      if (!v) return;
      const L = LANGS()[v.lang];
      const parts = v.cells.map((c, i) => {
        const src = c.cm.getValue();
        if (c.type === 'markdown') return src.split('\n').map((l) => '# ' + l).join('\n');
        if (c.type === 'raw') return '';
        if (BASH.test(src)) return src.replace(BASH, '').split('\n').map((l) => '# $ ' + l).join('\n') + (v.lang === 'python' ? '\n# (shell commands: run them in a terminal)' : '');
        return `# %% [${i + 1}]\n` + (v.lang === 'python' ? src.replace(/^(\s*)([!%].*)$/gm, '$1# $2') : src);
      });
      MG.downloadText(parts.filter(Boolean).join('\n\n') + '\n', MG.path.basename(v.path).replace(/\.ipynb$/i, '') + L.ext, 'text/plain');
    }
    downloadHtml() {
      const v = this.view;
      if (!v) return;
      const title = MG.path.basename(v.path).replace(/\.ipynb$/i, '');
      const cells = v.cells
        .map((c) => {
          if (c.type === 'markdown') return `<div class="md">${renderMarkdown(c.cm.getValue())}</div>`;
          if (c.type === 'raw') return `<pre class="raw">${esc(c.cm.getValue())}</pre>`;
          const outs = c.outEl.innerHTML.replace(/<button[\s\S]*?<\/button>/g, '');
          return `<div class="cell"><div class="in"><span class="n">[${c.count || ' '}]</span><pre>${esc(c.cm.getValue())}</pre></div>${outs ? `<div class="out">${outs}</div>` : ''}</div>`;
        })
        .join('\n');
      const css = `body{font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#18212f}
.cell{margin:10px 0}.in{display:flex;gap:8px}.n{font:12px monospace;color:#647086;min-width:3em;padding-top:8px}
.in pre{flex:1;background:#f6f8fa;border:1px solid #e0e5ec;border-radius:6px;padding:8px;margin:0;white-space:pre-wrap;font:13px/1.45 ui-monospace,Menlo,Consolas,monospace}
.out{margin-left:3.6em}.out pre{white-space:pre-wrap;font:12.5px/1.45 ui-monospace,Menlo,Consolas,monospace;margin:4px 0}
.nb-stream.err{background:#fff8e8;color:#7a5200}.nb-error{border:1px solid #f1c2bf;background:#fdeceb;border-radius:6px;padding:6px 10px}
img{max-width:100%}table{border-collapse:collapse;font-size:12px}th,td{border-bottom:1px solid #e0e5ec;padding:3px 8px;text-align:right}
.md{margin:14px 0}.md pre{background:#f6f8fa;padding:8px;border-radius:6px}`;
      const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${esc(title)}</title><style>${css}</style></head><body><h1>${esc(title)}</h1><p style="color:#647086">${esc(LANGS()[v.lang].label)} notebook from the Pedigree workbench · ${new Date().toLocaleString('en-GB')}</p>${cells}</body></html>`;
      MG.downloadText(html, title + '.html', 'text/html');
    }
    duplicate() {
      const v = this.view;
      if (!v) return;
      if (v.dirty) v.saveNow();
      const stem = MG.path.basename(v.path).replace(/\.ipynb$/i, '') + '-copy';
      const to = this.freeName(MG.path.dirname(v.path), stem);
      this.fs.copy(v.path, to);
      this.open(to);
    }
    deleteNotebook() {
      const v = this.view;
      if (!v) return;
      const m = MG.modal('Delete this notebook?', `<p><b>${esc(this.fs.pretty(v.path))}</b> will be deleted from your files. Download it first if you want to keep a copy.</p><div class="prompt-actions"><button class="btn" data-x="no" type="button">Cancel</button><button class="btn danger" data-x="yes" type="button">Delete</button></div>`);
      m.box.querySelector('[data-x="no"]').addEventListener('click', () => m.close());
      m.box.querySelector('[data-x="yes"]').addEventListener('click', async () => {
        m.close();
        const p = v.path;
        clearTimeout(v._st);
        v.gone = true;
        this.views.delete(p);
        this.fs.remove(p);
        v.destroy();
        this.view = null;
        const next = this.list()[0];
        if (next) await this.open(next.path);
        else await this.newNotebook('python');
      });
    }

    /* ---------------- for the help pages, the AI and the other tabs ---------------- */
    /** put code into a notebook of the right language (opening or making one) and optionally run it */
    async insertCode(code, opts = {}) {
      const lang = 'python';
      let v = this.view;
      if (!v || (v.lang !== lang && !BASH.test(code))) {
        const other = this.list()
          .map((n) => this.views.get(n.path) || n)
          .find((n) => (n.lang ? n.lang === lang : this._langOf(n.path) === lang));
        if (other) v = await this.open(other.path || other.path);
        else v = await this.newNotebook(lang, { stem: lang === 'r' ? 'scratch-R' : 'scratch' });
        if (v) toast(`This is ${lang === 'r' ? 'R' : 'Python'} code, so it went into <b>${esc(MG.path.basename(v.path))}</b>.`, null, 3500);
      }
      if (!v) return null;
      return v.insertCode(code, opts);
    }
    _langOf(path) {
      try {
        const e = this.fs.get(path);
        if (e && e.kind === 'text') return parseIpynb(e.text).lang;
      } catch (err) {
        /* not readable */
      }
      return null;
    }
    /** the open notebook's code (for the AI) */
    codeContext(n) {
      return this.view ? this.view.codeContext(n) : '';
    }
    shown() {
      if (this.view) this.view.refresh();
    }
  }

  MG.NotebookApp = NotebookApp;
  MG.NotebookView = NotebookView;
})();
