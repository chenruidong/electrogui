# ElectroGUI suggestions: decision and review checklist

Evaluated 2026-10-20 Boston time against ElectroGUI `f15a1a5` and its installed
analysis_imitation dependency `90498a7`. ElectroGUI moved to its own repository
on October 9; the expected analysis_imitation checkout is its dependency.
This review branch is for user testing before a merge. No production checkout,
service, Tailscale setting, authentication setting or runtime data is changed.

## Decisions before implementation

1. **Implement population-to-raster navigation and explicit roster stepping.**
   Heatmap and loading hit regions already share the same active-unit index and
   displayed order. Use that mapping to open a raster without resetting shared
   selection settings. The picker, arrows and keyboard must use one list. Keep
   quality/area filters active; direct clicks may select a filtered unit, with a
   visible explanation, rather than silently changing those filters. Roster
   stepping uses the most recently displayed population order, with safe
   roster-ID fallback when the fit is missing/stale and skips missing units.
2. **Defer classic retirement and the inference port.** `server.py` imports
   exports, annotations and preview; its job worker imports analysis/population.
   `explorer.py`, `tdr.py`, findings and configuration handling still depend on
   conditions. `/classic/` and `/api/jobs` have current callers and tests.
   `analysis._infer` averages events within trial, shares sign flips across a
   block for paired tests, and permutes disjoint block means for block tests.
   It has exact thresholds (16 sign-flip blocks / 50,000 block allocations),
   seeded Monte Carlo, corrected Monte Carlo p-values and explicit invalid
   designs. Window-rate bars alone do not establish exchangeability. The
   columnar explorer drops constant columns, so block_id is not guaranteed to
   be present even though trial IDs and count rates exist. Annotation layers,
   source-bound membership/statistics/SVG exports and queued jobs are not
   replaced by the v0.2 display. Loading fingerprints a session and uses the
   same bounded queue/store lock; replacing polling with synchronous loading
   has no demonstrated responsiveness benefit. Keep every module, route,
   inference behavior and executor until a dedicated parity migration.
3. **Implement explicit training subsets and A-minus-B heatmaps.** The existing
   fit uses *all* group means to choose constant units, center/scale, estimate
   the basis and order/sign its components. Its cached affine operator supports
   exact projection, but selecting groups only after fitting would leak data.
   Add training-group selection and trial-ID subsets (API), plus exploratory
   odd/even trial-ID splitting. Fit every model and normalization step on the
   training subset. In split mode display only the complementary trials, and
   report actual training/display events, trials, active/dropped units and
   trial overlap. A projected condition with shared trials is not a held-out
   trial test. TDR factor design, denoising and peak selection use training
   events only and must still pass existing level/rank/axis checks. Reject
   empty/unsupported splits instead of silently fitting all data. Odd/even
   splits are exploratory and may remain dependent under autocorrelation.
   Pairwise differences reuse raw means from one response (identical unit and
   time axes), subtract A minus B before display scaling, use shared per-unit
   normalization and a symmetric diverging color range, and carry no p-value.

## Validation and user test checklist

Results and exact launch instructions are recorded below after implementation.
- Open a population heatmap and loading bar; double-click each and verify the
  correct raster opens with alignment, filters, grouping and window intact.
- Toggle roster stepping in the unit picker; compare picker order, arrows and
  left/right keys with the population order. Check filtered/absent units.
- Fit selected groups, then use an odd/even split. Verify labels and counts;
  try a TDR split lacking factor variation and expect an explicit error.
- With 2–4 visible groups choose A and a subtracting B; verify sign and symmetric
  scale, reverse A/B, and return to an ordinary heatmap.
- Exercise classic inference, annotations, exports and queued loading unchanged.
