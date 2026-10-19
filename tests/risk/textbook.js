/* PedRisk on the examples of genetic counselling textbooks, whose answers are known */
'use strict';
const R = require(process.argv[2] || '../../assets/js/risk-engine.js');
let failures = 0;
function expect(what, got, want, tol) {
  const ok = Math.abs(got - want) <= (tol || 1e-9);
  if (!ok) failures++;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${what}: ${got} (${R.describe(got).text}), expected ${want}`);
}

// A couple who are both unaffected have a child with cystic fibrosis. Their unaffected daughter's chance of being a
// carrier is 2/3, and with a partner from the population, whose chance is 1/25, their child's is 2/3 x 1/25 x 1/4 =
// 1/150. (An allele frequency of 1/49 gives an unaffected person from the population exactly 1/25.)
const cf = [
  { id: 'I-1', sex: 'M', affected: false }, { id: 'I-2', sex: 'F', affected: false },
  { id: 'II-1', sex: 'M', father: 'I-1', mother: 'I-2', affected: true },
  { id: 'II-2', sex: 'F', father: 'I-1', mother: 'I-2', affected: false },
  { id: 'II-3', sex: 'M', affected: false }
];
const ar = { mode: 'AR', q: 1 / 49 };
let a = R.analyse(cf, ar);
expect('AR: the parents of an affected child are carriers', a.people['I-1'].one, 1);
expect("AR: an affected child's unaffected sister is a carrier", a.people['II-2'].one, 2 / 3);
expect('AR: an unaffected partner from the population is a carrier', a.people['II-3'].one, 1 / 25);
expect("AR: the couple's child is affected", R.childRisk(cf, ar, 'II-3', 'II-2').any.affected, 1 / 150);

// The same, by Bayes: the sister's prior, from her parents, is 1/2 carrier, 1/4 not, 1/4 two copies; being
// unaffected, the conditional is 1, 1, 0; so the posterior is 2/3
let b = R.bayes(cf, ar, 'II-2');
const row = (t, copies) => t.rows.find((r) => r.copies === copies);
expect('AR Bayes: the prior of a carrier', row(b, 1).prior, 1 / 2);
expect('AR Bayes: the conditional of two copies (affected, but she is not)', row(b, 2) ? row(b, 2).conditional : 0, 0);
expect('AR Bayes: the posterior of a carrier', row(b, 1).posterior, 2 / 3);

// Duchenne muscular dystrophy (X-linked recessive): a woman's brother is affected, so her unaffected mother is a
// carrier and she has a prior of 1/2. She has two unaffected sons: the conditional is 1/4 if she is a carrier and 1
// if not, so her posterior is (1/8) / (1/8 + 1/2) = 1/5
const dmd = [
  { id: 'I-1', sex: 'M', affected: false }, { id: 'I-2', sex: 'F', affected: false },
  { id: 'II-1', sex: 'M', father: 'I-1', mother: 'I-2', affected: true },
  { id: 'II-2', sex: 'F', father: 'I-1', mother: 'I-2', affected: false },
  { id: 'II-3', sex: 'M', affected: false },
  { id: 'III-1', sex: 'M', father: 'II-3', mother: 'II-2', affected: false },
  { id: 'III-2', sex: 'M', father: 'II-3', mother: 'II-2', affected: false }
];
const xlr = { mode: 'XLR', q: 1e-6 };
a = R.analyse(dmd, xlr);
expect('XLR: the mother of an affected son, with no new mutations, is a carrier', a.people['I-2'].one, 1, 1e-5);
expect('XLR: his sister, with two unaffected sons, is a carrier', a.people['II-2'].one, 1 / 5, 1e-5);
b = R.bayes(dmd, xlr, 'II-2');
expect('XLR Bayes: her prior', row(b, 1).prior, 1 / 2, 1e-5);
expect('XLR Bayes: her conditional, as a carrier', row(b, 1).conditional, 1 / 4, 1e-5);
expect('XLR Bayes: her conditional, not a carrier', row(b, 0).conditional, 1, 1e-5);
expect('XLR Bayes: her joint, as a carrier', row(b, 1).joint, 1 / 8, 1e-5);
expect('XLR Bayes: her posterior', row(b, 1).posterior, 1 / 5, 1e-5);
const kid = R.childRisk(dmd, xlr, 'II-3', 'II-2');
expect('XLR: her next son is affected', kid.son.affected, 1 / 10, 1e-5);
expect('XLR: her next daughter is a carrier', kid.daughter.one, 1 / 10, 1e-5);

// An isolated case of a lethal X-linked recessive condition: with new mutations at rate mu, and carrier women in
// the population at 4 mu, as at equilibrium (an allele frequency of 2 mu), his mother is a carrier with chance 2/3
// (Haldane)
const mu = 1e-5;
const iso = [
  { id: 'I-1', sex: 'M', affected: false }, { id: 'I-2', sex: 'F', affected: false },
  { id: 'II-1', sex: 'M', father: 'I-1', mother: 'I-2', affected: true }
];
a = R.analyse(iso, { mode: 'XLR', q: 2 * mu, mutation: mu });
expect("XLR with new mutations: an isolated case's mother is a carrier", a.people['I-2'].one, 2 / 3, 1e-3);

// Huntington's disease (autosomal dominant) with reduced penetrance: the unaffected child of an affected parent has
// the variant with chance (1/2)(1 - f) / ((1/2)(1 - f) + 1/2) = 1/6 for a penetrance f of 80%
const ad = [
  { id: 'I-1', sex: 'M', affected: true }, { id: 'I-2', sex: 'F', affected: false },
  { id: 'II-1', sex: 'F', father: 'I-1', mother: 'I-2', affected: false }
];
a = R.analyse(ad, { mode: 'AD', q: 1e-7, penetrance: 0.8 });
expect('AD, penetrance 80%: an unaffected child of an affected parent has the variant', a.people['II-1'].variant, 1 / 6, 1e-6);
expect('AD, penetrance 80%: her child will be affected', R.childRisk(ad.concat([{ id: 'II-2', sex: 'M', affected: false }]), { mode: 'AD', q: 1e-7, penetrance: 0.8 }, 'II-2', 'II-1').any.affected, (1 / 6) * 0.5 * 0.8, 1e-6);
// with complete penetrance, an affected child of two unaffected parents can't happen without a new mutation
const denovo = [
  { id: 'I-1', sex: 'M', affected: false }, { id: 'I-2', sex: 'F', affected: false },
  { id: 'II-1', sex: 'F', father: 'I-1', mother: 'I-2', affected: true }
];
const imp = R.analyse(denovo, { mode: 'AD', q: 1e-4 });
console.log(`${!imp.ok && imp.who === 'II-1' ? 'ok  ' : 'FAIL'}  AD: an affected child of two unaffected parents is impossible without new mutations: ${imp.message}`);
if (imp.ok || imp.who !== 'II-1') failures++;
a = R.analyse(denovo, { mode: 'AD', q: 1e-4, mutation: 1e-5 });
expect('AD with new mutations: her unaffected parents have the variant', a.people['I-1'].variant, 0, 1e-12);

// First cousins whose shared grandfather is a carrier of a rare recessive allele: each cousin is a carrier with
// chance 1/4 (1/2 for each generation), and their child is affected with chance 1/4 x 1/4 x 1/4 = 1/64
const cousins = [
  { id: 'I-1', sex: 'M', test: 'carrier' }, { id: 'I-2', sex: 'F' },
  { id: 'II-1', sex: 'M', father: 'I-1', mother: 'I-2' }, { id: 'II-2', sex: 'F' },
  { id: 'II-3', sex: 'F', father: 'I-1', mother: 'I-2' }, { id: 'II-4', sex: 'M' },
  { id: 'III-1', sex: 'M', father: 'II-1', mother: 'II-2' },
  { id: 'III-2', sex: 'F', father: 'II-4', mother: 'II-3' }
];
const rare = { mode: 'AR', q: 1e-9 };
a = R.analyse(cousins, rare);
expect('AR: a cousin is a carrier', a.people['III-1'].one, 1 / 4, 1e-6);
expect("AR: first cousins' child is affected", R.childRisk(cousins, rare, 'III-1', 'III-2').any.affected, 1 / 64, 1e-6);

// a person tested and found not to carry the variant can't pass it on
const tested = cf.concat([{ id: 'II-4', sex: 'F', test: 'none' }]);
expect('a tested non-carrier has no chance of the variant', R.analyse(tested, ar).people['II-4'].variant, 0);

// identical twins have one genotype: the unaffected identical twin of someone with a dominant condition (full
// penetrance) can't be; a non-identical twin is a sibling, with a chance of 1/2
const twins = [
  { id: 'I-1', sex: 'M', affected: true }, { id: 'I-2', sex: 'F', affected: false },
  { id: 'II-1', sex: 'F', father: 'I-1', mother: 'I-2', affected: true },
  { id: 'II-2', sex: 'F', father: 'I-1', mother: 'I-2', twin: 'II-1' },
  { id: 'II-3', sex: 'M', father: 'I-1', mother: 'I-2' }
];
a = R.analyse(twins, { mode: 'AD', q: 1e-6 });
expect("AD: an affected woman's identical twin has the variant", a.people['II-2'].variant, 1, 1e-6);
expect('AD: ...and her brother has it with chance 1/2', a.people['II-3'].variant, 1 / 2, 1e-6);
const unaffectedTwin = twins.map((p) => (p.id === 'II-2' ? Object.assign({}, p, { affected: false }) : p));
const imp2 = R.analyse(unaffectedTwin, { mode: 'AD', q: 1e-6 });
console.log(`${!imp2.ok && imp2.who === 'II-2' ? 'ok  ' : 'FAIL'}  AD: an unaffected identical twin of an affected woman is impossible with full penetrance: ${imp2.message}`);
if (imp2.ok || imp2.who !== 'II-2') failures++;
a = R.analyse(unaffectedTwin, { mode: 'AD', q: 1e-6, penetrance: 0.8 });
expect('AD, penetrance 80%: ...but possible with less', a.people['II-2'].variant, 1, 1e-6);
let threw = '';
try { R.analyse(twins.map((p) => (p.id === 'II-2' ? Object.assign({}, p, { sex: 'M' }) : p)), { mode: 'AD', q: 1e-6 }); } catch (e) { threw = e.message; }
console.log(`${/identical twins, but not of the same sex/.test(threw) ? 'ok  ' : 'FAIL'}  identical twins of different sexes are refused: ${threw}`);
if (!/identical twins, but not of the same sex/.test(threw)) failures++;

// describing chances
const d = (x) => R.describe(x).text;
const say = (x, want) => { const ok = d(x) === want; if (!ok) failures++; console.log(`${ok ? 'ok  ' : 'FAIL'}  describe(${x}) = ${d(x)}, expected ${want}`); };
say(2 / 3, '2/3'); say(1 / 150, '1 in 150'); say(98 / 2499, '2/51'); say(0.0384, 'about 1 in 26'); say(0.2500000009999999, '1 in 4'); say(1 / 2500, '1 in 2,500'); say(0.9999999, 'over 99.9%'); say(0.6612, 'about 66%'); say(1e-9, 'less than 1 in a million'); say(0, '0');

console.log(failures ? `${failures} failed` : 'all passed');
process.exit(failures ? 1 : 0);
