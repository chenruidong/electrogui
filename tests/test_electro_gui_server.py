import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from electro_gui.data import SessionStore
from electro_gui.server import Application, make_server
from tests.synthetic_session import write_synthetic_session_file


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = write_synthetic_session_file(Path(self.temp.name))
        self.sid = self.path.name.removesuffix("_session.nwb")
        store = SessionStore([], [self.path], Path(self.temp.name) / "cache")
        self.app = Application(store)
        self.server = make_server(self.app, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.close()
        self.thread.join()
        self.temp.cleanup()

    def get(self, path, method="GET", body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=30)
        hdr = {"Content-Type": "application/json", **(headers or {})}
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=hdr)
        response = connection.getresponse()
        data = response.read()
        status = response.status
        connection.close()
        return status, data

    def job(self, request):
        status, data = self.get("/api/jobs", "POST", request)
        self.assertEqual(status, 202, data)
        job_id = json.loads(data)["id"]
        for _ in range(200):
            _, raw = self.get("/api/jobs/" + job_id)
            result = json.loads(raw)
            if result["status"] in ("error", "done"):
                return job_id, result
            time.sleep(.025)
        self.fail("Synthetic job did not complete")

    def test_dynamic_load_computation_and_bound_export(self):
        status, data = self.get("/api/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["sessions"][0]["id"], self.sid)
        _, load = self.job({"action": "load", "session_id": self.sid})
        self.assertEqual(load["status"], "done", load)
        self.assertEqual(len(load["result"]["units"]), 6)
        request = {"action": "unit", "session_id": self.sid, "unit_id": 1, "alignment": "object_outcome",
                   "pre": -.5, "post": .5, "bin": .05, "sigma": 0, "count_window": [0, .5], "stability": "all_complete"}
        job_id, computed = self.job(request)
        self.assertEqual(computed["status"], "done", computed)
        result = computed["result"]
        self.assertTrue(result["rows"])
        self.assertEqual(result["provenance"]["computation_identity"]["source_nwb"]["sha256"], load["result"]["source"]["sha256"])
        status, downloaded = self.get(f"/api/jobs/{job_id}/export?format=json")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(downloaded)["settings"], request)
        status, svg = self.get(f"/api/jobs/{job_id}/export?format=svg")
        self.assertEqual(status, 200)
        self.assertIn(b"<svg", svg)
        _, bad = self.job({**request, "unit_id": 99999})
        self.assertEqual(bad["status"], "error")

    def test_stable_selection_job_matches_verified_eligibility(self):
        _, job = self.job({"action": "stable_selection", "session_id": self.sid})
        self.assertEqual(job["status"], "done", job)
        result = job["result"]
        self.assertEqual(result["kind"], "stable_selection")
        self.assertEqual(result["session_id"], self.sid)
        loaded = self.app.store.get(self.sid)
        units = {u["id"]: u for u in loaded.units}
        self.assertTrue(result["unit_ids"])
        self.assertTrue(all(units[i]["quality"].lower() in ("sua", "mua") for i in result["unit_ids"]))
        eligible, _ = loaded.eligibility(result["unit_ids"], "verified_stable")
        self.assertEqual(set(result["trial_ids"]), eligible)
        self.assertEqual(result["coverage"], len(result["unit_ids"]) * len(eligible))

    def test_foreign_origin_host_and_unknown_paths_rejected(self):
        self.assertEqual(self.get("/api/catalog", headers={"Host": "attacker.test"})[0], 403)
        self.assertEqual(self.get("/api/jobs", "POST", {"action": "load", "session_id": self.sid}, {"Origin": "https://attacker.test"})[0], 403)
        self.assertEqual(self.get("/../../pyproject.toml")[0], 404)
        self.assertEqual(self.get("/api/jobs/missing")[0], 404)
        self.assertEqual(self.get("/api/jobs", "POST", {"action": "unknown"})[0], 400)


if __name__ == "__main__":
    unittest.main()
