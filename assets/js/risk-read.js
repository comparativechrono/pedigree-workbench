/* =====================================================================
   PedRead: families for the Risk tab, read in the page from a drawing
   in Pedigree Studio, a PED file or an MPED file. Each is read as the
   workbench's converters read it, so that the Risk tab sees the family
   the Tools tab does: a drawing as studio2ped and studio2ga4gh read it,
   and PED and MPED files as mpedtools does. GA4GH files are read in
   Python, with pedigree-ga4gh (python/pedwb/risk.py), into the same
   shape.

   A file is one or more families: { id, people, conditions, notes,
   unrecorded, partners }; partners lists couples, as [id, id], the
   drawn couples of a drawing, who may have no children yet.
     people: [{ id, label, name, sex: 'M', 'F' or 'U', father, mother,
                twin (an identical twin's id), status, pregnancy, loss,
                deceased, proband, index }]
       status: { conditionKey: 'affected', 'unaffected' or 'carrier' };
       someone with no status for a condition has no record of it
     conditions: [{ key, label, id, colour, pattern, unnamed }]
     unrecorded: what to take people with no record of a condition to
       be: 'unknown', or 'auto' (unaffected, unless anyone is recorded
       as unaffected: see PedNet's reading of GA4GH files); and
       unrecordedFor, the same for particular conditions

   In a page this is window.PedRead; in Node, require('./risk-read.js').
   ===================================================================== */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PedRead = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /* ---------------- a drawing from Pedigree Studio ---------------- */
  const SHAPE_SEX = { male: 'M', female: 'F', unknown: 'U', 'adopted-male': 'M', 'adopted-female': 'F', 'adopted-unknown': 'U' };
  // a bar under a couple for "no children", and a double bar for infertility: symbols, not people
  const MARKERS = { 'no-offspring': 'no children', infertile: 'infertility' };
  const WHITE = new Set(['#fff', '#ffffff', 'white', '#fffffe']);
  const ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII'];
  const LEGACY_FILL = '#1a2332';

  const isDrawing = (doc) => !!doc && typeof doc === 'object' && Array.isArray(doc.persons);

  /** the symbols of a drawing, as studio2ga4gh reads them (any version of the Studio's files from 3 on) */
  function symbols(data) {
    const persons = new Map();
    for (const pd of data.persons || []) {
      if (!pd || pd.id == null) continue;
      let fillMode = pd.fillMode || 'none', fillColor = pd.fillColor;
      if (pd.affected && fillMode === 'none') { fillMode = 'solid'; fillColor = LEGACY_FILL; }   // files from before fills
      persons.set(String(pd.id), {
        id: String(pd.id), shape: pd.shape || 'unknown', x: Number(pd.x) || 0, y: Number(pd.y) || 0,
        text: pd.text || '', deceased: !!pd.deceased, proband: !!pd.proband,
        fillMode, fillColor, halves: Array.isArray(pd.halves) ? pd.halves : [null, null],
        quarters: Array.isArray(pd.quarters) ? pd.quarters : [null, null, null, null],
        shadingPattern: pd.shadingPattern || 'stripes', shadingCoverage: pd.shadingCoverage || 'full',
        centre: String(pd.centerText || ''), lossSex: pd.miscarriageSex || 'unknown', customLabel: pd.customLabel || ''
      });
    }
    return persons;
  }

  /** each symbol's label as the drawing shows it: I-1, II-3 ... (a generation starts 80 px below the first symbol of
      the one above, as in the Studio), I-A, letters, or the drawer's own */
  function labels(persons, mode) {
    const items = [...persons.values()].sort((a, b) => a.y - b.y);
    const gens = [];
    for (const p of items) {
      if (gens.length && p.y - gens[gens.length - 1][0].y < 80) gens[gens.length - 1].push(p);
      else gens.push([p]);
    }
    const letter = (n) => { let s = ''; while (n >= 0) { s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26) - 1; } return s; };
    const nums = {}, lets = {}, only = {};
    let k = 0;
    gens.forEach((gen, gi) => {
      const g = gi < ROMAN.length ? ROMAN[gi] : String(gi + 1);
      gen.slice().sort((a, b) => a.x - b.x).forEach((p, pi) => {
        nums[p.id] = `${g}-${pi + 1}`;
        lets[p.id] = `${g}-${letter(pi)}`;
        only[p.id] = letter(k++);
      });
    });
    if (mode === 'letters') return lets;
    if (mode === 'lettersonly') return only;
    if (mode === 'freetext') {
      const out = {};
      for (const p of persons.values()) { const l = (p.customLabel || '').trim(); out[p.id] = l && l !== 'Lbl' ? l : nums[p.id]; }
      return out;
    }
    return nums;
  }

  const lc = (c) => String(c || '').toLowerCase();
  const isHalf = (coverage) => coverage === 'half-left' || coverage === 'half-right';

  /** the conditions of a drawing: the entries of its key, in the key's order, and then any colour or shading in
      use that the key doesn't name (each a condition of its own, named by how it is drawn). An entry may end with
      its ontology term in brackets, as studio2ga4gh reads it: Breast cancer [MONDO:0007254] is named Breast cancer,
      with the id MONDO:0007254 */
  function conditionsOf(persons, legend) {
    const out = [], seen = new Set();
    for (const [key, raw] of Object.entries(legend || {})) {
      const text = String(raw || '').trim();
      if (!text) continue;
      const m = /^(.*?)\s*\[([A-Za-z][\w.-]*:[^\]\s]+)\]$/.exec(text);
      const label = m && m[1] ? m[1] : text, id = m ? m[2] : null;
      if (key.startsWith('shading:')) {
        const parts = key.split(':');
        out.push({ key, label, id, pattern: parts[1] || 'stripes', coverage: parts[2] || 'full' });
      } else {
        if (WHITE.has(lc(key))) continue;
        out.push({ key: lc(key), label, id, colour: key });
      }
      seen.add(key.startsWith('shading:') ? key : lc(key));
    }
    const named = new Set(out.filter((c) => c.pattern).map((c) => c.pattern));
    for (const p of persons.values()) {
      if (p.shape in MARKERS) continue;
      const cs = p.fillMode === 'solid' ? [p.fillColor] : p.fillMode === 'half' ? p.halves : p.fillMode === 'quartered' ? p.quarters : [];
      for (const c of cs) {
        if (!c || WHITE.has(lc(c)) || seen.has(lc(c))) continue;
        seen.add(lc(c));
        out.push({ key: lc(c), label: `the colour ${c}`, colour: c, unnamed: true });
      }
      if (p.fillMode === 'shading' && !named.has(p.shadingPattern)) {
        named.add(p.shadingPattern);
        const key = `shading:${p.shadingPattern}:full`;
        out.push({ key, label: `${p.shadingPattern === 'dots' ? 'dotted' : 'striped'} shading`, pattern: p.shadingPattern, coverage: 'full', unnamed: true });
      }
    }
    return out;
  }

  /** each condition's status for one symbol, as studio2ped classifies it: a solid fill, a quarter or full shading is
      affected; one half filled (the other empty) or half shading is a carrier; and a dot in the symbol makes a carrier
      of every condition shown (or of the first, if none is) */
  function statusOf(p, conditions) {
    const out = {};
    conditions.forEach((c) => { out[c.key] = 'unaffected'; });
    const colours = new Map();   // colour -> whether it fills only one half
    if (p.fillMode === 'solid' && p.fillColor) colours.set(lc(p.fillColor), false);
    else if (p.fillMode === 'half') p.halves.forEach((c, i) => { if (c) colours.set(lc(c), !p.halves[1 - i]); });
    else if (p.fillMode === 'quartered') p.quarters.forEach((c) => { if (c) colours.set(lc(c), false); });
    for (const c of conditions) if (c.colour && colours.has(c.key)) out[c.key] = colours.get(c.key) ? 'carrier' : 'affected';
    if (p.fillMode === 'shading') {
      const key = `shading:${p.shadingPattern}:${p.shadingCoverage}`;
      for (const c of conditions) {
        if (!c.pattern) continue;
        if (c.key === key) out[c.key] = isHalf(p.shadingCoverage) ? 'carrier' : 'affected';
        else if (c.pattern === p.shadingPattern && c.key === `shading:${p.shadingPattern}:full` && isHalf(p.shadingCoverage)) out[c.key] = 'carrier';
      }
    }
    if (p.centre === 'dot') {
      if (conditions.some((c) => out[c.key] !== 'unaffected')) conditions.forEach((c) => { if (out[c.key] === 'affected') out[c.key] = 'carrier'; });
      else if (conditions.length) out[conditions[0].key] = 'carrier';
    }
    return out;
  }

  /** a drawing (a Studio session, as saved or as the Studio has it) as a family */
  function fromStudio(data, name) {
    if (!isDrawing(data)) throw new Error('This is not a drawing from Pedigree Studio: it has no people');
    const persons = symbols(data);
    const shown = labels(persons, data.numberingMode || 'numbers');
    const conditions = conditionsOf(persons, data.legendLabels);
    const notes = [];
    const people = new Map();
    for (const p of persons.values()) {
      if (p.shape in MARKERS) continue;
      const loss = p.shape === 'miscarriage';
      const sex = loss ? ({ male: 'M', female: 'F' }[p.lossSex] || 'U') : (SHAPE_SEX[p.shape] || 'U');
      const status = statusOf(p, conditions);
      people.set(p.id, {
        id: p.id, label: shown[p.id] || p.id, name: String(p.text || '').split('\n')[0].trim(), sex,
        father: null, mother: null, twin: null, status,
        pregnancy: p.centre === 'P', loss, deceased: p.deceased, proband: p.proband, index: p.proband
      });
    }
    // parents, as studio2ped finds them: the man of a couple is the father (or, if the sexes don't say, the partner
    // the line was drawn from); a dashed line, an adoption, gives no genetic parents; and a parent marked G, a
    // gestational carrier (S in drawings from before the 2025 correction to the nomenclature), is not a genetic
    // parent. Twins count as one genotype only when identical: neither non-identical twins nor twins whose
    // zygosity is not known ("?") do.
    const couples = new Map();
    for (const pd of data.partnerships || []) {
      if (pd && persons.has(String(pd.fromId)) && persons.has(String(pd.toId))) couples.set(String(pd.id), [String(pd.fromId), String(pd.toId)]);
    }
    for (const cl of data.childLinks || []) {
      const couple = couples.get(String(cl.partnershipId));
      const child = people.get(String(cl.childId));
      if (!couple || !child) continue;
      const [a, b] = couple.map((id) => persons.get(id));
      const sa = SHAPE_SEX[a.shape] || 'U', sb = SHAPE_SEX[b.shape] || 'U';
      const [father, mother] = sa === 'F' && sb === 'M' ? [b, a] : [a, b];
      if (cl.dashed) { notes.push(`${child.label} is adopted: their adoptive parents are not their genetic parents`); continue; }
      for (const [parent, role] of [[father, 'father'], [mother, 'mother']]) {
        if (parent.centre === 'G' || parent.centre === 'S') notes.push(`${shown[parent.id]} carried ${child.label} as a gestational carrier, so is not a genetic parent`);
        else if (people.has(parent.id)) child[role] = parent.id;
      }
    }
    const partners = [...couples.values()].filter(([a, b]) => people.has(a) && people.has(b));
    for (const t of data.twinLinks || []) {
      const one = people.get(String(t.child1Id)), two = people.get(String(t.child2Id));
      if (one && two && (t.type || 'identical') === 'identical') two.twin = one.id;
    }
    if (conditions.some((c) => c.unnamed))
      notes.push('Some colours or shadings have no entry in the drawing’s key, so they are named by how they are drawn: name them in the Studio’s key');
    return { id: name || 'drawing', people: [...people.values()], conditions, notes, unrecorded: 'unknown', partners };
  }

  /* ---------------- PED and MPED files, as mpedtools reads them ---------------- */
  const PED_STATUS = { 1: 'unaffected', 2: 'affected', 3: 'carrier' };

  /** a PED or MPED file: a family for each family ID in it, in the order they first appear */
  function fromPed(text) {
    const lines = String(text || '').split(/\r?\n/);
    let names = null, mped = false, start = lines.length;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (!line) continue;
      if (line.startsWith('# MPED v')) { mped = true; names = line.split('\t').slice(1).map((s) => s.trim()).filter(Boolean); continue; }
      if (line.startsWith('#')) continue;
      start = i;
      break;
    }
    if (!mped) names = ['Phenotype'];
    // (the Carrier column that studio2ped adds says who has a carrier's dot, who are carriers in the other columns
    // too: it isn't a condition)
    const shown = names.filter((n) => !(mped && names.length > 1 && n.toLowerCase() === 'carrier'));
    const conditions = shown.map((n) => ({ key: n, label: mped ? n.replace(/_/g, ' ') : 'affected, as the PED file has it' }));
    const families = new Map();
    for (const raw of lines.slice(start)) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;
      let parts = line.split('\t');
      if (parts.length < 6) parts = line.split(/\s+/);
      if (parts.length < 6) continue;
      const [fam, id, father, mother, sex] = parts;
      const status = {};
      names.forEach((n, j) => {
        const code = parseInt(parts[5 + j], 10);
        if (PED_STATUS[code] && shown.includes(n)) status[n] = PED_STATUS[code];
      });
      if (!families.has(fam)) families.set(fam, []);
      families.get(fam).push({
        id, label: id, name: '', sex: sex === '1' ? 'M' : sex === '2' ? 'F' : 'U',
        father: father === '0' || father === '-9' ? null : father, mother: mother === '0' || mother === '-9' ? null : mother,
        twin: null, status
      });
    }
    if (!families.size) throw new Error('There is no one in this file: a PED file has a line for each person, in six columns');
    return [...families].map(([id, people]) => ({ id, people, conditions, notes: [], unrecorded: 'unknown', partners: [] }));
  }

  /* ---------------- what the risk engine is given ---------------- */

  /** the people of a family as PedRisk takes them, for one condition: affected (true, false or null), a test result
      ('carrier' for a carrier mark), and the status of everyone with no record of it, as unrecorded says. tests
      (optional) gives, by id, what replaces what the family says: a test result, 'variant', 'carrier', 'homozygous'
      or 'none'; 'clear' for no test result (not even a carrier mark); or a status, 'affected', 'unaffected' or
      'unknown' (which leaves out what is known of the person, as if their status weren't known) */
  function forEngine(family, conditionKey, tests, unrecorded) {
    const rule = unrecorded || unrecordedAs(family, conditionKey);
    const fill = rule === 'unaffected' ? false : null;
    return family.people.map((p) => {
      const s = p.status ? p.status[conditionKey] : undefined;
      let affected = s === 'affected' ? true : s === 'unaffected' ? false : s === 'carrier' ? null : fill;
      let test = s === 'carrier' ? 'carrier' : null;
      // someone not yet born, or lost in pregnancy, can't be said to be unaffected
      if ((p.pregnancy || p.loss) && affected === false) affected = null;
      const given = tests && tests[p.id];
      if (given === 'unknown' || given === 'affected' || given === 'unaffected') {
        affected = given === 'affected' ? true : given === 'unaffected' ? false : null;
        test = null;
      } else if (given) test = given === 'clear' ? null : given;
      return { id: p.id, label: p.label, sex: p.sex, father: p.father, mother: p.mother, twin: p.twin, affected, test };
    });
  }
  /** what to take people with no record of a condition to be, under rule 'auto': 'unaffected' or 'unknown' */
  function unrecordedAs(family, conditionKey) {
    const rule = (family.unrecordedFor && family.unrecordedFor[conditionKey]) || family.unrecorded || 'unknown';
    if (rule !== 'auto') return rule;
    return family.people.some((p) => p.status && p.status[conditionKey] === 'unaffected') ? 'unknown' : 'unaffected';
  }

  return { isDrawing, fromStudio, fromPed, forEngine, unrecordedAs, _labels: labels, _statusOf: statusOf, _conditionsOf: conditionsOf, _symbols: symbols };
});
