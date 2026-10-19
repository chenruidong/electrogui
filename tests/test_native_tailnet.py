"""Exercise the private Serve boundary over real HTTP without experimental data."""
import argparse
import http.client
import json
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from electro_gui import cli
from electro_gui.server import make_server


class NativeTailnetTests(unittest.TestCase):
    origin = "https://macmini.tail62f972.ts.net:8443"

    def setUp(self):
        app = SimpleNamespace(store=SimpleNamespace(catalog=lambda: []))
        self.server = make_server(app, port=0, token="standalone-secret", tailnet_origin=self.origin)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, headers=(), method="GET", path="/api/catalog"):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.putrequest(method, path, skip_host=True)
        for key, value in headers:
            connection.putheader(key, value)
        if method == "POST":
            connection.putheader("Content-Length", "2")
        connection.endheaders(b"{}" if method == "POST" else None)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_shared_and_tagged_peers_need_no_browser_secret(self):
        for identity in ((), (("Tailscale-User-Login", "family@example.com"),)):
            headers = (("Host", self.origin[8:]),) + identity
            status, response_headers, body = self.request(headers)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["sessions"], [])
            self.assertNotIn("Set-Cookie", response_headers)
            self.assertNotIn(b"standalone-secret", body)
        local = (("Host", f"127.0.0.1:{self.server.server_port}"),)
        self.assertEqual(self.request(local)[0], 200)

    def test_wrong_hosts_duplicate_headers_and_local_remote_confusion_are_rejected(self):
        for headers in ((), (("Host", "evil.example"),),
                        (("Host", "macmini.tail62f972.ts.net:8444"),),
                        (("Host", self.origin[8:]), ("Host", self.origin[8:])),
                        (("Host", f"127.0.0.1:{self.server.server_port}"),
                         ("Tailscale-User-Login", "family@example.com"))):
            self.assertEqual(self.request(headers)[0], 403)

    def test_origin_validation_applies_before_posts_or_reads(self):
        host = (("Host", self.origin[8:]),)
        for origin in ("https://evil.example", "http://" + self.origin[8:]):
            for method in ("GET", "POST"):
                self.assertEqual(self.request(host + (("Origin", origin),), method)[0], 403)
        self.assertEqual(self.request(host + (("Origin", self.origin),))[0], 200)
        self.assertEqual(self.request(host + (("Origin", self.origin),), "POST", "/unknown")[0], 404)

    def test_duplicate_origins_and_forwarded_local_requests_are_rejected(self):
        remote = (("Host", self.origin[8:]),)
        self.assertEqual(self.request(remote + (("Origin", self.origin), ("Origin", self.origin)))[0], 403)
        local = (("Host", f"127.0.0.1:{self.server.server_port}"),)
        self.assertEqual(self.request(local + (("X-Forwarded-Host", self.origin[8:]),))[0], 403)

    def test_finder_action_remains_local_in_native_mode(self):
        # Retain main's newer Finder feature while keeping it unavailable remotely.
        host = (("Host", self.origin[8:]), ("Content-Type", "application/json"))
        with mock.patch("electro_gui.server._reveal_in_finder") as reveal:
            status, _, _ = self.request(host, "POST", "/api/findings/20261019T000000Z-abcdef/reveal")
        self.assertEqual(status, 400)
        reveal.assert_not_called()

    def test_owner_mode_remains_available_without_explicit_native_origin(self):
        tailnet = SimpleNamespace(names={"node.ts.net"}, owner="owner@example.com")
        app = SimpleNamespace(store=SimpleNamespace(catalog=lambda: []))
        other = make_server(app, port=0, token="standalone-secret", tailnet=tailnet)
        thread = threading.Thread(target=other.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(other.server_close)
        self.addCleanup(other.shutdown)
        for login, expected in (("owner@example.com", 200), ("shared@example.com", 403)):
            connection = http.client.HTTPConnection("127.0.0.1", other.server_port, timeout=5)
            connection.request("GET", "/api/catalog", headers={"Host": "node.ts.net", "Tailscale-User-Login": login})
            response = connection.getresponse()
            self.assertEqual(response.status, expected)
            response.read()
            connection.close()

    def test_cli_requires_a_choice_between_explicit_access_modes(self):
        parser = cli.add_arguments(argparse.ArgumentParser())
        self.assertEqual(parser.parse_args(["--tailnet-origin", self.origin]).tailnet_origin, self.origin)
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            parser.parse_args(["--tailnet-origin", self.origin, "--owner", "owner@example.com"])

    def test_native_ingress_is_explicit_and_cannot_listen_on_the_network(self):
        for host, origin in (("0.0.0.0", self.origin), ("127.0.0.1", "http://node.ts.net"),
                             ("127.0.0.1", self.origin + "/"),
                             ("127.0.0.1", "https://user@node.ts.net")):
            with self.assertRaises(ValueError):
                make_server(None, host=host, port=0, token="secret", tailnet_origin=origin)
