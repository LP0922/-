"""Offline HTTP contract tests: no DeviceReader and no serial devices."""
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import device_control_server as server


def offline_service():
    service = server.DeviceControlService.__new__(server.DeviceControlService)
    service._snapshot_lock = threading.Lock()
    service._test_lock = threading.Lock()
    service._cancel_event = threading.Event()
    service._powder_session = None
    service._probe_result = None
    service._rate_search_result = None
    service._snapshot = {
        'at8811c': {'online': False, 'error': '离线验证，不连接硬件'},
        'la10': {'online': False, 'error': '离线验证，不连接硬件'},
        'test': {'status': 'idle'},
    }
    service._run_feedback_dispense = Mock()
    service._run_dispense_batch = Mock()
    service._run_grid_constant_rate = Mock()
    return service


class MigratedApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = offline_service()
        cls.http = ThreadingHTTPServer(('127.0.0.1', 0), server.make_handler(cls.service))
        cls.worker = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.worker.start()
        cls.base = 'http://127.0.0.1:' + str(cls.http.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.worker.join(timeout=2)

    def setUp(self):
        self.service._snapshot['test'] = {'status':'idle'}

    def call(self, path, payload=None):
        request = Request(self.base + path, data=None if payload is None else json.dumps(payload).encode(),
                          headers={'Content-Type':'application/json'})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_available_powders_and_configs(self):
        status, powders = self.call('/api/dispense/powders')
        self.assertEqual(status, 200)
        ids = {p['powder_id'] for p in powders}
        self.assertIn('bentonite', ids)
        self.assertIn('water_loss_agent_2', ids)
        self.assertNotIn('powder-20260811-101154-c32e23', ids)
        self.assertNotIn('powder-20260817-110326-9f48b6', ids)
        for powder in powders:
            if powder.get('selectable') is False:
                continue
            for mass in (100, 437, 1000):
                with self.subTest(powder=powder['powder_id'], target=mass):
                    code, config = self.call('/api/dispense/config?powder_id=' + powder['powder_id'] + '&target_mg=' + str(mass))
                    self.assertEqual(code, 200, config)
                    self.assertEqual(config['powder_id'], powder['powder_id'])
                    self.assertEqual(config['target_mg'], mass)
                    self.assertEqual(config['acceptance_min_mg'], mass-10)
                    self.assertEqual(config['acceptance_max_mg'], mass+10)
                    self.assertIn('stall_recovery_enabled', config['controller'])

    def test_preview_rejects_missing_identity_and_invalid_target(self):
        for query in ('target_mg=500','powder_id=bentonite&target_mg=99','powder_id=bentonite&target_mg=100.5'):
            self.assertEqual(self.call('/api/dispense/config?' + query)[0], 400)

    def test_start_requires_powder_and_resolves_automatic_settings(self):
        self.assertEqual(self.call('/api/dispense/start', {'target_mg':500})[0], 400)
        status, response = self.call('/api/dispense/start', {'powder_id':'bentonite','target_mg':1000})
        self.assertEqual(status, 202, response)
        self.assertEqual(response['submitted']['powder_name'], '膨润土')
        self.assertEqual(response['submitted']['config_source'], 'dedicated_profile')
        self.assertFalse(response['submitted']['close_window_after_run'])

    def test_batch_rejects_mixed_powders(self):
        seed = {'target_mg':1000,'frequency_hz':80,'duty_permyriad':2200,'window_position_units':300,'repeat_count':1}
        status, response = self.call('/api/dispense/batch', {'sets':[
            {**seed,'powder_id':'bentonite'}, {**seed,'powder_id':'water_loss_agent_2'}]})
        self.assertEqual(status, 400)
        self.assertIn('一种粉末', response['error'])

    def test_dispense_batch_closes_window_after_each_run_by_default(self):
        seed = {
            'powder_id': 'bentonite', 'target_mg': 1000,
            'frequency_hz': 80, 'duty_permyriad': 2200,
            'window_position_units': 300, 'repeat_count': 1,
        }
        status, response = self.call('/api/dispense/batch', {'sets': [seed]})
        self.assertEqual(status, 202, response)
        self.assertFalse(response['submitted']['close_window_between_runs'])

    def test_grid_preserves_explicit_preview_rows(self):
        rows = [{'frequency_hz':55,'duty_permyriad':2200,'window_position_units':280,'duration_s':12,'repeat_count':2},
                {'frequency_hz':70,'duty_permyriad':2000,'window_position_units':250,'duration_s':12,'repeat_count':2}]
        status, response = self.call('/api/experiment/grid/start', {
            'experiment_type':'constant_rate','powder_id':'bentonite','powder_name':'膨润土','sets':rows})
        self.assertEqual(status, 202, response)
        self.assertEqual(response['expanded_sets'], len(rows))
        self.assertEqual(self.service.snapshot()['test']['submitted']['sets'], rows)

    def test_control_profiles_and_templates(self):
        self.assertEqual(self.call('/api/control-profiles')[0], 200)
        code, response = self.call('/api/experiment/grid/templates')
        self.assertEqual(code, 200)
        self.assertTrue(response['templates'])


if __name__ == '__main__':
    unittest.main()
