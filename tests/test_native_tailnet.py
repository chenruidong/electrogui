"""Exercise the private Serve boundary over real HTTP without experimental data."""
import http.client
import json
import threading
import unittest
from types import SimpleNamespace

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

    def test_native_ingress_is_explicit_and_cannot_listen_on_the_network(self):
        for host, origin in (("0.0.0.0", self.origin), ("127.0.0.1", "http://node.ts.net"),
                             ("127.0.0.1", self.origin + "/"),
                             ("127.0.0.1", "https://user@node.ts.net")):
            with self.assertRaises(ValueError):
                make_server(None, host=host, port=0, token="secret", tailnet_origin=origin)
