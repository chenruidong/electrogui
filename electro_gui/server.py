"""Loopback server and bounded asynchronous computation queue."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import gzip
import hmac
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from . import __version__
from .data import SessionStore
from .exports import export_csv, export_json, export_membership, export_statistics, export_svg
from .annotations import annotate_result
from .preview import preview
from . import explorer


class Application:
    def __init__(self, store: SessionStore, views_path: str | Path | None = None):
        self.store = store
        self.views_path = Path(views_path).expanduser() if views_path is not None else None
        self.views_lock = threading.Lock()
        self.jobs = OrderedDict()
        self.preview_jobs = OrderedDict()
        self.lock = threading.RLock()
        self.store_lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="electro-compute")
        self.preview_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="electro-preview")

    def submit(self, request):
        action = request.get("action")
        if action not in ("load", "unit", "population", "preview", "annotate", "stable_selection"):
            raise ValueError("Action must be load, unit, population, preview, annotate, or stable_selection.")
        if action == "annotate":
            base_id = request.get("completed_job_id", request.get("job_id"))
            with self.lock:
                base = self.jobs.get(base_id)
            if not base or base.get("status") != "done" or base.get("result", {}).get("kind") not in ("unit", "population"):
                raise ValueError("Annotate requires a completed unit or population job.")
            # Retain the completed snapshot while the annotation job is queued;
            # preview eviction must never make an exportable result disappear.
            base_session = base["result"].get("session_id")
            if request.get("session_id") is not None and request.get("session_id") != base_session:
                raise ValueError("Annotation session_id must match the completed result session.")
            request = dict(request, session_id=base_session, _base_result=base["result"])
        if not isinstance(request.get("session_id"), str):
            raise ValueError("Select a session before computing.")
        target = self.preview_jobs if action == "preview" else self.jobs
        with self.lock:
            if sum(j["status"] in ("queued", "running") for j in target.values()) >= (2 if action == "preview" else 4):
                raise ValueError("Four computations are already pending; wait for them to finish.")
            # Preview entries have their own bounded store and never evict exportable results.
            while len(target) >= (8 if action == "preview" else 12):
                # Keep each workspace's most recent completed result even if
                # the other workspace performs many display-only updates.
                latest = {}
                if target is self.jobs:
                    for key, completed in target.items():
                        kind = completed.get("result", {}).get("kind")
                        if completed["status"] == "done" and kind in ("unit", "population"):
                            latest[kind] = key
                protected = set(latest.values())
                oldest = next((k for k, j in target.items() if j["status"] in ("done", "error") and k not in protected), None)
                if oldest is None:
                    break
                del target[oldest]
            job_id = uuid4().hex
            target[job_id] = {"id": job_id, "status": "queued", "message": "Waiting for the local computation worker."}
        if action == "preview":
            self.preview_executor.submit(self._run_preview, job_id, request)
        else:
            self.executor.submit(self._run, job_id, request)
        return {"id": job_id}

    def _run(self, job_id, request):
        start = time.monotonic()
        with self.lock:
            job = self.jobs[job_id]
            job.update(status="running", message="Loading and verifying the assembled NWB; the first load reads its complete fingerprint.")
        self.store_lock.acquire()
        try:
            loaded = self.store.get(request["session_id"])
            if request["action"] == "load":
                result = loaded.metadata()
            elif request["action"] == "stable_selection":
                from .selection import select_stable_population
                with self.lock:
                    job["message"] = "Selecting SUA/MUA units for shared stable neuron × trial coverage."
                result = select_stable_population(loaded)
            elif request["action"] == "annotate":
                base_result = request.get("_base_result")
                if not isinstance(base_result, dict) or base_result.get("session_id") != loaded.session_id:
                    raise ValueError("Annotation source session does not match the completed result.")
                base_sha = base_result.get("provenance", {}).get("computation_identity", {}).get("source_nwb", {}).get("sha256")
                current_sha = loaded.session.source_identity().get("sha256")
                if base_sha and current_sha and base_sha != current_sha:
                    raise ValueError("Annotation source NWB changed since the completed result; recompute before annotating.")
                from imitation_phys.derived_cache import computation_identity, cache_key
                package = Path(__file__).resolve().parent
                annotation_parameters = {"layers": request.get("layers", []),
                                         "base_computation_key": base_result.get("provenance", {}).get("computation_key")}
                annotation_code = [package / name for name in ("annotations.py", "exports.py", "server.py")]
                identity = computation_identity(kind="electro_gui_annotations", schema=1,
                                                source=loaded.session.source_identity(), parameters=annotation_parameters,
                                                code_paths=annotation_code)
                result = annotate_result(base_result, loaded, request.get("layers", []))
                after = computation_identity(kind="electro_gui_annotations", schema=1,
                                             source=loaded.session.source_identity(), parameters=annotation_parameters,
                                             code_paths=annotation_code)
                if identity != after:
                    raise RuntimeError("Annotation source or code changed while running; retry the annotation update.")
                result.setdefault("provenance", {}).update(annotation_job=job_id, source_path=str(loaded.session.path),
                                                          annotation_identity=identity, annotation_key=cache_key(identity))
            else:
                from imitation_phys.derived_cache import computation_identity, cache_key
                from .analysis import compute_unit
                from .population import compute_population
                package = Path(__file__).resolve().parent
                repo = package.parent
                code = list(package.rglob("*.py")) + list((repo / "imitation_phys").rglob("*.py"))
                code += list(getattr(loaded, "code_paths", []))
                identity = computation_identity(kind=f"electro_gui_{request['action']}", schema=1,
                                                source=loaded.session.source_identity(), parameters=request, code_paths=code)
                with self.lock:
                    job["message"] = "Computing eligibility, event selection and numerical results from the selected session."
                result = (compute_unit if request["action"] == "unit" else compute_population)(loaded, request)
                after = computation_identity(kind=f"electro_gui_{request['action']}", schema=1,
                                             source=loaded.session.source_identity(), parameters=request, code_paths=code)
                if identity != after:
                    raise RuntimeError("Computation code changed while running; retry using the current code.")
                provenance = result.setdefault("provenance", {})
                provenance.update(version=__version__, source_path=str(loaded.session.path),
                                  computation_identity=identity, computation_key=cache_key(identity),
                                  upstream_freshness="not audited; exact assembled NWB is the empirical source",
                                  repository=_git_identity(repo))
            # Reject nonfinite / unserializable payloads before claiming completion.
            json.dumps(result, allow_nan=False)
            with self.lock:
                job.update(status="done", message=f"Completed in {time.monotonic() - start:.1f} s.", result=result)
        except Exception as exc:
            with self.lock:
                job.update(status="error", message="Computation stopped.", error=f"{type(exc).__name__}: {exc}")
        finally:
            self.store_lock.release()

    def _run_preview(self, job_id, request):
        start = time.monotonic()
        with self.lock:
            job = self.preview_jobs[job_id]
            job.update(status="running", message="Preparing selection support; no spikes, counts, fits, or tests are computed.")
        self.store_lock.acquire()
        try:
            loaded = self.store.get(request["session_id"])
            result = preview(loaded, request)
            result.setdefault("provenance", {}).update(source_identity=loaded.session.source_identity(), source_path=str(loaded.session.path))
            with self.lock:
                job.update(status="done", message=f"Preview ready in {time.monotonic() - start:.1f} s.", result=result)
        except Exception as exc:
            with self.lock:
                job.update(status="error", message="Preview stopped.", error=f"{type(exc).__name__}: {exc}")
        finally:
            self.store_lock.release()

    def explore(self, what, query):
        """Synchronous explorer reads; the session must load first (a ``load`` job)."""
        def one(name, default=None):
            value = query.get(name, [default])[0]
            if value is None:
                raise ValueError(f"Missing query parameter {name!r}.")
            return value
        with self.store_lock:
            loaded = self.store.get(one("session"))
            if what == "session":
                return explorer.session_summary(loaded)
            if what == "table":
                return explorer.alignment_table(loaded, one("alignment"))
            if what == "raster":
                try:
                    unit = int(one("unit"))
                except ValueError:
                    raise ValueError("unit must be an integer ID") from None
                policy = one("policy", "verified_stable")
                if policy not in ("verified_stable", "all_complete"):
                    raise ValueError("policy must be verified_stable or all_complete")
                return explorer.unit_raster(loaded, one("alignment"), unit, policy, one("lo"), one("hi"))
            if what == "events":
                return explorer.event_times(loaded, one("event"))
            if what == "popspans":
                try:
                    ids = [int(x) for x in one("units").split(",") if x.strip()]
                except ValueError:
                    raise ValueError("units must be comma-separated integer IDs") from None
                policy = one("policy", "verified_stable")
                if policy not in ("verified_stable", "all_complete"):
                    raise ValueError("policy must be verified_stable or all_complete")
                return explorer.population_spans(loaded, one("alignment"), ids, policy)
            if what == "stability":
                return explorer.stability_masks(loaded)
            if what == "stable_roster":
                from .selection import select_stable_population
                return select_stable_population(loaded)
        raise KeyError("Unknown explorer endpoint")

    def population_fit(self, request):
        with self.store_lock:
            loaded = self.store.get(request.get("session_id"))
            return explorer.population_fit(loaded, request)

    def population_probe(self, request):
        with self.store_lock:
            loaded = self.store.get(request.get("session_id"))
            return explorer.population_probe(loaded, request)

    def views(self, update=None):
        """Named explorer views shared by every device that opens this server."""
        if self.views_path is None:
            raise ValueError("Saved views are disabled (no --views-file).")
        with self.views_lock:
            try:
                views = json.loads(self.views_path.read_text())
            except FileNotFoundError:
                views = {}
            if not isinstance(views, dict):
                raise ValueError(f"{self.views_path} is not a JSON object of saved views.")
            if update is None:
                return views
            name = update.get("name")
            if not isinstance(name, str) or not name.strip() or len(name) > 120:
                raise ValueError("A saved view needs a name of 1-120 characters.")
            if update.get("delete"):
                views.pop(name.strip(), None)
            else:
                if not isinstance(update.get("state"), dict):
                    raise ValueError("A saved view needs a state object.")
                views[name.strip()] = {"state": update["state"], "saved": time.strftime("%Y-%m-%d %H:%M")}
            self.views_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.views_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(views, indent=1, sort_keys=True))
            os.replace(tmp, self.views_path)
            return views

    def snapshot(self, job_id):
        with self.lock:
            if job_id in self.jobs:
                return dict(self.jobs[job_id])
            if job_id in self.preview_jobs:
                return dict(self.preview_jobs[job_id])
            raise KeyError(job_id)

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.preview_executor.shutdown(wait=True, cancel_futures=True)


def _git_identity(repo):
    def run(*args):
        try:
            return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=3, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain", "--untracked-files=no"))}


LOOPBACK = ("127.0.0.1", "localhost", "::1")
_COMPRESSIBLE = ("application/json", "text/", "application/javascript", "image/svg+xml")


def make_server(application, host="127.0.0.1", port=8765, token=None):
    """Serve on ``host``.  Any non-loopback host requires ``token``.

    On loopback the Host header must be local (DNS-rebinding guard).  With a
    token, a request is served only when it carries ``?token=`` (which also
    sets a same-site cookie) or that cookie, so a phone or tablet on the LAN
    can open the printed URL once and then browse normally.
    """
    if host not in LOOPBACK and not token:
        raise ValueError("A non-loopback --host requires an access token.")
    static = Path(__file__).resolve().parent / "static"

    class Handler(BaseHTTPRequestHandler):
        _set_cookie = False

        def _send(self, body, status=200, content_type="application/json; charset=utf-8", filename=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, allow_nan=False, separators=(",", ":")).encode()
            gzipped = (len(body) > 1400 and content_type.startswith(_COMPRESSIBLE)
                       and "gzip" in self.headers.get("Accept-Encoding", ""))
            if gzipped:
                body = gzip.compress(body, compresslevel=5)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if gzipped:
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
            if self._set_cookie:
                self.send_header("Set-Cookie", f"electro_token={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _local_request(self):
            # A local tool must not be callable by arbitrary websites/DNS rebinding.
            if token:
                offered = parse_qs(urlsplit(self.path).query).get("token", [None])[0]
                cookie = SimpleCookie(self.headers.get("Cookie", "")).get("electro_token")
                if offered and hmac.compare_digest(offered, token):
                    self._set_cookie = True
                elif not (cookie and hmac.compare_digest(cookie.value, token)):
                    self._send({"error": "Open the URL with ?token=... printed by the launcher."}, 403)
                    return False
            else:
                authority = urlsplit("http://" + self.headers.get("Host", "")).hostname
                if authority not in LOOPBACK:
                    self._send({"error": "Local Host header required."}, 403)
                    return False
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + self.headers.get("Host"):
                self._send({"error": "Same-origin requests required."}, 403)
                return False
            return True

        def do_GET(self):
            if not self._local_request():
                return
            url = urlsplit(self.path)
            try:
                if url.path == "/api/catalog":
                    sessions = application.store.catalog()
                    self._send({"version": __version__, "sessions": sessions,
                                "default_session": sessions[0]["id"] if sessions else None})
                elif url.path.startswith("/api/explorer/"):
                    self._send(application.explore(url.path.rsplit("/", 1)[1], parse_qs(url.query)))
                elif url.path == "/api/views":
                    self._send(application.views())
                elif url.path.startswith("/api/jobs/"):
                    parts = url.path.strip("/").split("/")
                    if len(parts) not in (3, 4):
                        raise KeyError("Unknown job endpoint")
                    job = application.snapshot(parts[2])
                    if len(parts) == 3:
                        self._send(job)
                    elif parts[3] == "export":
                        if job["status"] != "done" or job["result"].get("kind") not in ("unit", "population"):
                            raise ValueError("An analysis must complete before export.")
                        query = parse_qs(url.query)
                        fmt = query.get("format", ["json"])[0]
                        if fmt not in ("json", "csv", "svg", "membership", "stats"):
                            raise ValueError("Export format must be json, csv, svg, membership, or stats.")
                        result = job["result"]
                        if fmt == "svg":
                            axes = tuple(int(query.get(a, [str(i)])[0]) for i, a in enumerate(("x", "y")))
                            payload = export_svg(result, axes)
                        else:
                            payload = {"json": export_json, "csv": export_csv, "membership": export_membership, "stats": export_statistics}[fmt](result)
                        ext = "csv" if fmt in ("membership", "stats") else fmt
                        mime = {"json": "application/json", "csv": "text/csv", "svg": "image/svg+xml"}[ext]
                        self._send(payload, content_type=mime, filename=f"electro_gui_{result['kind']}_{parts[2][:8]}_{fmt}.{ext}")
                    else:
                        raise KeyError("Unknown job endpoint")
                elif url.path.startswith("/api/"):
                    raise KeyError("Unknown API endpoint")
                else:
                    relative = url.path.lstrip("/")
                    if relative == "" or relative.endswith("/"):
                        relative += "index.html"
                    path = (static / relative).resolve()
                    if not path.is_relative_to(static.resolve()) or not path.is_file():
                        raise KeyError("Unknown file")
                    self._send(path.read_bytes(), content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            except KeyError as exc:
                self._send({"error": str(exc)}, 404)
            except (ValueError, OSError) as exc:
                self._send({"error": str(exc)}, 400)

        def do_POST(self):
            if not self._local_request():
                return
            try:
                route = urlsplit(self.path).path
                if route not in ("/api/jobs", "/api/views", "/api/explorer/popfit", "/api/explorer/popprobe"):
                    self._send({"error": "Unknown endpoint"}, 404)
                    return
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("JSON request required.")
                length = int(self.headers.get("Content-Length", "0"))
                limit = 8 * 1048576 if route.startswith("/api/explorer/pop") else 262144
                if not 0 < length <= limit:
                    raise ValueError(f"Request must be between 1 byte and {limit // 1024} KiB.")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError("Request must be a JSON object.")
                if route == "/api/views":
                    self._send(application.views(request))
                    return
                if route == "/api/explorer/popfit":
                    self._send(application.population_fit(request))
                    return
                if route == "/api/explorer/popprobe":
                    self._send(application.population_probe(request))
                    return
                self._send(application.submit(request), 202)
            except KeyError as exc:
                self._send({"error": str(exc).strip("'\"")}, 404)
            except (ValueError, TypeError) as exc:
                self._send({"error": str(exc)}, 400)

        def log_message(self, fmt, *args):
            # Polling is intentionally quiet. The UI reports progress and errors.
            pass

    return ThreadingHTTPServer((host, port), Handler)
