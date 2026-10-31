"""Bounded, server-side Prometheus scrape for configured vLLM replicas."""

import asyncio
import json
import math
import os
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

SINGLE = {
    "num_requests_running",
    "num_requests_waiting",
    "kv_cache_usage_perc",
    "prompt_tokens_total",
    "generation_tokens_total",
    "prefix_cache_queries_total",
    "prefix_cache_hits_total",
    "num_preemptions_total",
    "request_success_total",
    "spec_decode_num_draft_tokens_total",
    "spec_decode_num_accepted_tokens_total",
    "simple_kv_offload_used_blocks",
    "simple_kv_offload_pending_store_blocks",
    "simple_kv_offload_load_blocks_total",
}
HISTOGRAMS = {
    "time_to_first_token_seconds",
    "request_queue_time_seconds",
    "request_prefill_time_seconds",
    "request_decode_time_seconds",
    "e2e_request_latency_seconds",
    "inter_token_latency_seconds",
}
LINE = re.compile(r"^vllm:([a-zA-Z0-9_:]+)(?:\{([^}]*)\})?\s+([^\s]+)")
LABEL = re.compile(r'(\w+)="((?:\\.|[^"\\])*)"')


# Inspect only local processes and existing outbound SSH sessions; no subnet scan.
_DISCOVERY_LOCK = threading.Lock()
_DISCOVERY_CACHE = {"until": 0.0, "endpoints": [], "warnings": []}
_REMOTE_DISCOVERY = r"""
import json, os
from pathlib import Path
rows=[]
for p in Path('/proc').iterdir():
 if not p.name.isdigit(): continue
 try:
  a=p.joinpath('cmdline').read_bytes().decode(errors='replace').split('\0'); s=' '.join(a)
  if not ('vllm.entrypoints.openai.api_server' in a or ('serve' in a and any(Path(x).name == 'vllm' for x in a[:3]))): continue
  port=next((int(x.split('=',1)[1]) if '=' in x else int(a[i+1]) for i,x in enumerate(a) if x=='--port' or x.startswith('--port=')),8000)
  rows.append({'port':port})
 except (OSError,ValueError,IndexError): pass
print(json.dumps(rows))
"""


def _processes():
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            argv = p.joinpath("cmdline").read_bytes().decode(errors="replace").rstrip("\0").split("\0")
            if argv and argv[0]:
                yield p, argv
        except OSError:
            continue


def _option(argv, name, default=None):
    for i, arg in enumerate(argv):
        if arg == name and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return default


def _local_endpoints(processes):
    result = []
    for proc, args in processes:
        if not (
            "vllm.entrypoints.openai.api_server" in args
            or ("serve" in args and any(Path(x).name == "vllm" for x in args[:3]))
        ):
            continue
        try:
            port = int(_option(args, "--port", "8000"))
            if not 1 <= port <= 65535:
                continue
            env = proc.joinpath("environ").read_bytes().split(b"\0")
            gpu = next(
                (
                    x.split(b"=", 1)[1].decode(errors="replace")
                    for x in env
                    if x.startswith(b"CUDA_VISIBLE_DEVICES=")
                ),
                None,
            )
            result.append({"server": "本机", "gpu": gpu or "自动", "role": "vLLM", "port": port})
        except (OSError, ValueError):
            continue
    return result


def _ssh_sessions(processes):
    sessions = {}
    for _, args in processes:
        if Path(args[0]).name != "ssh":
            continue
        # Reuse existing forward or interactive sessions; never accept API-provided hosts.
        destination = args[-1]
        if "-N" not in args and "@" not in destination:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.@-]+", destination) or destination.startswith("-"):
            continue
        port = _option(args, "-p", "22")
        identity = _option(args, "-i")
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            continue
        options = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=3",
            "-o",
            "StrictHostKeyChecking=yes",
            "-p",
            port,
        ]
        if identity:
            options += ["-i", identity, "-o", "IdentitiesOnly=yes"]
        options.append(destination)
        forwards = {}
        for i, arg in enumerate(args):
            if arg == "-L" and i + 1 < len(args):
                parts = args[i + 1].split(":")
                if (
                    len(parts) == 4
                    and parts[0] in ("127.0.0.1", "localhost")
                    and parts[2] in ("127.0.0.1", "localhost")
                ):
                    try:
                        forwards[int(parts[3])] = int(parts[1])
                    except ValueError:
                        pass
        sessions[(destination, port, identity)] = (options, forwards)
    return sessions


def _remote_discover(options):
    command = "PATH=/root/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:$PATH python3 -c " + shlex.quote(
        _REMOTE_DISCOVERY
    )
    out = subprocess.run(options + [command], capture_output=True, text=True, timeout=5, check=True)
    rows = json.loads(out.stdout)
    if not isinstance(rows, list):
        raise ValueError("invalid remote result")
    return [
        int(r["port"])
        for r in rows
        if isinstance(r, dict) and isinstance(r.get("port"), int) and 1 <= r["port"] <= 65535
    ][:32]


def endpoints():
    """Discover local/SSH vLLM processes, with optional explicit loopback endpoints."""
    with _DISCOVERY_LOCK:
        now = time.monotonic()
        if now < _DISCOVERY_CACHE["until"]:
            return _DISCOVERY_CACHE["endpoints"], _DISCOVERY_CACHE["warnings"]
        processes = list(_processes())
        found = _local_endpoints(processes)
        warnings = []
        for (host, ssh_port, _), (options, forwards) in _ssh_sessions(processes).items():
            try:
                ports = _remote_discover(options)
                for port in ports:
                    endpoint = {
                        "server": f"SSH {host}:{ssh_port}",
                        "gpu": "远端",
                        "role": "vLLM",
                        "port": port,
                    }
                    if port in forwards:
                        endpoint["_local_port"] = forwards[port]
                    else:
                        endpoint["_ssh"] = options
                    found.append(endpoint)
            except (OSError, subprocess.SubprocessError, ValueError, KeyError, json.JSONDecodeError):
                warnings.append(f"SSH {host}:{ssh_port} 自动发现失败")
        configured = os.getenv("VIEWER_VLLM_ENDPOINTS")
        if configured:
            extra = json.loads(configured)
            if not isinstance(extra, list) or len(extra) > 32:
                raise ValueError("Invalid vLLM endpoint configuration")
            for entry in extra:
                if (
                    not isinstance(entry, dict)
                    or not isinstance(entry.get("port"), int)
                    or not 1 <= entry["port"] <= 65535
                ):
                    raise ValueError("Invalid vLLM endpoint configuration")
                found.append({key: entry.get(key) for key in ("server", "gpu", "role", "port")})
        unique = {(str(e.get("server")), e["port"]): e for e in found}
        result = list(unique.values())[:64]
        _DISCOVERY_CACHE.update(until=now + 20, endpoints=result, warnings=warnings)
        return result, warnings


def parse_metrics(text):
    values = {}
    histograms = {}
    model = None
    for line in text.splitlines():
        match = LINE.match(line)
        if not match:
            continue
        name, raw_labels, raw_value = match.groups()
        try:
            value = float(raw_value)
        except ValueError:
            continue
        if not math.isfinite(value):
            continue
        labels = dict(LABEL.findall(raw_labels or ""))
        model = model or labels.get("model_name")
        if name in SINGLE:
            values[name] = values.get(name, 0) + value
        for histogram in HISTOGRAMS:
            if name == histogram + "_bucket" and "le" in labels:
                buckets = histograms.setdefault(histogram, {}).setdefault("buckets", {})
                bound = labels["le"]
                buckets[bound] = buckets.get(bound, 0) + value
            elif name in (histogram + "_sum", histogram + "_count"):
                key = name[len(histogram) + 1 :]
                target = histograms.setdefault(histogram, {})
                target[key] = target.get(key, 0) + value
    return {"model": model, "values": values, "histograms": histograms}


def scrape_one(endpoint):
    result = {key: endpoint.get(key) for key in ("server", "gpu", "role", "port")}
    start = time.monotonic()
    try:
        if "_ssh" in endpoint:
            remote = "PATH=/root/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:$PATH python3 -c " + shlex.quote(
                "import sys,urllib.request; sys.stdout.buffer.write(urllib.request.urlopen("
                + repr(f"http://127.0.0.1:{endpoint['port']}/metrics")
                + ", timeout=2).read(2000001))"
            )
            body = subprocess.run(
                endpoint["_ssh"] + [remote], capture_output=True, timeout=4, check=True
            ).stdout
        else:
            with urlopen(
                f"http://127.0.0.1:{endpoint.get('_local_port', endpoint['port'])}/metrics", timeout=1.5
            ) as response:
                body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError("metrics response too large")
        result.update(parse_metrics(body.decode("utf-8")), online=True)
    except (OSError, URLError, ValueError, UnicodeError, subprocess.SubprocessError) as exc:
        result.update(online=False, error=type(exc).__name__)
    result["sampledAt"] = time.time()
    result["scrapeMs"] = round((time.monotonic() - start) * 1000)
    return result


async def scrape_all():
    discovered, warnings = await asyncio.to_thread(endpoints)
    rows = await asyncio.gather(*(asyncio.to_thread(scrape_one, e) for e in discovered))
    return {"sampledAt": time.time(), "endpoints": rows, "discoveryWarnings": warnings}
