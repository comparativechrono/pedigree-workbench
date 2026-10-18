/* =====================================================================
   The Files tab: your files (~) and the examples (/data/examples) as a
   tree; an editor for text files (CodeMirror: Python, JSON, YAML,
   shell, Markdown); viewers for pictures, tables, PDF and HTML; and the
   ways in and out – upload (also by dragging files here), download,
   .zip – and to the other tabs: a drawing opens in Studio, pedigree
   files go to the Tools tab (MG.app.fileActions, in page-wb.js).
   Files are saved into the page's file system: the terminal and Python
   see a change at once, and it is kept in the browser.
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const { h, esc, bus, store, toast } = MG;

  const SMK_KEYWORDS = ['rule', 'checkpoint', 'input', 'output', 'params', 'log', 'benchmark', 'threads', 'resources', 'conda', 'shell', 'run', 'script', 'message', 'wildcard_constraints', 'priority', 'container', 'default_target', 'localrule', 'retries', 'configfile', 'include', 'localrules', 'ruleorder', 'onsuccess', 'onerror', 'onstart', 'envmodules', 'notebook', 'wrapper'];
  const SMK_BUILTINS = ['expand', 'collect', 'temp', 'protected', 'directory', 'ancient', 'touch', 'glob_wildcards', 'multiext', 'unpack', 'config', 'rules', 'workflow', 'min_version', 'report'];
  const EXAMPLES = '/data/examples';

  function modeFor(path) {
    const n = path.split('/').pop();
    if (/^Snakefile$|\.smk$|^snakefile$/i.test(n)) return { name: 'python', extra_keywords: SMK_KEYWORDS, extra_builtins: SMK_BUILTINS, singleLineStringErrors: false };
    if (/\.py$/i.test(n)) return { name: 'python', singleLineStringErrors: false };
    if (/\.(r|rprofile)$/i.test(n)) return 'r';
    if (/\.ya?ml$/i.test(n)) return 'yaml';
    if (/\.(sh|bash)$|^\.bashrc$/i.test(n)) return 'shell';
    if (/\.(md|markdown|rmd|qmd)$/i.test(n)) return 'markdown';
    if (/\.(js|mjs)$/i.test(n)) return 'javascript';
    if (/\.(json|ipynb|ga|cyjs|cx2|jsonl)$/i.test(n)) return { name: 'javascript', json: true };
    return null;
  }
  /** how a file is shown: in the editor ('text') or by a viewer */
  const kindOf = (path) => {
    const n = path.toLowerCase();
    if (/\.(png|jpe?g|gif|webp|bmp|ico)$/.test(n)) return 'image';
    if (/\.svg$/.test(n)) return 'svg';
    if (/\.html?$/.test(n)) return 'html';
    if (/\.pdf$/.test(n)) return 'pdf';
    if (/\.(tsv|csv|tab)$/.test(n)) return 'table';
    if (/\.(nwk|newick|tree|treefile|tre|nhx)$/.test(n)) return 'tree';
    if (/\.(afa|aln|clustal|msa|aln\.fasta|aln\.fa|mfa|sto|stockholm)$/.test(n)) return 'alignment';
    if (/\.(fa|fasta|fna|faa|ffn|fas|seq)$/.test(n)) return 'fasta';
    if (/\.ipynb$/.test(n)) return 'notebook';
    if (/\.(pdb|ent|cif|mmcif|bcif|mol2|sdf|pqr|gro|mmtf)(\.gz)?$/.test(n)) return 'structure';
    // (MACS3's NAME_peaks.xls is a table in plain text – tab-separated, with comment lines – not an Excel workbook)
    if (/_peaks\.xls$/.test(n)) return 'text';
    if (/\.(gz|bgz|bam|bai|cram|crai|bcf|csi|tbi|zip|pkl|npy|npz|xlsx?|docx?|pptx?|rds|rda|rdata|bt2|bt2l|mmi|sqlite|db|h5|parquet|tar|tgz|bw|bigwig|bb|bigbed|2bit|wasm)$/.test(n)) return 'binary';
    return 'text';
  };
  const ICON = (name, isDir) => {
    if (isDir) return 'folder';
    if (/\.(png|jpe?g|svg|gif|webp|pdf)$/i.test(name)) return 'image';
    if (/\.(bam|sam|cram)$/i.test(name)) return 'layers';
    if (/\.(vcf|bcf)(\.gz)?$/i.test(name)) return 'tag';
    if (/\.ipynb$/i.test(name)) return 'notebook';
    if (/\.studio\.json$/i.test(name)) return 'pedigree';
    if (/\.(ped|mped)$/i.test(name)) return 'table';
    if (/(_ga4gh-pedigree|_phenopackets-family|\.phenopacket)\.json$/i.test(name)) return 'tag';
    if (/\.(fa|fasta|fna|faa|fastq|fq)(\.gz)?$/i.test(name)) return 'dna';
    if (/\.(csv|tsv)$/i.test(name)) return 'table';
    if (/\.(py|r|sh|js|smk)$|^snakefile$/i.test(name)) return 'code';
    if (/\.(zip|tar|tgz|gz)$/i.test(name)) return 'zip';
    if (/\.(nwk|newick|tree|treefile)$/i.test(name)) return 'tree';
    if (/\.(sif|graphml|xgmml|gml|cyjs|cx2)$/i.test(name)) return 'network';
    return 'file';
  };

  class Editor {
    constructor(root, opts) {
      this.root = root;
      this.fs = opts.fs;
      this.home = this.fs.home;
      this.roots = [this.home, EXAMPLES];
      this.open = new Map(); // path -> {doc, saved, ro, entry}
      this.current = null;
      this.expanded = new Set(store.get('edExpanded', [this.home, this.home + '/notebooks']));
      this.showHidden = store.get('edHidden', false);
      this._build();
      this.fs.onChange((path, what) => this._fsChanged(path, what));
      this.renderTree();
      const last = store.get('edOpen', []);
      last.filter((p) => this.fs.exists(p) && kindOf(p) === 'text').forEach((p) => this._openText(p, { quiet: true, background: true }));
      const cur = store.get('edCurrent', null);
      if (cur && this.open.has(cur)) this.show(cur, { noFocus: true });
      else this._empty();
      this._usage();
    }

    _build() {
      const R = this.root;
      R.classList.add('ed');
      const btn = (icon, label, title, fn) => {
        const b = h('button.tbtn', { type: 'button', title, 'aria-label': label ? null : title, html: MG.icon(icon) + (label ? '<span>' + esc(label) + '</span>' : '') });
        b.addEventListener('click', fn);
        return b;
      };
      this.tree = h('div.ed-tree', { role: 'tree', 'aria-label': 'Files' });
      const treeBar = h(
        'div.ed-treebar',
        h('b', 'Files'),
        h('span.grow'),
        btn('upload', '', 'Upload files from your computer into the selected folder (or drag them here)', () => this.upload(false)),
        btn('plus', '', 'New file', () => this.newFile()),
        btn('folder', '', 'New folder', () => this.newFolder()),
        (this.hiddenBtn = btn('eye', '', 'Show hidden files (names that start with a dot)', () => this.toggleHidden()))
      );
      this.hiddenBtn.classList.toggle('on', this.showHidden);
      this.usageEl = h('div.ed-usage', { title: 'Your files are kept in this browser, on this computer' });
      this.side = h('aside.ed-side', treeBar, this.tree, this.usageEl);
      this.tabs = h('div.ed-tabs', { role: 'tablist' });
      this.saveBtn = btn('save', 'Save', 'Save (Ctrl+S)', () => this.save());
      this.pathEl = h('span.ed-path');
      this.actsEl = h('span.ed-acts');
      this.dlBtn = btn('download', '', 'Download this file to your computer', () => this.download());
      this.runBtn = btn('play', 'Run', '', () => this.runCurrent());
      this.runBtn.hidden = true;
      const bar = h('div.ed-bar', this.pathEl, h('span.grow'), this.actsEl, this.runBtn, this.dlBtn, this.saveBtn);
      this.cmHost = h('div.ed-cm');
      this.view = h('div.ed-view', { hidden: true });
      this.emptyEl = h('div.ed-empty');
      this.main = h('section.ed-main', this.tabs, bar, this.cmHost, this.view, this.emptyEl);
      R.append(this.side, this.main);
      this.cm = window.CodeMirror(this.cmHost, {
        value: '',
        lineNumbers: true,
        indentUnit: 4,
        tabSize: 4,
        indentWithTabs: false,
        matchBrackets: true,
        autoCloseBrackets: true,
        viewportMargin: 30,
        extraKeys: {
          'Ctrl-S': () => this.save(),
          'Cmd-S': () => this.save(),
          Tab: (cm) => (cm.somethingSelected() ? cm.indentSelection('add') : cm.replaceSelection(cm.getOption('indentUnit') === 2 ? '  ' : '    ', 'end')),
          'Shift-Tab': (cm) => cm.indentSelection('subtract'),
          'Ctrl-/': 'toggleComment',
          'Cmd-/': 'toggleComment'
        }
      });
      this.cm.on('change', () => this._dirtyCheck());
      this.cmHost.hidden = true;
      // files dragged from the computer: into the folder under the pointer (or the home folder)
      const over = (e) => {
        if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes('Files')) return;
        e.preventDefault();
        R.classList.add('dropping');
        const row = e.target.closest && e.target.closest('.ed-row');
        this.tree.querySelectorAll('.drop-on').forEach((x) => x.classList.remove('drop-on'));
        if (row) row.classList.add('drop-on');
      };
      R.addEventListener('dragover', over);
      R.addEventListener('dragleave', (e) => {
        if (!R.contains(e.relatedTarget)) {
          R.classList.remove('dropping');
          this.tree.querySelectorAll('.drop-on').forEach((x) => x.classList.remove('drop-on'));
        }
      });
      R.addEventListener('drop', async (e) => {
        R.classList.remove('dropping');
        this.tree.querySelectorAll('.drop-on').forEach((x) => x.classList.remove('drop-on'));
        if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
        e.preventDefault();
        const row = e.target.closest && e.target.closest('.ed-row');
        let folder = this.home;
        if (row && row.dataset.path && row.dataset.path.startsWith(this.home)) {
          const p = row.dataset.path;
          folder = this.fs.isDir(p) ? p : MG.path.dirname(p);
        } else if (!row) folder = this._baseDir();
        const files = await filesOfDrop(e.dataTransfer);
        const paths = await MG.project.addFiles(this.fs, folder, files);
        if (paths.length) {
          this.expanded.add(folder);
          toast(`Added <b>${paths.length}</b> file${paths.length === 1 ? '' : 's'} to ${esc(this.fs.pretty(folder))}.`, 'ok');
          if (paths.length === 1) this.reveal(paths[0]);
        }
      });
    }

    /* ---------------- the tree ---------------- */
    toggleHidden() {
      this.showHidden = !this.showHidden;
      store.set('edHidden', this.showHidden);
      this.hiddenBtn.classList.toggle('on', this.showHidden);
      this.renderTree();
    }
    renderTree() {
      clearTimeout(this._rt);
      const el = this.tree;
      const keep = el.scrollTop;
      el.innerHTML = '';
      const sel = this.current || this.viewPath;
      const row = (c, depth, label) => {
        const isDir = c.entry.kind === 'dir';
        const open = this.expanded.has(c.path);
        const r = h('div.ed-row' + (isDir ? '.dir' : '') + (c.path === sel ? '.on' : '') + (label ? '.root' : ''), { role: 'treeitem', tabindex: '0', title: c.path, dataset: { path: c.path }, style: { paddingLeft: 6 + depth * 14 + 'px' }, 'aria-expanded': isDir ? String(open) : null });
        r.appendChild(h('span.ed-caret', isDir ? (open ? '▾' : '▸') : ''));
        r.appendChild(h('span.ed-ic', { html: MG.icon(label ? (c.path === this.home ? 'folder' : 'book2') : ICON(c.name, isDir)) }));
        r.appendChild(h('span.ed-name', label || c.name));
        if (!isDir) r.appendChild(h('small.ed-size', MG.humanSize(this.fs.size(c.entry))));
        if (!label && (c.entry.readonly || c.entry.protected)) r.appendChild(h('span.ed-lock', { title: 'read-only', html: MG.icon('lock') }));
        if (c.entry.fresh && Date.now() - (c.entry.mtime || 0) < 60000) r.classList.add('fresh');
        const act = () => {
          if (isDir) {
            if (open) this.expanded.delete(c.path);
            else this.expanded.add(c.path);
            store.set('edExpanded', Array.from(this.expanded));
            this.renderTree();
          } else this.openFile(c.path);
        };
        r.addEventListener('click', act);
        r.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            act();
          } else if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) {
            e.preventDefault();
            this._menu(r, c);
          } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            const rows = Array.from(el.querySelectorAll('.ed-row'));
            const n = rows[rows.indexOf(r) + (e.key === 'ArrowDown' ? 1 : -1)];
            if (n) n.focus();
          }
        });
        r.addEventListener('contextmenu', (e) => {
          e.preventDefault();
          this._menu(r, c);
        });
        const more = h('button.ed-more', { type: 'button', title: 'What to do with ' + (label || c.name), 'aria-label': 'Actions', html: MG.icon('dots') });
        more.addEventListener('click', (e) => {
          e.stopPropagation();
          this._menu(r, c);
        });
        r.appendChild(more);
        el.appendChild(r);
        return open;
      };
      const walk = (path, depth) => {
        this.fs
          .list(path)
          .filter((c) => this.showHidden || (!c.name.startsWith('.') && !c.entry.hidden))
          .sort((a, b) => ((a.entry.kind === 'dir') === (b.entry.kind === 'dir') ? a.name.localeCompare(b.name) : a.entry.kind === 'dir' ? -1 : 1))
          .forEach((c) => {
            if (row(c, depth) && c.entry.kind === 'dir') walk(c.path, depth + 1);
          });
      };
      for (const r of this.roots) {
        const e = this.fs.get(r);
        if (!e) continue;
        const label = r === this.home ? 'My files  (~)' : 'Examples  (read-only)';
        if (row({ path: r, name: r, entry: e }, 0, label)) walk(r, 1);
      }
      if (this.fs.list(this.home).length === 0 && this.expanded.has(this.home)) el.insertBefore(h('p.ed-hint', 'You don’t have any files yet. Upload some with ↑ above, drag them here, or copy an example.'), el.children[1] || null);
      el.scrollTop = keep;
    }
    /** show a file or folder in the tree (open its folders, select it) */
    reveal(path) {
      let d = MG.path.dirname(path);
      while (d && d !== '/') {
        this.expanded.add(d);
        d = MG.path.dirname(d);
      }
      if (this.fs.isDir(path)) this.expanded.add(path);
      store.set('edExpanded', Array.from(this.expanded));
      if (!this.fs.isDir(path)) this.openFile(path);
      else this.renderTree();
      setTimeout(() => {
        const r = this.tree.querySelector(`.ed-row[data-path="${CSS.escape(path)}"]`);
        if (r) {
          r.scrollIntoView({ block: 'center' });
          r.classList.add('flash-attn');
          setTimeout(() => r.classList.remove('flash-attn'), 1400);
        }
      }, 60);
    }
    _menu(rowEl, c) {
      const p = c.path;
      const e = c.entry;
      const mine = p === this.home || p.startsWith(this.home + '/');
      const isDir = e.kind === 'dir';
      const items = [];
      if (!isDir) {
        items.push(['text', 'Open', () => this.openFile(p)]);
        const k = kindOf(p);
        if (k !== 'text' && k !== 'binary' && k !== 'notebook') items.push(['code', 'Open as text', () => this._openText(p)]);
        if (/\.ipynb$/i.test(p)) items.push(['notebook', 'Open in the Notebook tab', () => MG.app.openFile(p)]);
        for (const [icon, label, , fn] of MG.app.fileActions ? MG.app.fileActions(p) : []) items.push([icon, label, fn]);
        if (/\.zip$/i.test(p) && mine) items.push(['zip', 'Unpack (unzip) here', () => this.unzip(p)]);
        items.push(['download', 'Download', () => this.download(p)]);
      } else {
        if (mine) {
          items.push(['upload', 'Upload files here…', () => this.upload(false, p)]);
          items.push(['upload', 'Upload a folder here…', () => this.upload(true, p)]);
          items.push(['plus', 'New file here…', () => this.newFile(p)]);
          items.push(['folder', 'New folder here…', () => this.newFolder(p)]);
        }
        items.push(['zip', 'Download as a .zip', () => MG.project.download(p, (MG.path.basename(p) || 'files') + '.zip')]);
        items.push(['terminal', 'Open in the Terminal (cd)', async () => {
          await MG.app.showWorkbench('terminal');
          MG.app.term.type('cd ' + shq(this.fs.pretty(p)), true);
        }]);
      }
      if (!mine) items.push(['copy', 'Copy to my files', () => this.copyToHome(p)]);
      if (mine && p !== this.home) {
        items.push(['rename', 'Rename…', () => this.rename(p)]);
        if (!isDir) items.push(['copy', 'Duplicate', () => this.duplicate(p)]);
      }
      items.push(['link', 'Copy the path', () => MG.copyText(this.fs.pretty(p)).then(() => toast('Copied ' + esc(this.fs.pretty(p)), null, 1500))]);
      if (mine && p !== this.home && !e.protected) items.push(['trash', 'Delete…', () => this.remove(p)]);
      MG.popmenu(rowEl.querySelector('.ed-more') || rowEl, items);
    }
    _fsChanged(path, what) {
      clearTimeout(this._rt);
      this._rt = setTimeout(() => {
        this.renderTree();
        this._usage();
      }, 150);
      const o = this.open.get(path);
      if (!o) {
        if (what === 'rename' || what === 'write') this._refreshView(path);
        return;
      }
      if (what === 'remove') {
        o.gone = true;
        if (this.current === path) this._markGone();
        return;
      }
      if (what === 'write' || what === 'rename' || what === 'chmod') this._reloadFromFs(path);
    }
    async _usage() {
      clearTimeout(this._ut);
      this._ut = setTimeout(async () => {
        let n = 0, bytes = 0;
        for (const [p, e] of this.fs.entries) {
          if (e.kind === 'dir' || !p.startsWith(this.home + '/')) continue;
          n++;
          bytes += this.fs.size(e);
        }
        const u = await MG.project.usage();
        const kept = MG.project.ok ? 'kept in this browser' : 'NOT kept, perhaps because this is a private window';
        this.usageEl.innerHTML = `${MG.icon(MG.project.ok ? 'lock' : 'warning')}<span>${n} file${n === 1 ? '' : 's'}, ${MG.humanSize(bytes)}B · ${kept}${u && u.quota ? ` · room for about ${MG.humanSize(Math.max(0, u.quota - u.usage))}B more` : ''}</span>`;
        this.usageEl.classList.toggle('bad', !MG.project.ok);
      }, 300);
    }

    /* ---------------- opening files ---------------- */
    async openFile(path, opts = {}) {
      path = this.fs.resolve(path);
      const e = this.fs.get(path);
      if (!e) {
        if (opts.create) {
          this.fs.writeText(path, '');
          return this._openText(path, opts);
        }
        toast('There’s no file at ' + esc(path), 'error');
        return;
      }
      if (e.kind === 'dir') return this.reveal(path);
      const k = kindOf(path);
      if (k === 'text' || opts.asText) return this._openText(path, opts);
      return this.showView(path);
    }
    async _openText(path, opts = {}) {
      const e = this.fs.get(path);
      if (!e) return;
      let text = '';
      const size = this.fs.size(e);
      let truncated = false;
      if (size > 50e6) {
        toast(`${esc(this.fs.pretty(path))} is ${MG.humanSize(size)}B, which is too large for the editor. Look at it in the Terminal with head, less or grep.`, 'warn', 7000);
        return this.showView(path, { tooBig: true });
      }
      try {
        text = await this.fs.readText(path);
      } catch (err) {
        if (!opts.quiet) toast('Couldn’t read ' + esc(path), 'error');
        return;
      }
      if (size > 400000) {
        const L = text.split('\n');
        if (L.length > 400) {
          text = L.slice(0, 400).join('\n');
          truncated = true;
        }
      }
      const ro = !!(e.readonly || e.protected || truncated || !path.startsWith(this.home + '/'));
      let o = this.open.get(path);
      if (!o) {
        const doc = window.CodeMirror.Doc(text, modeFor(path));
        o = { doc, saved: text, ro, truncated, entry: e };
        this.open.set(path, o);
      } else if (!o.dirty) {
        o.saved = text;
        o.doc.setValue(text);
        o.dirty = false;
        o.ro = ro;
        o.entry = e;
      }
      this._persist();
      if (!opts.background) this.show(path, opts);
    }
    _persist() {
      store.set('edOpen', Array.from(this.open.keys()).filter((p) => p.startsWith(this.home + '/')));
      store.set('edCurrent', this.current);
    }
    show(path, opts = {}) {
      const o = this.open.get(path);
      if (!o) return;
      this.current = path;
      this.viewPath = null;
      this.view.hidden = true;
      this._closeView();
      this.emptyEl.hidden = true;
      this.cmHost.hidden = false;
      this.cm.swapDoc(o.doc);
      this.cm.setOption('readOnly', o.ro);
      this.cm.setOption('mode', modeFor(path));
      this.cm.setOption('indentUnit', /\.r$/i.test(path) ? 2 : 4);
      this.saveBtn.hidden = o.ro;
      this.pathEl.innerHTML = esc(this.fs.pretty(path)) + (o.ro ? ' <span class="pill small">read-only' + (o.truncated ? ', showing the first 400 lines' : '') + '</span>' : '');
      this._acts(path);
      this._runBtnFor(path);
      this._renderTabs();
      this._persist();
      setTimeout(() => {
        this.cm.refresh();
        if (opts.line) {
          const ln = Math.max(0, opts.line - 1);
          this.cm.setCursor({ line: ln, ch: 0 });
          this.cm.scrollIntoView({ line: ln, ch: 0 }, 80);
          this.cm.addLineClass(ln, 'background', 'cm-flash');
          setTimeout(() => this.cm.removeLineClass(ln, 'background', 'cm-flash'), 2200);
        }
        if (!opts.noFocus) this.cm.focus();
      }, 20);
      this.renderTree();
      bus.emit('editor:open', { path, name: path.split('/').pop() });
    }
    /** buttons for the file on show: to the other tabs */
    _acts(path) {
      const A = this.actsEl;
      A.innerHTML = '';
      const add = (icon, label, title, fn) => {
        const b = h('button.tbtn', { type: 'button', title, html: MG.icon(icon) + '<span>' + esc(label) + '</span>' });
        b.addEventListener('click', fn);
        A.appendChild(b);
      };
      if (!path) return;
      if (!(path === this.home || path.startsWith(this.home + '/'))) add('copy', 'Copy to my files', 'Make your own copy of this file in ~/examples, so you can change it', () => this.copyToHome(path));
      if (/\.ipynb$/i.test(path)) add('notebook', 'Open as a notebook', 'Open in the Notebook tab', () => MG.app.openFile(path));
      // a drawing → Studio; pedigree files → the Tools tab (saved first, so that what you see is what is used)
      for (const [icon, label, title, fn] of MG.app.fileActions ? MG.app.fileActions(path) : [])
        add(icon, label, title, () => {
          if (this.current === path && this.isDirty(path)) this.save();
          fn();
        });
    }
    _runBtnFor(path) {
      const n = path.split('/').pop();
      let label = null;
      if (/\.py$/i.test(n)) label = 'Run with python';
      else if (/\.sh$/i.test(n)) label = 'Run with bash';
      this.runBtn.hidden = !label || !path.startsWith(this.home + '/');
      if (label) {
        this.runBtn.querySelector('span').textContent = label;
        this.runBtn.title = label + ' in the Terminal (saves the file first)';
      }
    }
    async runCurrent() {
      const p = this.current;
      if (!p) return;
      if (this.isDirty(p)) this.save();
      const n = p.split('/').pop();
      const dir = MG.path.dirname(p);
      const cd = MG.app.fs.cwd === dir ? '' : `cd ${shq(this.fs.pretty(dir))} && `;
      let cmd;
      if (/\.py$/i.test(n)) cmd = `${cd}python ${shq(n)}`;
      else if (/\.sh$/i.test(n)) cmd = `${cd}bash ${shq(n)}`;
      else return;
      await MG.app.showWorkbench('terminal');
      await MG.app.term.type(cmd, true);
    }
    _renderTabs() {
      this.tabs.innerHTML = '';
      for (const [p, o] of this.open) {
        const t = h('div.ed-tab' + (p === this.current ? '.on' : '') + (o.dirty ? '.dirty' : '') + (o.gone ? '.gone' : ''), { role: 'tab', title: p });
        const lab = h('button.ed-tab-l', { type: 'button' }, p.split('/').pop());
        lab.addEventListener('click', () => this.show(p));
        const x = h('button.ed-tab-x', { type: 'button', 'aria-label': 'Close ' + p.split('/').pop(), html: o.dirty ? '●' : '×' });
        x.addEventListener('click', (ev) => {
          ev.stopPropagation();
          this.close(p);
        });
        t.append(lab, x);
        this.tabs.appendChild(t);
      }
    }
    close(p) {
      const o = this.open.get(p);
      if (!o) return;
      if (o.dirty && !o.gone && !window.confirm(`${p.split('/').pop()} has unsaved changes. Close it and lose them?`)) return;
      this.open.delete(p);
      if (this.current === p) {
        const next = Array.from(this.open.keys()).pop();
        if (next) this.show(next);
        else this._empty();
      } else this._renderTabs();
      this._persist();
    }
    _empty() {
      this.current = null;
      this.viewPath = null;
      this.cmHost.hidden = true;
      this.view.hidden = true;
      this._closeView();
      this.emptyEl.hidden = false;
      this.saveBtn.hidden = true;
      this.runBtn.hidden = true;
      this.actsEl.innerHTML = '';
      this.pathEl.textContent = '';
      this.emptyEl.innerHTML = `<div class="ex-empty ed-welcome">${MG.icon('folder')}<h3>Your files</h3>
        <p>Click a file on the left to open it. Text files, such as PED files, terms files and GA4GH or Phenopackets JSON, open in the editor. Pictures, tables and PDFs are shown here, and notebooks open in the Notebook tab. A Pedigree Studio drawing has a button to open it in Studio, and pedigree files have buttons that take them to the Tools tab.</p>
        <p>Add files from your computer with <b>↑ Upload</b> or by dragging them onto this tab. Right-click a file, or use its ⋯ button, for more options.</p></div>`;
      const b = h('button.btn', { type: 'button', html: MG.icon('upload') + '<span>Upload files</span>' });
      b.addEventListener('click', () => this.upload(false));
      this.emptyEl.firstChild.appendChild(b);
      this._renderTabs();
      this._persist();
    }
    isDirty(p) {
      const o = this.open.get(p);
      return !!(o && o.dirty);
    }
    dirtyPaths() {
      return Array.from(this.open.entries()).filter(([, o]) => o.dirty && !o.gone).map(([p]) => p);
    }
    /** add text at the end of a file (opening it), save it and highlight the new lines → first new line number */
    async appendText(path, text) {
      if (!this.open.get(path)) await this.openFile(path, { create: true, noFocus: true, asText: true });
      else this.show(path, { noFocus: true });
      const o = this.open.get(path);
      if (!o || o.ro) return 0;
      const doc = o.doc;
      const last = doc.lastLine();
      const tail = doc.getLine(last);
      const body = doc.getValue();
      const sep = !body.trim() ? '' : tail === '' ? (doc.getLine(Math.max(0, last - 1)) === '' ? '' : '\n') : '\n\n';
      const add = sep + text.replace(/\s+$/, '') + '\n';
      const first = last + (sep.match(/\n/g) || []).length;
      doc.replaceRange(add, { line: last, ch: tail.length });
      const n = text.replace(/\s+$/, '').split('\n').length;
      this.save();
      for (let i = first; i < first + n; i++) this.cm.addLineClass(i, 'background', 'cm-flash');
      setTimeout(() => {
        for (let i = first; i < first + n; i++) this.cm.removeLineClass(i, 'background', 'cm-flash');
      }, 2600);
      this.cm.scrollIntoView({ line: Math.min(doc.lastLine(), first + n), ch: 0 }, 60);
      return first + 1;
    }
    _dirtyCheck() {
      const o = this.open.get(this.current);
      if (!o) return;
      const d = o.doc.getValue() !== o.saved;
      if (d !== !!o.dirty) {
        o.dirty = d;
        this._renderTabs();
      }
    }
    save() {
      const p = this.current;
      const o = this.open.get(p);
      if (!o || o.ro) return;
      const text = o.doc.getValue();
      const old = this.fs.get(p);
      if (old && old.kind === 'dir') {
        toast('Can’t save ' + esc(p) + ', because it’s a folder', 'error');
        return;
      }
      if (!this.fs.isDir(MG.path.dirname(p))) this.fs.mkdirp(MG.path.dirname(p));
      o.saving = true;
      this.fs.writeText(p, text, old && old.mode ? { mode: old.mode } : {});
      o.saving = false;
      o.entry = this.fs.get(p);
      o.saved = text;
      o.dirty = false;
      o.gone = false;
      this._renderTabs();
      this.pathEl.innerHTML = esc(this.fs.pretty(p));
      toast('Saved ' + esc(this.fs.pretty(p)), null, 1600);
      bus.emit('editor:save', { path: p, name: p.split('/').pop(), text });
    }
    async _reloadFromFs(p) {
      const o = this.open.get(p);
      if (!o || o.saving) return;
      const e = this.fs.get(p);
      if (!e || e === o.entry) return;
      o.entry = e;
      o.gone = false;
      if (e.kind === 'dir') return;
      let text;
      try {
        text = await this.fs.readText(p);
      } catch (err) {
        return;
      }
      if (text === o.saved) return;
      if (o.dirty) {
        o.conflict = true;
        if (this.current === p) toast(esc(p.split('/').pop()) + ' was changed in another tab, for example by the terminal or a notebook. Your unsaved edits are kept, but saving will overwrite the new version.', 'warn', 7000);
        return;
      }
      const cur = this.current === p ? this.cm.getCursor() : null;
      o.saved = text;
      o.doc.setValue(text);
      o.dirty = false;
      if (cur) this.cm.setCursor(cur);
      this._renderTabs();
    }
    _markGone() {
      this.pathEl.innerHTML = esc(this.fs.pretty(this.current)) + ' <span class="pill small warn">deleted, but Save will write it again</span>';
      this._renderTabs();
    }

    /* ---------------- viewers ---------------- */
    async showView(path, opts = {}) {
      const e = this.fs.get(path);
      if (!e) return;
      const k = kindOf(path);
      if (k === 'notebook' && !opts.force) return MG.app.openFile(path);
      this.current = null;
      this.cmHost.hidden = true;
      this.emptyEl.hidden = true;
      this.view.hidden = false;
      this.saveBtn.hidden = true;
      this.runBtn.hidden = true;
      this.viewPath = path;
      this.pathEl.innerHTML = esc(this.fs.pretty(path)) + ` <span class="pill small">${esc(MG.humanSize(this.fs.size(e)))}B</span>`;
      this._acts(path);
      this._renderTabs();
      this.renderTree();
      await this._renderView(path, opts);
      bus.emit('editor:view', { path, name: path.split('/').pop(), kind: k });
    }
    async _refreshView(path) {
      if (this.view.hidden || this.viewPath !== path) return;
      await this._renderView(path);
    }
    /** what a viewer holds (a PDF document and its worker, a picture's URL): let go of it */
    _closeView() {
      this._viewToken = (this._viewToken || 0) + 1; // (a view still being made is not shown)
      if (this._pdf) {
        this._pdf.destroy();
        this._pdf = null;
      }
      if (this._url) URL.revokeObjectURL(this._url);
      this._url = null;
      this.view.classList.remove('pdf');
    }
    async _renderView(path, opts = {}) {
      const V = this.view;
      // (a PDF shown again – it was written anew – opens at the same page and zoom)
      this._closeView();
      V.innerHTML = '';
      const k = opts.tooBig ? 'binary' : kindOf(path);
      // (two views asked for one after the other: only the last one is shown)
      const token = (this._viewToken = (this._viewToken || 0) + 1);
      const stale = () => token !== this._viewToken;
      const textBtn = (label = 'Open as text') => {
        const b = h('button.btn.small', { type: 'button' }, label);
        b.addEventListener('click', () => this._openText(path));
        return b;
      };
      try {
        if (k === 'image') {
          const blob = await this.fs.toBlob(path);
          if (stale()) return;
          this._url = URL.createObjectURL(blob);
          V.appendChild(h('div.ed-img', h('img', { src: this._url, alt: path.split('/').pop() })));
        } else if (k === 'svg') {
          const text = await this.fs.readText(path);
          if (stale()) return;
          this._url = URL.createObjectURL(new Blob([text], { type: 'image/svg+xml' }));
          V.appendChild(h('div.ed-img.svg', h('img', { src: this._url, alt: path.split('/').pop() })));
          V.appendChild(h('p.ed-note', textBtn('Show the SVG text')));
        } else if (k === 'pdf') {
          // the browser's own PDF viewer
          const blob = await this.fs.toBlob(path);
          if (stale()) return;
          V.classList.add('pdf');
          this._url = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }));
          V.appendChild(h('iframe.ed-frame', { src: this._url, title: path.split('/').pop() }));
        } else if (k === 'html') {
          const text = await this.fs.readText(path);
          if (stale()) return;
          // (no scripts: an HTML file could come from anywhere – reports such as fastp's work without them)
          const fr = h('iframe.ed-frame', { sandbox: '', title: path.split('/').pop() });
          fr.srcdoc = text;
          V.appendChild(fr);
          V.appendChild(h('p.ed-note.muted', 'For safety, this page is shown without its scripts. To see it in full, download it and open it in your browser.'));
        } else if (k === 'table') {
          const text = await this.fs.readText(path);
          if (stale()) return;
          V.appendChild(tableView(text, /\.csv$/i.test(path) ? ',' : '\t'));
          V.appendChild(h('p.ed-note', textBtn()));
        } else if (k === 'fasta') {
          const text = await this.fs.readText(path);
          if (stale()) return;
          V.appendChild(fastaView(text, path));
          V.appendChild(h('p.ed-note', textBtn()));
        } else if (k === 'alignment') {
          const text = await this.fs.readText(path);
          if (stale()) return;
          const view = alignmentView(text);
          V.appendChild(view || h('p.muted', 'This file couldn’t be read as an alignment in FASTA or Clustal format.'));
          V.appendChild(h('p.ed-note', textBtn()));
        } else if (k === 'tree') {
          const text = await this.fs.readText(path);
          if (stale()) return;
          V.appendChild(treeView(text));
          V.appendChild(h('p.ed-note', textBtn()));
        } else if (k === 'notebook' || k === 'structure') {
          V.appendChild(h('p', textBtn()));
        } else {
          const n = path.split('/').pop();
          const rel = MG.app.fs.cwd && path.startsWith(MG.app.fs.cwd + '/') ? path.slice(MG.app.fs.cwd.length + 1) : this.fs.pretty(path);
          let tips = [`ls -l ${shq(rel)}`];
          if (/\.zip$/i.test(n)) tips = [`unzip -l ${shq(rel)}`];
          else if (/\.(tar|tgz|tar\.gz)$/i.test(n)) tips = [`tar -tzf ${shq(rel)} | head`];
          const box = h('div.ex-empty', h('h3', opts.tooBig ? 'A large file' : 'A compressed or binary file'), h('p', `${n} is ${opts.tooBig ? 'too large to show here' : 'not plain text, so it isn’t shown here'}. Look inside it with a program in the Terminal:`));
          tips.forEach((tip) => {
            const b = h('button.btn.small.ed-tip', { type: 'button' }, 'Run: ' + tip);
            b.addEventListener('click', async () => {
              await MG.app.showWorkbench('terminal');
              MG.app.term.type(tip, true);
            });
            box.appendChild(b);
          });
          V.appendChild(box);
        }
      } catch (err) {
        if (stale()) return;
        V.appendChild(h('p.muted', 'Couldn’t show this file: ' + err.message));
      }
    }

    /* ---------------- file operations ---------------- */
    _baseDir() {
      const p = this.current || this.viewPath;
      if (p && p.startsWith(this.home + '/')) return MG.path.dirname(p);
      return MG.app.fs.cwd.startsWith(this.home) ? MG.app.fs.cwd : this.home;
    }
    async upload(dir, folder) {
      folder = folder || this._baseDir();
      const paths = await MG.app.pickFiles(folder, dir);
      if (paths && paths.length) {
        this.expanded.add(folder);
        store.set('edExpanded', Array.from(this.expanded));
        if (paths.length === 1) this.reveal(paths[0]);
        else this.renderTree();
      }
    }
    async unzip(p) {
      const folder = MG.path.dirname(p);
      try {
        const out = await MG.project.unzip(this.fs, p, folder);
        toast(`Unpacked ${out.length} file${out.length === 1 ? '' : 's'} into ${esc(this.fs.pretty(folder))}.`, 'ok');
        this.expanded.add(folder);
        this.renderTree();
      } catch (e) {
        toast('Couldn’t unpack it: ' + esc(e.message), 'error');
      }
    }
    async _ask(title, label, value, ok) {
      return (MG.promptText ? await MG.promptText(title, label, value, ok) : window.prompt(label, value)) || null;
    }
    async newFile(base) {
      base = base || this._baseDir();
      const name = await this._ask('New file', 'Name of the new file (in ' + this.fs.pretty(base) + '):', 'new_file.txt', 'Create');
      if (!name) return;
      const abs = this.fs.resolve(name, base);
      if (!abs.startsWith(this.home + '/')) return toast('Files can only be made in your home folder.', 'warn');
      if (this.fs.exists(abs)) return this.openFile(abs);
      this.fs.mkdirp(MG.path.dirname(abs));
      this.fs.writeText(abs, '');
      this.expanded.add(MG.path.dirname(abs));
      this.openFile(abs, { asText: true });
    }
    async newFolder(base) {
      base = base || this._baseDir();
      const name = await this._ask('New folder', 'Name of the new folder (in ' + this.fs.pretty(base) + '):', 'new_folder', 'Create');
      if (!name) return;
      const abs = this.fs.resolve(name, base);
      if (!abs.startsWith(this.home + '/')) return toast('Folders can only be made in your home folder.', 'warn');
      this.fs.mkdirp(abs);
      this.expanded.add(abs);
      this.expanded.add(base);
      this.renderTree();
    }
    async rename(p) {
      const name = await this._ask('Rename', 'New name for ' + MG.path.basename(p) + ':', MG.path.basename(p), 'Rename');
      if (!name || name === MG.path.basename(p)) return;
      if (/[\/\\]/.test(name)) return toast('A name can’t contain /. To move a file, use mv in the Terminal.', 'warn');
      const to = MG.path.dirname(p) + '/' + name;
      if (this.fs.exists(to)) return toast(`There’s already a ${esc(name)} here.`, 'warn');
      const dirty = this.open.get(p);
      this.fs.rename(p, to);
      if (dirty) {
        this.open.delete(p);
        this._openText(to, { quiet: true, background: this.current !== p });
      }
      if (this.expanded.has(p)) {
        this.expanded.delete(p);
        this.expanded.add(to);
      }
      toast(`Renamed to <b>${esc(name)}</b>.`, 'ok', 1800);
    }
    duplicate(p) {
      const dir = MG.path.dirname(p);
      const base = MG.path.basename(p);
      const m = /^(.*?)(\.[^.]*)?$/.exec(base);
      let to = `${dir}/${m[1]}-copy${m[2] || ''}`;
      for (let i = 2; this.fs.exists(to); i++) to = `${dir}/${m[1]}-copy${i}${m[2] || ''}`;
      this.fs.copy(p, to);
      this.reveal(to);
    }
    copyToHome(p) {
      const rel = p.startsWith(EXAMPLES + '/') ? p.slice(EXAMPLES.length + 1) : MG.path.basename(p);
      const dest = this.home + '/examples/' + rel;
      if (this.fs.isDir(p)) {
        for (const [q, e] of Array.from(this.fs.entries)) if (q.startsWith(p + '/') && e.kind !== 'dir') this.fs.copy(q, dest + q.slice(p.length));
      } else this.fs.copy(p, dest);
      toast(`Copied to <b>${esc(this.fs.pretty(dest))}</b>. It’s your own copy, so you can change it.`, 'ok');
      this.reveal(dest);
    }
    remove(p) {
      const e = this.fs.get(p);
      if (!e) return;
      const n = e.kind === 'dir' ? Array.from(this.fs.entries.keys()).filter((k) => k.startsWith(p + '/')).length : 0;
      const m = MG.modal('Delete?', `<p>Delete <b>${esc(this.fs.pretty(p))}</b>${e.kind === 'dir' ? ` and everything in it (${n} item${n === 1 ? '' : 's'})` : ''}? You can’t undo this.</p><div class="prompt-actions"><button class="btn" data-x="no" type="button">Cancel</button><button class="btn danger" data-x="yes" type="button">Delete</button></div>`);
      m.box.querySelector('[data-x="no"]').addEventListener('click', () => m.close());
      m.box.querySelector('[data-x="yes"]').addEventListener('click', () => {
        m.close();
        this.fs.remove(p);
        for (const q of Array.from(this.open.keys())) {
          if (q === p || q.startsWith(p + '/')) {
            this.open.get(q).dirty = false;
            this.close(q);
          }
        }
        if (this.viewPath && (this.viewPath === p || this.viewPath.startsWith(p + '/'))) this._empty();
      });
    }
    async download(p) {
      p = p || this.current || this.viewPath;
      if (!p) return;
      if (this.fs.isDir(p)) return MG.project.download(p, (MG.path.basename(p) || 'files') + '.zip');
      try {
        MG.downloadBlob(await this.fs.toBlob(p), p.split('/').pop());
        bus.emit('file:download', { path: p });
      } catch (err) {
        toast(esc(err.message), 'error');
      }
    }
    shown() {
      if (!this.cmHost.hidden) this.cm.refresh();
      this._usage();
    }
  }

  const shq = (s) => (/^[\w~@%+=:,./-]+$/.test(s) ? s : "'" + String(s).replace(/'/g, "'\\''") + "'");

  /** the files of a drop – folders too (webkitGetAsEntry), with their paths */
  async function filesOfDrop(dt) {
    const items = Array.from(dt.items || []);
    const entries = items.map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null)).filter(Boolean);
    if (!entries.length || !entries.some((e) => e.isDirectory)) return Array.from(dt.files);
    const out = [];
    const walk = (entry, prefix) =>
      new Promise((resolve) => {
        if (entry.isFile) {
          entry.file(
            (f) => {
              try {
                Object.defineProperty(f, 'relativePath', { value: prefix + f.name });
              } catch (e) {
                /* read-only */
              }
              out.push(f);
              resolve();
            },
            () => resolve()
          );
        } else if (entry.isDirectory) {
          const reader = entry.createReader();
          const all = [];
          const more = () =>
            reader.readEntries(
              async (batch) => {
                if (!batch.length) {
                  for (const c of all) await walk(c, prefix + entry.name + '/');
                  resolve();
                } else {
                  all.push(...batch);
                  more();
                }
              },
              () => resolve()
            );
          more();
        } else resolve();
      });
    for (const e of entries) await walk(e, '');
    return out;
  }

  /* ---------------- tables ---------------- */
  function splitRow(line, sep) {
    if (sep === '\t' || line.indexOf('"') < 0) return line.split(sep);
    const out = [];
    let cur = '', q = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (q) {
        if (ch === '"' && line[i + 1] === '"') {
          cur += '"';
          i++;
        } else if (ch === '"') q = false;
        else cur += ch;
      } else if (ch === '"') q = true;
      else if (ch === sep) {
        out.push(cur);
        cur = '';
      } else cur += ch;
    }
    out.push(cur);
    return out;
  }
  function tableView(text, sep) {
    const lines = text.split(/\r?\n/).filter((l) => l.length && !l.startsWith('##'));
    const rows = lines.slice(0, 1001).map((l) => splitRow(l, sep));
    const t = h('table.table.small.ed-table');
    const head = rows[0] || [];
    const thead = h('thead', h('tr', head.map((c, j) => {
      const th = h('th', { title: 'Click to sort' }, c);
      th.addEventListener('click', () => sortBy(j, th));
      return th;
    })));
    const tbody = h('tbody');
    const body = rows.slice(1);
    const fill = () => {
      tbody.innerHTML = '';
      body.forEach((r) => tbody.appendChild(h('tr', r.map((c) => h('td', c)))));
    };
    let dir = 1, by = -1;
    const sortBy = (j, th) => {
      dir = by === j ? -dir : 1;
      by = j;
      const num = body.every((r) => r[j] === '' || r[j] == null || !isNaN(Number(r[j])));
      body.sort((a, b) => (num ? (Number(a[j]) - Number(b[j])) * dir : String(a[j] || '').localeCompare(String(b[j] || '')) * dir));
      thead.querySelectorAll('th').forEach((x) => x.removeAttribute('data-sort'));
      th.dataset.sort = dir > 0 ? '▲' : '▼';
      fill();
    };
    fill();
    t.append(thead, tbody);
    const box = h('div.ed-tablebox', t);
    const info = h('p.muted.small', lines.length > 1001 ? `The first 1,000 of ${(lines.length - 1).toLocaleString('en-GB')} rows · ${head.length} columns. Click a column name to sort. In a notebook, you can read the file with pandas.read_csv.` : `${(lines.length - 1).toLocaleString('en-GB')} rows · ${head.length} columns. Click a column name to sort.`);
    return h('div', info, box);
  }

  /* ---------------- FASTA ---------------- */
  function parseFasta(text) {
    const seqs = [];
    let cur = null;
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.trim();
      if (!line) continue;
      if (line.startsWith('>')) {
        cur = { name: line.slice(1).split(/\s+/)[0], desc: line.slice(1), seq: '' };
        seqs.push(cur);
      } else if (cur) cur.seq += line.replace(/\s+/g, '');
    }
    return seqs;
  }
  function fastaView(text, path) {
    const seqs = parseFasta(text);
    const box = h('div.ed-fasta');
    if (!seqs.length) return h('p.muted', 'No sequences were found. A FASTA file has lines that start with >.');
    const dna = seqs.every((s) => /^[ACGTUNRYSWKMBDHV\-*.]*$/i.test(s.seq));
    const total = seqs.reduce((n, s) => n + s.seq.replace(/[-.]/g, '').length, 0);
    box.appendChild(h('p', h('b', `${seqs.length.toLocaleString('en-GB')} ${dna ? 'DNA/RNA' : 'protein'} sequence${seqs.length === 1 ? '' : 's'}`), ` · ${total.toLocaleString('en-GB')} ${dna ? 'bases' : 'residues'} in all`));
    const t = h('table.table.small.ed-table');
    t.appendChild(h('thead', h('tr', h('th', 'Name'), h('th', 'Length'), dna ? h('th', 'GC %') : null, h('th', 'Description'), h('th', 'Start'))));
    const tb = h('tbody');
    seqs.slice(0, 500).forEach((s) => {
      const len = s.seq.replace(/[-.]/g, '').length;
      const gc = dna && len ? ((s.seq.match(/[GCS]/gi) || []).length / len) * 100 : null;
      tb.appendChild(h('tr', h('td', h('code', s.name)), h('td', len.toLocaleString('en-GB')), dna ? h('td', gc == null ? '–' : gc.toFixed(1)) : null, h('td', s.desc.slice(s.name.length).trim().slice(0, 90)), h('td', h('code.ed-seq', s.seq.slice(0, 40) + (s.seq.length > 40 ? '…' : '')))));
    });
    t.appendChild(tb);
    box.appendChild(h('div.ed-tablebox', t));
    if (seqs.length > 500) box.appendChild(h('p.muted.small', `The first 500 of ${seqs.length.toLocaleString('en-GB')} sequences.`));
    void path;
    return box;
  }

  /* ---------------- alignments (aligned FASTA, Clustal) ---------------- */
  function parseAlignment(text) {
    if (/^CLUSTAL|^MUSCLE|^PROBCONS/m.test(text.split('\n')[0] || '')) {
      const seqs = new Map();
      for (const line of text.split(/\r?\n/).slice(1)) {
        if (!line.trim() || /^\s/.test(line)) continue;
        const m = /^(\S+)\s+(\S+)/.exec(line);
        if (!m) continue;
        seqs.set(m[1], (seqs.get(m[1]) || '') + m[2]);
      }
      return Array.from(seqs, ([name, seq]) => ({ name, seq }));
    }
    if (/^# STOCKHOLM/.test(text)) {
      const seqs = new Map();
      for (const line of text.split(/\r?\n/)) {
        if (!line.trim() || line.startsWith('#') || line.startsWith('//')) continue;
        const m = /^(\S+)\s+(\S+)/.exec(line);
        if (m) seqs.set(m[1], (seqs.get(m[1]) || '') + m[2].replace(/\./g, '-'));
      }
      return Array.from(seqs, ([name, seq]) => ({ name, seq }));
    }
    return parseFasta(text).map((s) => ({ name: s.name, seq: s.seq }));
  }
  const AA_GROUP = { A: 'h', V: 'h', L: 'h', I: 'h', M: 'h', F: 'a', W: 'a', Y: 'a', K: 'p', R: 'p', H: 'p', D: 'n', E: 'n', S: 'o', T: 'o', N: 'o', Q: 'o', G: 'g', P: 'r', C: 'c' };
  function alignmentView(text) {
    const seqs = parseAlignment(text).filter((s) => s.seq);
    if (!seqs.length) return null;
    const L = Math.max(...seqs.map((s) => s.seq.length));
    const dna = seqs.every((s) => /^[ACGTUN\-.]*$/i.test(s.seq));
    // conservation: share of the most common residue in each column
    const cons = [];
    for (let i = 0; i < L; i++) {
      const counts = {};
      let n = 0;
      for (const s of seqs) {
        const c = (s.seq[i] || '-').toUpperCase();
        if (c === '-' || c === '.') continue;
        counts[c] = (counts[c] || 0) + 1;
        n++;
      }
      const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
      cons.push(top ? { c: top[0], f: top[1] / seqs.length, n } : { c: '-', f: 0, n: 0 });
    }
    const box = h('div.ed-aln');
    const ident = cons.filter((x) => x.f === 1).length;
    box.appendChild(h('p', h('b', `${seqs.length} aligned ${dna ? 'nucleotide' : 'protein'} sequences`), ` · ${L} columns · ${ident} columns identical in all (${((ident / L) * 100).toFixed(0)} %)`));
    const BLOCK = 60;
    const nameW = Math.min(24, Math.max(...seqs.map((s) => s.name.length)));
    const pre = h('div.aln-rows');
    for (let b = 0; b < L; b += BLOCK) {
      const block = h('div.aln-block');
      block.appendChild(h('div.aln-ruler', ' '.repeat(nameW + 1) + String(b + 1)));
      for (const s of seqs) {
        const row = h('div.aln-row', h('span.aln-name', (s.name.length > nameW ? s.name.slice(0, nameW - 1) + '…' : s.name).padEnd(nameW) + ' '));
        const span = h('span.aln-seq');
        let html = '';
        for (let i = b; i < Math.min(L, b + BLOCK); i++) {
          const ch = s.seq[i] || '-';
          const up = ch.toUpperCase();
          const strong = cons[i].f >= 0.5 && up === cons[i].c;
          const cls = up === '-' || up === '.' ? 'gap' : dna ? 'n' + up : strong ? 'a' + (AA_GROUP[up] || 'x') : '';
          html += cls ? `<i class="${cls}">${esc(ch)}</i>` : esc(ch);
        }
        span.innerHTML = html;
        row.appendChild(span);
        block.appendChild(row);
      }
      let mark = '';
      for (let i = b; i < Math.min(L, b + BLOCK); i++) mark += cons[i].f === 1 ? '*' : cons[i].f >= 0.75 ? ':' : cons[i].f >= 0.5 ? '.' : ' ';
      block.appendChild(h('div.aln-cons', ' '.repeat(nameW + 1) + mark));
      pre.appendChild(block);
    }
    box.appendChild(pre);
    box.appendChild(h('p.muted.small', dna ? 'Colours: A green, C blue, G orange, T/U red. Below each block: * the same in all sequences, : in ¾ or more, . in half or more.' : 'Residues that agree with the most common one in their column (in half the sequences or more) are coloured by kind: hydrophobic, aromatic, positive, negative, polar, glycine, proline, cysteine. * the same in all, : in ¾ or more, . in half or more.'));
    return box;
  }

  /* ---------------- trees (Newick) ---------------- */
  function parseNewick(s) {
    s = s.replace(/\[[^\]]*\]/g, '').trim();
    let i = 0;
    const node = () => {
      const n = { children: [], name: '', len: null };
      if (s[i] === '(') {
        i++;
        n.children.push(node());
        while (s[i] === ',') {
          i++;
          n.children.push(node());
        }
        if (s[i] !== ')') throw new Error('a ) is missing');
        i++;
      }
      let name = '';
      if (s[i] === "'") {
        i++;
        while (i < s.length && s[i] !== "'") name += s[i++];
        i++;
      } else while (i < s.length && !/[:,();]/.test(s[i])) name += s[i++];
      n.name = name.trim().replace(/_/g, ' ');
      if (s[i] === ':') {
        i++;
        let num = '';
        while (i < s.length && /[0-9eE.+\-]/.test(s[i])) num += s[i++];
        n.len = parseFloat(num);
      }
      return n;
    };
    const root = node();
    return root;
  }
  function treeView(text) {
    let root;
    try {
      root = parseNewick(text.trim().split(';')[0]);
    } catch (e) {
      return h('p.muted', 'This file couldn’t be read as a tree in Newick format: ' + e.message);
    }
    const leaves = [];
    const hasLen = (function any(n) {
      return (n.len != null && n !== root) || n.children.some(any);
    })(root);
    let maxX = 0;
    (function place(n, x) {
      n.x = x;
      maxX = Math.max(maxX, x);
      if (!n.children.length) {
        n.y = leaves.length;
        leaves.push(n);
      } else {
        n.children.forEach((c) => place(c, x + (hasLen ? Math.max(0, c.len || 0) : 1)));
        n.y = (n.children[0].y + n.children[n.children.length - 1].y) / 2;
      }
    })(root, 0);
    if (!hasLen) {
      // a cladogram: leaves line up on the right
      const depth = (n) => (n.children.length ? 1 + Math.max(...n.children.map(depth)) : 0);
      const D = depth(root);
      (function fix(n, d) {
        n.x = n.children.length ? d : D;
        n.children.forEach((c) => fix(c, d + 1));
      })(root, 0);
      maxX = D;
    }
    const W = 640, rowH = 20, left = 12, labelW = 220;
    const Hh = Math.max(60, leaves.length * rowH + 30);
    const sx = (x) => left + (maxX ? (x / maxX) * (W - left - labelW) : 0);
    const sy = (y) => 16 + y * rowH;
    let svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${Hh}" width="${W}" height="${Hh}" font-family="system-ui, sans-serif" font-size="12">`;
    (function draw(n) {
      for (const c of n.children) {
        svg += `<path d="M${sx(n.x).toFixed(1)},${sy(c.y).toFixed(1)} H${sx(c.x).toFixed(1)}" stroke="#2c4a63" stroke-width="1.6" fill="none"/>`;
        draw(c);
      }
      if (n.children.length) svg += `<path d="M${sx(n.x).toFixed(1)},${sy(n.children[0].y).toFixed(1)} V${sy(n.children[n.children.length - 1].y).toFixed(1)}" stroke="#2c4a63" stroke-width="1.6" fill="none"/>`;
      if (n.children.length && n.name && /^[\d.]+$/.test(n.name)) svg += `<text x="${(sx(n.x) + 3).toFixed(1)}" y="${(sy(n.y) - 3).toFixed(1)}" font-size="9.5" fill="#8a96a8">${esc(n.name)}</text>`;
      if (!n.children.length) svg += `<text x="${(sx(n.x) + 5).toFixed(1)}" y="${(sy(n.y) + 4).toFixed(1)}" fill="#18212f">${esc(n.name)}</text>`;
    })(root);
    if (hasLen && maxX > 0) {
      const nice = Math.pow(10, Math.floor(Math.log10(maxX / 4)));
      const step = [1, 2, 5].map((m) => m * nice).find((v) => v >= maxX / 6) || nice;
      const y = Hh - 8;
      svg += `<path d="M${left},${y} H${(sx(step) - sx(0) + left).toFixed(1)}" stroke="#647086" stroke-width="1.5"/><text x="${(sx(step) - sx(0) + left + 6).toFixed(1)}" y="${y + 4}" fill="#647086" font-size="10.5">${step} substitutions per site</text>`;
    }
    svg += '</svg>';
    const box = h('div.ed-tree-view');
    box.appendChild(h('p', h('b', `A tree of ${leaves.length} leaves`), hasLen ? ' · branch lengths drawn to scale' : ' · no branch lengths (a cladogram)'));
    box.appendChild(h('div.ed-img.tree', { html: svg }));
    const dl = h('button.btn.small', { type: 'button', html: MG.icon('download') + '<span>Save the picture (SVG)</span>' });
    dl.addEventListener('click', () => MG.downloadText(svg, 'tree.svg', 'image/svg+xml'));
    box.appendChild(h('p.ed-note', dl));
    return box;
  }
  MG.treeSvg = treeView;
  MG.Editor = Editor;
})();
