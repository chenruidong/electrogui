"""Training-only normalization, exact projection and trial partition regressions."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from electro_gui import explorer
from imitation_phys.explorer_core import population_spans
from imitation_phys.session_store import SessionStore
from imitation_phys.synthetic_session import write_synthetic_session_file, default_events, _event_row, TRIAL_STARTS_S


class PopulationTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        events = default_events()
        extra = []
        for i, t in enumerate(TRIAL_STARTS_S):
            event, uid, dt = ('predator_avoid', 'pred-1', 3.) if i % 2 == 0 else ('prey_capture', 'prey-1', 1.)
            extra.append(_event_row(event, t + dt, i, session_id=str(events.iloc[0]['session']), object_uid=uid))
        events = pd.DataFrame([*events.to_dict('records'), *extra], columns=events.columns)
        path = write_synthetic_session_file(Path(cls.temp.name), events=events)
        cls.loaded = SessionStore([], [path], Path(cls.temp.name) / 'cache').get(path.name.removesuffix('_session.nwb'))
        rows = explorer.alignment_rows(cls.loaded, 'object_outcome')
        spans = population_spans(cls.loaded, 'object_outcome', list(range(1, 7)), 'all_complete')['span']
        cls.rows = [r for r, span in zip(rows, spans) if span and -.9 >= span[0] and 1.4 <= span[1]]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def request(self, **extra):
        req = dict(unit_ids=list(range(1, 7)), alignment='object_outcome', policy='all_complete',
                   pre=-.5, post=1., bin=.05, sigma=.05, weight='trial', method='pca', scaling='zscore', components=2,
                   groups=[dict(key='all', label='All', row_ids=[int(r['row_id']) for r in self.rows])])
        req.update(extra)
        return req

    def group_request(self, **extra):
        return self.request(groups=[dict(key=k, label=k, row_ids=[int(r['row_id']) for r in self.rows if r['trial'] % 2 == parity])
                                    for k, parity in [('train', 1), ('project', 0)]], fit_group_keys=['train'], **extra)

    def test_training_group_fit_equals_fit_without_projected_data_for_every_method(self):
        for method in ('pca', 'ica', 'fa', 'tdr'):
            for scaling in ('center', 'zscore'):
                with self.subTest(method=method, scaling=scaling):
                    req = self.group_request(method=method, scaling=scaling, factors=['world', 'action'])
                    got = explorer.population_fit(self.loaded, req)
                    reference = explorer.population_fit(self.loaded, {**req, 'groups': req['groups'][:1]})
                    self.assertEqual(got['active_unit_ids'], reference['active_unit_ids'])
                    self.assertEqual(got['normalization'], reference['normalization'])
                    self.assertEqual(got['loadings'], reference['loadings'])
                    self.assertEqual(got['component_r2'], reference['component_r2'])
                    self.assertEqual(got['groups'][0]['coords'], reference['groups'][0]['coords'])
                    op = got['normalization']
                    for g in got['groups']:
                        expected = ((np.array(g['means']) - op['center']) / op['scale']) @ op['operator'] + op['offset']
                        np.testing.assert_allclose(expected, g['coords'], atol=1e-3)
                    self.assertEqual(got['groups'][1]['sample'], 'projected group')

    def test_changed_held_out_responses_cannot_affect_training_or_constant_unit_selection(self):
        original = {u: np.array(self.loaded.spikes(u)) for u in range(1, 7)}
        held = [float(r['t']) for r in self.rows if r['trial'] % 2 == 0]
        # Unit 6 is constant in training but strongly modulated in projected data.
        base = {**original, 6: np.array([])}
        perturbed = {u: np.concatenate([base[u], *[t + np.linspace(-.4, .8, 100 + 7*u) for t in held]]) for u in base}
        for method in ('pca', 'ica', 'fa', 'tdr'):
            req = self.group_request(method=method, factors=['world', 'action'])
            with mock.patch.object(self.loaded, 'spikes', side_effect=lambda u: base[u]):
                first = explorer.population_fit(self.loaded, req)
            with mock.patch.object(self.loaded, 'spikes', side_effect=lambda u: perturbed[u]):
                second = explorer.population_fit(self.loaded, req)
            self.assertIn(6, second['dropped_constant_units'])
            self.assertEqual(first['normalization'], second['normalization'])
            self.assertEqual(first['loadings'], second['loadings'])
            self.assertNotEqual(first['groups'][1]['means'], second['groups'][1]['means'])

    def test_odd_even_and_explicit_trials_display_complement_and_probe_uses_same_operator(self):
        for split in ('odd', 'even'):
            parity = 1 if split == 'odd' else 0
            tids = sorted({int(r['trial']) for r in self.rows if r['trial'] % 2 == parity})
            req = self.request(fit_split=split)
            fit = explorer.population_fit(self.loaded, req)
            explicit = explorer.population_fit(self.loaded, self.request(fit_trial_ids=tids))
            self.assertEqual(fit['groups'], explicit['groups'])
            self.assertEqual(fit['normalization'], explicit['normalization'])
            self.assertEqual(fit['training']['shared_trials'], 0)
            self.assertEqual(fit['training']['trial_ids'], tids)
            self.assertTrue(fit['training']['held_out_trials'])
            train_ids = set(fit['training']['row_ids'])
            self.assertFalse(train_ids.intersection(fit['groups'][0]['row_ids']))
            for method in ('pca', 'ica', 'fa', 'tdr'):
                for weight in ('event', 'trial'):
                    r = {**req, 'method': method, 'weight': weight, 'factors': ['world', 'action']}
                    f = explorer.population_fit(self.loaded, r)
                    probe = explorer.population_probe(self.loaded, {**r, 'probe_times': [.25]})['probes'][0]
                    np.testing.assert_allclose(np.mean(probe['groups'][0]['points'], axis=0),
                                               f['groups'][0]['coords'][probe['bin_index']], atol=1e-4)
                    if weight == 'trial':
                        self.assertFalse(set(probe['groups'][0]['ids']).intersection(tids))
        keys = [explorer._fit_inputs(self.loaded, self.request(fit_split=k))['key'] for k in ('all', 'odd', 'even')]
        self.assertEqual(len(set(keys)), 3)

    def test_invalid_training_selections_fail_instead_of_falling_back(self):
        for change in [dict(fit_group_keys=[]), dict(fit_group_keys=['missing']), dict(fit_group_keys=['all', 'all']),
                       dict(fit_split='random'), dict(fit_trial_ids=[]), dict(fit_trial_ids=[99999]),
                       dict(fit_trial_ids=[True]), dict(fit_split='odd', fit_trial_ids=[1]),
                       dict(fit_trial_ids=sorted({int(r['trial']) for r in self.rows}))]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                explorer.population_fit(self.loaded, self.request(**change))
        # All fitting methods must reject a single-time training matrix's rank;
        # TDR additionally needs training-only factor variation.
        req = self.request(method='tdr', factors=['world', 'action'])
        pp = [int(r['row_id']) for r in self.rows if r['world'] == 'PP']
        req['groups'] = [dict(key='pp', row_ids=pp), dict(key='other', row_ids=[int(r['row_id']) for r in self.rows if r['world'] != 'PP'])]
        with self.assertRaisesRegex(ValueError, 'single level'):
            explorer.population_fit(self.loaded, {**req, 'fit_group_keys': ['pp']})

    def test_overlapping_training_and_display_spike_windows_are_rejected(self):
        req = self.request(fit_split='odd')
        rows = deepcopy(explorer.alignment_rows(self.loaded, 'object_outcome'))
        train_t = next(r['t'] for r in rows if r['trial'] % 2)
        for r in rows:
            if r['trial'] % 2 == 0:
                r['t'] = train_t + .1
        with mock.patch.object(explorer, 'alignment_rows', return_value=rows), mock.patch.object(
                explorer, 'eligible_spans', return_value=([[-1000, 1000]] * len(rows), [])):
            with self.assertRaisesRegex(ValueError, 'spike windows overlap'):
                explorer._fit_inputs(self.loaded, req)
