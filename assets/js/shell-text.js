/* =====================================================================
   The terminal's text tools, written for this workbench in JavaScript
   after the GNU programs of the same names (with their common options,
   not all of them – NAME --help says which):

     cat head tail wc grep sort uniq cut tr tee paste diff seq date sed

   The larger Bioinformatics workbench runs the GNU programs themselves,
   compiled to WebAssembly; they are not needed for pedigree files, which
   are small, and leaving them out keeps this page light. awk is not here:
   for PED files mpedtools does most jobs, and Python the rest.
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const B = MG.shellBuiltins;
  const { userErr, readOne, inputOf, linesOf } = MG.shellUtil;

  /* ------------------------------------------------------------------ helpers */
  const tryMsg = (name) => `\nTry '${name} --help' for more information.`;
  const bad = (name, a) => userErr((a.startsWith('--') ? `${name}: unrecognized option '${a}'` : `${name}: invalid option -- '${a.replace(/^-+/, '')[0]}'`) + tryMsg(name));
  const needs = (name, opt) => userErr(`${name}: option requires an argument -- '${opt}'` + tryMsg(name));

  /** read the named files (or the input: none, or "-"); a file that is not there is reported and skipped.
      → [{name, text}] and the exit status so far */
  async function inputs(ctx, files, name) {
    const out = [];
    let code = 0;
    for (const f of files.length ? files : ['-']) {
      if (f === '-') {
        out.push({ name: '(standard input)', text: await inputOf(ctx, [], name) });
        continue;
      }
      try {
        out.push({ name: f, text: await readOne(ctx, f, name) });
      } catch (e) {
        ctx.err((e.userMessage || e.message) + '\n');
        code = 1;
      }
    }
    return { list: out, code };
  }
  /** parse short options: spec "n:c:qv" (a colon: takes a value); long: {name: 'n'} (the value after = or next) */
  function parse(ctx, name, spec, long = {}, opts = {}) {
    const takes = {};
    spec.replace(/([A-Za-z0-9])(:?)/g, (m, c, colon) => (takes[c] = !!colon));
    const rest = [];
    const a = ctx.args;
    for (let i = 0; i < a.length; i++) {
      const x = a[i];
      if (x === '--') {
        rest.push(...a.slice(i + 1));
        break;
      }
      if (x === '--help') return { help: true };
      if (x.startsWith('--')) {
        const [k, v] = x.slice(2).split(/=(.*)/s);
        if (!(k in long)) throw bad(name, x);
        const c = long[k];
        if (takes[c]) {
          const val = v != null ? v : a[++i];
          if (val === undefined) throw userErr(`${name}: option '--${k}' requires an argument` + tryMsg(name));
          opts[c] = val;
        } else opts[c] = true;
        continue;
      }
      if (x.length > 1 && x[0] === '-' && !(opts.__numbers && /^-\d+$/.test(x))) {
        for (let j = 1; j < x.length; j++) {
          const c = x[j];
          if (!(c in takes)) throw bad(name, '-' + c);
          if (takes[c]) {
            const val = j + 1 < x.length ? x.slice(j + 1) : a[++i];
            if (val === undefined) throw needs(name, c);
            if (opts.__multi && opts.__multi.includes(c)) (opts[c] = opts[c] || []).push(val);
            else opts[c] = val;
            break;
          }
          opts[c] = true;
        }
        continue;
      }
      rest.push(x);
    }
    return { opts, rest };
  }
  const lines = (text) => linesOf(text);
  const joinLines = (L) => (L.length ? L.join('\n') + '\n' : '');
  /** C-style escapes in an argument: \t \n \\ (tr, paste, cut -d, seq -s) */
  const unescape = (s) => s.replace(/\\([tnr\\0]|[0-7]{1,3})/g, (m, c) => ({ t: '\t', n: '\n', r: '\r', '\\': '\\', 0: '\0' }[c] || String.fromCharCode(parseInt(c, 8))));

  /* ------------------------------------------------------------------ cat */
  const HELP = {};
  HELP.cat = `Usage: cat [OPTION]... [FILE]...
Print the files one after the other (with no FILE, or when FILE is -, read the input).
  -n  number every line        -b  number the lines that are not empty
  -s  squeeze runs of empty lines into one     -E  show $ at the end of each line`;
  B.cat = async (ctx) => {
    const p = parse(ctx, 'cat', 'nbsEuA', { number: 'n', 'number-nonblank': 'b', 'squeeze-blank': 's', 'show-ends': 'E' });
    if (p.help) return ctx.out(HELP.cat + '\n'), 0;
    const { opts, rest } = p;
    const { list, code } = await inputs(ctx, rest, 'cat');
    let n = 0;
    for (const { text } of list) {
      if (!opts.n && !opts.b && !opts.s && !opts.E && !opts.A) {
        ctx.out(text);
        continue;
      }
      const L = text.split('\n');
      const last = L.pop(); // '' if the text ends with a newline
      let prevEmpty = false, out = '';
      const put = (l, nl) => {
        if (opts.s && l === '' && prevEmpty) return;
        prevEmpty = l === '';
        const num = opts.b ? (l !== '' ? String(++n).padStart(6) + '\t' : '') : opts.n ? String(++n).padStart(6) + '\t' : '';
        out += num + l + (nl ? (opts.E || opts.A ? '$\n' : '\n') : '');
      };
      L.forEach((l) => put(l, true));
      if (last !== '') put(last, false);
      ctx.out(out);
    }
    return code;
  };

  /* ------------------------------------------------------------------ head, tail */
  HELP.head = `Usage: head [OPTION]... [FILE]...
Print the first 10 lines of each FILE (several files: each under a header).
  -n N   the first N lines (-n -N: all but the last N)     -N   the same as -n N
  -c N   the first N characters      -q  no headers     -v  always headers`;
  HELP.tail = `Usage: tail [OPTION]... [FILE]...
Print the last 10 lines of each FILE (several files: each under a header).
  -n N   the last N lines (-n +N: from line N on)     -N   the same as -n N
  -c N   the last N characters       -q  no headers     -v  always headers`;
  function headTail(name) {
    return async (ctx) => {
      const p = parse(ctx, name, 'n:c:qvf', { lines: 'n', bytes: 'c', quiet: 'q', silent: 'q', verbose: 'v', follow: 'f' }, { __numbers: true });
      if (p.help) return ctx.out(HELP[name] + '\n'), 0;
      const { opts, rest } = p;
      // -5 is -n 5
      const files = [];
      for (const r of rest) {
        if (/^-\d+$/.test(r) && files.length === 0 && opts.n == null) opts.n = r.slice(1);
        else files.push(r);
      }
      if (opts.f) ctx.io.note(`(${name} -f follows a file as it grows; here the file is printed once)`);
      const spec = opts.c != null ? String(opts.c) : String(opts.n != null ? opts.n : '10');
      const m = /^([+-]?)(\d+)$/.exec(spec.trim());
      if (!m) throw userErr(`${name}: invalid number of ${opts.c != null ? 'bytes' : 'lines'}: '${spec}'`);
      const sign = m[1], k = parseInt(m[2], 10);
      const { list, code } = await inputs(ctx, files, name);
      const headers = (list.length > 1 && !opts.q) || opts.v;
      list.forEach(({ name: fname, text }, i) => {
        if (headers) ctx.out((i ? '\n' : '') + `==> ${fname} <==\n`);
        if (opts.c != null) {
          const chars = Array.from(text);
          let part;
          if (name === 'head') part = sign === '-' ? chars.slice(0, Math.max(0, chars.length - k)) : chars.slice(0, k);
          else part = sign === '+' ? chars.slice(Math.max(0, k - 1)) : chars.slice(Math.max(0, chars.length - k));
          ctx.out(part.join(''));
          return;
        }
        const endsNl = text.endsWith('\n');
        const L = lines(text);
        let part;
        if (name === 'head') part = sign === '-' ? L.slice(0, Math.max(0, L.length - k)) : L.slice(0, k);
        else part = sign === '+' ? L.slice(Math.max(0, k - 1)) : k === 0 ? [] : L.slice(-k);
        if (!part.length) return;
        const whole = part.length && (name === 'tail' || part.length === L.length) ? endsNl : true;
        ctx.out(part.join('\n') + (whole ? '\n' : ''));
      });
      return code;
    };
  }
  B.head = headTail('head');
  B.tail = headTail('tail');

  /* ------------------------------------------------------------------ wc */
  HELP.wc = `Usage: wc [OPTION]... [FILE]...
Count the lines, words and bytes of each FILE (and a total for several).
  -l  lines    -w  words    -c  bytes    -m  characters    -L  the length of the longest line`;
  B.wc = async (ctx) => {
    const p = parse(ctx, 'wc', 'lwcmL', { lines: 'l', words: 'w', bytes: 'c', chars: 'm', 'max-line-length': 'L' });
    if (p.help) return ctx.out(HELP.wc + '\n'), 0;
    const { opts, rest } = p;
    const any = opts.l || opts.w || opts.c || opts.m || opts.L;
    const show = any ? opts : { l: true, w: true, c: true };
    const { list, code } = await inputs(ctx, rest, 'wc');
    const enc = new TextEncoder();
    const rows = list.map(({ name, text }) => ({
      name: rest.length ? name : '',
      l: (text.match(/\n/g) || []).length,
      w: (text.match(/\S+/g) || []).length,
      c: enc.encode(text).length,
      m: Array.from(text).length,
      L: Math.max(0, ...text.split('\n').map((x) => Array.from(x.replace(/\t/g, '        ')).length))
    }));
    if (rows.length > 1) rows.push(['l', 'w', 'c', 'm', 'L'].reduce((t, k) => ((t[k] = k === 'L' ? Math.max(...rows.map((r) => r.L)) : rows.reduce((s, r) => s + r[k], 0)), t), { name: 'total' }));
    const keys = ['l', 'w', 'm', 'c', 'L'].filter((k) => show[k]);
    const width = rows.length === 1 && keys.length === 1 && !rest.length ? 0 : Math.max(1, ...rows.map((r) => Math.max(...keys.map((k) => String(r[k]).length))));
    for (const r of rows) ctx.out(keys.map((k) => String(r[k]).padStart(width)).join(' ') + (r.name ? ' ' + r.name : '') + '\n');
    return code;
  };

  /* ------------------------------------------------------------------ grep */
  HELP.grep = `Usage: grep [OPTION]... PATTERN [FILE]...
Print the lines that match PATTERN (a regular expression).
  -i  ignore case       -v  the lines that do not match     -w  whole words     -x  whole lines
  -c  only a count      -n  line numbers                    -o  only the matching parts
  -l  only the names of files that match     -L  of those that do not      -q  print nothing (status only)
  -h  no file names     -H  always file names     -m N  stop after N matching lines
  -E  extended regular expressions (| + ? ( ) without \\)    -F  fixed strings (no regular expression)
  -e PATTERN  a pattern (several -e: any of them)     -r  search folders too
Exit status: 0 if a line matched, 1 if none did, 2 for an error.`;
  /** a basic regular expression (grep without -E) → one for JavaScript: \\( \\) \\| \\+ \\? \\{ \\} are the operators, the bare signs are themselves */
  function breToJs(p) {
    let out = '', inClass = false;
    for (let i = 0; i < p.length; i++) {
      const c = p[i];
      if (inClass) {
        out += c === '\\' ? '\\\\' : c;
        if (c === ']' && !/\[\^?$/.test(out.slice(0, -1).slice(-2))) inClass = false;
        continue;
      }
      if (c === '\\' && i + 1 < p.length) {
        const d = p[++i];
        if ('()|+?{}'.includes(d)) out += d;
        else if (d === '<' || d === '>') out += '\\b';
        else out += '\\' + d;
      } else if ('()|+?{}'.includes(c)) out += '\\' + c;
      else if (c === '[') {
        inClass = true;
        out += c;
      } else out += c;
    }
    return out.replace(/\[:(alpha|digit|alnum|upper|lower|space|punct|blank|xdigit):\]/g, (m, k) => ({ alpha: 'A-Za-z', digit: '0-9', alnum: 'A-Za-z0-9', upper: 'A-Z', lower: 'a-z', space: '\\s', punct: '!-\\/:-@\\[-`{-~', blank: ' \\t', xdigit: '0-9A-Fa-f' }[k]));
  }
  B.grep = B.egrep = B.fgrep = async (ctx) => {
    const name = ctx.name;
    const p = parse(ctx, name, 'ivwxcnolLqhHEFGrRe:m:sZ', { 'ignore-case': 'i', 'invert-match': 'v', 'word-regexp': 'w', 'line-regexp': 'x', count: 'c', 'line-number': 'n', 'only-matching': 'o', 'files-with-matches': 'l', 'files-without-match': 'L', quiet: 'q', silent: 'q', 'no-filename': 'h', 'with-filename': 'H', 'extended-regexp': 'E', 'fixed-strings': 'F', 'basic-regexp': 'G', recursive: 'r', regexp: 'e', 'max-count': 'm', 'no-messages': 's' }, { __multi: ['e'] });
    if (p.help) return ctx.out(HELP.grep + '\n'), 0;
    const { opts, rest } = p;
    if (name === 'egrep') opts.E = true;
    if (name === 'fgrep') opts.F = true;
    let pats = opts.e ? opts.e.slice() : null;
    if (!pats) {
      if (!rest.length) throw userErr(`Usage: ${name} [OPTION]... PATTERNS [FILE]...` + tryMsg(name), 2);
      pats = [rest.shift()];
    }
    pats = pats.flatMap((x) => x.split('\n'));
    let re;
    try {
      const src = pats
        .map((x) => (opts.F ? x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') : opts.E ? x : breToJs(x)))
        .map((x) => (opts.x ? `^(?:${x})$` : opts.w ? `(?<![A-Za-z0-9_])(?:${x})(?![A-Za-z0-9_])` : x))
        .join('|');
      re = new RegExp(src, 'g' + (opts.i ? 'i' : '') + 'u');
    } catch (e) {
      throw userErr(`${name}: invalid regular expression: ${e.message.replace(/^Invalid regular expression: /, '')}`, 2);
    }
    // the files: -r goes into folders
    let files = rest.slice();
    let code = 1, errs = 0;
    if (opts.r || opts.R) {
      const fs = ctx.fs;
      const out = [];
      for (const f of files.length ? files : ['.']) {
        const abs = fs.resolve(f);
        if (fs.isDir(abs)) {
          for (const [pth, e] of fs.entries) if (e.kind !== 'dir' && pth.startsWith(abs === '/' ? '/' : abs + '/')) out.push(f.replace(/\/$/, '') + pth.slice(abs.length));
        } else out.push(f);
      }
      files = out.sort();
    }
    const many = files.length > 1 || opts.r || opts.R;
    const withName = opts.H || (many && !opts.h);
    const max = opts.m != null ? parseInt(opts.m, 10) : Infinity;
    const { list, code: rc } = await inputs(ctx, files, name);
    if (rc) errs = 2;
    for (const { name: fname, text } of list) {
      let count = 0;
      const out = [];
      const L = lines(text);
      for (let i = 0; i < L.length && count < max; i++) {
        re.lastIndex = 0;
        const hit = re.test(L[i]);
        if (hit === !!opts.v) continue;
        count++;
        if (opts.q || opts.l || opts.L || opts.c) continue;
        const pre = (withName ? fname + ':' : '') + (opts.n ? i + 1 + ':' : '');
        if (opts.o && !opts.v) {
          re.lastIndex = 0;
          let m;
          while ((m = re.exec(L[i]))) {
            if (!m[0].length) {
              re.lastIndex++;
              continue;
            }
            out.push(pre + m[0]);
          }
        } else out.push(pre + L[i]);
      }
      if (count) code = 0;
      if (opts.q) {
        if (count) return 0;
        continue;
      }
      if (opts.l) {
        if (count) ctx.out(fname + '\n');
      } else if (opts.L) {
        if (!count) ctx.out(fname + '\n');
      } else if (opts.c) ctx.out((withName ? fname + ':' : '') + count + '\n');
      else if (out.length) ctx.out(out.join('\n') + '\n');
    }
    return errs && code ? 2 : code;
  };

  /* ------------------------------------------------------------------ sort */
  HELP.sort = `Usage: sort [OPTION]... [FILE]...
Sort the lines of the files together.
  -n  by number     -g  by number (also 1e3)     -V  by version (II-10 after II-9)    -h  by size (2K, 1G)
  -r  backwards     -u  each line once           -f  ignore case       -b  ignore spaces at the start
  -k N[,M]  by field N (to M); a field can carry its own n, r … (-k3,3n)     -t SEP  fields are split at SEP
  -s  keep the order of equal lines       -o FILE  write to FILE (it may be the input)
Fields are separated by blanks unless -t is given (-t $'\\t' for tabs).`;
  B.sort = async (ctx) => {
    const p = parse(ctx, 'sort', 'nrufbghVsk:t:o:', { numeric: 'n', 'numeric-sort': 'n', reverse: 'r', unique: 'u', 'ignore-case': 'f', 'ignore-leading-blanks': 'b', 'general-numeric-sort': 'g', 'human-numeric-sort': 'h', 'version-sort': 'V', stable: 's', key: 'k', 'field-separator': 't', output: 'o' }, { __multi: ['k'] });
    if (p.help) return ctx.out(HELP.sort + '\n'), 0;
    const { opts, rest } = p;
    const sep = opts.t != null ? unescape(opts.t) : null;
    if (sep != null && [...sep].length !== 1) throw userErr('sort: multi-character tab ' + JSON.stringify(sep));
    const { list, code } = await inputs(ctx, rest, 'sort');
    let L = [];
    for (const { text } of list) L = L.concat(lines(text));
    const fieldsOf = (line) => (sep != null ? line.split(sep) : line.match(/\s*\S+/g) || ['']);
    const keys = (opts.k || []).map((k) => {
      const m = /^(\d+)(?:\.(\d+))?([bdfghinrV]*)(?:,(\d+)(?:\.(\d+))?([bdfghinrV]*))?$/.exec(k);
      if (!m) throw userErr(`sort: invalid field specification '${k}'`);
      const flags = (m[3] || '') + (m[6] || '');
      return { a: +m[1], ac: m[2] ? +m[2] : 0, b: m[4] ? +m[4] : null, bc: m[5] ? +m[5] : 0, flags };
    });
    const HUM = { K: 1e3, M: 1e6, G: 1e9, T: 1e12, P: 1e15 };
    const cmpBy = (flags) => {
      const has = (c) => flags.includes(c) || (!flags.replace(/[br]/g, '') && !!opts[c]);
      const f = has('f'), n = has('n'), g = has('g'), V = has('V'), hh = has('h'), b = has('b');
      return (x, y) => {
        if (b) {
          x = x.replace(/^\s+/, '');
          y = y.replace(/^\s+/, '');
        }
        if (n || g || hh) {
          const num = (s) => {
            const m = /^\s*([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)([KMGTP]?)/.exec(s);
            if (!m) return n ? 0 : -Infinity;
            return parseFloat(m[1]) * (hh && m[2] ? HUM[m[2]] : 1);
          };
          const d = num(x) - num(y);
          if (d) return d < 0 ? -1 : 1;
          return 0;
        }
        if (V) return x.localeCompare(y, 'en', { numeric: true });
        if (f) {
          x = x.toUpperCase();
          y = y.toUpperCase();
        }
        return x < y ? -1 : x > y ? 1 : 0;
      };
    };
    const extract = (line, k) => {
      const F = fieldsOf(line);
      const from = F.slice(k.a - 1, k.b == null ? undefined : k.b);
      let s = from.join(sep != null ? sep : '');
      if (k.ac) s = s.slice(k.ac - 1);
      return s;
    };
    const cmps = keys.map((k) => ({ k, c: cmpBy(k.flags), r: k.flags.includes('r') }));
    const whole = cmpBy('');
    const cmp = (x, y) => {
      for (const { k, c, r } of cmps) {
        const d = c(extract(x, k), extract(y, k));
        if (d) return r ? -d : d;
      }
      if (cmps.length && opts.s) return 0;
      const d = whole(x, y);
      return d || (opts.s || opts.u ? 0 : x < y ? -1 : x > y ? 1 : 0);
    };
    L = L.map((l, i) => [l, i]);
    L.sort((x, y) => {
      const d = cmp(x[0], y[0]);
      return (opts.r && !cmps.some((c) => c.r) ? -d : d) || x[1] - y[1];
    });
    let out = L.map((x) => x[0]);
    if (opts.u) out = out.filter((l, i) => i === 0 || cmp(out[i - 1], l) !== 0);
    const text = joinLines(out);
    if (opts.o) ctx.fs.writeText(ctx.fs.resolve(opts.o), text);
    else ctx.out(text);
    return code;
  };

  /* ------------------------------------------------------------------ uniq */
  HELP.uniq = `Usage: uniq [OPTION]... [INPUT [OUTPUT]]
Put together lines that repeat one after the other (sort first, to put together all of them).
  -c  how many times each came     -d  only the lines that repeat     -u  only those that do not
  -i  ignore case                   -f N  ignore the first N fields   -s N  ignore the first N characters`;
  B.uniq = async (ctx) => {
    const p = parse(ctx, 'uniq', 'cduif:s:', { count: 'c', repeated: 'd', unique: 'u', 'ignore-case': 'i', 'skip-fields': 'f', 'skip-chars': 's' });
    if (p.help) return ctx.out(HELP.uniq + '\n'), 0;
    const { opts, rest } = p;
    const { list, code } = await inputs(ctx, rest.slice(0, 1), 'uniq');
    if (code) return code;
    const L = lines(list[0].text);
    const keyOf = (l) => {
      let s = l;
      if (opts.f) s = s.replace(new RegExp(`^(\\s*\\S+){${parseInt(opts.f, 10)}}`), '');
      if (opts.s) s = s.slice(parseInt(opts.s, 10));
      return opts.i ? s.toLowerCase() : s;
    };
    const out = [];
    for (let i = 0; i < L.length; ) {
      let j = i + 1;
      while (j < L.length && keyOf(L[j]) === keyOf(L[i])) j++;
      const n = j - i;
      if ((!opts.d || n > 1) && (!opts.u || n === 1)) out.push(opts.c ? String(n).padStart(7) + ' ' + L[i] : L[i]);
      i = j;
    }
    if (rest[1]) ctx.fs.writeText(ctx.fs.resolve(rest[1]), joinLines(out));
    else ctx.out(joinLines(out));
    return 0;
  };

  /* ------------------------------------------------------------------ cut */
  HELP.cut = `Usage: cut OPTION... [FILE]...
Print parts of each line.
  -f LIST  these fields (columns): 1,3  2-4  5-  (fields are split at tabs, or at -d)
  -d SEP   the field separator (one character: -d ' ', -d ',')     -s  leave out lines without SEP
  -c LIST  these characters      -b LIST  these bytes      --output-delimiter=STRING`;
  function ranges(spec, name) {
    const out = [];
    for (const part of spec.split(',')) {
      const m = /^(\d*)(-?)(\d*)$/.exec(part.trim());
      if (!m || (!m[1] && !m[3])) throw userErr(`${name}: invalid field range` + tryMsg(name));
      const a = m[1] ? +m[1] : 1;
      const b = m[2] ? (m[3] ? +m[3] : Infinity) : a;
      if (a < 1) throw userErr(`${name}: fields and positions are numbered from 1` + tryMsg(name));
      out.push([a, b]);
    }
    return (i) => out.some(([a, b]) => i >= a && i <= b);
  }
  B.cut = async (ctx) => {
    const p = parse(ctx, 'cut', 'f:d:c:b:sn', { fields: 'f', delimiter: 'd', characters: 'c', bytes: 'b', 'only-delimited': 's', 'output-delimiter': 'O' });
    if (p.help) return ctx.out(HELP.cut + '\n'), 0;
    const { opts, rest } = p;
    const outSep = ctx.args.find((a) => a.startsWith('--output-delimiter='));
    const mode = opts.f != null ? 'f' : opts.c != null ? 'c' : opts.b != null ? 'b' : null;
    if (!mode) throw userErr('cut: you must specify a list of bytes, characters, or fields' + tryMsg('cut'));
    const pick = ranges(opts[mode], 'cut');
    const d = opts.d != null ? unescape(opts.d) : '\t';
    if (mode === 'f' && [...d].length !== 1) throw userErr('cut: the delimiter must be a single character' + tryMsg('cut'));
    const od = outSep ? unescape(outSep.split('=').slice(1).join('=')) : mode === 'f' ? d : '';
    const { list, code } = await inputs(ctx, rest, 'cut');
    let out = '';
    for (const { text } of list) {
      for (const l of lines(text)) {
        if (mode === 'f') {
          if (!l.includes(d)) {
            if (!opts.s) out += l + '\n';
            continue;
          }
          out += l.split(d).filter((x, i) => pick(i + 1)).join(od) + '\n';
        } else out += Array.from(l).filter((x, i) => pick(i + 1)).join(od) + '\n';
      }
    }
    ctx.out(out);
    return code;
  };

  /* ------------------------------------------------------------------ tr */
  HELP.tr = `Usage: tr [OPTION]... SET1 [SET2]
Change, squeeze or delete characters of the input.
  tr a-z A-Z            upper case       tr -d '\\r'      delete carriage returns
  tr -s ' '             squeeze runs of spaces           tr '\\t' ,       tabs to commas
  -d  delete the characters of SET1     -s  squeeze repeats of the characters of the last SET
  -c  the complement of SET1 (the characters not in it)
SETs: characters, ranges (a-z), \\t \\n \\\\, and [:upper:] [:lower:] [:digit:] [:alpha:] [:alnum:] [:space:] [:punct:]`;
  function trSet(s) {
    s = s.replace(/\[:(upper|lower|digit|alpha|alnum|space|punct|blank):\]/g, (m, k) => ({ upper: 'A-Z', lower: 'a-z', digit: '0-9', alpha: 'A-Za-z', alnum: '0-9A-Za-z', space: ' \t\n\r\v\f', blank: ' \t', punct: '!-/:-@[-`{-~' }[k]));
    const chars = Array.from(unescape(s));
    const out = [];
    for (let i = 0; i < chars.length; i++) {
      if (chars[i + 1] === '-' && i + 2 < chars.length) {
        const a = chars[i].codePointAt(0), b = chars[i + 2].codePointAt(0);
        for (let c = a; c <= b; c++) out.push(String.fromCodePoint(c));
        i += 2;
      } else out.push(chars[i]);
    }
    return out;
  }
  B.tr = async (ctx) => {
    const p = parse(ctx, 'tr', 'dscC', { delete: 'd', 'squeeze-repeats': 's', complement: 'c' });
    if (p.help) return ctx.out(HELP.tr + '\n'), 0;
    const { opts, rest } = p;
    if (rest.length > 2) throw userErr(`tr: extra operand '${rest[2]}'\nOnly one string may be given when deleting without squeezing repeats.` + tryMsg('tr'));
    if (!rest.length) throw userErr('tr: missing operand' + tryMsg('tr'));
    if (!opts.d && !opts.s && rest.length < 2) throw userErr(`tr: missing operand after '${rest[0]}'\nTwo strings must be given when translating.` + tryMsg('tr'));
    const s1 = new Set(trSet(rest[0]));
    const a1 = trSet(rest[0]);
    const s2 = rest[1] != null ? trSet(rest[1]) : [];
    const inS1 = (c) => (opts.c || opts.C ? !s1.has(c) : s1.has(c));
    const text = await inputOf(ctx, [], 'tr');
    let out = [];
    for (const c of Array.from(text)) {
      if (opts.d) {
        if (inS1(c)) continue;
        out.push(c);
      } else if (rest[1] != null && !opts.d) {
        if (inS1(c)) {
          const i = opts.c || opts.C ? s2.length - 1 : a1.indexOf(c);
          out.push(s2.length ? s2[Math.min(i, s2.length - 1)] : c);
        } else out.push(c);
      } else out.push(c);
    }
    if (opts.s) {
      const sq = new Set(rest[1] != null && !opts.d ? s2 : opts.d ? s2 : a1);
      out = out.filter((c, i) => !(i > 0 && c === out[i - 1] && sq.has(c)));
    }
    ctx.out(out.join(''));
    return 0;
  };

  /* ------------------------------------------------------------------ tee, paste */
  HELP.tee = `Usage: tee [-a] [FILE]...
Copy the input to the files, and to the output.   -a  add to the end of the files`;
  B.tee = async (ctx) => {
    const p = parse(ctx, 'tee', 'ai', { append: 'a', 'ignore-interrupts': 'i' });
    if (p.help) return ctx.out(HELP.tee + '\n'), 0;
    const { opts, rest } = p;
    const text = await inputOf(ctx, [], 'tee');
    for (const f of rest) {
      const abs = ctx.fs.resolve(f);
      const old = opts.a && ctx.fs.exists(abs) ? await ctx.fs.readText(abs) : '';
      ctx.fs.writeText(abs, old + text);
    }
    ctx.out(text);
    return 0;
  };
  HELP.paste = `Usage: paste [OPTION]... [FILE]...
Put the lines of the files side by side, separated by tabs.
  -d LIST  separators instead of tabs (used in turn)      -s  each file on one line`;
  B.paste = async (ctx) => {
    const p = parse(ctx, 'paste', 'd:s', { delimiters: 'd', serial: 's' });
    if (p.help) return ctx.out(HELP.paste + '\n'), 0;
    const { opts, rest } = p;
    const seps = Array.from(unescape(opts.d != null ? opts.d : '\t'));
    const { list, code } = await inputs(ctx, rest, 'paste');
    const cols = list.map((x) => lines(x.text));
    const sepAt = (i) => (seps.length ? seps[i % seps.length] : '');
    let out = '';
    if (opts.s) for (const c of cols) out += c.reduce((s, l, i) => s + (i ? sepAt(i - 1) : '') + l, '') + '\n';
    else {
      const n = Math.max(0, ...cols.map((c) => c.length));
      for (let r = 0; r < n; r++) out += cols.reduce((s, c, i) => s + (i ? sepAt(i - 1) : '') + (c[r] != null ? c[r] : ''), '') + '\n';
    }
    ctx.out(out);
    return code;
  };

  /* ------------------------------------------------------------------ diff */
  HELP.diff = `Usage: diff [OPTION]... FILE1 FILE2
Compare two files line by line: what changes FILE1 into FILE2.
  -u  unified: the changes with 3 lines around them (-U N: N lines)     -q  only say whether they differ
  -i  ignore case     -w  ignore all spaces     -b  ignore changes in the amount of space    -B  ignore empty lines
Exit status: 0 the same, 1 different, 2 trouble. For GA4GH and Phenopackets files,  phenotk diff A B  compares the content.`;
  /** the longest common subsequence of two lists of lines (Myers' O(ND) algorithm) → edit script [[op, aLine, bLine]] */
  function lineDiff(A, B, same) {
    const N = A.length, M = B.length, MAX = N + M;
    const V = new Map([[1, 0]]);
    const trace = [];
    for (let d = 0; d <= MAX; d++) {
      trace.push(new Map(V));
      for (let k = -d; k <= d; k += 2) {
        let x = k === -d || (k !== d && (V.get(k - 1) || 0) < (V.get(k + 1) || 0)) ? V.get(k + 1) || 0 : (V.get(k - 1) || 0) + 1;
        let y = x - k;
        while (x < N && y < M && same(A[x], B[y])) {
          x++;
          y++;
        }
        V.set(k, x);
        if (x >= N && y >= M) {
          // walk back
          const ops = [];
          let cx = N, cy = M;
          for (let dd = d; dd > 0; dd--) {
            const Vp = trace[dd];
            const kk = cx - cy;
            const prevK = kk === -dd || (kk !== dd && (Vp.get(kk - 1) || 0) < (Vp.get(kk + 1) || 0)) ? kk + 1 : kk - 1;
            const px = Vp.get(prevK) || 0, py = px - prevK;
            while (cx > px && cy > py) ops.push(['=', --cx, --cy]);
            if (cx === px) ops.push(['+', null, --cy]);
            else ops.push(['-', --cx, null]);
          }
          while (cx > 0 && cy > 0) ops.push(['=', --cx, --cy]);
          return ops.reverse();
        }
      }
    }
    return [];
  }
  B.diff = async (ctx) => {
    const p = parse(ctx, 'diff', 'uqiwbBU:', { unified: 'u', brief: 'q', 'ignore-case': 'i', 'ignore-all-space': 'w', 'ignore-space-change': 'b', 'ignore-blank-lines': 'B' });
    if (p.help) return ctx.out(HELP.diff + '\n'), 0;
    const { opts, rest } = p;
    if (rest.length !== 2) throw userErr(rest.length < 2 ? `diff: missing operand after '${rest[0] || 'diff'}'` + tryMsg('diff') : `diff: extra operand '${rest[2]}'` + tryMsg('diff'), 2);
    let ta, tb;
    try {
      ta = rest[0] === '-' ? await inputOf(ctx, [], 'diff') : await readOne(ctx, rest[0], 'diff');
      tb = rest[1] === '-' ? await inputOf(ctx, [], 'diff') : await readOne(ctx, rest[1], 'diff');
    } catch (e) {
      ctx.err((e.userMessage || e.message) + '\n');
      return 2;
    }
    let A = lines(ta), Bl = lines(tb);
    const norm = (s) => {
      if (opts.i) s = s.toLowerCase();
      if (opts.w) s = s.replace(/\s+/g, '');
      else if (opts.b) s = s.replace(/\s+/g, ' ').replace(/ $/, '');
      return s;
    };
    const ops = lineDiff(A, Bl, (x, y) => norm(x) === norm(y));
    let changed = ops.filter((o) => o[0] !== '=');
    if (opts.B) changed = changed.filter((o) => (o[0] === '-' ? A[o[1]] : Bl[o[2]]).trim() !== '');
    if (!changed.length) return 0;
    if (opts.q) {
      ctx.out(`Files ${rest[0]} and ${rest[1]} differ\n`);
      return 1;
    }
    // hunks: runs of changes
    const hunks = [];
    let cur = null;
    ops.forEach((o, i) => {
      if (o[0] === '=') {
        cur = null;
        return;
      }
      if (!cur) hunks.push((cur = { start: i, end: i }));
      cur.end = i;
    });
    let out = '';
    if (opts.u || opts.U != null) {
      const ctxN = opts.U != null ? parseInt(opts.U, 10) || 0 : 3;
      out += `--- ${rest[0]}\n+++ ${rest[1]}\n`;
      // merge hunks closer than 2·context
      const groups = [];
      for (const hk of hunks) {
        const g = groups[groups.length - 1];
        if (g && hk.start - g.end <= 2 * ctxN) g.end = hk.end;
        else groups.push({ start: hk.start, end: hk.end });
      }
      for (const g of groups) {
        const s = Math.max(0, g.start - ctxN), e = Math.min(ops.length - 1, g.end + ctxN);
        const part = ops.slice(s, e + 1);
        const aStart = (part.find((o) => o[1] != null) || [0, 0])[1], bStart = (part.find((o) => o[2] != null) || [0, 0, 0])[2];
        const aLen = part.filter((o) => o[0] !== '+').length, bLen = part.filter((o) => o[0] !== '-').length;
        const rng = (st, len) => (len === 1 ? `${st + 1}` : `${len ? st + 1 : st},${len}`);
        out += `@@ -${rng(aStart, aLen)} +${rng(bStart, bLen)} @@\n`;
        for (const o of part) out += o[0] === '=' ? ' ' + A[o[1]] + '\n' : o[0] === '-' ? '-' + A[o[1]] + '\n' : '+' + Bl[o[2]] + '\n';
      }
    } else {
      const r = (a, b) => (a === b ? `${a}` : `${a},${b}`);
      for (const hk of hunks) {
        const part = ops.slice(hk.start, hk.end + 1);
        const dels = part.filter((o) => o[0] === '-'), adds = part.filter((o) => o[0] === '+');
        // the line before the hunk, in each file
        let ai = -1, bi = -1;
        for (let i = hk.start - 1; i >= 0; i--) {
          if (ops[i][1] != null && ai < 0) ai = ops[i][1];
          if (ops[i][2] != null && bi < 0) bi = ops[i][2];
          if (ai >= 0 && bi >= 0) break;
        }
        if (dels.length && adds.length) out += `${r(dels[0][1] + 1, dels[dels.length - 1][1] + 1)}c${r(adds[0][2] + 1, adds[adds.length - 1][2] + 1)}\n`;
        else if (dels.length) out += `${r(dels[0][1] + 1, dels[dels.length - 1][1] + 1)}d${bi + 1}\n`;
        else out += `${ai + 1}a${r(adds[0][2] + 1, adds[adds.length - 1][2] + 1)}\n`;
        for (const o of dels) out += '< ' + A[o[1]] + '\n';
        if (dels.length && adds.length) out += '---\n';
        for (const o of adds) out += '> ' + Bl[o[2]] + '\n';
      }
    }
    ctx.out(out);
    return 1;
  };

  /* ------------------------------------------------------------------ seq, date */
  HELP.seq = `Usage: seq [OPTION]... [FIRST [STEP]] LAST
Print numbers from FIRST (1) to LAST, STEP (1) apart.   -s SEP  between them (a newline)   -w  same width`;
  B.seq = async (ctx) => {
    const a = ctx.args.slice();
    let sep = '\n', wide = false;
    const nums = [];
    for (let i = 0; i < a.length; i++) {
      if (a[i] === '--help') return ctx.out(HELP.seq + '\n'), 0;
      if (a[i] === '-s') sep = unescape(a[++i] == null ? '' : a[i]);
      else if (a[i].startsWith('-s') && !/^-s\d/.test(a[i])) sep = unescape(a[i].slice(2));
      else if (a[i] === '-w') wide = true;
      else nums.push(a[i]);
    }
    if (!nums.length || nums.length > 3) throw userErr(nums.length ? `seq: extra operand '${nums[3]}'` + tryMsg('seq') : 'seq: missing operand' + tryMsg('seq'));
    for (const n of nums) if (!/^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(n)) throw userErr(`seq: invalid floating point argument: '${n}'` + tryMsg('seq'));
    const [first, step, last] = nums.length === 1 ? [1, 1, +nums[0]] : nums.length === 2 ? [+nums[0], 1, +nums[1]] : [+nums[0], +nums[1], +nums[2]];
    if (step === 0) throw userErr("seq: invalid Zero increment value: '0'" + tryMsg('seq'));
    const dec = Math.max(...nums.map((n) => (n.includes('.') ? n.split('.')[1].replace(/e.*/i, '').length : 0)));
    const out = [];
    for (let k = 0, v = first; step > 0 ? v <= last + 1e-10 : v >= last - 1e-10; k++, v = first + k * step) {
      if (out.length > 1e6) throw userErr('seq: more than a million numbers: ask for fewer');
      out.push(v.toFixed(dec));
    }
    const w = wide ? Math.max(...out.map((x) => x.replace('-', '').length)) : 0;
    ctx.out((wide ? out.map((x) => (x.startsWith('-') ? '-' + x.slice(1).padStart(w, '0') : x.padStart(w, '0'))) : out).join(sep) + (out.length ? '\n' : ''));
    return 0;
  };
  HELP.date = `Usage: date [-u] [-I] [+FORMAT]
Print the date and time.   -u  in UTC     -I  as 2026-10-17     +FORMAT  e.g. +%Y-%m-%d, +%H:%M`;
  B.date = async (ctx) => {
    let fmt = null, utc = false;
    for (const a of ctx.args) {
      if (a === '--help') return ctx.out(HELP.date + '\n'), 0;
      if (a === '-u' || a === '--utc') utc = true;
      else if (a === '-I' || a === '--iso-8601') fmt = '%Y-%m-%d';
      else if (a.startsWith('+')) fmt = a.slice(1);
      else throw userErr(`date: this terminal's date has -u, -I and +FORMAT only (not ${a})`);
    }
    const d = new Date();
    const S = MG.shellUtil.strftime;
    const zone = utc ? (MG.shellUtil.zoneUTC ? MG.shellUtil.zoneUTC(ctx) : null) : null;
    if (S) ctx.out(S(fmt || '%a %b %e %H:%M:%S %Z %Y', d, utc ? zone || 'UTC' : undefined) + '\n');
    else ctx.out((fmt ? d.toISOString().slice(0, 10) : d.toString()) + '\n');
    return 0;
  };

  /* ------------------------------------------------------------------ sed (substitutions and a little more) */
  HELP.sed = `Usage: sed [OPTION]... SCRIPT [FILE]...
Edit text line by line. This sed has the commands most used with tables:
  s/OLD/NEW/[g][i][N]   replace (OLD is a regular expression; & and \\1 … in NEW)     p  print     d  delete
  q  stop     an address before a command: N (line N), $ (the last), /RE/, N,M (from N to M)
  -n  print only what p prints     -E or -r  extended regular expressions     -i  change the files themselves
  -e SCRIPT  several scripts     commands on one line are separated by ;
Examples:  sed 's/\\t/,/g' family.ped     sed -n '2,5p' FILE     sed '/^#/d' FILE     sed -i 's/FAM1/OKAFOR/' FILE`;
  function sedParse(script, ere) {
    const cmds = [];
    let i = 0;
    const s = script;
    const re = (src) => {
      const js = ere ? src : breToJs(src);
      return js;
    };
    const readDelim = (d) => {
      let out = '';
      while (i < s.length && s[i] !== d) {
        if (s[i] === '\\' && i + 1 < s.length) {
          out += s[i + 1] === d ? d : s[i] + s[i + 1];
          i += 2;
        } else out += s[i++];
      }
      if (s[i] !== d) throw userErr(`sed: -e expression #1, char ${i}: unterminated \`s' command`);
      i++;
      return out;
    };
    const addr = () => {
      if (s[i] === '$') {
        i++;
        return { last: true };
      }
      if (/\d/.test(s[i] || '')) {
        let n = '';
        while (/\d/.test(s[i] || '')) n += s[i++];
        return { line: +n };
      }
      if (s[i] === '/' || s[i] === '\\') {
        const d = s[i] === '\\' ? s[++i] : '/';
        i++;
        return { re: new RegExp(re(readDelim(d))) };
      }
      return null;
    };
    while (i < s.length) {
      while (/[\s;]/.test(s[i] || '')) i++;
      if (i >= s.length) break;
      const a1 = addr();
      let a2 = null;
      if (a1 && s[i] === ',') {
        i++;
        a2 = addr();
      }
      while (s[i] === ' ') i++;
      let neg = false;
      if (s[i] === '!') {
        neg = true;
        i++;
      }
      const c = s[i++];
      if (c === 's') {
        const d = s[i++];
        const pat = readDelim(d);
        const rep = readDelim(d);
        let flags = '';
        while (/[gipI0-9]/.test(s[i] || '')) flags += s[i++];
        const nth = +(flags.match(/\d+/) || [0])[0];
        cmds.push({ c: 's', a1, a2, neg, re: new RegExp(re(pat), (flags.includes('g') ? 'g' : '') + (/[iI]/.test(flags) ? 'i' : '')), rep, nth, p: flags.includes('p') });
      } else if (c === 'p' || c === 'd' || c === 'q' || c === '=') cmds.push({ c, a1, a2, neg });
      else throw userErr(`sed: this terminal's sed has the commands s, p, d, q and = (not '${c}'); for more, use Python`);
    }
    return cmds;
  }
  B.sed = async (ctx) => {
    const a = ctx.args.slice();
    let quiet = false, ere = false, inPlace = false;
    const scripts = [], files = [];
    for (let i = 0; i < a.length; i++) {
      const x = a[i];
      if (x === '--help') return ctx.out(HELP.sed + '\n'), 0;
      if (x === '-n' || x === '--quiet' || x === '--silent') quiet = true;
      else if (x === '-E' || x === '-r' || x === '--regexp-extended') ere = true;
      else if (x === '-i' || x.startsWith('-i') || x === '--in-place') inPlace = true;
      else if (x === '-e') scripts.push(a[++i] || '');
      else if (/^-[nErs]+$/.test(x)) {
        if (x.includes('n')) quiet = true;
        if (/[Er]/.test(x)) ere = true;
      } else if (x.startsWith('-') && x !== '-') throw bad('sed', x);
      else if (!scripts.length && !a.slice(0, i).includes('-e')) scripts.push(x);
      else files.push(x);
    }
    if (!scripts.length) throw userErr('Usage: sed [OPTION]... {script-only-if-no-other-script} [input-file]...' + tryMsg('sed'));
    const cmds = sedParse(scripts.join('\n'), ere);
    const conv = (rep) => rep.replace(/\\(\d)/g, '$$$1').replace(/(^|[^\\])&/g, '$1$$&').replace(/\\&/g, '&').replace(/\\n/g, '\n').replace(/\\t/g, '\t');
    const run = (text) => {
      const L = lines(text);
      let out = '';
      const inRange = cmds.map(() => false);
      const hits = (cm, k, line, n) => {
        const at = (ad) => (ad.last ? n === L.length : ad.line != null ? n === ad.line : ad.re.test(line));
        let ok;
        if (!cm.a1) ok = true;
        else if (!cm.a2) ok = at(cm.a1);
        else if (inRange[k]) {
          ok = true;
          if (cm.a2.line != null ? n >= cm.a2.line : at(cm.a2)) inRange[k] = false;
        } else if (at(cm.a1)) {
          ok = true;
          inRange[k] = !(cm.a2.line != null && n >= cm.a2.line);
        } else ok = false;
        return cm.neg ? !ok : ok;
      };
      for (let i = 0; i < L.length; i++) {
        let line = L[i], del = false, stop = false;
        for (let k = 0; k < cmds.length && !del; k++) {
          const cm = cmds[k];
          if (!hits(cm, k, line, i + 1)) continue;
          if (cm.c === 's') {
            let count = 0, changed = false;
            const r = new RegExp(cm.re.source, cm.re.flags.includes('g') || cm.nth ? cm.re.flags.replace('g', '') + 'g' : cm.re.flags);
            line = line.replace(r, (...m) => {
              count++;
              if (cm.nth && count !== cm.nth) return m[0];
              changed = true;
              const groups = m.slice(1, -2);
              return conv(cm.rep).replace(/\$(\d|&)/g, (x, g) => (g === '&' ? m[0] : groups[+g - 1] != null ? groups[+g - 1] : ''));
            });
            if (cm.p && changed) out += line + '\n';
          } else if (cm.c === 'p') out += line + '\n';
          else if (cm.c === '=') out += i + 1 + '\n';
          else if (cm.c === 'd') del = true;
          else if (cm.c === 'q') stop = true;
        }
        if (!del && !quiet) out += line + '\n';
        if (stop) break;
      }
      return out;
    };
    if (inPlace) {
      if (!files.length) throw userErr('sed: no input files');
      for (const f of files) ctx.fs.writeText(ctx.fs.resolve(f), run(await readOne(ctx, f, 'sed')));
      return 0;
    }
    const { list, code } = await inputs(ctx, files, 'sed');
    ctx.out(run(list.map((x) => x.text).join('')));
    return code;
  };

  /* NAME --help for these commands, and man NAME (the shell asks MG.shellHelp first) */
  MG.textHelp = HELP;
  HELP.egrep = HELP.grep.replace('Usage: grep', 'Usage: egrep') + '\n(egrep is grep -E)';
  HELP.fgrep = HELP.grep.replace('Usage: grep', 'Usage: fgrep') + '\n(fgrep is grep -F)';
  const help0 = MG.shellHelp;
  MG.shellHelp = (name, version) => {
    if (!HELP[name]) return help0 ? help0(name, version) : null;
    if (version) return `${name} (the terminal of this workbench) – written for it after the GNU program of that name; it is not that program and has no version of it.\n`;
    return HELP[name] + `\n\nThis is the terminal's own ${name}, written for the workbench after the GNU program: it has the options above, not all of the original's.\n`;
  };

  /* split and truncate (shell-extra.js) write through the WebAssembly programs' file system, which this page does
     not have */
  delete B.split;
  delete B.truncate;
})();
