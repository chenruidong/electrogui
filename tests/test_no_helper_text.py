"""The interface explains itself through its layout, not through captions.

Taglines, helper paragraphs and secondary labels were cut from the explorer; where a screen needed
one, its layout changed instead (electro_gui/DESIGN.md, "Quiet interface").  These checks keep the
cut text from drifting back: they read the static page and script, so they need no session data.
Empty and error states keep their one-line reasons, and exports keep their full captions.
"""
import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "electro_gui" / "static"
HTML = (STATIC / "index.html").read_text()
JS = (STATIC / "explorer.js").read_text()


class QuietInterfaceTests(unittest.TestCase):
    def test_page_has_no_caption_elements(self):
        for cls in ("note", "help", "foot", "lg-hint", "bt-hint", "bt-legend-note", "bt-worlds", "mini-label", "ylock"):
            self.assertIsNone(re.search(rf'class="(?:[^"]* )?{cls}(?: [^"]*)?"', HTML), cls)
        self.assertNotIn('id="subtitle"', HTML)
        # Sentence-long switch labels and parenthetical captions became segments, steppers and placeholders.
        for text in ("Keep groups together", "lock at", "type up to 50", "blank = display window", "Filter on any field",
                     "Marker from any event", "<span>Raster height</span>", "or drag on the PSTH", "Median marker lines",
                     "Window-rate bars beside", "Rate by row beside", "yoke to rasters", "A · heatmap", "Subtract B",
                     '<span class="pick-label">unit</span>', '<span class="pick-label">aligned to</span>'):
            self.assertNotIn(text, HTML, text)

    def test_figure_controls_sit_on_the_figure(self):
        # Axis pickers and the heatmap header are overlays on the population figure; the yoke sits on the divider.
        overlay = HTML[HTML.index('id="figOverlay"'):HTML.index('<div class="empty"')]
        for control in ('id="axX"', 'id="axY"', 'id="axZ"', 'id="heatGroup"', 'id="heatCompare"', 'data-key="heatNorm"', 'id="heatSort"'):
            self.assertIn(control, overlay, control)
        divider = HTML[HTML.index('class="bt-divider"'):HTML.index('<section class="behavior"')]
        self.assertIn('id="btYoke"', divider)
        self.assertIn('id="ruler"', HTML)
        # Exports still draw the captions the screen replaced with controls.
        for kept in ("if (opts.export) out.push(`<text x=\"${f(heat.x)}\"", "events (${L.thinned.shown} of ${L.thinned.total} drawn)",
                     "rate in [${C.fmtNum(M.cw[0])}, ${C.fmtNum(M.cw[1])}) s"):
            self.assertIn(kept, JS, kept)

    def test_script_draws_no_captions_on_screen(self):
        for needle in ('class="lg-hint"', 'class="bt-hint"', "$('foot')", "$('subtitle')", "Most limiting", "in this session · Result Viewer",
                       "scroll for more", "drag to rotate", "your judgement, not a test", "separated by commas"):
            self.assertFalse(needle in JS, needle)

    def test_popover_notes_are_one_line_statuses(self):
        # A pop-note may say what is empty or what failed; it may not explain the interface.
        for m in re.finditer(r'class="pop-note"[^>]*>([^<`$]*)', JS):
            self.assertLessEqual(len(m.group(1)), 60, m.group(1))

    def test_menu_and_export_items_are_named_not_described(self):
        for m in re.finditer(r'data-exp="[a-z]+"[^`]*', JS):
            self.assertNotIn("<small>", m.group(0))
        self.assertNotIn("Templates · ", JS)
        self.assertNotIn("Config files · ", JS)

    def test_what_left_the_screen_is_kept_for_exports_and_agents(self):
        # Exported figures keep title and subtitle; the page publishes a machine-readable view.
        self.assertIn("subtitle: `${D.summary.session_id} · ${D.figMeta.subtitle}`", JS)
        self.assertIn('id="figure-state"', HTML)
        self.assertIn("function figureState()", JS)
        self.assertGreaterEqual(JS.count("publishState();"), 3)


if __name__ == "__main__":
    unittest.main()
