"""Find a result-viewer (github.com/chenruidong/result-viewer) to open the unit in view.

result-viewer opens a unit from its address bar, ``<base>/#s=<session>&u=<unit>``,
and applies a new one in place when its tab already shows it, so the page only
needs a base URL; it builds the fragment itself.  Which result-viewer:

* **Finding them.**  This Mac's apps dashboard (github.com/chenruidong/apps-dashboard)
  lists the apps of this Mac (``peer: false``) and of its peer Macs, each with its
  loopback URL and the ``tailscale serve`` routes in front of it, so a
  result-viewer on any port of either Mac is found.  The dashboard listens on
  8790, or on 8797 where electro_gui has 8790 (the Mac mini); this server's own
  port is skipped.  Without a dashboard, result-viewer's default
  ``http://127.0.0.1:8766`` is tried.
* **Which one.**  This Mac's first, then a peer's.  A page opened at localhost
  gets this Mac's loopback URL; any other page (through ``tailscale serve``, or
  a LAN address) gets a tailnet address, which is the only kind a peer's
  result-viewer has.
* **Available.**  A result-viewer counts when it answers and its
  ``/api/sessions`` lists the session (each Mac reads its own results drive);
  one that answers without saying which sessions it has counts too.
"""
from __future__ import annotations

import json
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

DASHBOARD_URLS = ("http://127.0.0.1:8790", "http://127.0.0.1:8797")
FALLBACK_URL = "http://127.0.0.1:8766"
LOOPBACK = ("127.0.0.1", "localhost", "::1")
_RUNS_RESULT_VIEWER = re.compile(r"(?:^|\s)-m\s+result_viewer(?:\s|$)|(?:^|/)rv(?:\s|$)")


def _endpoint(base_url, path):
    parts = urlsplit(base_url)
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _loopback_port(url):
    """The port of an ``http://<loopback>:<port>`` URL, else None."""
    try:
        parts = urlsplit(url or "")
        port = parts.port
    except ValueError:
        return None
    return port if parts.scheme == "http" and parts.hostname in LOOPBACK and port else None


def dashboard_apps(dashboard_urls, own_port=None, timeout=3.0):
    """``apps`` from the first dashboard that answers ``/api/apps``, or None.

    A loopback URL on ``own_port`` is this server, not a dashboard, and is skipped.
    """
    for url in dashboard_urls:
        if not url or (own_port and _loopback_port(url) == own_port):
            continue
        try:
            with urllib.request.urlopen(_endpoint(url, "/api/apps"), timeout=timeout) as resp:
                apps = json.load(resp).get("apps")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(apps, list):
            return apps
    return None


def _is_result_viewer(app):
    process = app.get("process") or {}
    commands = (process.get("command"), (app.get("launchd") or {}).get("program"))
    return app.get("id") == "result-viewer" or any(_RUNS_RESULT_VIEWER.search(c or "") for c in commands)


def _routes(app):
    """Tailnet addresses (``tailscale serve`` proxies) in front of ``app``, freshest first."""
    port = _loopback_port((app.get("local") or {}).get("url"))
    out = []
    for route in app.get("routes") or ():
        if not isinstance(route, dict) or route.get("kind") != "proxy" or route.get("stale") or not route.get("url"):
            continue
        if port and _loopback_port(route.get("target")) not in (None, port):
            continue
        out.append(route["url"])
    return out


def candidates(apps, local_page):
    """Result-viewers from the dashboard's ``apps``, in the order they are tried.

    Each is ``{"url", "probe", "host", "here"}``: ``url`` is what the page opens,
    ``probe`` what this server asks whether it is up.  This Mac's come first,
    then the peers'; within each, the ones the dashboard sees up.
    """
    found = []
    for app in apps if isinstance(apps, list) else ():
        if not isinstance(app, dict) or not _is_result_viewer(app):
            continue
        here = not app.get("peer")
        local = (app.get("local") or {}).get("url")
        routes = _routes(app)
        if here and _loopback_port(local):
            url = local if local_page else (routes[0] if routes else None)
            probe = local
        else:
            url = probe = routes[0] if routes else None
        if not url:
            continue
        host = app.get("host_label") or ("this Mac" if here else "another Mac")
        found.append(((not here, app.get("status") != "up"), {"url": url, "probe": probe, "host": host, "here": here}))
    found.sort(key=lambda x: x[0])
    out, seen = [], set()
    for _, c in found:
        if c["url"] not in seen:
            seen.add(c["url"])
            out.append(c)
    return out


def sessions_at(base_url, timeout=5.0):
    """``(up, sessions)`` for the result-viewer at ``base_url``.

    ``sessions`` is the set of session ids its ``/api/sessions`` lists, or None
    when it answers without one (an older or refusing server).  A proxy's
    502-504 (``tailscale serve`` with nothing behind it) or no connection means
    down; one that takes the request but is slow to answer is up (its session
    list reads the notebooks, which takes seconds now and then).
    """
    try:
        with urllib.request.urlopen(_endpoint(base_url, "/api/sessions"), timeout=timeout) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code not in (502, 503, 504), None
    except urllib.error.URLError:  # refused, unreachable, or no connection in time
        return False, None
    except socket.timeout:          # connected and asked, but no answer in time
        return True, None
    except OSError:
        return False, None
    except ValueError:
        return True, None
    listed = body.get("sessions") if isinstance(body, dict) else None
    if not isinstance(listed, list):
        return True, None
    return True, {s.get("id") if isinstance(s, dict) else s for s in listed}


class ResultViewerFinder:
    """Where the page should open a session in result-viewer (see the module docstring).

    ``url`` (``--result-viewer-url``) replaces the lookup.  Dashboard answers
    are kept for 10 s and each result-viewer's session list for 30 s (5 s when
    it did not answer), so the page can ask on every session change.
    """

    def __init__(self, url=None, dashboard_urls=DASHBOARD_URLS, fallback_url=FALLBACK_URL,
                 apps_ttl=10.0, sessions_ttl=30.0, probe_timeout=5.0):
        self.url = url or None
        self.dashboard_urls = [u for u in dashboard_urls or () if u]
        self.fallback_url = fallback_url
        self.apps_ttl, self.sessions_ttl, self.probe_timeout = apps_ttl, sessions_ttl, probe_timeout
        self._apps = None
        self._sessions = {}
        self._lock = threading.Lock()

    def _candidates(self, local_page, own_port):
        if self.url:
            return [{"url": self.url, "probe": self.url, "host": "--result-viewer-url",
                     "here": urlsplit(self.url).hostname in LOOPBACK}]
        now = time.monotonic()
        if self._apps is None or now - self._apps[0] > self.apps_ttl:
            self._apps = (now, dashboard_apps(self.dashboard_urls, own_port))
        apps = self._apps[1]
        if apps is not None:
            return candidates(apps, local_page)
        if self.fallback_url and local_page:
            return [{"url": self.fallback_url, "probe": self.fallback_url, "host": "this Mac", "here": True}]
        return []

    def _state(self, probe):
        # A result-viewer that did not answer is asked again sooner: it may just have been started.
        now = time.monotonic()
        cached = self._sessions.get(probe)
        if cached is None or now - cached[0] > (self.sessions_ttl if cached[1] else min(self.sessions_ttl, 5.0)):
            cached = (now, *sessions_at(probe, self.probe_timeout))
            self._sessions[probe] = cached
        return cached[1], cached[2]

    def find(self, session, local_page=True, own_port=None):
        """``{"url", "host", "here", "tried"}`` for ``session``; ``url`` is None (with ``error``) when none will do."""
        with self._lock:
            tried = []
            for c in self._candidates(local_page, own_port):
                up, sessions = self._state(c["probe"])
                state = "down" if not up else "unknown" if sessions is None else "has" if session in sessions else "lacks"
                tried.append({"host": c["host"], "url": c["url"], "here": c["here"], "state": state})
                if state in ("has", "unknown"):
                    return {"session": session, "url": c["url"], "host": c["host"], "here": c["here"], "tried": tried}
            if not tried:
                error = ("No result viewer found: the apps dashboard lists none"
                         + ("" if local_page else " with a tailnet address") + ".")
            elif any(t["state"] == "lacks" for t in tried):
                error = f"No result viewer has {session}: " + "; ".join(
                    f"{t['host']} {'does not list it' if t['state'] == 'lacks' else 'is not answering'}" for t in tried) + "."
            else:
                error = "No result viewer is answering (" + ", ".join(t["host"] for t in tried) + ")."
            return {"session": session, "url": None, "host": None, "here": None, "tried": tried, "error": error}
