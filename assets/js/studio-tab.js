/* =====================================================================
   The Studio tab: Pedigree Studio (assets/studio/index.html, a copy of
   the Studio – see build/update_studio.py) in a frame, with a bar that
   joins it to the workbench's files.

   The drawing on show belongs to a file among your files (or to none
   yet): Save writes it there, Open shows another, and Convert takes it
   to the Tools tab. The Studio's own menu still saves to, and opens
   from, your computer.

   The frame is the same site as the page, so the bar calls the Studio
   directly through assets/studio/bridge.js (window.pedwbStudio).
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const { h, esc, store, toast } = MG;

  /** what decides whether a drawing has changed: everything but where the view is */
  const sig = (data) => {
    const d = Object.assign({}, data);
    delete d.zoom;
    delete d.panX;
    delete d.panY;
    return JSON.stringify(d);
  };
  const isDrawing = (doc) => !!doc && typeof doc === 'object' && Array.isArray(doc.persons) && (Array.isArray(doc.partnerships) || Array.isArray(doc.childLinks));

  class StudioTab {
    constructor(root, opts) {
      this.root = root;
      this.fs = opts.fs;
      this.home = MG.app.HOME;
      this.path = store.get('studioFile', null);
      this.base = store.get('studioSig', null);
      this.dirty = false;
      this._build();
      this.ready = new Promise((resolve) => (this._ready = resolve));
      this.frame.addEventListener('load', () => this._attach());
      this.fs.onChange((p, what) => this._fsChanged(p, what));
    }

    /* ---------------- the bar and the frame ---------------- */
    _build() {
      const btn = (icon, label, title, fn, cls = '') => {
        const b = h('button.tbtn' + cls, { type: 'button', title, html: MG.icon(icon) + `<span>${esc(label)}</span>` });
        b.addEventListener('click', fn);
        return b;
      };
      this.fileBtn = h('button.st-file', { type: 'button', title: 'The file this drawing is kept in – click for your other drawings' });
      this.fileBtn.addEventListener('click', () => this.recentMenu(this.fileBtn));
      this.stateEl = h('span.st-state', { 'aria-live': 'polite' });
      this.saveBtn = btn('save', 'Save', 'Save the drawing in its file among your files (Ctrl+S)', () => this.save());
      const bar = h(
        'div.st-bar',
        h('span.st-label', { html: MG.icon('pedigree') + '<span>Drawing</span>' }),
        this.fileBtn,
        this.stateEl,
        h('span.grow'),
        btn('plus', 'New', 'Start a new drawing', () => this.newDrawing()),
        btn('openfolder', 'Open…', 'Open a drawing from your files or the examples', () => this.openDialog()),
        this.saveBtn,
        btn('newfile', 'Save as…', 'Save the drawing as a new file among your files', () => this.saveAs()),
        h('span.st-sep'),
        btn('wand', 'Tidy', 'Lay the whole pedigree out again (Pedigree Studio’s Tidy) – it can be undone', () => this.tidy()),
        btn('convert', 'Convert or check…', 'Take this drawing to the Tools tab: GA4GH, Phenopackets and PED files, ontology terms', () => this.toTools(), '.primary'),
        btn('dots', '', 'More', (e) => this.moreMenu(e.currentTarget), '.icon-only')
      );
      this.frame = h('iframe.st-frame', { src: 'assets/studio/index.html?v=' + encodeURIComponent((MG.config.buildId || '') + (window.WB_STUDIO || '')), title: 'Pedigree Studio' });
      this.cover = h('div.st-cover', h('span.spinner'), h('span', 'Opening Pedigree Studio…'));
      this.root.append(h('div.st-wrap', bar, h('div.st-stage', this.frame, this.cover)));
      this._label();
      // Ctrl+S in the bar (inside the frame, the Studio has its own keys)
      this.root.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
          e.preventDefault();
          this.save();
        }
      });
    }
    _attach() {
      const win = this.frame.contentWindow;
      const api = win && win.pedwbStudio;
      if (!api) {
        this.cover.innerHTML = '<span>Pedigree Studio could not start in this browser. Reload the page to try again.</span>';
        return;
      }
      this.api = api;
      this.win = win;
      api.onChange(() => this._changed());
      // Ctrl+S inside the frame saves to the workbench as well (the Studio's own Ctrl+S, if any, is left to it)
      win.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's' && !e.defaultPrevented) {
          e.preventDefault();
          this.save();
        }
      });
      this.cover.hidden = true;
      // the Studio has put back the drawing it kept in the browser: is it the file's, as it was saved?
      this._check();
      this._ready(this);
    }
    shown() {
      if (this.api) {
        try {
          // (the frame was hidden: the Studio measures itself again)
          this.win.dispatchEvent(new Event('resize'));
        } catch (e) {
          /* not ready */
        }
      }
    }

    /* ---------------- the state: which file, saved or not ---------------- */
    _label() {
      const p = this.path;
      this.fileBtn.innerHTML = p ? `<span>${esc(this.fs.pretty(p))}</span>${MG.icon('chevD')}` : `<span class="muted">not saved in a file yet</span>${MG.icon('chevD')}`;
      this.stateEl.textContent = !p ? '' : this.dirty ? 'changes not saved' : 'saved';
      this.stateEl.dataset.state = !p ? 'none' : this.dirty ? 'dirty' : 'saved';
      this.saveBtn.classList.toggle('attn', !!(p && this.dirty));
    }
    _changed() {
      clearTimeout(this._t);
      this._t = setTimeout(() => this._check(), 250);
    }
    _check() {
      if (!this.api) return;
      let now;
      try {
        now = sig(this.api.data());
      } catch (e) {
        return;
      }
      const empty = this.api.isEmpty();
      this.dirty = this.path ? now !== this.base : !empty;
      this._label();
    }
    _remember() {
      store.set('studioFile', this.path);
      store.set('studioSig', this.base);
    }
    /** the drawing has unsaved changes that would be lost: ask → true to go on */
    async _mayDiscard(what) {
      this._check();
      if (!this.dirty) return true;
      const where = this.path ? `<b>${esc(this.fs.pretty(this.path))}</b>` : 'a file';
      return MG.confirmBox('Leave the drawing unsaved?', `<p>The drawing on show has changes that are not saved in ${where}. ${esc(what)} replaces it (Undo in the Studio brings it back).</p>`, 'Go on without saving', { cancel: 'Keep it' });
    }

    /* ---------------- opening ---------------- */
    /** show the drawing in a file. opts.tidy: lay it out afresh (for drawings made by the converters) */
    async openFile(path, opts = {}) {
      await this.ready;
      let doc;
      try {
        doc = JSON.parse(await this.fs.readText(path));
      } catch (e) {
        toast(`<b>${esc(this.fs.pretty(path))}</b> could not be read as a drawing: ${esc(e.message)}`, 'error', 8000);
        return false;
      }
      if (!isDrawing(doc)) {
        const k = MG.app.pedKind(path);
        const hint = k === 'pedigree' || k === 'family' ? ' It is a GA4GH file: draw it with GA4GH or Phenopackets → drawing, in the Tools tab.' : k === 'ped' || k === 'mped' ? ' It is a PED file: draw it with PED or MPED → drawing, in the Tools tab.' : '';
        toast(`<b>${esc(this.fs.pretty(path))}</b> is not a Pedigree Studio drawing.${hint}`, 'warn', 9000);
        return false;
      }
      if (path !== this.path && !(await this._mayDiscard('Opening ' + MG.path.basename(path)))) return false;
      try {
        this.api.load(doc, { message: 'Opened ' + MG.path.basename(path) });
      } catch (e) {
        toast('Pedigree Studio could not show this drawing: ' + esc(e.message), 'error', 9000);
        return false;
      }
      const readonly = !(path === this.home || path.startsWith(this.home + '/'));
      // an example (read-only) is opened as a drawing that is not in a file of yours yet
      this.path = readonly ? null : path;
      this.base = sig(this.api.data());
      if (opts.tidy) this.api.tidy();
      this._remember();
      this._check();
      if (readonly) {
        this.dirty = false;
        this._label();
        toast(`<b>${esc(MG.path.basename(path))}</b> is an example: change it as you like, and use <b>Save as…</b> to keep your version.`, null, 6000);
      }
      MG.bus.emit('studio:open', { path });
      return true;
    }
    async openDialog() {
      const list = [];
      for (const [p, e] of this.fs.entries) {
        if (e.kind === 'dir' || MG.app.pedKind(p) !== 'studio') continue;
        if (p.startsWith(this.home + '/') || p.startsWith('/data/examples/')) list.push({ p, e });
      }
      list.sort((a, b) => (a.p.startsWith('/data') - b.p.startsWith('/data')) || (b.e.mtime || 0) - (a.e.mtime || 0));
      const m = MG.modal('Open a drawing', '');
      const body = m.box.querySelector('.modal-b');
      const mine = list.filter((x) => !x.p.startsWith('/data/'));
      const ex = list.filter((x) => x.p.startsWith('/data/'));
      const row = (x) => {
        const b = h('button.st-pick', { type: 'button' }, h('b', MG.path.basename(x.p)), h('small', this.fs.pretty(MG.path.dirname(x.p)) + (x.e.mtime && !x.p.startsWith('/data/') ? ' · ' + new Date(x.e.mtime).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' }) : '')));
        b.addEventListener('click', () => {
          m.close();
          this.openFile(x.p);
        });
        return b;
      };
      body.appendChild(h('h4', 'Your drawings'));
      body.appendChild(mine.length ? h('div.st-picks', mine.map(row)) : h('p.muted', 'None yet. Save the drawing on show with Save as…, or open an example and save your own copy.'));
      body.appendChild(h('h4', 'Examples (read-only)'));
      body.appendChild(h('div.st-picks', ex.map(row)));
      const up = h('button.btn', { type: 'button', html: MG.icon('upload') + '<span>Open a drawing from my computer…</span>' });
      up.addEventListener('click', async () => {
        m.close();
        const paths = await MG.app.pickFiles(this.home + '/pedigrees', false);
        if (paths && paths[0]) this.openFile(paths[0]);
      });
      body.appendChild(h('div.prompt-actions', up));
    }
    recentMenu(anchor) {
      const items = [];
      const list = [];
      for (const [p, e] of this.fs.entries) if (e.kind !== 'dir' && p.startsWith(this.home + '/') && MG.app.pedKind(p) === 'studio') list.push([p, e.mtime || 0]);
      list.sort((a, b) => b[1] - a[1]);
      list.slice(0, 12).forEach(([p]) => items.push(['pedigree', (p === this.path ? '● ' : '') + this.fs.pretty(p), () => this.openFile(p)]));
      items.push(['openfolder', 'Open… (all drawings and the examples)', () => this.openDialog()]);
      if (this.path) items.push(['folder', 'Show this file in Files', () => MG.app.revealFile(this.path)]);
      MG.popmenu(anchor, items);
    }
    moreMenu(anchor) {
      MG.popmenu(anchor, [
        ['download', 'Download the drawing (.studio.json)', () => this.download()],
        ['folder', 'Show the file in Files', () => (this.path ? MG.app.revealFile(this.path) : toast('Save the drawing first (Save as…).', 'warn'))],
        ['help', 'Help: the Studio tab', () => MG.app.showHelp('h-studio')],
        ['help', 'Help: drawing a pedigree in Pedigree Studio', () => MG.app.showHelp('h-studio', { anchor: 'drawing' })]
      ]);
    }

    /* ---------------- saving ---------------- */
    _text() {
      return JSON.stringify(this.api.data(), null, 2) + '\n';
    }
    /** save in its file (asking for a name if it has none) → the path, or null */
    async save() {
      if (!this.api) return null;
      if (!this.path) return this.saveAs();
      return this._writeTo(this.path);
    }
    async saveAs() {
      if (!this.api) return null;
      const dir = this.home + '/pedigrees';
      const stem = this.path ? MG.path.basename(this.path).replace(/\.studio\.json$|\.json$/i, '') : 'family';
      let name = await MG.promptText('Save the drawing as', `A name for the file, in ${this.fs.pretty(dir)} (or a path of your own, such as ~/project/family.studio.json):`, stem + '.studio.json', 'Save');
      if (!name) return null;
      name = name.trim();
      if (!/\.json$/i.test(name)) name += '.studio.json';
      const p = this.fs.resolve(name.replace(/^~(?=\/|$)/, this.home), dir);
      if (!(p.startsWith(this.home + '/'))) {
        toast('Drawings can only be saved in your home folder (~).', 'warn');
        return null;
      }
      if (this.fs.exists(p) && p !== this.path && !(await MG.confirmBox('Replace the file?', `<p>There is already a file <b>${esc(this.fs.pretty(p))}</b>. Replace it with this drawing?</p>`, 'Replace', { danger: true }))) return null;
      return this._writeTo(p);
    }
    _writeTo(p) {
      try {
        this.fs.mkdirp(MG.path.dirname(p));
        this._saving = true;
        this.fs.writeText(p, this._text());
      } catch (e) {
        toast('Could not save: ' + esc(e.message), 'error');
        return null;
      } finally {
        this._saving = false;
      }
      this.path = p;
      this.base = sig(this.api.data());
      this._remember();
      this._check();
      this.api.status('Saved in ' + this.fs.pretty(p));
      toast(`Saved <b>${esc(this.fs.pretty(p))}</b>.`, 'ok', 2000);
      MG.bus.emit('studio:save', { path: p });
      return p;
    }
    download() {
      if (!this.api) return;
      const name = this.path ? MG.path.basename(this.path) : 'pedigree.studio.json';
      MG.downloadText(this._text(), name, 'application/json');
    }
    /** for the Tools tab: the drawing on show, saved in a file → its path (asks for a name if it has none); null if
        the person cancels or the drawing is empty */
    async snapshot() {
      await this.ready;
      if (this.api.isEmpty()) {
        toast('The drawing in the Studio tab is empty.', 'warn');
        return null;
      }
      this._check();
      if (this.path && !this.dirty) return this.path;
      if (this.path) return this._writeTo(this.path);
      toast('Save the drawing first: the tools work on files.', null, 3000);
      return this.saveAs();
    }
    async newDrawing() {
      if (!this.api || !(await this._mayDiscard('A new drawing'))) return;
      this.api.clear();
      this.path = null;
      this.base = null;
      this._remember();
      this._check();
    }
    tidy() {
      if (!this.api) return;
      if (this.api.isEmpty()) return toast('There is nothing to tidy yet.', null, 2000);
      this.api.tidy();
    }
    async toTools() {
      const p = await this.snapshot();
      if (p) MG.app.toolsFor(p);
    }
    /* the file was changed elsewhere (the terminal, a tool): show the new version if there are no edits here */
    _fsChanged(p, what) {
      if (p !== this.path || this._saving || !this.api) return;
      if (what === 'remove') {
        setTimeout(() => {
          if (!this.fs.exists(this.path)) {
            this.path = null;
            this.base = null;
            this._remember();
            this._check();
            toast('The drawing’s file was deleted or moved: use Save as… to keep the drawing.', 'warn', 7000);
          }
        }, 50);
        return;
      }
      if (what !== 'write') return;
      this._check();
      if (this.dirty) {
        toast(`<b>${esc(this.fs.pretty(p))}</b> was changed elsewhere. The drawing on show has edits of its own, so it is kept: Save writes it over the new version.`, 'warn', 9000);
        return;
      }
      this.fs.readText(p).then((text) => {
        let doc;
        try {
          doc = JSON.parse(text);
        } catch (e) {
          return;
        }
        if (!isDrawing(doc) || sig(doc) === this.base) return;
        this.api.load(doc, { message: 'The file changed: this is the new version' });
        this.base = sig(this.api.data());
        this._remember();
        this._check();
      });
    }
  }

  MG.StudioTab = StudioTab;
  /** the drawing on show, saved in a file → its path (for the Tools tab's "the drawing in Studio") */
  MG.app = MG.app || {};
  MG.app.studioSnapshot = async () => {
    // (the Studio tab is built when it is first shown: if it has not been, it is built now, and shown)
    if (!MG.app.studio) await MG.app.showWorkbench('studio');
    const S = await MG.app.waitFor(() => MG.app.studio, 8000);
    return S ? S.snapshot() : null;
  };
})();
