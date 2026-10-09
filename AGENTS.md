# AGENTS.md

Standing instructions for Codex and Claude working in `electrogui`.  `CLAUDE.md`
is a pointer here.  `README.md` and `electro_gui/README.md` document the tool;
`electro_gui/DESIGN.md` documents its internals.

## Thread handoff (always on)

Work here may be continued by another agent (Claude Code or Codex) on another
machine.  Threads live in the shared store `projects/electro_gui/threads/`,
reached through this clone's `.threads` link; publish every entry with
`python3 ~/.agents/skills/thread-handoff/scripts/thread.py` (`list`, `new`,
`show`, `log`, `plan`) and never edit the store by hand.  Every non-trivial
piece of work belongs to one thread, and every turn ends with a `thread.py log`
entry.  Before coding, run `code_sync.py work-start` on a `task/<name>` branch;
see `~/.agents/skills/thread-handoff/SKILL.md`.

## The dependency runs one way

electro_gui imports analysis_imitation's `imitation_phys`; nothing in
`imitation_phys` imports electro_gui (analysis_imitation's
`tests/test_pipeline_does_not_import_gui.py` enforces it).  Session loading
(`imitation_phys.session_store`) and the arithmetic the world-axis stages share
with the Population view (`imitation_phys.explorer_core`) belong to the
pipeline: change them in analysis_imitation, run both repositories' tests, and
push analysis_imitation first.  `tests/test_electro_gui_world_axis_contract.py`
here is the check that a GUI export is still what world-axis-projection
reproduces.

## Checks

```bash
python -m unittest discover -s tests -t . -v
```

The tests build a synthetic session with `imitation_phys.synthetic_session`
and need no experimental data; they need imitation_phys importable (see
README's Install).

## Data and outputs

Sessions are the assembled `<sid>_session.nwb` files under
`/Volumes/T7/engaging-results/<sid>/analysis/nwb/` (Mac mini) or
`/Volumes/Transfer/engaging_results/<sid>/analysis/nwb/` (office iMac);
analysis_imitation's AGENTS.md is the rule for finding and validating them, and
for interpreting task worlds and behavior labels.  The cache and findings live
in `<Dropbox>/projects/electro_gui/output/` (`electro_gui/paths.py`); keep
generated outputs out of Git.
