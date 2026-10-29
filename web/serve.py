#!/usr/bin/env python3
"""Serve the local QUEST trace workspace without starting an evaluation."""
import argparse
import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

STATUS_ROUTE = "/api/workspace-status"
_status_lock = threading.Lock()
_status_cache = {}


def _count_cases(data, stopped=False):
    counts = {"total": 0, "pass": 0, "fail": 0, "running": 0, "stopped": 0, "error": 0}
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, list):
        return counts
    for case in cases:
        if not isinstance(case, dict):
            continue
        counts["total"] += 1
        if case.get("inProgress"):
            counts["stopped" if stopped else "running"] += 1
        elif case.get("correct") is True:
            counts["pass"] += 1
        elif case.get("correct") is False:
            counts["fail"] += 1
        else:
            counts["error"] += 1
    return counts


def _dataset_status(site, item):
    raw_path = item.get("data") or f"datasets/{item.get('id')}/traces.json"
    path = (site / raw_path).resolve()
    try:
        path.relative_to(site)
    except ValueError:
        return None
    if not path.is_file():
        return None
    override_stopped = item.get("lifecycleOverride") == "stopped"
    stat = path.stat()
    cache_key = (stat.st_mtime_ns, stat.st_size, override_stopped)
    cache_name = str(path)
    with _status_lock:
        cached = _status_cache.get(cache_name)
        if cached and cached.get("key") == cache_key:
            return cached["counts"]
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            _status_cache.pop(cache_name, None)
            return None
        run = data.get("run") if isinstance(data, dict) else {}
        stopped = override_stopped or bool(run.get("stopped")) if isinstance(run, dict) else override_stopped
        counts = _count_cases(data, stopped)
        _status_cache[cache_name] = {"key": cache_key, "counts": counts}
        return counts


def build_workspace_status(site):
    manifest = site / "datasets" / "index.json"
    try:
        payload = json.loads(manifest.read_text())
    except (OSError, ValueError):
        return {"generatedAt": int(time.time()), "datasets": {}}
    datasets = {}
    for item in payload.get("datasets", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        counts = _dataset_status(site, item)
        if counts is not None:
            datasets[item["id"]] = counts
    return {"generatedAt": int(time.time()), "datasets": datasets}


class ViewerRequestHandler(SimpleHTTPRequestHandler):
    site = None

    def do_GET(self):
        if urlsplit(self.path).path == STATUS_ROUTE:
            try:
                payload = build_workspace_status(self.site)
                body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            except Exception:
                self.send_error(500, "Unable to build workspace status")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=6080)
    args = parser.parse_args()
    site = (Path(__file__).resolve().parent / 'trace-viewer').resolve()
    if not site.is_dir():
        raise SystemExit(f'Viewer directory not found: {site}')
    ViewerRequestHandler.site = site
    handler = partial(ViewerRequestHandler, directory=str(site))
    with ThreadingHTTPServer((args.host, args.port), handler) as server:
        print(f'Trace viewer: http://{args.host}:{server.server_port}/trace-viewer-zh/', flush=True)
        print(f'Workspace status: http://{args.host}:{server.server_port}{STATUS_ROUTE}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
