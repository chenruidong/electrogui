# electro_gui 0.2

A local application for exploring an assembled session NWB, one unit at a
time as a raster over a PSTH (**Rasters**) or many neurons at once as a
heatmap, component time courses and trajectories (**Population**).  The
**Rasters | Population** switch beside the logo (in the ⋯ menu on a phone)
flips between them; both share the alignment, filters, groups, markers,
window and templates, so each shows the other's view of the same selection.
Display computations run in the browser, so display knobs redraw immediately.
It works on a desktop, a tablet or a phone.  The v0.1 workspaces
(block-permutation tests, provenance-bound job exports, the original
population tab) remain at `/classic/`, documented under **Classic workspace**.
The application contains no frozen experimental fixture.

## Launch

From the repository, using its scientific Python environment:

```bash
/Users/rc/miniforge3/envs/imitation-phys/bin/python -m electro_gui
```

This opens `http://127.0.0.1:8765`. If that port is occupied, use `--port 0`
(or e.g. `--port 8777`) and open the URL printed by the launcher. Stop the
server with Ctrl-C.
There are two equivalent entry points:

```bash
python -m imitation_phys electro-gui --no-browser --port 0
# After installing this repository with pip install -e .:
electro-gui --version
electro-gui
```

By default, the catalog looks in `/Volumes/T7/engaging-results` followed by
`/Volumes/Transfer/engaging_results`. It discovers only exact
`<session>/analysis/nwb/<session>_session.nwb` files, ignoring sidecars and
misnamed scratch copies. To use other assembled sessions:

```bash
python -m electro_gui --data-root /path/to/session-products
python -m electro_gui --session-file /path/to/sub-Subject_ses-Date_session.nwb
```

Both flags can be repeated. Explicit files must have the exact assembled-session
filename and matching embedded session identity. No external behavioral data,
prepared bundles or scene files are substituted when a field is missing.

`--config-dir DIR` (repeatable, default `output/presentation`, relative to the current
directory; a missing directory is simply empty) names where the Views menu looks
for JSON config files; see **Config files** below.
The optional canonical trial-strategy classifier is resolved through the
repository's sibling `mworks/imitation` or `IMITATION_REPO` environment variable.
Only its code is used, with its fingerprint recorded. If it is unavailable,
strategy-dependent comparisons are unavailable; other fields remain usable.

### On a tablet or phone

```bash
/Users/rc/miniforge3/envs/imitation-phys/bin/python -m electro_gui --lan --port 8777
```

`--lan` listens on every interface (`--host` picks one) and prints a URL with a
random `?token=`; open it once on the tablet or phone (same Wi-Fi, or a VPN such
as Tailscale) and the device keeps a cookie for 30 days.  Requests without the
token are refused, and without `--lan`/`--host` the server stays on loopback as
before.  Anyone holding the URL can read the sessions it serves, so stop the
server when you are done.  `--token` fixes the token instead of drawing one.

## Explorer (the default page)

The page is a figure card — title (`unit · ch · area · quality`), a legend of
groups, the raster over the PSTH, and window-rate bars — beside a control panel
with four sections.  On narrow screens the controls move into a bottom sheet
with Filter / Group / Markers / Display tabs.

- **Unit and alignment.**  `‹ ›` (or ← / →) step through units; the unit picker
  searches by unit ID, peak channel or area and filters by quality (SUA and MUA
  by default) and area.  Units are always labelled with both unit ID and peak
  channel, since the channel survives a re-sort.  The alignment picker lists
  every recorded event with its candidate count, common ones first;
  `object outcome (any)` is the four-outcome union.  `object_spawn` is
  deliberately not offered (`HIDDEN_EVENTS` in `data.py`, also absent from
  markers and the events API): it is the task creating an object, and a trial
  the animal never initiates times out with every object spawned and none
  shown (`sub-Ravel_ses-2026_09_15` trial 314), so a spawn-aligned row can be an
  object that never appeared and has no action.  Use `object_visible_onset`.
  For the same reason every event row tied to a spawned object that was never
  shown and never resolved (no `object_visible_onset`, no outcome) is left out
  of the session — its spawn, `gaze_on_object_*` and `saccade_target` rows — and
  opening the session says how many were hidden.  Gaze on the agent or the
  starting point stays.  Such objects occur only in trials the animal never
  initiated (all `episode_timeout`; 4 objects in 09_15, 20 in 09_02, 52 in 09_01,
  192 in 09_04, none in 08_26).  Trial-level fields still count them, so a trial
  with an unseen object is never classified from the shown ones alone.
  A trial the animal never initiated (the trials table's `initiated` is False: a
  timeout on the start block such as 09_15 trial 314, or a session's last trial)
  has no world and is not complete — the rule of the pipeline's
  `TrialsTable.complete()` — so none of its rows is a candidate for any
  alignment, raster or PSTH, whatever the colouring.  Its scheduled block stays
  readable as `trial.block_type`.  Counts: 2 in 09_15, 6 in 09_02, 14 in 09_01,
  49 in 09_04, none in 08_26.  Because it is not eligible, a neighbour whose
  padded window reaches into it leaves the stable run (09_15 trial 315 at a
  −1.5 s trial-display-start window).
- **Filter.**  World, role and action are one-tap chips with live counts (counts
  honour every other filter and the eligibility rule).  *Filter on any field*
  opens a searchable list — Common, History, Task & trial, Timing (s from
  event), Object details, Trial details — and a value editor: category chips
  with counts (missing is its own chip), or a numeric range over a histogram.
  A filter on a field the current alignment lacks is kept, shown dashed, and
  ignored.
- **Group & sort.**  *Colour*, *Line style* and *Panels* each take any field;
  their product defines the groups.  Numbers with at most 12 integer values
  group by value, other numbers by quantile bins (2–5).  World, strategy, role,
  action and outcome use fixed colours (PP green, PM violet, MM red; prey green,
  predator red), and a missing previous/next object reads *first object* /
  *no next object*.  Click a legend entry to hide a group, double-click to show
  only it, right-click (long-press on touch) to set its colour and dash.  Rows
  can be sorted by session order, spikes in the count window, any marker's
  latency or any field; *Keep groups together* stacks one block per group.
- **Markers.**  A marker is a recorded event matched to each row in the same
  object or the same trial, choosing the nearest, first-after, last-before or
  every occurrence; optionally *shade until* a second event draws a per-row
  band.  Rows show a dot at the event; the PSTH shows the median across shown
  rows as a dashed line plus a small triangle per group.  One-tap presets add
  object visible, joystick onset, trial initiation, goal release, reward and
  outcome.  Reference lines sit at fixed times.  Markers never change which
  events are counted.  Joystick markers use the recorded joystick events,
  which are sparse in the Sep 15 session and are not detected movement bouts.
- **Display.**  Window (−10 to 10 s), count window (sliders, number boxes, or
  drag across the PSTH with a mouse), bin width 5–200 ms, Gaussian σ 0–100 ms,
  error band (SEM, 95% CI = 1.96 SEM, none), averaging over events or trials,
  eligibility (*stable for unit* = v0.1's verified stable, or *all complete*),
  raster ticks as lines or dots, raster height, a locked y-maximum for
  comparing units, and the window-rate bars.

Hovering (or tapping) the PSTH shows every group's rate at that bin; hovering a
raster row shows its trial, time, fields, window count and marker times.

### Behavior timeline and pinned trials

Below the raster, **Behavior** draws the session's objects on session time, in
the style of imitation's `plot_trial_object_actions`: predator (−) row on top,
prey (+) below, one square per object at its outcome time — filled grey when
touched, empty when passed, a red × when incorrect, a wide bar for a bar
object — outlined in the object's displayed colour, with a faint line back to
its recorded `object_visible_onset`.  Same-role objects of one trial sit on
separate lanes by ordinal.  Trials are shaded by world (PP / PM / MM; faint
grey with ✕ after the number if incomplete; unshaded, like the inter-trial
interval, if the animal never initiated it and no object appeared), a dashed
line and label mark each world change (read across an uninitiated trial), and an
*events* strip shows every row of the current alignment: coloured by its raster
group when it is in the raster, faint grey when it is filtered, ineligible or
hidden.  Under it, *spikes* is the current unit's spike train on the same time
axis — every spike, with no eligibility rule, so it runs through inter-trial
intervals and uninitiated trials — with the mean rate over the visible window
beside the label.  Each pixel column is one tick shaded by its spike count
(relative to the 95th percentile of occupied columns): single spikes while they
are sparser than a pixel, a density strip when zoomed out.  The train is
fetched once per unit and kept for the last six units.  The strip below is the
whole session with the visible window boxed.

- **Zoom** with the *trials* slider (3 to all), pinch or ctrl-scroll on the
  timeline; **pan** by dragging, swiping sideways, `‹ ›`, or clicking/dragging
  the session strip.  A vertical wheel still scrolls the page.
- **Pin** by clicking a raster row, an object, an event tick or a trial.  The
  trial stays highlighted in every raster panel (the clicked row outlined, ▸ at
  the right) until another trial is clicked, and the timeline centres on it with
  the trial boxed, the object ringed and the event time dashed.  The pin chip
  says how many of the trial's rows are in the raster, or why none are (not
  stable for this unit, filtered, window leaves the stable run, hidden group).
  It follows alignment changes (it is a trial, not a row), survives reloads and
  links, and clears on `Esc`, its `×`, or a session change.  Clicking the chip
  re-centres the timeline.
- **Yoke to rasters** (the switch left of the slider) makes the rasters, PSTHs,
  window-rate bars, quick-filter counts and exports use only the timeline's
  trials — those whose centre is in view — widened to at least 20 (or every
  trial there is), as close to centred on the pinned trial as covering the whole
  view allows (on the view's centre when nothing is pinned).  An accent bar
  under the trial numbers and under the session strip marks those trials; the
  subtitle and support line name them, and exports record them as
  `yoked_trials` in their provenance.  Panning or zooming redraws the rasters
  only when that range changes.  Yoking is inactive while the timeline is
  collapsed; off, the rasters show every trial.

Displayed colours come from the image ID: `<shape>equalum_<i>_…` is colour *i*
of mworks/imitation's `generate_equal_luminosity_stimuli.py` (hue 0.99 *i* on
its 0–100 scale, the most saturated HSV colour at luma 0.5), which `core.js`
recomputes exactly; it matches the pixels of the stimulus PNGs.  An image ID
outside that convention is outlined grey.  The timeline reads only the
assembled NWB's joined outcome rows and visible onsets; an object without a
recorded outcome (an aborted trial) is not drawn.  Collapse the section with its
header when it is not needed.

## Population (the Population switch)

The same page, with a **Neurons** section added (first in the sidebar; a
Neurons tab on phones) and a model block at the top of *Model & display*.

- **Neurons.**  One-tap sets: *Shared-stable SUA + MUA* (the server's greedy
  search for the most neurons × stable trials they all share — the usual
  starting point; it sets Trials to stable), *All SUA*, *All SUA + MUA*, and
  SUA per area.  *Choose neurons…* opens a searchable, quality/area-filtered
  checklist that shows each unit's stable-trial count and updates "N selected ·
  M shared stable trials" as you tick.  Under *Trials: stable for unit*, a
  population uses only trials stable for **every** neuron (v0.1's rule).  The
  section lists the neurons whose removal regains the most shared trials, a
  one-tap removal of neurons with no stable trials, and *trim* — the same
  greedy search restricted to the current roster.
- **Groups and fit.**  The groups are exactly the raster view's (filters ×
  colour × line style; panels do not apply).  The server computes every
  neuron's group-mean rates on the explorer's grid (per-event or per-trial
  weighting as chosen) and fits one PCA, ICA or factor-analysis basis to all
  groups' condition-time rows jointly — the classic workspace's sklearn fit
  (`population.fit_basis`), with the same constant-neuron and rank checks.
  Every event is re-checked on the server against the common-trial eligibility
  rule for this roster and window.  Component signs are set so each
  component's largest loading is positive; ICA/FA components are listed by
  variance explained.  *Components* has a 2–10 slider and a number box that
  takes up to 50 (`explorer.MAX_COMPONENTS`); past that the neurons and the
  fit's rank are the limit.  Refits run automatically about 0.3 s after a change
  that affects them and are cached; hiding a group in the legend, axes,
  2D/3D, heatmap group, sorting and the cursor only redraw.
- **Figure.**  A trajectory (any two components, or three in a 3D view you
  drag to rotate; ○ start, ● t = 0, the count window thickened, ◆ marker
  medians), the component time courses in the PSTH's style (count window,
  t = 0, reference lines and marker medians), a neuron × time heatmap for one
  group — z-scored per neuron across all groups, or rate / neuron peak — with
  an area strip, sorted by a component's loading, peak time, mean rate, peak
  channel, area or unit ID, the chosen component's loadings as bars aligned to
  the heatmap rows, variance explained per component (single-component R²
  for ICA/FA) and, to its right, the cumulative variance explained by
  components 1…k together, in the order shown — computed from the partial
  reconstruction, so it ends at the diagnostics' "all K components together"
  figure and is exact for FA, whose scores need not be uncorrelated — with the
  fit's diagnostics.  The toolbar's time cursor (▶ plays;
  ← / → step; space plays) marks the same moment in every panel.
- **Layout.**  On wide screens the trajectory and the time courses share the
  top row half and half.  Drag the divider between them to resize (at least
  240 px each); double-click it, or press *Reset*, for half each.  The split is
  kept with the view.  The trajectory box is at most 600 px tall and keeps
  equal axis scales.  Past eight components the time courses scroll in a box
  the height of eight, under a "PC1–PC8 of 25" header and above a fixed time
  axis, and redraws keep the scroll position; exports draw every component.
- **Reference markers and single trials.**  t = 0 (●) and every reference line
  (■ ▲ ▼ ✚ in time order, set in *Markers*) are marked on each trajectory at the
  bin that contains that time.  *Show single trials at those times* adds a cloud
  of every trial's population state at those times, projected with the fitted
  basis (not full single-trial trajectories), with an opacity slider, an
  optional t = 0, and *Fit axes to* trajectories (the default; dots beyond the
  frame are counted) or the trial cloud (central 98%).  A point is one trial —
  its events averaged — under *Average over trials*, or one event under
  *events*, the same unit as the group means; rates use the fit's grid, kernel
  and normalisation, so each group's cloud is centred exactly on its trajectory
  marker (tested).  The server caches each fit's linear transform, so the cloud
  needs no refit.  Hover a dot for its trial (or event row) and coordinates;
  *Export → Single-trial cloud · CSV* writes every point.
- **Export**: figure SVG/PNG, coordinates CSV (every group's component time
  courses), loadings CSV (unit, peak channel, area, quality) and a settings &
  fit JSON (roster, groups, method, variance, source SHA256).

The fit is descriptive and in-sample: no held-out prediction, no
cross-session alignment, no significance test, and no claim that a
component is a latent cognitive variable.

### What the numbers mean

Row candidacy and eligibility are exactly v0.1's: complete trials; finite event
times inside the recording and the sync-fit window; and a display window that,
padded by the fixed 0.4 s guard, lies inside the run of consecutive eligible
trials containing the event.  The server returns each row's eligible span, so
moving the window re-applies the rule without a round trip.  PSTH bins are
half-open `[a, b)` steps of the bin width from the window start; rates are
counts / bin; the Gaussian kernel is sampled at the bin spacing out to
ceil(4σ / bin) bins, normalised, and applied to bins beyond the window (σ is
capped at 100 ms so the kernel stays inside the guard).  *Average over events*
weights every row equally (n = events, as in the unit 315/893 figures);
*trials* averages rows within a trial first (v0.1's rule, n = trials).  SEM is
the sample SD (ddof 1) / √n.  Window rates are counts in the half-open count
window / its width.  `tests/test_electro_gui_explorer.py` checks the browser
PSTH against `analysis.compute_unit` on the same rows.  All of it is
descriptive: there is no significance testing in the explorer (use `/classic/`),
and nothing corrects for browsing many units, windows or groupings.

Rasters with more rows than about four per pixel of raster height are thinned
for drawing only (evenly spaced within each group; the axis says how many are
drawn); PSTHs, bars, counts and exports always use every row.

### Views, links and export

- **Templates** (Views menu) set the alignment, filters, groups, windows and
  markers of a known figure while keeping the current session and unit:
  *Touch: predator vs prey* (unit 893 style), *Prey touch: world × previous
  object* (unit 315 style), *World × role × action*, *PM touches: did the trial
  go wrong?*, *Trial initiation by world*, *Prey visible, sorted by touch time*.
- **Saved views** store the session, unit and every setting on the server
  (`--views-file`, default `output/electro_gui/saved_views.json`), so every
  device that opens the server sees them.
- **Links.**  The address bar always holds the complete view (`#s=…`); *Copy
  link* shares it.  The last view is also restored from browser storage.
- **Export**: figure SVG (vector, with title, legend and the settings plus
  source SHA256 in `<metadata>`), PNG (2×), PSTH CSV (mean/SEM/n per group and
  bin), rows CSV (one line per shown event: group, window count and rate,
  marker times, key fields) and settings JSON.  CSVs start with a `#` line of
  provenance.

### Config files

A **config file** is a JSON view state kept in the repository, so a figure can be
restored from a file that is reviewed and versioned with the analysis instead of
from a link or a server-side saved view.  The deck configs live next to their
slides, in `output/presentation/<deck>/electro_gui_configs/*.json`; launching from the
repository root finds them all (`--config-dir output/presentation` is the default), and
`--config-dir output/presentation/<deck>/electro_gui_configs` (or any folder of
`*.json`) lists just one.  Views menu → **Config files** shows them under their
`group`; a click applies the file, and **Open config file…** in the same menu
applies any `.json` from disk (read in the browser, never uploaded).  The folder
is re-scanned each time the menu opens, so an edited file needs no restart.

```json
{"electro_gui_config": 1,
 "title": "Unit 893: touch, predator vs prey",
 "hint": "touches aligned to contact, colour = role, style = world",
 "group": "Slide 6 · example neurons",
 "slide": 6,
 "note": "shown as a tooltip; free text for the reader of the file",
 "state": {"session": "sub-Ravel_ses-2026_09_15", "unit": 893, "align": "object_outcome",
           "filters": [{"k": "action", "v": ["touch"]}], "color": "role", "style": "world",
           "win": [-2.2, 0.6], "cw": [-0.5, 0]}}
```

Only `electro_gui_config` (the format version, `1`) and `state` are required;
`title` falls back to the file name, and `hint`, `group`, `slide` (a number or a
label, used only to order the list) and `note` are optional.  `state` is the
explorer's own settings object, the one in the address bar's `#s=…` and in every
export: keys not named here take the GUI defaults, except `session` and `unit`,
which stay as they are when the file names none.  The page passes it through the
same validation as a saved view (unknown keys are dropped, out-of-range values
are clamped or reset), so a typo in a key or value is ignored silently; the
test-suite checks every deck config against the page's key list and types for
that reason.  If `state.session` is not on this server the file is refused with
a message and nothing changes.  Two other shapes are accepted, so no
conversion is needed: the GUI's own **Settings & provenance · JSON** export and
a bare state object (one with an `align` or `unit` key).  That makes the round
trip a copy: export the figure you like, save the file into a deck's
`electro_gui_configs/` (its title is then the file name), and, to give it a
title, hint and slide, wrap the export's `state` in the format above.  Files that are none of these, larger than 256 KiB, dotfiles and
macOS `._*` sidecars are skipped; unreadable files are listed at the bottom of
the section instead of stopping the menu.  `GET /api/configs` returns
`{configs, errors}` and there is no write route.

How they differ from the other ways to restore a view.  **Templates** are built
into the page, change the figure but keep your unit and session.  **Saved views**
are made in the GUI and live in one server-side file
(`--views-file`, under the git-ignored `output/`).  **Config files** are
hand-written or exported, live in git with the deck, and restore the whole view
including the session and unit.

### Explorer API

`GET /api/explorer/session?session=` (units with peak channels, alignment
counts, event names), `/api/explorer/table?session=&alignment=` (columnar joined
fields; `*_t` times become seconds from the row's event),
`/api/explorer/raster?session=&alignment=&unit=&policy=&lo=&hi=` (spike times in
`[t+lo, t+hi)` per row, eligible spans and status codes) and
`/api/explorer/events?session=&event=`,
`/api/explorer/behavior?session=` (every trial's span and world, every resolved
object's outcome time, visible onset, role, action, correctness, bar flag and
image ID, for the behavior timeline),
`/api/explorer/spiketrain?session=&unit=` (the unit's whole spike train as integer
0.1 ms tick differences, `t[i] = tick_s · (dt[0] + … + dt[i])`, for the
timeline's spike lane); for Population,
`/api/explorer/popspans?session=&alignment=&units=1,2,…&policy=` (eligible spans
under the common-trial rule), `/api/explorer/stability?session=` (every unit's
stable trials as base64 bitmasks over complete trials),
`/api/explorer/stable_roster?session=`, `POST /api/explorer/popfit`
(roster, window, grid, weighting, method, groups as row IDs → coordinates,
loadings, group means, variance, diagnostics) and `POST /api/explorer/popprobe`
(the same body plus `probe_times` → every trial's or event's projection at
those times); `GET`/`POST /api/views`; `GET /api/configs`.  The session
must first be opened with a `load` job, which verifies the file.  Responses are
gzip-compressed when the client accepts it.

# Classic workspace (`/classic/`)

The v0.1 interface, unchanged apart from its URL.

## Unit workflow

1. Choose a session and unit. Every recorded unit is listed, including MUA;
   unit IDs are always specific to the chosen source. The first session load
   fingerprints the entire NWB and prepares its event/trial joins.
2. Choose any recorded alignment event, or the four-event `object_outcome`
   union. Set the display interval, 25/50/100 ms bins, Gaussian smoothing up
   to 100 ms, and a separate count interval inside the displayed interval.
3. Choose **Verified stable** or **All complete** explicitly. Verified stable
   derives eligibility from the exact current NWB or the repository's validated
   content-bound cache. All complete deliberately applies no stability filter.
   Neither option uses an unverified embedded mask. Empty support stays empty.
4. Build **Apply to all groups** restrictions and named **Comparison groups**.
   Search for fields by meaning, choose recorded category values or Yes/No,
   and use numeric inputs for numeric comparisons. Definitions, timing,
   recorded-value counts and missingness are shown beside the rules. Task world, observed full-trial
   strategy, object role, action and correctness remain separate. `NA` is a
   literal strategy label, not a missing value. Trial-table fields are also
   exposed as `trial.*`; object metadata appear as `object.*`.
5. Optionally use separate panels or subdivide curves, exclude/allow overlapping memberships, restrict
   to common trial/world strata, or require the whole count interval to end
   before the next actual outcome or trial end. Shared support is a restriction,
   not automatic matching, pairing or covariate adjustment.
6. Inspect the selection preview before computing: events, trials, blocks,
   overlap and exclusions describe the same selection engine used by Compute.
   Eligibility remains pending while its preparation is in progress.
7. Compute. The raster, faceted PSTH, count-window zoom, distribution, support
   ledger and raw-count membership all describe that completed computation.
   Editing a condition labels the completed plots **Previous result — settings
   changed**. Their exports retain the completed settings. Only a successful
   new computation replaces that result.

Question templates create editable comparisons without changing the session or
selected neuron. Historical named-unit examples are reference recipes, not an
instruction to switch the current data. Joystick/gaze window features, color-epoch experience, preswitch
NA-bridge rules, variable-duration exposures, adjusted regression and decoding
are not implemented in 0.1. Available raw trial/object fields can still be used
to construct additional comparisons.

Histories use the complete object chronology before filtering. Previous-object
information requires its actual outcome to have occurred by the anchor; next
object and full-trial fields are retrospective. Gaze-only scene targets do not
become task objects. Dynamic raw metadata may describe a complete object/trial;
they are not automatically prospective features.

For object-aligned rows, next-role/action/outcome refer to the next object by
ordinal. For trial initiation and other non-object anchors, they refer to the
first object with a recorded visible onset at or after the anchor within that
same trial. Pre-spawn timestamps do not establish visibility; absent visible
onsets stay unavailable.
Objects without an outcome still supply any recorded role; missing fields stay
missing. These future-object conditions are retrospective. The separate
`next_outcome_t` field remains the next actual outcome timestamp for temporal gates.

Rasters and counts use
half-open `[start,end)` windows. A fixed 0.4 s guard plus the full display window
must lie inside recording bounds and a run of consecutive eligible trials.
Changing smoothing therefore does not change eligibility. PSTHs average events
within each trial, then trials equally; SEM is descriptive across trial means.

## Significance

Tests evaluate the selected fixed count interval using unsmoothed rates. They
require exactly two declared cohorts, no facets/subdivision, known recorded
block IDs, and no shared event membership. Unsupported designs return an
explicit blocked result, never a substitute test or zero p value.

- **Within-trial contrast / block sign flips:** average each cohort within each
  paired trial; compute A minus B; flip one sign for all trial differences in a
  block. Requires paired support in at least three blocks. Up to 16 blocks use
  the exact sign reference, otherwise a seeded Monte Carlo reference.
- **Disjoint block-label permutation:** each block must belong to one cohort.
  Average events within trial, trials within block, and blocks within cohort.
  Requires at least two blocks per cohort. Enumerate up to 50,000 assignments;
  otherwise use seeded Monte Carlo permutations with fixed cohort block counts.

Both are two-sided exploratory association tests. Exchangeability/symmetry
assumptions require scientific judgment; block structure does not establish
causality. Monte Carlo p values use a plus-one correction. There is **no
correction across the windows, units or recipes explored in the GUI**; q is
null. Null construction, effect units, exact/Monte Carlo status, seed, support
and requested contrast are exported. No nuisance covariates are added implicitly.

## Population workflow

Population has its own alignment, windows, eligibility policy, conditions and
completed result. **Copy settings from Unit** takes an explicit snapshot;
later edits in either workspace remain independent. Choose an explicit unit roster from
one session (one or several recorded areas), then choose PCA, ICA or factor analysis,
centering or z-scoring, and 2–10 components. All units use the intersection of
their eligible trial sets and the same event membership. The backend rebuilds
trial-weighted condition means and fits one shared basis to all displayed
condition-time rows jointly. Constant units are reported and excluded; rank
deficiency or empty common support is an explicit error.

Area, quality and selected-only filters help inspect the roster. Replacing a
selection and adding to it are separate actions. The preview reports common
trial support and the effect of individual neurons on that intersection;
neither the preview nor a failed fit changes the stability policy or roster.

**Select shared-stable SUA + MUA** replaces the roster using all SUA/MUA in the
session, regardless of roster display filters, and sets **Verified stable**.
A deterministic multistart greedy heuristic tries each distinct unit stability
mask, adds units while neurons × shared complete stable trials does not decrease,
and keeps the best result. This is a coverage heuristic, not a guaranteed global
optimum. The shared trial set can contain several periods; it does not imply one
continuous interval. The shortcut reports neurons, shared trials and their
product. Event/condition/window restrictions apply afterward and may reduce
usable support. It never selects units by effect size or population separation.
Units from multiple areas can share one fit; their recorded areas remain in the
result's unit metadata. Manual roster edits remain available.

The population panel supports selected component planes, rotatable 3D views,
time markers, separate component time courses, unit loadings and diagnostics.
These are descriptive in-sample fits. The application does not claim held-out
predictive performance, cross-session alignment, latent cognitive-state
identification or population significance. ICA/FA convergence warnings remain
visible and in the exported diagnostics.

## Saved setups and plot annotations

**Save analysis setup** stores the active workspace's complete settings,
including its conditions, windows, stability policy, selected neuron or
population roster/model, and annotation definitions. **Load analysis setup**
requires the exact session and source fingerprint, validates all fields before changing controls, and shows a readable restore summary. Older conditions-only files use the explicit conditions importer.
**Import conditions only** intentionally leaves the other settings alone.

Unit reference lines and event ticks are overlaid directly on both raster views,
with duration bands behind the spikes and coverage details inside the raster card.
The Unit workspace has no separate pooled annotation plot.

Plot annotations distinguish fixed reference lines, per-row event ticks and
per-row duration bands. Event matching explicitly uses the same object or
trial, with first/last/all occurrence selection. Duration bands retain endpoint
identities, reject ambiguous pairings, report missing endpoints and clip only
their drawing to the viewing window. They do not change event membership,
spike counts, significance tests or population fitting.

Joystick layers use **recorded movement events**. These events can chatter
around the acquisition deadzone; they are not the repository's thresholded
continuous-signal movement bouts. A source name in the event menu is not a
guarantee of complete duration coverage. Coverage and pairing diagnostics are
part of the layer. Variable event times are summarized as explicitly weighted
event-time distributions or occupancy strips, not a single common behavioral
line or band on an average curve. The analysis count-window shade remains
separately labeled.

## Exports, cache and provenance

- **JSON:** the complete result, recipe, source/event membership, exact raw
  counts or population input means, support, test results, transform operators,
  preprocessing, unit order, code/runtime fingerprints and source SHA256.
- **PSTH / coordinates CSV:** full numerical curves or component trajectories. Annotated CSVs append layer definitions, display provenance and source identity; unannotated CSV columns stay unchanged.
- **Counts / events CSV:** every retained unit-event/cohort membership, raw
  count and rate, source row/trial/object identifiers and joined fields.
- **Stats CSV:** the declared unit test or population diagnostics, including
  effect/null details or rank/convergence and the exact source fingerprint.
- **SVG:** a vector scientific figure with embedded settings/provenance.
  Population SVG exports the selected X/Y component plane, also when viewing 3D.

Downloads go through the browser. Persistent eligibility caches default to
`output/electro_gui/cache` (`--cache-dir` changes this). Cached stability is
validated against source bytes, code, parameters, runtime and payload hashes.
Upstream source freshness is separate and is not asserted from successful NWB
loading. The server keeps two prepared sessions, at most twelve analysis/load job records
and eight separate preview records in memory. The latest completed Unit and
Population results are protected from eviction by previews; download results you wish to retain. It serializes numerical jobs to
bound memory use. The HTTP server listens only on loopback and uses local assets.
No pipeline/cluster job or remote publication is launched.

## Verification

```bash
python -m unittest discover -s tests -p 'test_electro_gui*.py' -v
python -m unittest discover -s tests -t . -v
```

The focused tests cover synthetic assembled NWBs, identity/discovery rules,
missingness, histories, membership, raw count boundaries, trial/block weighting,
permutation references, transform reconstruction, HTTP jobs and portable exports.
HTTP integration tests require permission to bind a loopback socket.
The original release evidence remains under `output/electro_gui/validation/`.
Usability implementation, independent real-data checks and browser evidence are
in `output/electro_gui/usability_implementation_20260926/VALIDATION.md`.
