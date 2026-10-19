/* Checks PedRisk against brute force: for small random pedigrees, every combination of everyone's alleles is
   enumerated and weighed, written here independently of the engine (alleles, not genotypes). */
'use strict';
const R = require(process.argv[2] || '../../assets/js/risk-engine.js');

let seed = 12345;
const rand = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
const pick = (a) => a[Math.floor(rand() * a.length)];

function randomPedigree() {
  const people = [];
  let n = 0;
  const id = () => `P${++n}`;
  const founders = 2 + Math.floor(rand() * 3);
  for (let i = 0; i < founders; i++) people.push({ id: id(), sex: pick(['M', 'F']), father: null, mother: null });
  const target = 4 + Math.floor(rand() * 4);   // 4 to 7 people
  let guard = 0;
  while (people.length < target && guard++ < 50) {
    const men = people.filter((p) => p.sex === 'M'), women = people.filter((p) => p.sex === 'F');
    if (!men.length || !women.length) { people.push({ id: id(), sex: men.length ? 'F' : 'M', father: null, mother: null }); continue; }
    const f = pick(men), m = pick(women);
    // no one's child with their own parent or grandparent, which the engine allows but is beside the point here
    people.push({ id: id(), sex: pick(['M', 'F', 'F', 'M', 'U']), father: f.id, mother: m.id });
  }
  // only people who are no one's parent may be of unknown sex
  const parents = new Set(people.flatMap((p) => [p.father, p.mother]).filter(Boolean));
  for (const p of people) if (p.sex === 'U' && parents.has(p.id)) p.sex = 'F';
  for (const p of people) if (p.father) { people.find((q) => q.id === p.father).sex = 'M'; people.find((q) => q.id === p.mother).sex = 'F'; }
  // a parent who has been both a father and a mother is impossible: drop such pedigrees
  for (const p of people) {
    const asFather = people.some((c) => c.father === p.id), asMother = people.some((c) => c.mother === p.id);
    if (asFather && asMother) return null;
  }
  // now and then an identical twin of a child: the same parents and sex, and the same alleles
  if (rand() < 0.35) {
    const children = people.filter((p) => p.father && !p.twin);
    if (children.length) {
      const c = pick(children);
      people.push({ id: `P${++n}`, sex: c.sex, father: c.father, mother: c.mother, twin: c.id });
    }
  }
  for (const p of people) {
    p.affected = pick([true, false, null, null, false]);
    p.test = rand() < 0.15 ? pick(['variant', 'carrier', 'none', 'homozygous']) : null;
  }
  return people;
}

/* the model, as the engine's documentation states it */
function pen(mode, sex, copies, m) {
  let has;
  if (mode === 'AD' || mode === 'XLD') has = copies >= 1;
  else if (mode === 'AR') has = copies === 2;
  else has = sex === 'M' ? copies === 1 : copies === 2;
  return has ? m.penetrance : m.phenocopy;
}
function fitsTest(mode, test, copies) {
  if (!test) return 1;
  if (test === 'variant') return copies >= 1 ? 1 : 0;
  if (test === 'carrier') return (mode === 'AR' || mode === 'XLR') ? (copies === 1 ? 1 : 0) : (copies >= 1 ? 1 : 0);
  if (test === 'homozygous') return copies === 2 ? 1 : 0;
  return copies === 0 ? 1 : 0;
}

/* every assignment of alleles: each person has a sex (fixed, or either if unknown) and alleles (two, or one for a
   man under an X-linked mode); a founder's alleles are each the variant with chance q; a child's are copies of one
   of each parent's (a son's one X from his mother; a daughter's from her father's X and one of her mother's), each
   becoming the variant by new mutation with chance mu */
function brute(people, model, extraChild) {
  const x = model.mode === 'XLR' || model.mode === 'XLD';
  const list = people.slice();
  if (extraChild) list.push(extraChild);
  const idx = new Map(list.map((p, i) => [p.id, i]));
  const n = list.length;
  const results = list.map(() => ({ variant: 0, one: 0, two: 0, affected: 0 }));
  let total = 0;
  const sexes = new Array(n), alleles = new Array(n);
  function weightOfAllele(childAllele, parentAlleles) {
    // chance that a child's allele from this parent is childAllele: the parent passes one of parentAlleles at random
    let p1 = 0;
    for (const a of parentAlleles) p1 += (a ? 1 : model.mutation) / parentAlleles.length;
    return childAllele ? p1 : 1 - p1;
  }
  function rec(i, w) {
    if (w === 0) return;
    if (i === n) {
      total += w;
      for (let k = 0; k < n; k++) {
        const c = alleles[k].reduce((s, a) => s + a, 0);
        if (c >= 1) results[k].variant += w;
        if (c === 1) results[k].one += w;
        if (c === 2) results[k].two += w;
        results[k].affected += w * pen(model.mode, sexes[k], c, model);
      }
      return;
    }
    const p = list[i];
    if (p.twin) {
      // an identical twin: their co-twin's sex and alleles, for certain
      const k = idx.get(p.twin);
      const c = alleles[k].reduce((s, a) => s + a, 0);
      const pn = pen(model.mode, sexes[k], c, model);
      sexes[i] = sexes[k];
      alleles[i] = alleles[k];
      rec(i + 1, w * (p.affected === true ? pn : p.affected === false ? 1 - pn : 1) * fitsTest(model.mode, p.test, c));
      return;
    }
    const sexOptions = p.sex === 'U' ? ['M', 'F'] : [p.sex];
    for (const sex of sexOptions) {
      const ws = p.sex === 'U' ? 0.5 : 1;
      const nAlleles = x && sex === 'M' ? 1 : 2;
      for (let code = 0; code < (1 << nAlleles); code++) {
        const al = [];
        for (let b = 0; b < nAlleles; b++) al.push((code >> b) & 1);
        let wi;
        if (!p.father) {
          wi = al.reduce((s, a) => s * (a ? model.q : 1 - model.q), 1);
        } else {
          const fa = alleles[idx.get(p.father)], mo = alleles[idx.get(p.mother)];
          if (!x) wi = weightOfAllele(al[0], fa) * weightOfAllele(al[1], mo);
          else if (sex === 'M') wi = weightOfAllele(al[0], mo);
          else wi = weightOfAllele(al[0], fa) * weightOfAllele(al[1], mo);
        }
        const c = al.reduce((s, a) => s + a, 0);
        const pn = pen(model.mode, sex, c, model);
        const known = p.id === '\u0000child' ? 1 : (p.affected === true ? pn : p.affected === false ? 1 - pn : 1) * fitsTest(model.mode, p.test, c);
        sexes[i] = sex;
        alleles[i] = al;
        rec(i + 1, w * ws * wi * known);
      }
    }
  }
  // parents before children
  const order = [];
  const seen = new Set();
  const visit = (p) => { if (seen.has(p.id)) return; seen.add(p.id); if (p.father) { visit(list[idx.get(p.father)]); visit(list[idx.get(p.mother)]); } if (p.twin) visit(list[idx.get(p.twin)]); order.push(p); };
  list.forEach(visit);
  list.splice(0, n, ...order);
  list.forEach((p, i) => idx.set(p.id, i));
  rec(0, 1);
  if (total === 0) return null;
  const out = {};
  list.forEach((p, k) => { out[p.id] = Object.fromEntries(Object.entries(results[k]).map(([key, v]) => [key, v / total])); });
  return out;
}

let checked = 0, impossible = 0, failures = 0;
const close = (a, b) => Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(b));
for (let trial = 0; trial < 600; trial++) {
  const people = randomPedigree();
  if (!people) continue;
  const model = {
    mode: pick(['AD', 'AR', 'XLR', 'XLD']),
    q: pick([0.001, 0.01, 0.05, 0.2]),
    penetrance: pick([1, 1, 0.8, 0.5]),
    phenocopy: pick([0, 0, 0, 0.01]),
    mutation: pick([0, 0, 0.001, 0.05])
  };
  const want = brute(people, model);
  const got = R.analyse(people, model);
  if (!want) {
    if (got.ok) { failures++; console.log('should be impossible', JSON.stringify({ people, model })); }
    else impossible++;
    continue;
  }
  if (!got.ok) { failures++; console.log('said impossible wrongly', got.message, JSON.stringify({ people, model })); continue; }
  for (const p of people) {
    for (const key of ['variant', 'one', 'two', 'affected']) {
      if (!close(got.people[p.id][key], want[p.id][key])) {
        failures++;
        console.log(`trial ${trial} ${model.mode} ${p.id} ${key}: engine ${got.people[p.id][key]} brute ${want[p.id][key]}`, JSON.stringify({ people, model }));
      }
    }
  }
  // a child of a random couple
  const men = people.filter((p) => p.sex === 'M'), women = people.filter((p) => p.sex === 'F');
  if (men.length && women.length) {
    const f = pick(men), m = pick(women);
    const cr = R.childRisk(people, model, f.id, m.id);
    const x = model.mode === 'XLR' || model.mode === 'XLD';
    for (const [sex, key] of x ? [['M', 'son'], ['F', 'daughter']] : [['U', 'any']]) {
      const w = brute(people, model, { id: '\u0000child', sex, father: f.id, mother: m.id });
      for (const k of ['variant', 'affected'])
        if (!close(cr[key][k], w['\u0000child'][k])) { failures++; console.log(`child ${key} ${k}: engine ${cr[key][k]} brute ${w['\u0000child'][k]}`, JSON.stringify({ people, model, f: f.id, m: m.id })); }
    }
  }
  // the Bayes table: its posterior is the analysis's, and its prior is the brute force without the person's and
  // their descendants' phenotypes and tests
  const who = pick(people);
  const table = R.bayes(people, model, who.id);
  if (table.ok) {
    // the person, their identical twins (whose phenotypes say as much about the same genotype), and the descendants
    // of them all
    const desc = new Set([who.id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const p of people) {
        const inside = desc.has(p.father) || desc.has(p.mother) || (p.twin && desc.has(p.twin)) || people.some((q) => q.twin === p.id && desc.has(q.id));
        if (!desc.has(p.id) && inside) { desc.add(p.id); grew = true; }
      }
    }
    const blind = people.map((p) => (desc.has(p.id) ? Object.assign({}, p, { affected: null, test: null }) : p));
    const priorWant = brute(blind, model);
    const postVariant = table.rows.filter((r) => r.copies >= 1).reduce((s, r) => s + r.posterior, 0);
    const priorVariant = table.rows.filter((r) => r.copies >= 1).reduce((s, r) => s + r.prior, 0);
    const sumJ = table.rows.reduce((s, r) => s + r.joint, 0);
    const postFromJoint = table.rows.filter((r) => r.copies >= 1).reduce((s, r) => s + r.joint, 0) / sumJ;
    if (!close(postVariant, want[who.id].variant) && Math.abs(postVariant - want[who.id].variant) > 2e-6) { failures++; console.log('bayes posterior', postVariant, want[who.id].variant); }
    if (Math.abs(priorVariant - priorWant[who.id].variant) > 2e-6) { failures++; console.log('bayes prior', priorVariant, priorWant[who.id].variant, JSON.stringify({ people, model, who: who.id })); }
    if (Math.abs(postFromJoint - postVariant) > 2e-6) { failures++; console.log('bayes joint', postFromJoint, postVariant); }
  }
  checked++;
}
console.log(`${checked} pedigrees checked against brute force, ${impossible} impossible under their model (as brute force found too), ${failures} failures`);
process.exit(failures ? 1 : 0);
