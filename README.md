# electro_gui

An interactive raster / PSTH and population explorer for the imitation
project's assembled session NWBs (`<sid>_session.nwb`, written by
analysis_imitation's `assemble-session`): a raster over a PSTH with filters,
grouping, sorting, markers and instant display knobs; a behavior timeline;
findings (a saved figure with its notes, picture and numbers, re-checked when
reopened); and a Population view that fits one PCA / ICA / FA / TDR basis
across a neuron roster.  The full manual is
[electro_gui/README.md](electro_gui/README.md) and the internals are in
[electro_gui/DESIGN.md](electro_gui/DESIGN.md).

Until 2026-10-09 this lived in the analysis_imitation repository; its history
came with it.

## How it relates to analysis_imitation

electro_gui depends on analysis_imitation's `imitation_phys` package, and never
the other way round.  It reads sessions through `imitation_phys.session_store`
and draws its population view with `imitation_phys.explorer_core`, the same
functions analysis_imitation's world-axis stages call, so a GUI export and the
pipeline's reproduction of it cannot drift apart
(`tests/test_electro_gui_world_axis_contract.py` checks the hand-off).  A
change to either side that touches those modules should be tested in both
repositories.

## Install

Into the `imitation-phys` conda environment, analysis_imitation first:

```bash
pip install --no-deps --no-build-isolation -e ../analysis_imitation
pip install --no-deps --no-build-isolation -e .
```

## Run

```bash
python -m electro_gui            # or: electro-gui
python -m electro_gui --lan      # token-protected, for a tablet or phone
tailscale serve --bg --https=8765 http://127.0.0.1:8765   # tailnet, owner only, no token
```

Sessions are discovered under `/Volumes/T7/engaging-results` and
`/Volumes/Transfer/engaging_results` (`--data-root` / `--session-file` for
others).  The stability cache and findings live in Dropbox,
`<Dropbox>/projects/electro_gui/output/{cache,findings}`, and figure configs are
read from analysis_imitation's presentation decks; see the folder table in
[electro_gui/README.md](electro_gui/README.md) and `electro_gui/paths.py`.

Persistent services can run directly from a source checkout: set their working
directory and, if configured, `PYTHONPATH` to that checkout, and use the same
Python environment as the interactive launcher. No release-directory copy is
needed. Update the clean checkout through the checked Git workflow, then restart
its LaunchAgent and verify its existing HTTPS URL. Python changes need a restart;
static assets are read from the checkout on each request. See the manual's
tailnet section for the owner-login and explicit private-origin access modes.

## Tests

```bash
python -m unittest discover -s tests -t . -v
```

They build a synthetic session with `imitation_phys.synthetic_session`, so they
need imitation_phys installed (above) and no experimental data.
