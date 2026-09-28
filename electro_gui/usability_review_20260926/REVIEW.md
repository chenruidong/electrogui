# electro_gui usability review — 26 September 2026

The current interface requires the user to know the data schema, exact category spellings, and cross-tab dependencies. The highest priorities are guided condition selection and genuinely independent Unit/Population workspaces. Event ticks and movement shading need an explicit annotation feature; they are absent from the current renderer.

This is a review and proposed design, not an implementation. Application code, scientific data, and existing results were left unchanged.

## Scope and evidence

- Reviewed the current uncommitted `electro_gui` in `/Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation`, based on `main@04c1a02`. The calling `5c2a` worktree has the same base commit but does not contain that implementation. Source references below point to the main checkout.
- Opened the running interface at `http://127.0.0.1:55035/`, inspected Unit and Population, and selected **Object action** in a condition. The loaded September 15 session presented **112 condition fields, 70 alignments, and 875 units**. These are live UI counts, not general constants.
- The selected action field displayed a blank text box, all 11 operators, and `category · object_outcome_posthoc`. It did not present action values or a definition. Population displayed **Shared selection** and **Edit alignment / conditions**.
- Read frontend, registry, condition validation, selection, population, export/import, and movement helper code. A focused execution of current `conditions.validate_group` with the saved session field registry accepted `action=touchh`, `role=preey`, and `world=PMPP` without validation errors. No new neural fit or full numerical regression suite was run for this review.
- Browser screenshots were visually inspected at the available 855 × 938 viewport. This is a scoped walkthrough, not an exhaustive accessibility or cross-browser audit. The presence of movement event names does not establish correctly paired or scientifically appropriate movement intervals.

## Findings in priority order

### 1. P1 — Condition choices are neither discoverable nor reliably validated

Every field uses the same free-text value box. Every field also offers numeric comparisons, set membership, and missingness operators regardless of type. The help line describes internal type/timing tokens rather than the field's meaning. Changing to Object action leaves the value blank. A user cannot learn the valid choices from that control.

There is a data-contract defect behind the UI: the core categorical registry entries, including world, strategy, role, action, and outcome, do not include `values`. Only extra categorical fields receive observed values. The validator accepts an arbitrary string when `values` is absent. A misspelling can therefore pass validation and later select no matching events, which is easily mistaken for lack of data.

Evidence: [condition renderer](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/static/app.js:95>), [field-change handler](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/static/app.js:125>), [registry](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/data.py:256>), [validator](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/conditions.py:38>).

Proposed interaction:

- Categories: searchable single/multiple selection, human-readable labels, exact recorded value available in details, and counts for each value.
- Numbers: appropriate numeric operators, separate lower/upper inputs for ranges, units and observed range.
- Booleans: Yes / No. Missingness: explicit **is missing / is recorded**, with counts; literal strategy `NA` remains a separate value.
- Use **is**, **is not**, **is one of**, **between**, and other ordinary labels, with only compatible operators.
- Show a one-sentence definition and timing explanation beside the chosen field. For example, observed trial strategy describes the full trial and is determined afterward; it is not a prospective belief estimate.
- Validate incomplete/unknown values next to the rule before Compute. Distinguish a valid category with zero support from a typo or unavailable producer.

### 2. P1 — Population is coupled to hidden Unit controls and results

Population has roster/model controls but reads alignment, display/count windows, binning, smoothing, stability and conditions from the Unit form. Editing its alignment requires leaving the workspace. Both workspaces also share one revision and one invalidation function: changing a population model or roster clears the unit result, and computing either result clears the other result and its exports.

Evidence: [requestBase](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/static/app.js:81>), [global invalidation](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/static/app.js:59>), [run](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/static/app.js:194>), [shared-selection navigation](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/static/app.js:412>).

Give each workspace its own alignment, windows, eligibility policy, filters, comparison groups, grouping, overlays, draft settings, completed result, and job revision. Population additionally owns its neuron roster and model. Keep the session shared initially, and make the Unit-specific neuron picker local to Unit. Provide **Copy settings from Unit** as an explicit snapshot action; subsequent changes remain independent. Reuse the same selection engine and control components internally.

Distinguish population **neuron selection** (area, quality, explicit IDs, eligibility) from **trial/event selection** (alignment and conditions). Preview their intersection before fitting. Show the number of common trials and why particular neurons reduce it; do not silently drop neurons or switch stability policies to make a fit run.

### 3. P1 — Saved recipes do not restore the analysis settings they contain

Download includes both `recipe` and `settings`. Import reads `recipe` and ignores the saved settings. Alignment, time windows, smoothing, stability and test selection can remain from the current screen. The download also omits the population roster and model. A user reasonably expects an imported saved setup to reproduce the setup they saved.

Evidence: [download/import handlers](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/static/app.js:447>).

Provide **Save analysis setup** and **Load analysis setup**, scoped to the active workspace. Restore the complete configuration with session/source compatibility checks and a readable summary of what will be restored. Retain a separately named **Import conditions only** operation when that is the intended scope. Include the population roster, model and annotation definitions in its saved setup.

### 4. P2 — Field and alignment lists expose too much at once

The field selector is one flat list of 112 items. Useful fields sit beside IDs, aliases, raw `trial.*`/`object.*` metadata, unavailable derivations, and fields such as manifest paths. The same menu is reused for Facet, Group by and Split by, including high-cardinality numbers/timestamps that can exceed plot limits. Alignment has 70 raw event names, including synchronization and diagnostic events.

Evidence: [fieldOptions](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/static/app.js:88>), [grouping menus](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/static/app.js:143>), [curve/facet limits](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/analysis.py:153>).

Use a search-first picker with a short **Common** section, then **Task/trial**, **Object/outcome**, **History**, and **Advanced recorded fields**. Keep unavailable fields in a separate explanatory section, disabled for new rules. Hide duplicate aliases from common choices while preserving imported recipes. Show grouping cardinality and require explicit bins for continuous values. Alignment should similarly group **Trial**, **Object**, **Movement**, **Reward**, **Eye**, and **Technical**, with plain-language descriptions.

### 5. P2 — Event markers and duration overlays need a dedicated design

The renderer draws spike ticks, the automatic dashed zero line, and the fixed count-window shade. There is no Add marker/Add interval interface or corresponding result contract. The existing population time cursor is a selected coordinate time, not a behavioral event annotation.

Evidence: [plot frame and shade](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/static/app.js:229>), [raster/PSTH](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/static/app.js:247>).

Add **Plot annotations** with three distinct choices:

| Choice | Example | Drawing and definition |
|---|---|---|
| Reference line | +200 ms | One constant position relative to the alignment |
| Event ticks | Object spawn, reward, movement offset | Per-row times relative to that row's anchor; explicit same-object/same-trial or first/last/all matching |
| Duration bands | Joystick movement, object visibility | Per-row onset–offset intervals, clipped to the viewing window, with identity and pairing rules |

Each layer needs a name, source, match rule, color/style, visibility toggle, legend entry and coverage count. Missing or ambiguous endpoints should be reported. Do not pair unrelated objects or movements by simply zipping all onsets with all offsets. Display-only annotations must not change membership, counts, tests or model fitting.

The loaded session exposes `joystick_move_onset` and `joystick_move_offset`. However, existing [movement analysis documentation](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/imitation_phys/decoding.py:27>) warns that raw event excursions can chatter; the repository also has a continuous-signal bout detector and [movement-ID event generation](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/imitation_phys/unit_rates.py:1067>). The GUI must name the chosen movement definition: **recorded movement events** versus **detected joystick bouts**, with detection parameters available. Continuous direction/window features being unavailable in the GUI does not mean movement timing is absent from the NWB. Verify the selected source's channels, pairs and coverage before promising a particular duration layer.

For a PSTH or population mean, variable event times cannot honestly become one unexplained vertical line or one common band. Show an optional event-time distribution or movement-occupancy strip, labeled with its averaging/weighting and support. Keep exact intervals on raster rows. Distinguish the analysis count-window shade from behavioral duration shades through labels and styles. Preserve annotations and their provenance in exports.

### 6. P2 — Selection feedback arrives too late

Counts appear only after computation; detailed exclusion reasons are buried in JSON. The user cannot see whether a rule removed all data, whether cohorts overlap, or whether stability intersection made a population impossible while building it.

Evidence: [support construction](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/analysis.py:162>), [support rendering](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/static/app.js:293>).

Add a debounced selection preview with events, unique trials, blocks and missing values per group; common population support; overlap; and a short exclusion breakdown. Reuse the same selection engine as Compute. If stability preparation is still running, say **eligibility pending** rather than displaying a provisional count as final. Explain errors beside the responsible control and offer a concrete correction. Disable inapplicable significance designs before submission with the reason shown.

### 7. P2 — Defaults and terminology make the workflow harder to interpret

Population silently starts with the first 12 SUA units in the first unit's area. The roster can retain hidden selections while filtering; mixed areas fail only at Compute. Presets are named around historical neuron IDs and can change session/unit. At the inspected narrow viewport, settings dominate the first screen and plots lie below the long form.

Evidence: [default roster](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/static/app.js:161>), [roster filtering](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/static/app.js:185>), [same-area guard](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/population.py:43>), [preset changes](</Volumes/Drive1T/MIT Dropbox/Ruidong Chen/analysis_imitation/electro_gui/static/app.js:394>).

Make the roster an explicit choice with area/quality controls, **selected only**, visible quality labels, and separate **replace selection** and **add to selection** actions. Keep named-unit recipes as examples; add reusable question-based templates that do not silently select another neuron. Rename **Shared restriction → Apply to all groups**, **Cohort → Comparison group**, **Facet → Separate panels**, and **Split by → Subdivide curves**; explain whether Group by changes membership or styling. Move advanced rules/statistics behind disclosures and keep the current analysis summary and Compute action close to the plots.

## Proposed workspace structure

Both tabs should follow the same order: **Data → Alignment & window → Selection → Comparison groups → Plot annotations → Display → Results**. Population adds **Neuron selection** before trial/event selection and **Model** before Results. Support counts remain visible near Compute. Advanced/raw fields remain available without occupying the default workflow.

Preserve the last completed result under an explicit **Previous result — settings changed** label while editing a draft. The result keeps its own immutable settings and exports; Compute replaces it only after success. A display-only change should redraw the existing result. A Unit change should not clear Population, and vice versa. Do not show an old result as if it used the new controls.

## Acceptance checks for implementation

1. A user can create “non-bar prey, touched, PP versus PM” without typing a category code, consulting source files, or guessing an operator. Definitions, supported values and group support are visible.
2. Invalid categorical strings fail at the rule; valid values with zero support remain distinguishable from missing data and unavailable fields. `NA` remains literal strategy data.
3. Unit remains object-outcome aligned while Population is initiation aligned with different filters. Editing/running either preserves the other's settings, completed result and exports.
4. A saved setup round-trips alignment, windows, conditions, stability, roster/model and annotations. Applying only conditions is explicitly labeled.
5. Add object-spawn ticks and joystick movement bands to an outcome-aligned raster. Inspect exact source identity and onset/offset pairing; report missing endpoints; export the same overlays. Annotation toggles leave raw counts and membership unchanged.
6. Population warns about mixed areas, missing support and an empty common trial intersection before fitting. Selection is explicit and no default silently broadens eligibility.
7. Show a meaningful zero-support explanation and keep the prior completed result clearly labeled. Long forms remain usable with keyboard navigation and at narrow widths.

Recommended sequence: condition registry/controls and workspace isolation first; complete setup save/load and support preview next; then annotations with validated event relationships and movement definitions. These changes address discoverability, error prevention and reproducibility together.
