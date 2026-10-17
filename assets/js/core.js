/* =====================================================================
   Genomics practicals – shared helpers (namespace, events, storage, fetch, dialogs)
   Plain browser JavaScript: no build step needed.
   ===================================================================== */
(function () {
  'use strict';

  const MG = (window.MG = window.MG || {});
  const CFG = (MG.config = Object.assign(
    {
      showModelAnswers: true,
      preferBundledData: true,
      bundled: {},
      fetchTimeoutMs: 20000
    },
    window.MG_CONFIG || {}
  ));

  /* ---------- tiny DOM helpers ---------- */
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /** h('div.cls#id', {attr}, children...) – minimal hyperscript */
  function h(tag, attrs, ...kids) {
    const m = /^([a-z0-9-]+)?((?:[.#][\w-]+)*)$/i.exec(tag) || [];
    const el = document.createElement(m[1] || 'div');
    (m[2] || '').replace(/([.#])([\w-]+)/g, (_, t, v) => {
      if (t === '.') el.classList.add(v);
      else el.id = v;
    });
    if (attrs && (typeof attrs !== 'object' || attrs instanceof Node || Array.isArray(attrs))) {
      kids.unshift(attrs);
      attrs = null;
    }
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === 'class') el.className += (el.className ? ' ' : '') + v;
        else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
        else if (k === 'html') el.innerHTML = v;
        else if (k === 'text') el.textContent = v;
        else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
        else if (k === 'dataset') Object.assign(el.dataset, v);
        else el.setAttribute(k, v === true ? '' : v);
      }
    }
    const add = (k) => {
      if (k == null || k === false) return;
      if (Array.isArray(k)) k.forEach(add);
      else el.appendChild(k instanceof Node ? k : document.createTextNode(String(k)));
    };
    kids.forEach(add);
    return el;
  }

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  /* ---------- event bus ---------- */
  const listeners = {};
  const bus = {
    on(type, fn) {
      (listeners[type] = listeners[type] || []).push(fn);
      return () => bus.off(type, fn);
    },
    off(type, fn) {
      listeners[type] = (listeners[type] || []).filter((f) => f !== fn);
    },
    emit(type, detail) {
      (listeners[type] || []).slice().forEach((fn) => {
        try {
          fn(detail || {}, type);
        } catch (e) {
          console.error('listener error', type, e);
        }
      });
      (listeners['*'] || []).slice().forEach((fn) => {
        try {
          fn(detail || {}, type);
        } catch (e) {
          console.error(e);
        }
      });
    }
  };

  /* ---------- storage (never throws) ---------- */
  /* keys are namespaced per page, e.g. "genomics:reads:progress" */
  const pfx = () => (CFG.storePrefix || 'genomics') + ':' + ((document.body && document.body.dataset.page) ? document.body.dataset.page + ':' : '');
  const store = {
    get(key, fallback) {
      try {
        const v = window.localStorage.getItem(pfx() + key);
        return v == null ? fallback : JSON.parse(v);
      } catch (e) {
        return fallback;
      }
    },
    set(key, value) {
      try {
        window.localStorage.setItem(pfx() + key, JSON.stringify(value));
        return true;
      } catch (e) {
        return false;
      }
    },
    remove(key) {
      try {
        window.localStorage.removeItem(pfx() + key);
      } catch (e) {
        /* ignore */
      }
    },
    clearAll() {
      try {
        Object.keys(window.localStorage)
          .filter((k) => k.startsWith(pfx()))
          .forEach((k) => window.localStorage.removeItem(k));
      } catch (e) {
        /* ignore */
      }
    }
  };

  /* ---------- the name of the person at the workbench ----------
     The terminal's user is "user" (user@workbench:~$), unless the person has put in a name of their own – the button
     with the name at the top of the page. That name is kept in this browser only. It is what the prompt, whoami, id,
     ls -l, $USER and $LOGNAME, and Python's USER show. The home folder stays /home/user whatever the name.
     The AI agent's commands run as "user": its commands' output goes to an AI service, the person's name does not. */
  const USER0 = 'user';
  const NAME_RE = /^[A-Za-z_][A-Za-z0-9_.-]{0,31}$/;
  const user = {
    DEFAULT: USER0,
    /** a name that can be a user's name here: a letter or _ first, then letters, digits, . _ -, at most 32; not root */
    valid: (n) => typeof n === 'string' && NAME_RE.test(n) && n !== 'root',
    /** the name the person chose, or "user" */
    name() {
      const n = store.get('userName', '');
      return user.valid(n) ? n : USER0;
    },
    /** the name that the commands see just now: "user" while the AI agent runs a command */
    login() {
      return MG.app && MG.app.term && MG.app.term.agentCmd ? USER0 : user.name();
    },
    /** what was typed, as a user name: "Ada Lovelace" → "Ada.Lovelace", "José" → "Jose"; '' if nothing usable is left */
    suggest(text) {
      let s = String(text == null ? '' : text).normalize('NFKD').replace(/[̀-ͯ]/g, '').trim();
      s = s.replace(/\s+/g, '.').replace(/[^A-Za-z0-9_.-]/g, '').replace(/([._-])[._-]+/g, '$1').replace(/^[^A-Za-z_]+/, '').slice(0, 32).replace(/[.-]+$/, '');
      return user.valid(s) ? s : '';
    },
    /** keep a new name (an empty one, or "user": back to "user") → false if it cannot be a user name */
    set(n) {
      const old = user.name();
      n = n == null || n === '' ? USER0 : String(n);
      if (!user.valid(n)) return false;
      if (n === USER0) store.remove('userName');
      else store.set('userName', n);
      if (n !== old) bus.emit('user:name', { name: n, old });
      return true;
    },
    /** what the commands printed, with "user" in place of the person's name where the name stands for the user: the
        prompt (NAME@workbench), whoami, logname, $USER (a line of nothing else), id and stat (uid=1000(NAME)), the
        owner and group of ls -l, find -ls and tar -tv, sudo's refusal. Elsewhere the text is left as it is: a name
        that is also a word or a folder (data, home) must not change a path or a sentence. For what goes to an AI service. */
    mask(text) {
      const n = user.name();
      if (n === USER0 || text == null) return text;
      const N = n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const perms = '[-bcdlps][-rwxsStT]{9}[.+@]?';
      return String(text)
        .replace(new RegExp('(^|[^A-Za-z0-9_.-])' + N + '@', 'g'), '$1' + USER0 + '@')
        .replace(new RegExp('(\\d\\(|\\d/\\s*)' + N + '\\)', 'g'), '$1' + USER0 + ')')
        .replace(new RegExp('^((?:\\s*\\d+\\s+\\d+\\s+)?' + perms + '\\s+\\d+\\s+)' + N + '(?=\\s)', 'gm'), '$1' + USER0)
        .replace(new RegExp('^((?:\\s*\\d+\\s+\\d+\\s+)?' + perms + '\\s+\\d+\\s+\\S+\\s+)' + N + '(?=\\s)', 'gm'), '$1' + USER0)
        .replace(new RegExp('^(' + perms + '\\s+)' + N + '/' + N + '(?=\\s)', 'gm'), '$1' + USER0 + '/' + USER0)
        .replace(new RegExp('^' + N + ' is not in the sudoers file', 'gm'), USER0 + ' is not in the sudoers file')
        .replace(new RegExp('^' + N + ' : ' + N + '$', 'gm'), USER0 + ' : ' + USER0)
        .replace(new RegExp('^' + N + '(\\s+' + N + ')*$', 'gm'), (m) => m.split(/(\s+)/).map((w) => (w === n ? USER0 : w)).join(''));
    }
  };

  /* ---------- fetch with timeout ---------- */
  async function fetchWithTimeout(url, opts = {}, ms) {
    const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    const t = ctrl ? setTimeout(() => ctrl.abort(), ms || CFG.fetchTimeoutMs) : null;
    try {
      const r = await fetch(url, Object.assign({}, opts, ctrl ? { signal: ctrl.signal } : {}));
      if (!r.ok) {
        const err = new Error('HTTP ' + r.status + ' for ' + url);
        err.status = r.status;
        throw err;
      }
      return r;
    } catch (e) {
      if (e.name === 'AbortError') throw new Error('Timed out fetching ' + url);
      throw e;
    } finally {
      if (t) clearTimeout(t);
    }
  }
  async function fetchJSON(url, opts, ms) {
    const r = await fetchWithTimeout(url, opts, ms);
    return r.json();
  }
  async function fetchText(url, opts, ms) {
    const r = await fetchWithTimeout(url, opts, ms);
    return r.text();
  }

  /** Try each source in order; return the first that works. */
  async function firstOk(tasks) {
    let lastErr;
    for (const task of tasks) {
      if (!task) continue;
      try {
        return await task();
      } catch (e) {
        lastErr = e;
      }
    }
    throw lastErr || new Error('No source available');
  }

  /* ---------- downloads & clipboard ---------- */
  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = h('a', { href: url, download: filename, style: { display: 'none' } });
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(url);
      a.remove();
    }, 2000);
  }
  function downloadText(text, filename, type) {
    downloadBlob(new Blob([text], { type: type || 'text/plain' }), filename);
  }
  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      const ta = h('textarea', { style: { position: 'fixed', left: '-9999px' } }, text);
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try {
        ok = document.execCommand('copy');
      } catch (e2) {
        ok = false;
      }
      ta.remove();
      return ok;
    }
  }

  /* ---------- toast messages ---------- */
  let toastBox;
  function toast(msg, kind, ms) {
    if (!toastBox) {
      toastBox = h('div.toasts', { role: 'status', 'aria-live': 'polite' });
      document.body.appendChild(toastBox);
    }
    const t = h('div.toast' + (kind ? '.' + kind : ''), { html: msg });
    toastBox.appendChild(t);
    requestAnimationFrame(() => t.classList.add('show'));
    setTimeout(() => {
      t.classList.remove('show');
      setTimeout(() => t.remove(), 400);
    }, ms || (kind === 'error' ? 6000 : 3200));
  }

  /* ---------- misc ---------- */
  const debounce = (fn, ms) => {
    let t;
    return (...a) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...a), ms);
    };
  };
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const fmt = (n, d = 0) =>
    n == null || isNaN(n) ? '–' : Number(n).toLocaleString('en-GB', { maximumFractionDigits: d, minimumFractionDigits: d });

  const AA3 = {
    ALA: 'A', ARG: 'R', ASN: 'N', ASP: 'D', CYS: 'C', GLN: 'Q', GLU: 'E', GLY: 'G', HIS: 'H', ILE: 'I',
    LEU: 'L', LYS: 'K', MET: 'M', PHE: 'F', PRO: 'P', SER: 'S', THR: 'T', TRP: 'W', TYR: 'Y', VAL: 'V',
    SEC: 'U', PYL: 'O', MSE: 'M', SEP: 'S', TPO: 'T', PTR: 'Y', HYP: 'P', MLY: 'K', CSO: 'C', HID: 'H', HIE: 'H', HIP: 'H',
    DA: 'A', DC: 'C', DG: 'G', DT: 'T', DU: 'U', A: 'A', C: 'C', G: 'G', U: 'U', T: 'T', I: 'I', DI: 'I'
  };
  const AA3_NICE = {
    ALA: 'Ala', ARG: 'Arg', ASN: 'Asn', ASP: 'Asp', CYS: 'Cys', GLN: 'Gln', GLU: 'Glu', GLY: 'Gly', HIS: 'His',
    ILE: 'Ile', LEU: 'Leu', LYS: 'Lys', MET: 'Met', PHE: 'Phe', PRO: 'Pro', SER: 'Ser', THR: 'Thr', TRP: 'Trp',
    TYR: 'Tyr', VAL: 'Val', SEP: 'pSer', TPO: 'pThr', PTR: 'pTyr', MSE: 'MSe'
  };
  const AA1_NAME = {
    A: 'alanine', R: 'arginine', N: 'asparagine', D: 'aspartate', C: 'cysteine', Q: 'glutamine', E: 'glutamate',
    G: 'glycine', H: 'histidine', I: 'isoleucine', L: 'leucine', K: 'lysine', M: 'methionine', F: 'phenylalanine',
    P: 'proline', S: 'serine', T: 'threonine', W: 'tryptophan', Y: 'tyrosine', V: 'valine'
  };
  const niceRes = (resname) => AA3_NICE[resname] || resname;

  /* ---------- modal dialog and pop-up menu ---------- */
  MG.modal = function (title, html, opts = {}) {
    const before = document.activeElement;
    const close = () => {
      back.remove();
      document.removeEventListener('keydown', onKey);
      if (opts.onClose) opts.onClose();
      // give the keyboard focus back to where it was
      if (before && before.isConnected && typeof before.focus === 'function') before.focus();
    };
    const onKey = (e) => e.key === 'Escape' && close();
    const x = h('button.icon-btn.modal-x', { type: 'button', 'aria-label': 'Close', html: MG.icon('x') });
    x.addEventListener('click', close);
    const box = h('div.modal', { role: 'dialog', 'aria-modal': 'true', 'aria-label': title }, h('div.modal-h', h('h3', title), x), h('div.modal-b', { html }));
    const back = h('div.modal-back', box);
    back.addEventListener('click', (e) => e.target === back && close());
    document.body.appendChild(back);
    document.addEventListener('keydown', onKey);
    setTimeout(() => x.focus(), 10);
    return { close, box };
  };

  MG.popmenu = function (anchor, items) {
    document.querySelectorAll('.popmenu').forEach((m) => m.remove());
    const m = h('div.popmenu', { role: 'menu' });
    const close = (refocus) => {
      m.remove();
      document.removeEventListener('pointerdown', off, true);
      if (refocus && anchor.isConnected) anchor.focus();
    };
    items.forEach(([ic, label, fn]) => {
      const b = h('button', { type: 'button', role: 'menuitem', html: MG.icon(ic) + '<span>' + esc(label) + '</span>' });
      b.addEventListener('click', () => {
        close(false);
        fn();
      });
      m.appendChild(b);
    });
    // keyboard: arrows move, Escape or Tab closes
    m.addEventListener('keydown', (e) => {
      const bs = Array.from(m.querySelectorAll('button'));
      const i = bs.indexOf(document.activeElement);
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        bs[(i + (e.key === 'ArrowDown' ? 1 : bs.length - 1)) % bs.length].focus();
      } else if (e.key === 'Escape' || e.key === 'Tab') {
        e.preventDefault();
        close(true);
      }
    });
    document.body.appendChild(m);
    const r = anchor.getBoundingClientRect();
    m.style.left = Math.max(8, Math.min(window.innerWidth - m.offsetWidth - 8, r.left)) + 'px';
    // open upwards when there is no room below the button
    const below = r.bottom + 4 + m.offsetHeight <= window.innerHeight - 8;
    m.style.top = (below ? r.bottom + 4 : Math.max(8, r.top - 4 - m.offsetHeight)) + 'px';
    function off(e) {
      if (!m.contains(e.target)) close(false);
    }
    setTimeout(() => document.addEventListener('pointerdown', off, true), 0);
    const first = m.querySelector('button');
    if (first) first.focus();
  };

  /* a question with a text answer (a modal dialog) → a promise of the text, or '' */
  MG.promptText = function (title, hint, def, okLabel) {
    return new Promise((resolve) => {
      const input = h('input.prompt-input', { type: 'text', value: def || '', 'aria-label': title, spellcheck: 'false' });
      const ok = h('button.btn.primary', { type: 'submit', text: okLabel || 'OK' });
      const cancel = h('button.btn', { type: 'button', text: 'Cancel' });
      const form = h('form.prompt-form', h('p', hint || ''), input, h('div.prompt-actions', cancel, ok));
      let done = false;
      const m = MG.modal(title, '', {
        onClose: () => {
          if (!done) {
            done = true;
            resolve('');
          }
        }
      });
      m.box.querySelector('.modal-b').appendChild(form);
      const finish = (v) => {
        if (done) return;
        done = true;
        m.close();
        resolve(v);
      };
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        finish(input.value.trim());
      });
      cancel.addEventListener('click', () => finish(''));
      setTimeout(() => {
        input.focus();
        input.select();
      }, 30);
    });
  };
  /* a yes-or-no question → a promise of true (the first button) or false */
  MG.confirmBox = function (title, html, okLabel, opts = {}) {
    return new Promise((resolve) => {
      let done = false;
      const m = MG.modal(title, `${html}<div class="prompt-actions"><button class="btn" data-x="no" type="button">${esc(opts.cancel || 'Cancel')}</button><button class="btn ${opts.danger ? 'danger' : 'primary'}" data-x="yes" type="button">${esc(okLabel || 'OK')}</button></div>`, {
        onClose: () => {
          if (!done) {
            done = true;
            resolve(false);
          }
        }
      });
      const fin = (v) => {
        if (done) return;
        done = true;
        m.close();
        resolve(v);
      };
      m.box.querySelector('[data-x="no"]').addEventListener('click', () => fin(false));
      m.box.querySelector('[data-x="yes"]').addEventListener('click', () => fin(true));
    });
  };

  Object.assign(MG, {
    esc, h, $, $$, bus, store, toast, debounce, clamp, fmt, user,
    fetchWithTimeout, fetchJSON, fetchText, firstOk,
    downloadBlob, downloadText, copyText,
    AA3, AA3_NICE, AA1_NAME, niceRes
  });
})();
