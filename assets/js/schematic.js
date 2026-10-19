/* =====================================================================
   The map: the file formats (boxes) and the tools that turn one into
   another (arrows), after the diagram on the Software page of the lab's
   web site. Point at an arrow to see what it does; click it to open
   that tool, or click a box to see what can be done with that kind of
   file.

     MG.pedMap(container, { onTool(id), onFormat(kind), onHover(name), layout })
       → { highlight(name) }   name: a tool id, a package name or a kind

   It has two layouts: a wide one, and a tall one for narrow places (the
   help, a phone), in which the writing stays large enough to read. The
   map picks the one that fits its width, and changes when the width does
   (layout: 'wide' or 'tall' fixes it).

   Used on the Tools tab's first page and in the help: a help page holds
   <div class="pw-map"></div>, which is drawn the first time the page is
   shown (workbench.js announces each page with the event 'help:page').
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const NS = 'http://www.w3.org/2000/svg';
  const reduced = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // the formats: their titles, and where each layout puts them: x, y (centre), w (width)
  const FORMATS = {
    image: { title: 'Picture of a pedigree', sub: 'PNG or JPEG' },
    terms: { title: 'Ontology terms', sub: 'HPO and Mondo · a terms file' },
    ped: { title: 'PED or MPED file', sub: 'for linkage programs' },
    studio: { title: 'Pedigree Studio drawing', sub: '.studio.json', main: true },
    pedigree: { title: 'GA4GH Pedigree', sub: 'Phenopackets form' },
    family: { title: 'Phenopackets Family', sub: 'Phenopackets v2' }
  };
  const PLACES = {
    wide: { image: [112, 44, 180], terms: [380, 44, 230], ped: [112, 222, 180], studio: [380, 222, 214], pedigree: [650, 124, 176], family: [650, 318, 176] },
    tall: { image: [100, 36, 150], terms: [330, 36, 230], ped: [78, 190, 150], studio: [330, 190, 230], pedigree: [135, 400, 190], family: [390, 400, 190] }
  };
  const VIEWBOX = { wide: '0 0 900 440', tall: '0 0 500 545' };
  // the routes, the same in both layouts and in this order (ROUTE_ENDS below goes by it):
  // [tool id, package (for highlight), label, path, label x, y, anchor, arrow, dashed, both ends]
  // (a label at 0, 0 with the anchor at its end is not seen, but the route is still a button for the keyboard)
  const WIDE = [
    ['studio2ped', 'studio2ped', 'studio2ped', 'M274 208 C244 180 232 180 204 206', 240, 174, 'middle', true],
    ['ped2studio', 'ped2studio', 'ped2studio', 'M204 238 C232 264 244 264 274 236', 240, 282, 'middle', true],
    ['mped-info', 'mpedtools', 'mpedtools', 'M84 196 C60 134 164 134 140 196', 112, 128, 'middle', true],
    ['studio2ga4gh', 'studio2ga4gh', 'studio2ga4gh', 'M488 210 C520 168 532 134 560 128', 0, 0, 'end', true],
    ['studio2ga4gh', 'studio2ga4gh', 'studio2ga4gh', 'M488 234 C520 276 532 308 560 314', 498, 306, 'end', true],
    ['ga4gh2studio', 'ga4gh2studio', 'ga4gh2studio', 'M562 144 C536 152 524 190 490 216', 540, 194, 'start', true],
    ['ga4gh2studio', 'ga4gh2studio', '', 'M562 300 C536 292 524 256 490 228', 0, 0, 'start', true],
    ['ga4gh-convert', 'phenotk', 'convert', 'M650 150 L650 292', 658, 226, 'start', true, false, true],
    ['validate', 'phenotk', 'phenotk\ncheck · view\nfilter\nde-identify', 'M738 116 C796 136 796 306 738 326', 806, 196, 'start', true],
    ['export', 'phenotk', 'phenotk: GA4GH → PED', 'M580 344 C470 430 230 430 126 250', 350, 404, 'middle', true],
    ['terms', 'hponorm', 'match terms', 'M380 196 L380 70', 372, 136, 'end', true, true],
    ['normalise', 'phenotk', '', 'M496 44 C580 44 630 70 644 98', 0, 0, 'start', true, true],
    ['pedinterp', 'PedInterp', 'pedinterp', 'M184 70 L184 194', 192, 136, 'start', true]
  ];
  const TALL = [
    ['studio2ped', 'studio2ped', 'studio2ped', 'M213 180 C195 166 175 166 156 180', 184, 152, 'middle', true],
    ['ped2studio', 'ped2studio', 'ped2studio', 'M156 200 C175 214 195 214 213 200', 184, 238, 'middle', true],
    ['mped-info', 'mpedtools', 'mpedtools', 'M48 162 C28 104 128 104 108 162', 78, 98, 'middle', true],
    ['studio2ga4gh', 'studio2ga4gh', 'studio2ga4gh', 'M250 218 C240 280 175 320 165 372', 172, 334, 'end', true],
    ['studio2ga4gh', 'studio2ga4gh', 'studio2ga4gh', 'M370 218 C375 280 385 330 392 372', 0, 0, 'end', true],
    ['ga4gh2studio', 'ga4gh2studio', 'ga4gh2studio', 'M205 372 C220 320 275 280 285 218', 258, 304, 'start', true],
    ['ga4gh2studio', 'ga4gh2studio', '', 'M422 372 C417 330 412 280 407 218', 0, 0, 'start', true],
    ['ga4gh-convert', 'phenotk', 'convert', 'M232 400 L293 400', 262.5, 389, 'middle', true, false, true],
    ['validate', 'phenotk', 'phenotk: check · view · filter · de-identify', 'M120 428 C120 515 405 515 405 428', 262, 532, 'middle', true],
    ['export', 'phenotk', 'phenotk: GA4GH → PED', 'M40 396 C10 340 12 262 50 220', 36, 294, 'start', true],
    ['terms', 'hponorm', 'match terms', 'M330 162 L330 66', 322, 118, 'end', true, true],
    ['normalise', 'phenotk', '', 'M447 36 C490 40 494 220 470 370', 0, 0, 'start', true, true],
    ['pedinterp', 'PedInterp', 'pedinterp', 'M132 62 L132 162', 138, 116, 'start', true]
  ];
  const ROUTES = { wide: WIDE, tall: TALL };
  /** the layout for a width: tall below 720 pixels, where the wide one's writing would be too small */
  const layoutFor = (width) => (width && width < 720 ? 'tall' : 'wide');

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs || {}) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function text(parent, x, y, s, cls, anchor) {
    const t = el('text', { x, y, class: cls, 'text-anchor': anchor || 'middle' }, parent);
    const lines = String(s).split('\n');
    if (lines.length === 1) t.textContent = s;
    else lines.forEach((l, i) => (el('tspan', { x, dy: i ? '1.25em' : 0, class: i ? 'pm-more' : null }, t).textContent = l));
    return t;
  }

  function pedMap(container, opts = {}) {
    container.classList.add('pw-map');
    let current = null, api = null;
    const draw = () => {
      const want = opts.layout || layoutFor(container.clientWidth);
      if (want === current) return;
      current = want;
      container.dataset.layout = want;
      if (api) api.stop();
      api = drawMap(container, opts, want);
    };
    draw();
    if (!opts.layout && 'ResizeObserver' in window) new ResizeObserver(() => draw()).observe(container);
    return { highlight: (name) => api && api.highlight(name) };
  }

  function drawMap(container, opts, layout) {
    container.innerHTML = '';
    const NODES = Object.fromEntries(Object.entries(FORMATS).map(([k, f]) => [k, Object.assign({ x: PLACES[layout][k][0], y: PLACES[layout][k][1], w: PLACES[layout][k][2] }, f)]));
    const uid = 'pm' + Math.random().toString(36).slice(2, 8);
    const svg = el('svg', { viewBox: VIEWBOX[layout], role: 'img', 'aria-labelledby': uid + 't' }, container);
    const title = el('title', { id: uid + 't' }, svg);
    title.textContent =
      'A Pedigree Studio drawing is in the middle. studio2ped and ped2studio convert it to and from PED files, and studio2ga4gh and ga4gh2studio to and from a GA4GH Pedigree and a Phenopackets Family. The drawing’s conditions are matched to HPO and Mondo terms. phenotk converts, checks, filters and de-identifies the GA4GH files, and makes PED files from them. pedinterp reads a picture of a pedigree into a PED file.';
    const defs = el('defs', {}, svg);
    const mk = (id, cls) => {
      const m = el('marker', { id, viewBox: '0 0 10 10', refX: 8.5, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' }, defs);
      el('path', { d: 'M0 0 L10 5 L0 10 z', class: cls }, m);
    };
    mk(uid + 'a', 'pm-head');
    mk(uid + 'b', 'pm-head on');
    const routesG = el('g', { class: 'pm-routes' }, svg);
    const nodesG = el('g', { class: 'pm-nodes' }, svg);
    const routes = ROUTES[layout].map(([tool, pkg, label, d, lx, ly, anchor, arrow, dashed, both], i) => {
      const g = el('g', { class: 'pm-route' + (dashed ? ' dashed' : ''), tabindex: label ? '0' : null, role: label ? 'button' : null, 'aria-label': label ? `${label}: open the tool` : null }, routesG);
      el('path', { d, class: 'pm-hit' }, g);
      const path = el('path', { d, class: 'pm-edge', 'marker-end': arrow ? `url(#${uid}a)` : null, 'marker-start': both ? `url(#${uid}a)` : null }, g);
      if (label) text(g, lx, ly, label, 'pm-label', anchor);
      const dots = reduced() ? [] : [0, 0.5].map((o) => ({ o, c: el('circle', { r: 2.6, class: 'pm-dot' }, g) }));
      const r = { tool, pkg, g, path, dots, len: 0, both, ends: ROUTE_ENDS[i] || [] };
      const go = () => opts.onTool && opts.onTool(tool);
      g.addEventListener('click', go);
      g.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          go();
        }
      });
      g.addEventListener('pointerenter', () => set(tool));
      g.addEventListener('pointerleave', () => set(null));
      g.addEventListener('focus', () => set(tool));
      g.addEventListener('blur', () => set(null));
      return r;
    });
    const nodes = Object.entries(NODES).map(([kind, n]) => {
      const g = el('g', { class: 'pm-node' + (n.main ? ' main' : ''), tabindex: '0', role: 'button', 'aria-label': `${n.title}: what you can do with it` }, nodesG);
      el('rect', { x: n.x - n.w / 2, y: n.y - 26, width: n.w, height: 52, rx: 12 }, g);
      text(g, n.x, n.y - 3, n.title, 'pm-title');
      text(g, n.x, n.y + 16, n.sub, 'pm-sub');
      const go = () => opts.onFormat && opts.onFormat(kind);
      g.addEventListener('click', go);
      g.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          go();
        }
      });
      g.addEventListener('pointerenter', () => set(kind));
      g.addEventListener('pointerleave', () => set(null));
      return { kind, g };
    });
    // what a route is: the tool it opens and the package it belongs to; a box lights up its routes
    const touches = (r, name) => r.tool === name || r.pkg === name || r.ends.includes(name);
    let active = null;
    function set(name) {
      active = name;
      routes.forEach((r) => {
        const on = !!name && touches(r, name);
        r.g.classList.toggle('on', on);
        r.g.classList.toggle('off', !!name && !on);
        r.path.setAttribute('marker-end', r.path.getAttribute('marker-end') ? `url(#${uid}${on ? 'b' : 'a'})` : null);
        if (r.both) r.path.setAttribute('marker-start', `url(#${uid}${on ? 'b' : 'a'})`);
      });
      nodes.forEach((n) => n.g.classList.toggle('on', n.kind === name));
      if (opts.onHover) opts.onHover(name);
    }
    // moving dots along the routes, while the map is in view
    let t = 0, last = 0, raf = 0, visible = false;
    const frame = (now) => {
      raf = 0;
      if (!visible) return;
      const dt = last ? Math.min(0.1, (now - last) / 1000) : 0;
      last = now;
      t += dt;
      routes.forEach((r) => {
        if (!r.dots.length) return;
        if (!r.len) r.len = r.path.getTotalLength();
        const speed = 46 * (active && touches(r, active) ? 2.2 : 1);
        r.dots.forEach((d) => {
          const f = ((t * speed) / Math.max(80, r.len) + d.o) % 1;
          const pt = r.path.getPointAtLength(f * r.len);
          d.c.setAttribute('cx', pt.x.toFixed(1));
          d.c.setAttribute('cy', pt.y.toFixed(1));
        });
      });
      raf = requestAnimationFrame(frame);
    };
    let io = null;
    if (!reduced() && 'IntersectionObserver' in window) {
      io = new IntersectionObserver((es) => {
        visible = es.some((e) => e.isIntersecting);
        last = 0;
        if (visible && !raf) raf = requestAnimationFrame(frame);
      });
      io.observe(container);
    }
    // (when the map is drawn again in the other layout, this one stops)
    const stop = () => {
      visible = false;
      if (io) io.disconnect();
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    };
    return { highlight: set, stop };
  }
  // which formats each route joins (a box lights up the routes that start or end at it)
  const ROUTE_ENDS = [
    ['studio', 'ped'],
    ['ped', 'studio'],
    ['ped', 'mped'],
    ['studio', 'pedigree'],
    ['studio', 'family'],
    ['pedigree', 'studio'],
    ['family', 'studio'],
    ['pedigree', 'family'],
    ['pedigree', 'family', 'cohort', 'phenopacket'],
    ['family', 'pedigree', 'ped'],
    ['studio', 'terms'],
    ['terms', 'pedigree', 'family'],
    ['image', 'ped']
  ];

  /** the maps in help pages (<div class="pw-map"></div>), drawn the first time their page is shown */
  pedMap.mountAll = (root) => {
    (root || document).querySelectorAll('div.pw-map:not([data-drawn])').forEach((d) => {
      d.dataset.drawn = '1';
      pedMap(d, {
        onTool: (id) => MG.app.useTool && MG.app.useTool(id),
        onFormat: (kind) => MG.app.useTool && MG.app.useTool('start', { kind })
      });
    });
  };
  MG.pedMap = pedMap;
  if (MG.bus) MG.bus.on('help:page', ({ id }) => pedMap.mountAll(document.getElementById(id)));
})();
