/* electro_gui explorer statistics: which window-rate bars differ, no DOM.
 *
 * Loaded by the page as window.EGStats, by node (tests) via require(), and as
 * a Web Worker (new Worker('/stats.js')), where it answers
 * {id, groups} with {id, result} so the test never runs on the page's thread.
 *
 * The test, for each pair of bars (rateTests):
 * - samples are the bar's own weighting units (core.js windowRates `values`:
 *   one count-window rate per event, or per trial mean), so n is the number
 *   printed on the bar.  Like the SEM bars, the units are treated as
 *   independent; several events of one trial, or groups sharing trials,
 *   are not modelled.
 * - two-sided permutation test of the difference of means: the pooled values
 *   are split at random into groups of the two sizes, and p is the share of
 *   splits whose |mean A - mean B| is at least the observed one
 *   (|null| >= |observed| - 1e-12, as electro_gui.analysis._infer).  When
 *   every split can be listed within the budget, they are (exact, p = b / C);
 *   otherwise random splits: p = (b + 1) / (N + 1), stopping early once 50
 *   splits reach the observed difference (Besag & Clifford 1991, p = 50 / l).
 *   N = max(10000, 1200 m) for m pairs, so p < 0.001 / m, and *** after
 *   correction, is reachable.  The random splits are seeded from the pair's
 *   values, so the same view always gives the same stars.
 * - pairs: every pair of bars within a panel; when no panel has two bars,
 *   every pair across panels.  A bar needs n >= 2.  More than MAX_PAIRS
 *   pairs are not tested (the brackets could not be read).
 * - Holm-Bonferroni across all the figure's pairs; stars at adjusted
 *   p < 0.05 (*), 0.01 (**), 0.001 (***).
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EGStats = api;
  if (typeof importScripts === 'function' && typeof postMessage === 'function' && typeof module === 'undefined') {
    root.onmessage = function (e) {
      const msg = e.data || {};
      let reply;
      try { reply = {id: msg.id, result: api.rateTests(msg.groups || [])}; } catch (err) { reply = {id: msg.id, error: String((err && err.message) || err)}; }
      postMessage(reply);
    };
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const MIN_N = 2;
  const MAX_PAIRS = 45;          // ten bars in one panel
  const STOP_AT = 50;            // Besag-Clifford: exceedances that end a clearly non-significant pair
  const LEVELS = [[0.001, '***'], [0.01, '**'], [0.05, '*']];

  /**
   * Pairs to test, as [i, j] indices into groups ({panel, values}) in bar order, and the
   * families they come from (the bars compared with each other: a panel's, or the figure's).
   */
  function comparisons(groups) {
    const ok = groups.map(g => g.values.length >= MIN_N);
    const byPanel = new Map();
    groups.forEach((g, i) => {
      if (!ok[i]) return;
      const p = String(g.panel);
      if (!byPanel.has(p)) byPanel.set(p, []);
      byPanel.get(p).push(i);
    });
    const allPairs = list => {
      const out = [];
      for (let a = 0; a < list.length; a++) for (let b = a + 1; b < list.length; b++) out.push([list[a], list[b]]);
      return out;
    };
    let families = [...byPanel.values()].filter(list => list.length > 1), scope = 'panel';
    if (!families.length) { families = [groups.map((g, i) => i).filter(i => ok[i])].filter(list => list.length > 1); scope = 'figure'; }
    let pairs = [];
    for (const list of families) pairs = pairs.concat(allPairs(list));
    if (pairs.length > MAX_PAIRS) return {pairs: [], families: [], scope, skipped: `${pairs.length} pairs (more than ${MAX_PAIRS})`};
    return {pairs, families, scope, skipped: null};
  }

  /**
   * 32-bit MurmurHash3-style hash of numbers (their float64 bits) and strings.  Every word is
   * mixed in full: rates are often small whole numbers over a fixed window, whose float64 low
   * word is 0 and whose high word varies only in its top bits.
   */
  function hashParts(parts, seed) {
    let h = (seed === undefined ? 0x9747b28c : seed) | 0, len = 0;
    const mix = k => {
      k = Math.imul(k, 0xcc9e2d51); k = (k << 15) | (k >>> 17); k = Math.imul(k, 0x1b873593);
      h ^= k; h = (h << 13) | (h >>> 19); h = (Math.imul(h, 5) + 0xe6546b64) | 0; len++;
    };
    const buf = new Float64Array(1), words = new Uint32Array(buf.buffer);
    for (const part of parts) {
      if (typeof part === 'string') { for (let i = 0; i < part.length; i++) mix(part.charCodeAt(i)); mix(0x1f1f1f1f); continue; }
      for (let i = 0; i < part.length; i++) { buf[0] = part[i]; mix(words[0]); mix(words[1]); }
      mix(0x1e1e1e1e);
    }
    h ^= len; h ^= h >>> 16; h = Math.imul(h, 0x85ebca6b); h ^= h >>> 13; h = Math.imul(h, 0xc2b2ae35); h ^= h >>> 16;
    return h >>> 0;
  }
  /** What a result depends on: each bar's key, panel and values, in order (64 bits, two seeds). */
  function contentKey(groups) {
    const parts = [];
    for (const g of groups) parts.push(String(g.key), String(g.panel), g.values);
    const hex = h => h.toString(16).padStart(8, '0');
    return `${groups.map(g => g.values.length).join('.')}:${hex(hashParts(parts, 1))}${hex(hashParts(parts, 0x5bd1e995))}`;
  }

  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /** C(n, k), or Infinity once it passes limit. */
  function choose(n, k, limit) {
    k = Math.min(k, n - k);
    let c = 1;
    for (let i = 1; i <= k; i++) { c = c * (n - k + i) / i; if (c > limit) return Infinity; }
    return Math.round(c);
  }

  /**
   * Two-sided permutation test of mean(a) - mean(b).
   * @returns {{diff, p, exact, permutations, exceed}}
   */
  function permutationTest(a, b, opts) {
    const o = opts || {};
    const budget = o.permutations || 10000, stopAt = o.stopAt || STOP_AT;
    const na = a.length, nb = b.length, n = na + nb;
    const pool = new Float64Array(n);
    let sumA = 0, total = 0;
    for (let i = 0; i < na; i++) { pool[i] = a[i]; sumA += a[i]; }
    for (let i = 0; i < nb; i++) pool[na + i] = b[i];
    for (let i = 0; i < n; i++) total += pool[i];
    const diff = sumA / na - (total - sumA) / nb;
    if (!Number.isFinite(diff)) return {diff: null, p: 1, exact: false, permutations: 0, exceed: 0};   // never a star
    const bar = Math.abs(diff) - 1e-12;
    // Splits are drawn by choosing the smaller group's members; s is their sum.
    const smallIsA = na <= nb, k = smallIsA ? na : nb;
    const gap = s => Math.abs(smallIsA ? s / na - (total - s) / nb : (total - s) / na - s / nb);
    const splits = choose(n, k, budget);
    if (splits !== Infinity) {
      // Every split: indices c[0] < ... < c[k-1], in lexicographic order.
      const c = new Int32Array(k);
      for (let i = 0; i < k; i++) c[i] = i;
      let exceed = 0, count = 0;
      for (;;) {
        let s = 0;
        for (let i = 0; i < k; i++) s += pool[c[i]];
        count++;
        if (gap(s) >= bar) exceed++;
        let i = k - 1;
        while (i >= 0 && c[i] === n - k + i) i--;
        if (i < 0) break;
        c[i]++;
        for (let j = i + 1; j < k; j++) c[j] = c[j - 1] + 1;
      }
      return {diff, p: exceed / count, exact: true, permutations: count, exceed};
    }
    // Random splits: a partial Fisher-Yates shuffle puts a uniform random k-subset first.
    // xorshift32, inlined (the inner loop is the whole cost), seeded through mulberry32.
    let x = (Math.floor(mulberry32(o.seed === undefined ? hashParts([a, b]) : o.seed)() * 4294967296) | 1) >>> 0;
    const work = pool.slice(), unit = 1 / 4294967296;
    let exceed = 0;
    for (let l = 1; l <= budget; l++) {
      let s = 0;
      for (let i = 0; i < k; i++) {
        x ^= x << 13; x ^= x >>> 17; x ^= x << 5;
        const j = i + Math.floor((x >>> 0) * unit * (n - i));
        const t = work[j]; work[j] = work[i]; work[i] = t;
        s += t;
      }
      if (gap(s) >= bar && ++exceed >= stopAt) return {diff, p: exceed / l, exact: false, permutations: l, exceed};
    }
    return {diff, p: (exceed + 1) / (budget + 1), exact: false, permutations: budget, exceed};
  }

  /** Holm-Bonferroni adjusted p-values, in the input order. */
  function holm(ps) {
    const m = ps.length, order = ps.map((p, i) => i).sort((x, y) => ps[x] - ps[y] || x - y), out = new Array(m);
    let run = 0;
    order.forEach((i, r) => { run = Math.max(run, Math.min(1, (m - r) * ps[i])); out[i] = run; });
    return out;
  }
  function stars(p) {
    for (const [cut, s] of LEVELS) if (p < cut) return s;
    return '';
  }

  /**
   * Every comparison of the bars: groups are {key, panel, values} in bar order.
   * pairs[k] = {i, j, a, b (keys), n_a, n_b, diff (mean a - mean b), p, p_holm, stars, exact, permutations}.
   */
  function rateTests(groups) {
    const plan = comparisons(groups), m = plan.pairs.length;
    const budget = Math.max(10000, 1200 * m);
    const pairs = plan.pairs.map(([i, j]) => {
      const a = groups[i].values, b = groups[j].values;
      const t = permutationTest(a, b, {permutations: budget});
      return {i, j, a: groups[i].key, b: groups[j].key, n_a: a.length, n_b: b.length, diff: t.diff, p: t.p,
        exact: t.exact, permutations: t.permutations};
    });
    const adj = holm(pairs.map(p => p.p));
    pairs.forEach((p, k) => { p.p_holm = adj[k]; p.stars = stars(adj[k]); });
    return {method: 'two-sided permutation test of the difference of means', correction: 'Holm across the figure\'s pairs',
      scope: plan.scope, skipped: plan.skipped, family: m, max_permutations: budget, levels: LEVELS.map(x => x[0]), pairs};
  }

  return {MIN_N, MAX_PAIRS, comparisons, contentKey, hashParts, permutationTest, holm, stars, rateTests};
});
