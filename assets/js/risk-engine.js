/* =====================================================================
   PedRisk: the chance that each person in a pedigree carries a variant,
   and that a child of a couple will be affected, given what is known of
   the whole family, under a single-gene model: autosomal dominant,
   autosomal recessive, X-linked recessive or X-linked dominant.

   No one's genotype is known for certain. The founders' genotypes come
   from the population, in Hardy–Weinberg proportions for the variant's
   allele frequency, and everyone else's from their parents by Mendel's
   laws, with new mutations if a rate is given. Whether someone is
   affected depends on their genotype through the penetrance (and a
   phenocopy rate, for people affected for another reason). A test
   result can be given too: that someone has the variant, is a carrier,
   or doesn't have it.

   The answers are exact. The genotypes are summed out one at a time
   (variable elimination, the general form of the "peeling" that
   pedigree risk programs use), which copes with loops in the pedigree,
   as when cousins marry, as well as with any number of generations.

   In a page this is window.PedRisk; in Node, require('./risk-engine.js').
   ===================================================================== */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PedRisk = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const MODES = {
    AD: { name: 'Autosomal dominant', x: false },
    AR: { name: 'Autosomal recessive', x: false },
    XLR: { name: 'X-linked recessive', x: true },
    XLD: { name: 'X-linked dominant', x: true }
  };
  /* the largest table of probabilities worked with at once: a pedigree with many loops can need more */
  const MAX_TABLE = 4000000;

  class RiskError extends Error {
    constructor(message, who) { super(message); this.name = 'RiskError'; this.who = who || null; }
  }

  /* ---------- the model ---------- */
  function checkModel(model) {
    const m = Object.assign({ penetrance: 1, phenocopy: 0, mutation: 0 }, model || {});
    if (!MODES[m.mode]) throw new RiskError(`unknown mode of inheritance: ${m.mode}`);
    const inRange = (v, lo, hi) => typeof v === 'number' && isFinite(v) && v >= lo && v <= hi;
    if (!inRange(m.q, 0, 1) || m.q <= 0 || m.q >= 1) throw new RiskError('the allele frequency must be between 0 and 1');
    if (!inRange(m.penetrance, 0, 1) || m.penetrance <= 0) throw new RiskError('the penetrance must be above 0, and at most 1');
    if (!inRange(m.phenocopy, 0, 1) || m.phenocopy >= m.penetrance) throw new RiskError('the phenocopy rate must be at least 0, and less than the penetrance');
    if (!inRange(m.mutation, 0, 0.5)) throw new RiskError('the mutation rate must be between 0 and 0.5');
    return m;
  }

  /* the chance that someone with this genotype is affected */
  function penetrance(state, m) {
    const c = state.copies;
    let has;
    if (m.mode === 'AD' || m.mode === 'XLD') has = c >= 1;
    else if (m.mode === 'AR') has = c === 2;
    else has = state.sex === 'M' ? c === 1 : c === 2;   // XLR: a man with his one X, a woman with both
    return has ? m.penetrance : m.phenocopy;
  }

  /* how well a test result fits a genotype (1 or 0) */
  function fitsTest(test, state, m) {
    const c = state.copies;
    switch (test) {
      case 'variant': return c >= 1 ? 1 : 0;
      case 'carrier': return (m.mode === 'AR' || m.mode === 'XLR') ? (c === 1 ? 1 : 0) : (c >= 1 ? 1 : 0);
      case 'homozygous': return c === 2 ? 1 : 0;
      case 'none': return c === 0 ? 1 : 0;
      default: return 1;
    }
  }

  /* each person's possible genotypes. A man has one X, so two genotypes under an X-linked mode; someone of unknown
     sex (who can only be a child, as a parent's sex is known from being a father or mother) may be either */
  const S = (sex, copies) => ({ sex, copies });
  function statesOf(sex, x) {
    if (!x) return [S(sex, 0), S(sex, 1), S(sex, 2)];
    if (sex === 'M') return [S('M', 0), S('M', 1)];
    if (sex === 'F') return [S('F', 0), S('F', 1), S('F', 2)];
    return [S('M', 0), S('M', 1), S('F', 0), S('F', 1), S('F', 2)];
  }

  /* a founder's genotype, from the population */
  function founderPrior(state, sex, x, q) {
    const p = 1 - q;
    const hw = [p * p, 2 * p * q, q * q];
    if (!x) return hw[state.copies];
    const one = state.sex === 'M' ? (state.copies ? q : p) : hw[state.copies];
    return sex === 'U' ? one / 2 : one;
  }

  /* the chance that a parent passes the variant on: half their copies (all of a man's X, to a daughter), or a new
     mutation in a copy without it */
  function passes(copies, of, mu) {
    const t = copies / of;
    return t + (1 - t) * mu;
  }
  function fromTwo(c, a, b) {   // the chance of c copies, getting one from each of two parents with chances a and b
    return c === 2 ? a * b : c === 1 ? a * (1 - b) + (1 - a) * b : (1 - a) * (1 - b);
  }
  function transmit(child, sex, father, mother, x, mu) {
    if (!x) return fromTwo(child.copies, passes(father.copies, 2, mu), passes(mother.copies, 2, mu));
    const fromMother = passes(mother.copies, 2, mu);
    let p;
    if (child.sex === 'M') p = child.copies ? fromMother : 1 - fromMother;   // a son's X is his mother's
    else p = fromTwo(child.copies, passes(father.copies, 1, mu), fromMother);   // a daughter has her father's
    return sex === 'U' ? p / 2 : p;
  }

  /* ---------- the people ---------- */
  function prepare(people) {
    if (!Array.isArray(people) || !people.length) throw new RiskError('the pedigree has no one in it');
    const byId = new Map();
    const list = [];
    for (const person of people) {
      const id = String(person.id);
      if (!id) throw new RiskError('someone has no id');
      if (byId.has(id)) throw new RiskError(`${id} is in the pedigree twice`, id);
      const sex = person.sex === 'M' || person.sex === 'F' ? person.sex : 'U';
      const p = {
        id, label: person.label != null && person.label !== '' ? String(person.label) : id, sex,
        father: person.father != null && person.father !== '' && person.father !== '0' ? String(person.father) : null,
        mother: person.mother != null && person.mother !== '' && person.mother !== '0' ? String(person.mother) : null,
        affected: person.affected === true ? true : person.affected === false ? false : null,
        test: ['variant', 'carrier', 'homozygous', 'none'].includes(person.test) ? person.test : null,
        twin: person.twin != null && person.twin !== '' ? String(person.twin) : null,
        added: false
      };
      byId.set(id, p);
      list.push(p);
    }
    // identical twins have one genotype: they are grouped (triplets too), take each other's parents if only one
    // has them, and must be of one sex. rep is the first of each group, whose genotype stands for them all
    const root = new Map(list.map((p) => [p.id, p.id]));
    const order = new Map(list.map((p, i) => [p.id, i]));
    const find = (id) => { while (root.get(id) !== id) id = root.get(id); return id; };
    for (const p of list) {
      if (!p.twin) continue;
      if (!byId.has(p.twin)) throw new RiskError(`${p.label}'s identical twin, ${p.twin}, is not in the pedigree`, p.id);
      if (p.twin === p.id) throw new RiskError(`${p.label} is their own twin`, p.id);
      const a = find(p.id), b = find(p.twin);
      if (a !== b) { if (order.get(a) < order.get(b)) root.set(b, a); else root.set(a, b); }
    }
    const groups = new Map();
    for (const p of list) {
      p.rep = find(p.id);
      if (!groups.has(p.rep)) groups.set(p.rep, []);
      groups.get(p.rep).push(p);
    }
    for (const group of groups.values()) {
      if (group.length < 2) continue;
      const names = group.map((p) => p.label).join(' and ');
      const sexes = new Set(group.map((p) => p.sex).filter((x) => x !== 'U'));
      if (sexes.size > 1) throw new RiskError(`${names} are identical twins, but not of the same sex`, group[0].id);
      const sex = sexes.size ? [...sexes][0] : 'U';
      const withParents = group.filter((p) => p.father || p.mother);
      const parents = withParents.length ? [withParents[0].father, withParents[0].mother] : [null, null];
      if (withParents.some((p) => p.father !== parents[0] || p.mother !== parents[1]))
        throw new RiskError(`${names} are identical twins, but have different parents`, group[0].id);
      for (const p of group) { p.sex = sex; p.father = parents[0]; p.mother = parents[1]; }
    }
    const add = (id, sex) => {
      const p = { id, label: id, sex, father: null, mother: null, affected: null, test: null, twin: null, added: true, rep: id };
      byId.set(id, p);
      list.push(p);
      return p;
    };
    for (const p of list.slice()) {
      if (p.father && p.father === p.mother) throw new RiskError(`${p.label}'s father and mother are the same person`, p.id);
      for (const role of ['father', 'mother'])
        if (p[role] && !byId.has(p[role])) add(p[role], role === 'father' ? 'M' : 'F');
      // someone with one parent known has another, unknown, who is added as a founder
      if (!p.father !== !p.mother) {
        const role = p.father ? 'mother' : 'father';
        let id = `${byId.get(p.rep).id}'s ${role}`;
        if (!byId.has(id)) add(id, role === 'father' ? 'M' : 'F');
        for (const q of groups.get(p.rep) || [p]) q[role] = id;
      }
    }
    for (const p of list) {
      for (const role of ['father', 'mother']) {
        if (!p[role]) continue;
        const parent = byId.get(p[role]);
        const sex = role === 'father' ? 'M' : 'F';
        if (parent.sex !== 'U' && parent.sex !== sex)
          throw new RiskError(`${parent.label} is ${p.label}'s ${role}, but is ${parent.sex === 'M' ? 'male' : 'female'}`, parent.id);
        for (const twin of groups.get(parent.rep) || [parent]) twin.sex = sex;
      }
    }
    // no one may be their own ancestor
    const state = new Map();
    const visit = (p, path) => {
      if (state.get(p.id) === 2) return;
      if (state.get(p.id) === 1) throw new RiskError(`${p.label} is their own ancestor`, p.id);
      state.set(p.id, 1);
      for (const role of ['father', 'mother']) if (p[role]) visit(byId.get(p[role]), path);
      state.set(p.id, 2);
    };
    list.forEach((p) => visit(p));
    return { list, byId };
  }

  /* ---------- tables of probabilities, and summing genotypes out of them ---------- */
  function product(factors, card) {
    const vars = [];
    for (const f of factors) for (const v of f.vars) if (!vars.includes(v)) vars.push(v);
    const cards = vars.map((v) => card[v]);
    let size = 1;
    for (const c of cards) size *= c;
    if (size > MAX_TABLE) throw new RiskError('This pedigree has too many loops to work out exactly here');
    const out = new Float64Array(size).fill(1);
    const n = vars.length;
    const idx = new Int32Array(n);
    for (const f of factors) {
      const stride = new Array(n).fill(0);
      let s = 1;
      for (let k = f.vars.length - 1; k >= 0; k--) { stride[vars.indexOf(f.vars[k])] = s; s *= f.cards[k]; }
      idx.fill(0);
      let fi = 0;
      for (let o = 0; o < size; o++) {
        out[o] *= f.values[fi];
        for (let k = n - 1; k >= 0; k--) {
          idx[k]++;
          fi += stride[k];
          if (idx[k] < cards[k]) break;
          fi -= stride[k] * cards[k];
          idx[k] = 0;
        }
      }
    }
    return { vars, cards, values: out };
  }
  function sumOut(f, v) {
    const k = f.vars.indexOf(v);
    const vars = f.vars.filter((_, i) => i !== k);
    const cards = f.cards.filter((_, i) => i !== k);
    let after = 1;
    for (let i = k + 1; i < f.cards.length; i++) after *= f.cards[i];
    const ck = f.cards[k];
    const before = f.values.length / (after * ck);
    const out = new Float64Array(before * after);
    for (let b = 0; b < before; b++)
      for (let j = 0; j < ck; j++)
        for (let a = 0; a < after; a++) out[b * after + a] += f.values[(b * ck + j) * after + a];
    return { vars, cards, values: out };
  }

  /* the order to sum genotypes out in: each time, the one whose table would be smallest */
  function eliminationOrder(factors, card) {
    const nb = card.map(() => new Set());
    for (const f of factors) for (const u of f.vars) for (const w of f.vars) if (u !== w) nb[u].add(w);
    const left = new Set(card.map((_, i) => i));
    const order = [];
    while (left.size) {
      let best = -1, bestCost = Infinity;
      for (const v of left) {
        let cost = 1;
        for (const u of nb[v]) cost *= card[u];
        if (cost < bestCost) { bestCost = cost; best = v; }
      }
      order.push(best);
      left.delete(best);
      for (const u of nb[best]) {
        nb[u].delete(best);
        for (const w of nb[best]) if (w !== u) nb[u].add(w);
      }
    }
    return order;
  }

  /* the genotypes of the people in keep, jointly, with everyone else summed out: a table, and the log of the scale
     it was divided by along the way (so that very small probabilities don't underflow) */
  function joint(net, keep) {
    let factors = net.factors.slice();
    let log = 0;
    for (const v of net.order) {
      if (keep.includes(v)) continue;
      const touching = [], rest = [];
      for (const f of factors) (f.vars.includes(v) ? touching : rest).push(f);
      if (!touching.length) continue;
      const g = sumOut(product(touching, net.card), v);
      let top = 0;
      for (const x of g.values) if (x > top) top = x;
      if (top === 0) return null;   // what is known can't happen under this model
      if (top < 1e-150 || top > 1e150) { for (let i = 0; i < g.values.length; i++) g.values[i] /= top; log += Math.log(top); }
      rest.push(g);
      factors = rest;
    }
    const left = factors.length ? product(factors, net.card) : { vars: [], cards: [], values: Float64Array.of(1) };
    if (!left.values.some((v) => v > 0)) return null;
    // in the order asked for (each person kept is in their own table, so in what is left)
    const order = keep.map((v) => left.vars.indexOf(v));
    const cards = keep.map((v) => net.card[v]);
    let size = 1;
    for (const c of cards) size *= c;
    const values = new Float64Array(size);
    const idx = new Int32Array(keep.length);
    const stride = left.vars.map((_, i) => { let s = 1; for (let j = i + 1; j < left.vars.length; j++) s *= left.cards[j]; return s; });
    for (let o = 0; o < size; o++) {
      let src = 0;
      for (let k = 0; k < keep.length; k++) src += idx[k] * stride[order[k]];
      values[o] = left.values[src];
      for (let k = keep.length - 1; k >= 0; k--) { idx[k]++; if (idx[k] < cards[k]) break; idx[k] = 0; }
    }
    return { values, log };
  }

  /* the network of tables for a pedigree: one for each person, of their genotype given their parents' (or the
     population's), times how well it fits what is known of them. ignore: ids whose phenotype and test are left out */
  function network(prep, m, ignore) {
    const x = MODES[m.mode].x;
    const list = prep.list;
    // a genotype for each person, but one for each group of identical twins
    const reps = list.filter((p) => p.rep === p.id);
    const index = new Map(reps.map((p, i) => [p.id, i]));
    for (const p of list) index.set(p.id, index.get(p.rep));
    const states = reps.map((p) => statesOf(p.sex, x));
    const card = states.map((s) => s.length);
    const fitOf = (p, i) => states[i].map((s) => {
      if (ignore && ignore.has(p.id)) return 1;
      const pen = penetrance(s, m);
      const phen = p.affected === true ? pen : p.affected === false ? 1 - pen : 1;
      return phen * fitsTest(p.test, s, m);
    });
    const twins = list.filter((p) => p.rep !== p.id).map((p) => {
      const i = index.get(p.id);
      return { vars: [i], cards: [card[i]], values: Float64Array.from(fitOf(p, i)) };
    });
    const factors = reps.map((p, i) => {
      const fit = fitOf(p, i);
      if (!p.father) return { vars: [i], cards: [card[i]], values: Float64Array.from(states[i], (s, k) => founderPrior(s, p.sex, x, m.q) * fit[k]) };
      const f = index.get(p.father), mo = index.get(p.mother);
      const values = new Float64Array(card[i] * card[f] * card[mo]);
      let o = 0;
      for (let a = 0; a < card[i]; a++)
        for (let b = 0; b < card[f]; b++)
          for (let c = 0; c < card[mo]; c++) values[o++] = transmit(states[i][a], p.sex, states[f][b], states[mo][c], x, m.mutation) * fit[a];
      return { vars: [i, f, mo], cards: [card[i], card[f], card[mo]], values };
    }).concat(twins);
    return { list, index, states, card, factors, order: eliminationOrder(factors, card), model: m };
  }

  function normalise(values) {
    let sum = 0;
    for (const v of values) sum += v;
    return sum > 0 ? Array.from(values, (v) => v / sum) : null;
  }

  /* what a distribution over someone's genotypes means for them */
  function summarise(states, probs, m) {
    const r = { variant: 0, one: 0, two: 0, male: null, affected: 0 };
    let male = 0;
    states.forEach((s, k) => {
      const p = probs[k];
      if (s.copies >= 1) r.variant += p;
      if (s.copies === 1) r.one += p;
      if (s.copies === 2) r.two += p;
      if (s.sex === 'M') male += p;
      r.affected += p * penetrance(s, m);
    });
    if (states.some((s) => s.sex === 'M') && states.some((s) => s.sex === 'F')) r.male = male;
    r.probs = probs;
    r.states = states.map((s) => ({ sex: s.sex, copies: s.copies }));
    return r;
  }

  /* when what is known can't happen under the model, the first person (parents before children) whose phenotype
     or test result makes it impossible */
  function firstImpossible(prep, m) {
    const order = [];
    const seen = new Set();
    const visit = (p) => {
      if (seen.has(p.id)) return;
      seen.add(p.id);
      for (const role of ['father', 'mother']) if (p[role]) visit(prep.byId.get(p[role]));
      order.push(p);
    };
    prep.list.forEach(visit);
    const ignore = new Set(order.map((p) => p.id));
    for (const p of order) {
      if (p.affected === null && !p.test) { ignore.delete(p.id); continue; }
      ignore.delete(p.id);
      const net = network(prep, m, ignore);
      if (!joint(net, [net.index.get(p.id)])) return p;
    }
    return null;
  }
  function impossible(prep, m) {
    const p = firstImpossible(prep, m);
    const what = p ? (p.affected === true ? 'affected' : p.affected === false ? 'unaffected' : 'tested as they were') : '';
    const message = p
      ? `${p.label} can't be ${what} under this model, given the rest of the family. ` +
        (p.affected === true ? 'Allow for new mutations, a lower penetrance or phenocopies, or try another mode of inheritance.'
          : p.affected === false ? 'Allow for a lower penetrance, or try another mode of inheritance.'
            : 'Check the test results, or try another mode of inheritance.')
      : 'What is known of this family can\'t happen under this model.';
    return { ok: false, impossible: true, who: p ? p.id : null, message };
  }

  /* ---------- what a page asks for ---------- */

  /* everyone's chances: { ok: true, people: { id: summary } } */
  function analyse(people, model) {
    const m = checkModel(model);
    const prep = prepare(people);
    const net = network(prep, m);
    const out = {};
    for (const p of prep.list) {
      const i = net.index.get(p.id);
      const j = joint(net, [i]);
      if (!j) return impossible(prep, m);
      out[p.id] = Object.assign(summarise(net.states[i], normalise(j.values), m), { added: p.added, sex: p.sex });
    }
    return { ok: true, people: out, model: m };
  }

  /* the chances for a child of a couple, not yet born: a son and a daughter under an X-linked mode, and any child */
  function childRisk(people, model, fatherId, motherId) {
    const m = checkModel(model);
    const x = MODES[m.mode].x;
    const base = prepare(people);
    const father = base.byId.get(String(fatherId)), mother = base.byId.get(String(motherId));
    if (!father || !mother) throw new RiskError('choose both parents');
    if (father.sex === 'F') throw new RiskError(`${father.label} is female, so can't be the father`, father.id);
    if (mother.sex === 'M') throw new RiskError(`${mother.label} is male, so can't be the mother`, mother.id);
    const one = (sex) => {
      const id = '\u0000child';
      const prep = prepare(people.concat([{ id, sex, father: father.id, mother: mother.id }]));
      const net = network(prep, m);
      const i = net.index.get(id);
      const j = joint(net, [i]);
      if (!j) return null;
      return summarise(net.states[i], normalise(j.values), m);
    };
    if (!x) {
      const any = one('U');
      return any ? { ok: true, any, son: any, daughter: any } : impossible(base, m);
    }
    const son = one('M'), daughter = one('F');
    if (!son || !daughter) return impossible(base, m);
    const any = { variant: (son.variant + daughter.variant) / 2, affected: (son.affected + daughter.affected) / 2 };
    return { ok: true, any, son, daughter };
  }

  /* how one person's chance comes about, as in a Bayesian risk table: the prior, from the rest of the family; the
     conditional, the chance of what is known of them and their descendants for each genotype; the joint; and the
     posterior. Genotypes that are impossible or less likely than one in a million both before and after are left out */
  function bayes(people, model, id) {
    const m = checkModel(model);
    const prep = prepare(people);
    const who = prep.byId.get(String(id));
    if (!who) throw new RiskError(`${id} is not in the pedigree`);
    const children = new Map();
    for (const p of prep.list) for (const role of ['father', 'mother']) if (p[role]) {
      if (!children.has(p[role])) children.set(p[role], []);
      children.get(p[role]).push(p.id);
    }
    const below = new Set(prep.list.filter((p) => p.rep === who.rep).map((p) => p.id));
    const queue = [...below];
    while (queue.length) for (const c of children.get(queue.shift()) || []) if (!below.has(c)) { below.add(c); queue.push(c); }
    const before = network(prep, m, below);
    const all = network(prep, m);
    const i = all.index.get(who.id);
    const a = joint(before, [before.index.get(who.id)]);
    const b = joint(all, [i]);
    if (!a || !b) return impossible(prep, m);
    const priorSum = a.values.reduce((s, v) => s + v, 0);
    const prior = Array.from(a.values, (v) => v / priorSum);
    const jointSum = b.values.reduce((s, v) => s + v, 0);
    const posterior = Array.from(b.values, (v) => v / jointSum);
    const conditional = Array.from(b.values, (v, k) => (a.values[k] > 0 ? (v / a.values[k]) * Math.exp(b.log - a.log) : 0));
    const rows = all.states[i].map((s, k) => ({ sex: s.sex, copies: s.copies, prior: prior[k], conditional: conditional[k], joint: prior[k] * conditional[k], posterior: posterior[k] }))
      .filter((r) => r.prior >= 1e-6 || r.posterior >= 1e-6);
    // the evidence the conditional is about: the person and their descendants who have a phenotype or test result
    const about = [...below].map((pid) => prep.byId.get(pid)).filter((p) => p.affected !== null || p.test);
    return { ok: true, rows, about: about.map((p) => p.id), descendants: below.size - 1 };
  }

  /* ---------- showing a chance ---------- */

  /* x as a fraction with a denominator no larger than maxDen, if it is one to within a millionth of itself (as a
     background allele frequency can put it out by less), or null */
  function fraction(x, maxDen) {
    maxDen = maxDen || 1000;
    if (!(x >= 0 && x <= 1)) return null;
    if (x === 0) return { n: 0, d: 1 };
    let h0 = 0, h1 = 1, k0 = 1, k1 = 0, v = x;
    for (let i = 0; i < 40; i++) {
      const a = Math.floor(v);
      const h2 = a * h1 + h0, k2 = a * k1 + k0;
      if (k2 > maxDen) break;
      h0 = h1; h1 = h2; k0 = k1; k1 = k2;
      if (Math.abs(x - h1 / k1) <= 1e-6 * x) return { n: h1, d: k1 };
      const r = v - a;
      if (r < 1e-15) break;
      v = 1 / r;
    }
    return null;
  }
  /* a chance in words: { text: '2/3' or '1 in 150' or 'about 1 in 26', pct: '67%' }. A chance that is a simple
     fraction is given as one: a numerator of 12 or less, or 1 in any number up to a million. It must be the fraction
     to within a millionth of itself, and to well within the gap between it and the fractions around it, so that a
     chance that only happens to be near one isn't shown as if it were exact. A chance that isn't a simple fraction is
     given as about 1 in so many, or, from 1 in 5 upwards, as a percentage alone (text is then the percentage, and pct
     empty) */
  function describe(x) {
    if (x == null || !isFinite(x)) return { text: '–', pct: '' };
    const pct = x * 100;
    const pctText = pct >= 99.95 && x < 1 ? 'over 99.9%' : pct >= 1 ? `${pct.toFixed(pct < 10 ? 1 : 0)}%` : pct >= 0.0001 ? `${pct.toPrecision(2)}%` : 'under 0.0001%';
    if (x === 0) return { text: '0', pct: '0%', n: 0, d: 1 };
    if (x === 1) return { text: '1', pct: '100%', n: 1, d: 1 };
    let fr = fraction(x, 1000);
    if (fr && !(fr.n <= 12 && fr.n * fr.d <= 2000)) fr = null;
    if (fr && fr.n === fr.d) fr = null;   // within a millionth of 1, but not 1
    if (!fr && x < 1) {
      const d = Math.round(1 / x);
      if (d > 1 && d <= 1e6 && Math.abs(x * d - 1) <= Math.min(1e-6, 1e-3 / d)) fr = { n: 1, d };
    }
    if (fr) return { text: fr.n === 1 ? `1 in ${fr.d.toLocaleString('en-GB')}` : `${fr.n}/${fr.d}`, pct: pctText, n: fr.n, d: fr.d };
    if (x < 1e-6) return { text: 'less than 1 in a million', pct: pctText };
    if (x >= 0.2) return { text: /^(over|under)/.test(pctText) ? pctText : `about ${pctText}`, pct: '' };
    const oneIn = 1 / x;
    const rounded = oneIn < 1000 ? Math.round(oneIn) : Number(oneIn.toPrecision(2));
    return { text: `about 1 in ${rounded.toLocaleString('en-GB')}`, pct: pctText };
  }

  /* an allele frequency from a carrier frequency (2pq) */
  function alleleFromCarrier(c) {
    if (!(c > 0 && c < 0.5)) return null;
    return (1 - Math.sqrt(1 - 2 * c)) / 2;
  }

  return { MODES, RiskError, analyse, childRisk, bayes, fraction, describe, alleleFromCarrier, penetrance, _prepare: prepare };
});
