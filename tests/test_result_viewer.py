"""Open in Result Viewer: which result-viewer the page is sent to (electro_gui/result_viewer.py)."""
import http.client
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from imitation_phys.session_store import SessionStore

from electro_gui.result_viewer import ResultViewerFinder, candidates
from electro_gui.server import Application, make_server

SID = "sub-Test_ses-2026_01_02"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Fake:
    """A loopback HTTP server answering GET ``path`` with ``body`` (JSON), or ``status`` alone."""

    def __init__(self, routes, delay=0.0):
        self.routes = routes
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                time.sleep(delay)
                status, body = fake.routes.get(self.path, (404, {"error": "no"}))
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def viewer(*sessions):
    return _Fake({"/api/sessions": (200, {"sessions": [{"id": s} for s in sessions]})})


def app(url, peer=False, host="Mac mini", route=None, status="up", **extra):
    """A dashboard ``/api/apps`` entry for a result-viewer at loopback ``url``, behind tailnet ``route``."""
    port = int(url.rstrip("/").rsplit(":", 1)[1])
    routes = [{"url": route, "kind": "proxy", "target": f"http://127.0.0.1:{port}", "stale": False}] if route else []
    return {"id": "result-viewer", "peer": peer, "host_label": host, "status": status,
            "local": {"url": url, "port": port}, "routes": routes, **extra}


class CandidateTests(unittest.TestCase):
    def test_this_macs_viewer_comes_first_with_the_url_the_page_can_open(self):
        apps = [app("http://127.0.0.1:8766/", peer=True, host="iMac", route="https://window.example.ts.net:8766/"),
                {"id": "electrogui", "peer": False, "local": {"url": "http://127.0.0.1:8790/"}, "routes": []},
                app("http://127.0.0.1:8767/", route="https://macmini.example.ts.net:8767/")]
        at_localhost = candidates(apps, local_page=True)
        self.assertEqual([(c["host"], c["url"], c["probe"], c["here"]) for c in at_localhost],
                         [("Mac mini", "http://127.0.0.1:8767/", "http://127.0.0.1:8767/", True),
                          ("iMac", "https://window.example.ts.net:8766/", "https://window.example.ts.net:8766/", False)])
        # Through tailscale serve the browser may be on another device: tailnet addresses only,
        # but this Mac's viewer is still asked on loopback.
        remote = candidates(apps, local_page=False)
        self.assertEqual([(c["url"], c["probe"]) for c in remote],
                         [("https://macmini.example.ts.net:8767/", "http://127.0.0.1:8767/"),
                          ("https://window.example.ts.net:8766/", "https://window.example.ts.net:8766/")])

    def test_a_viewer_without_a_usable_address_is_left_out(self):
        stale = app("http://127.0.0.1:8766/", peer=True, host="iMac", route="https://window.example.ts.net:8766/")
        stale["routes"][0]["stale"] = True
        apps = [stale, app("http://127.0.0.1:8767/")]  # this Mac's viewer is not published on the tailnet
        self.assertEqual([c["url"] for c in candidates(apps, local_page=True)], ["http://127.0.0.1:8767/"])
        self.assertEqual(candidates(apps, local_page=False), [])

    def test_a_viewer_is_recognised_by_its_command_line_too(self):
        hand_started = app("http://127.0.0.1:8899/", id="py-8899", process={"command": "python3 -m result_viewer serve --port 8899"})
        self.assertEqual([c["url"] for c in candidates([hand_started], local_page=True)], ["http://127.0.0.1:8899/"])


class FinderTests(unittest.TestCase):
    def setUp(self):
        self.fakes = []

    def tearDown(self):
        for fake in self.fakes:
            fake.close()

    def fake(self, fake):
        self.fakes.append(fake)
        return fake

    def finder(self, *apps, **options):
        dashboard = self.fake(_Fake({"/api/apps": (200, {"apps": list(apps)})}))
        return ResultViewerFinder(dashboard_urls=[dashboard.url], **options)

    def test_this_macs_viewer_wins_when_it_has_the_session(self):
        mine, theirs = self.fake(viewer(SID)), self.fake(viewer(SID))
        found = self.finder(app(theirs.url, peer=True, host="iMac", route=theirs.url), app(mine.url)).find(SID)
        self.assertEqual((found["url"], found["host"], found["here"]), (mine.url, "Mac mini", True))
        self.assertEqual(len(found["tried"]), 1)  # the other Mac is not asked

    def test_the_other_macs_viewer_when_this_ones_lacks_the_session_or_is_down(self):
        theirs = self.fake(viewer(SID))
        for mine_url in (self.fake(viewer("sub-Other_ses-2026_01_01")).url, f"http://127.0.0.1:{_free_port()}/"):
            found = self.finder(app(mine_url), app(theirs.url, peer=True, host="iMac", route=theirs.url)).find(SID)
            self.assertEqual((found["url"], found["host"], found["here"]), (theirs.url, "iMac", False))
            self.assertIn(found["tried"][0]["state"], ("lacks", "down"))

    def test_no_viewer_with_the_session_is_an_error_naming_each(self):
        mine, theirs = self.fake(viewer()), self.fake(viewer())
        found = self.finder(app(mine.url), app(theirs.url, peer=True, host="iMac", route=theirs.url)).find(SID)
        self.assertIsNone(found["url"])
        self.assertIn("Mac mini does not list it", found["error"])
        self.assertIn("iMac does not list it", found["error"])

    def test_a_viewer_that_answers_without_a_session_list_still_counts(self):
        mine = self.fake(_Fake({"/api/sessions": (403, {"error": "owner only"})}))
        self.assertEqual(self.finder(app(mine.url)).find(SID)["url"], mine.url)

    def test_a_viewer_slow_to_list_its_sessions_is_busy_not_down(self):
        mine = self.fake(_Fake({"/api/sessions": (200, {"sessions": []})}, delay=1.0))
        theirs = self.fake(viewer(SID))
        found = self.finder(app(mine.url), app(theirs.url, peer=True, host="iMac", route=theirs.url),
                            probe_timeout=0.3).find(SID)
        self.assertEqual((found["url"], found["tried"][0]["state"]), (mine.url, "unknown"))

    def test_this_servers_own_port_is_not_taken_for_a_dashboard(self):
        mine = self.fake(viewer(SID))
        own = self.fake(_Fake({"/api/apps": (200, {"apps": []})}))  # would hide the real dashboard
        dashboard = self.fake(_Fake({"/api/apps": (200, {"apps": [app(mine.url)]})}))
        finder = ResultViewerFinder(dashboard_urls=[own.url, dashboard.url])
        self.assertEqual(finder.find(SID, own_port=own.server.server_address[1])["url"], mine.url)

    def test_an_explicit_url_replaces_the_lookup(self):
        mine = self.fake(viewer(SID))
        finder = ResultViewerFinder(url=mine.url, dashboard_urls=[f"http://127.0.0.1:{_free_port()}"])
        self.assertEqual(finder.find(SID)["url"], mine.url)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.viewer = viewer(SID)
        self.dashboard = _Fake({"/api/apps": (200, {"apps": [app(self.viewer.url, route="https://node.example.ts.net:8767/")]})})
        store = SessionStore([], [], Path(self.temp.name) / "cache")
        self.app = Application(store, result_viewer=ResultViewerFinder(dashboard_urls=[self.dashboard.url]))
        self.server = make_server(self.app, port=0, tailnet_origin="https://node.example.ts.net")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.close()
        self.viewer.close()
        self.dashboard.close()
        self.temp.cleanup()

    def get(self, path, host=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        connection.request("GET", path, headers={"Host": host} if host else {})
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        return response.status, body

    def test_a_localhost_page_gets_loopback_and_a_tailnet_page_the_tailnet_address(self):
        status, body = self.get(f"/api/result_viewer?session={SID}")
        self.assertEqual((status, body["url"], body["here"]), (200, self.viewer.url, True))
        status, body = self.get(f"/api/result_viewer?session={SID}", host="node.example.ts.net")
        self.assertEqual((status, body["url"]), (200, "https://node.example.ts.net:8767/"))

    def test_the_session_is_required(self):
        self.assertEqual(self.get("/api/result_viewer")[0], 400)


if __name__ == "__main__":
    unittest.main()
