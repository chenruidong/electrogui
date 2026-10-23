"""The tailnet access log (electro_gui/accesslog.py, apps-dashboard's module): only a registered port logs.

No test writes ~/Library/Logs/tailnet-access: each one points TAILNET_ACCESS_LOG_DIR at a temporary folder.
"""
import argparse
import contextlib
from http.server import BaseHTTPRequestHandler
import http.client
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from electro_gui import accesslog, cli, server as server_module
from electro_gui.server import ACCESS_LOG_APPS, attach_access_log, make_server


class _App:
    """Application stand-in: no sessions, no jobs."""
    store = SimpleNamespace(catalog=lambda: [])

    def snapshot(self, job_id):
        raise KeyError("Unknown job")


class _Tailnet:
    """server.Tailnet stand-in: a fixed owner and MagicDNS name, no tailscale CLI."""
    owner, names = "owner@example.com", {"mac.tail.ts.net"}


class _BoundServer:
    """make_server stand-in bound to ``port``: serve_forever returns at once."""

    def __init__(self, port):
        self.server_address, self.restart_requested = ("127.0.0.1", port), False
        self.RequestHandlerClass = type("Handler", (BaseHTTPRequestHandler,), {})

    def serve_forever(self, poll_interval):
        pass

    def server_close(self):
        pass


class AccessLogTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = mock.patch.dict(os.environ, {accesslog.ENV_DIR: str(self.root), accesslog.ENV_SWITCH: ""})
        env.start()
        self.addCleanup(env.stop)

    def test_only_the_registered_ports_log_under_their_registry_ids(self):
        self.assertEqual(ACCESS_LOG_APPS, {8778: "electrogui", 8765: "electro_gui"})
        for port, app_id in ACCESS_LOG_APPS.items():
            server = _BoundServer(port)
            self.assertEqual(attach_access_log(server), app_id)
            log = server.RequestHandlerClass._access_log
            self.assertEqual((log.app_id, log.root), (app_id, self.root))
        for port in (8790, 8798, 43210):
            server = _BoundServer(port)
            self.assertIsNone(attach_access_log(server))
            self.assertFalse(hasattr(server.RequestHandlerClass, "_access_log"))
        real = make_server(_App(), port=0)  # what the tests use: never logged
        self.addCleanup(real.server_close)
        self.assertIsNone(attach_access_log(real))
        self.assertFalse(hasattr(real.RequestHandlerClass, "_access_log"))

    def test_cli_attaches_by_the_port_it_bound_not_the_one_asked_for(self):
        os.environ.pop(cli.RESTART_ENV, None)
        for bound, logged in ((8778, "electrogui"), (8765, "electro_gui"), (43210, None)):
            server = _BoundServer(bound)
            args = cli.add_arguments(argparse.ArgumentParser()).parse_args(
                ["--data-root", str(self.root), "--cache-dir", str(self.root), "--findings-dir", str(self.root / "f"),
                 "--port", "8778", "--no-browser"])
            with mock.patch("electro_gui.server.make_server", return_value=server), \
                    contextlib.redirect_stdout(io.StringIO()):
                cli.run(args)
            log = getattr(server.RequestHandlerClass, "_access_log", None)
            self.assertEqual(log and log.app_id, logged)

    def test_a_logged_server_still_answers_and_records_route_classes_only(self):
        server = make_server(_App(), port=0, tailnet=_Tailnet())
        port = server.server_address[1]
        with mock.patch.dict(server_module.ACCESS_LOG_APPS, {port: "electrogui"}, clear=True):
            self.assertEqual(attach_access_log(server), "electrogui")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        job = "0123456789abcdef0123456789abcdef"
        tailnet = {"Host": "mac.tail.ts.net", "Tailscale-User-Login": "owner@example.com",
                   "X-Forwarded-For": "100.101.102.103"}
        requests = [("/api/health", {}), ("/api/catalog", tailnet), (f"/api/jobs/{job}", {}),
                    (f"/api/jobs/{job}/export?format=csv", {}), ("/", {}), ("/nope.php?q=secret", {})]
        answers = []
        try:
            for path, headers in requests:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                connection.request("GET", path, headers=headers)
                response = connection.getresponse()
                answers.append((response.status, response.read()))
                connection.close()
        finally:
            server.shutdown()
            server.server_close()  # joins the request threads, so every line is written
            thread.join(5)
        self.assertEqual([status for status, _ in answers], [200, 200, 404, 404, 200, 404])
        self.assertEqual(json.loads(answers[0][1])["boot"], server_module.BOOT_ID)
        self.assertEqual(json.loads(answers[1][1])["sessions"], [])
        days = sorted((self.root / "electrogui").glob("*.jsonl"))
        lines = [line for day in days for line in day.read_text().splitlines()]
        events = [json.loads(line) for line in lines]
        self.assertEqual([(e["route"], e["status"], e["via"]) for e in events],
                         [("health", 200, "local"), ("api.catalog", 200, "serve"), ("api.jobs.poll", 404, "local"),
                          ("api.jobs.export", 404, "local"), ("page", 200, "local"), ("other", 404, "local")])
        self.assertEqual((events[1]["login"], events[1]["ip"]), ("owner@example.com", "100.101.102.103"))
        self.assertFalse(any(job in line or "secret" in line or "nope" in line for line in lines))
        self.assertTrue((self.root / "electrogui" / "status.json").is_file())


if __name__ == "__main__":
    unittest.main()
