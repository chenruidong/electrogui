"""The window-rate bars' significance tests (electro_gui/static/stats.js), pinned to scipy.

stats.js runs in the page's Web Worker; here it runs in node, or in macOS's JavaScriptCore shell,
on numbers built in Python, and its p-values are checked against scipy.stats.permutation_test.
The bracket drawing and the page's request/cache controller are checked in
tests/population_interactions.js.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

STATS_JS = Path(__file__).resolve().parents[1] / "electro_gui" / "static" / "stats.js"
JSC = Path("/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc")


def js_engine():
    node = shutil.which("node")
    return [node] if node else [str(JSC)] if JSC.is_file() else None


def run_stats(script, data):
    """Run ``script`` with ``St`` = stats.js's API and ``input`` = data; it ends by calling ``out(value)``."""
    program = ("const root = {};\n(function (self, module) {\n" + STATS_JS.read_text() + "\n})(root, undefined);\n"
               "const St = root.EGStats;\n"
               "const out = v => (typeof console !== 'undefined' ? console.log : print)(JSON.stringify(v));\n"
               f"const input = {json.dumps(data)};\n{script}\n")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "case.js"
        path.write_text(program)
        done = subprocess.run([*js_engine(), str(path)], capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise AssertionError(done.stderr or done.stdout)
    return json.loads(done.stdout.strip().splitlines()[-1])


def rates(rng, n, lam, window=0.5):
    """Count-window rates as the explorer has them: whole spike counts over a fixed window."""
    return (rng.poisson(lam, n) / window).tolist()


def scipy_p(a, b, n_resamples):
    """P(|mean A - mean B| under relabelling >= observed): the two-sided p of analysis._infer and stats.js.

    (scipy's own alternative="two-sided" doubles the smaller tail instead, which differs when the
    groups' sizes differ and the null distribution is skewed.)
    """
    from scipy import stats
    res = stats.permutation_test((np.asarray(a), np.asarray(b)), lambda x, y: abs(np.mean(x) - np.mean(y)),
                                 permutation_type="independent", alternative="greater", n_resamples=n_resamples,
                                 random_state=np.random.default_rng(0))
    return float(res.pvalue)


@unittest.skipUnless(js_engine(), "no JavaScript engine (node or jsc)")
class PermutationTestTests(unittest.TestCase):
    def test_small_groups_list_every_split_and_match_scipy_exactly(self):
        rng = np.random.default_rng(3)
        for na, nb, lam_b in ((4, 5, 6), (6, 6, 3), (3, 9, 5), (7, 4, 2)):
            a, b = rates(rng, na, 2), rates(rng, nb, lam_b)
            got = run_stats("out(St.permutationTest(input[0], input[1]));", [a, b])
            self.assertTrue(got["exact"], (na, nb))
            self.assertAlmostEqual(got["p"], scipy_p(a, b, np.inf), places=12)
            self.assertAlmostEqual(got["diff"], np.mean(a) - np.mean(b), places=12)

    def test_random_splits_estimate_the_exact_p(self):
        # 9 vs 9 has 48620 splits, more than the 10000 budget: random splits, early stop off.
        rng = np.random.default_rng(8)
        a, b = rates(rng, 9, 2), rates(rng, 9, 3.2)
        exact = scipy_p(a, b, np.inf)
        got = run_stats("out(St.permutationTest(input[0], input[1], {permutations: 40000, stopAt: 1e12}));", [a, b])
        self.assertFalse(got["exact"])
        self.assertLess(abs(got["p"] - exact), 4 * np.sqrt(exact * (1 - exact) / 40000) + 1e-4, (got["p"], exact))

    def test_large_groups_match_scipy_and_are_reproducible(self):
        rng = np.random.default_rng(11)
        a, b = rates(rng, 220, 3), rates(rng, 260, 3.5)
        ref = scipy_p(a, b, 99999)
        got = run_stats("out([St.permutationTest(input[0], input[1], {permutations: 50000, stopAt: 1e12}),"
                        " St.permutationTest(input[0], input[1], {permutations: 50000, stopAt: 1e12})]);", [a, b])
        self.assertEqual(got[0], got[1])   # seeded from the values: the same view, the same p
        self.assertLess(abs(got[0]["p"] - ref), 4 * np.sqrt(ref * (1 - ref) / 50000) + 4e-5, (got[0]["p"], ref))

    def test_identical_groups_stop_early_with_p_one(self):
        got = run_stats("out(St.permutationTest(input, input.slice()));", [2.0] * 30 + [4.0] * 30)
        self.assertEqual(got["diff"], 0)
        self.assertEqual(got["p"], 1)
        self.assertEqual(got["permutations"], 50)   # Besag-Clifford: every split reaches |0|

    def test_null_false_positive_rate(self):
        rng = np.random.default_rng(21)
        pairs = [[rates(rng, 30, 3), rates(rng, 40, 3)] for _ in range(300)]
        ps = run_stats("out(input.map(([a, b]) => St.permutationTest(a, b, {permutations: 2000}).p));", pairs)
        self.assertLess(abs(np.mean(np.asarray(ps) < 0.05) - 0.05), 0.04)


@unittest.skipUnless(js_engine(), "no JavaScript engine (node or jsc)")
class RateTestsTests(unittest.TestCase):
    def test_pairs_are_within_panels_unless_no_panel_has_two_bars(self):
        g = lambda key, panel, n=5: {"key": key, "panel": panel, "values": [1.0] * n}
        got = run_stats("out(input.map(gs => St.comparisons(gs)));", [
            [g("a", "x"), g("b", "x"), g("c", "y"), g("d", "y"), g("e", "y")],
            [g("a", "x"), g("b", "y"), g("c", "z")],
            [g("a", "x"), g("b", "x", 1), g("c", "x")],
            [g(str(i), "x") for i in range(11)],
        ])
        self.assertEqual(got[0]["pairs"], [[0, 1], [2, 3], [2, 4], [3, 4]])
        self.assertEqual(got[0]["families"], [[0, 1], [2, 3, 4]])
        self.assertEqual(got[0]["scope"], "panel")
        self.assertEqual(got[1]["pairs"], [[0, 1], [0, 2], [1, 2]])
        self.assertEqual(got[1]["scope"], "figure")
        self.assertEqual(got[2]["pairs"], [[0, 2]])   # a bar of one event is not compared
        self.assertEqual(got[3]["pairs"], [])
        self.assertIn("55 pairs", got[3]["skipped"])

    def test_holm_and_stars(self):
        got = run_stats("out([St.holm(input), input.map(St.stars), St.holm([0.01, 0.04, 0.03])]);", [0.0004, 0.004, 0.04, 0.2])
        holm = [0.0016, 0.012, 0.08, 0.2]
        for x, y in zip(got[0], holm):
            self.assertAlmostEqual(x, y, places=12)
        self.assertEqual(got[1], ["***", "**", "*", ""])
        for x, y in zip(got[2], [0.03, 0.06, 0.06]):   # monotone: a later rank never drops below an earlier one
            self.assertAlmostEqual(x, y, places=12)

    def test_rate_tests_correct_across_the_figure(self):
        rng = np.random.default_rng(5)
        groups = [{"key": "PP", "panel": 0, "values": rates(rng, 120, 2)}, {"key": "PM", "panel": 0, "values": rates(rng, 110, 2.1)},
                  {"key": "MM", "panel": 0, "values": rates(rng, 130, 4)}]
        got = run_stats("out([St.rateTests(input), St.rateTests(input), St.contentKey(input),"
                        " St.contentKey(input.map((g, i) => i ? g : {...g, values: g.values.map((v, j) => j ? v : v + 2)}))]);", groups)
        res, again, key, changed = got
        self.assertEqual(res, again)
        self.assertNotEqual(key, changed)
        self.assertEqual(res["family"], 3)
        self.assertEqual(res["max_permutations"], 10000)
        self.assertEqual([(p["a"], p["b"]) for p in res["pairs"]], [("PP", "PM"), ("PP", "MM"), ("PM", "MM")])
        ps = [p["p"] for p in res["pairs"]]
        order = np.argsort(ps, kind="stable")
        expected = np.maximum.accumulate([min(1, (3 - r) * ps[i]) for r, i in enumerate(order)])
        for r, i in enumerate(order):
            self.assertAlmostEqual(res["pairs"][i]["p_holm"], expected[r], places=12)
        stars = {(p["a"], p["b"]): p["stars"] for p in res["pairs"]}
        self.assertEqual(stars[("PP", "PM")], "")
        self.assertEqual(stars[("PP", "MM")], "***")
        self.assertEqual(stars[("PM", "MM")], "***")

    def test_three_stars_are_reachable_after_correction(self):
        # Ten bars (45 pairs): the budget grows so that no split reaching the observed difference
        # still gives Holm p < 0.001 for the most extreme pair.
        groups = [{"key": str(i), "panel": 0, "values": [float(i * 40 + (j % 3)) for j in range(25)]} for i in range(10)]
        res = run_stats("out(St.rateTests(input));", groups)
        self.assertEqual(res["family"], 45)
        self.assertEqual(res["max_permutations"], 54000)
        self.assertTrue(all(p["stars"] == "***" for p in res["pairs"]))


if __name__ == "__main__":
    unittest.main()
