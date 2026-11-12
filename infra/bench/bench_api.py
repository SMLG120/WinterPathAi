#!/usr/bin/env python3
"""Reusable Docker benchmark harness for the WinterPath API (stdlib only).

Starts ONE container of the API image under explicit resource limits (default: Render Free,
--cpus=0.1 --memory=512m), then measures:

* boot time: `docker run` -> first HTTP 200 on /api/v1/health (client wall clock);
* memory: `docker stats` sampled every --sample-s during the whole run (peak and last), plus the
  kernel's cgroup v2 `memory.peak` when the container exposes it (the authoritative peak);
* latency: POST /api/v1/routes/compare, sequential (concurrency 1), per route class, after
  --warmup unmeasured requests. p50/p95/max over HTTP-200 responses; every non-200 is counted and
  reported by status and error code, never folded into the latency figures.

Route pairs come either from --pairs FILE (JSON list of {"class","origin":{lon,lat},
"destination":{lon,lat}} — e.g. node-snapped pairs routing generates from the graph) or are
drawn uniformly at random inside --bbox for each class's straight-line distance band
(short <1 km, medium 2-5 km, cross 15-40 km by default), seeded by --seed so runs are repeatable.
Random points can land off the pedestrian network: those 422 OFF_NETWORK answers are reported
as such, which is itself a useful coverage signal — use --pairs for pure latency.

Nothing here invents numbers: every figure printed comes from a measurement in this run, and the
JSON result records the exact configuration (image id, limits, env NAMES only — never values).

Examples
  # pilot, fixture graph, Render-Free limits (no DB)
  python3 infra/bench/bench_api.py --image winterpath-api:local \\
      -e ROUTING_GRAPH_SOURCE=fixture -e API_STORE_BACKEND=memory -e WEATHER_SOURCE=none \\
      -e RISK_PROVIDER=none --classes short=0:1000 --n 100

  # island graph in the shared local DB (secrets via an env file; values are never printed)
  python3 infra/bench/bench_api.py --image winterpath-api:local --network winterpath_default \\
      --env-file /path/outside/repo/island.env --bbox -73.98,45.40,-73.47,45.71 \\
      --classes short=0:1000 medium=2000:5000 cross=15000:40000 --n 50 --boot-timeout 600 \\
      --json-out /tmp/island-bench.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

PILOT_BBOX = (-73.5880, 45.4960, -73.5620, 45.5130)  # architecture §3 (west, south, east, north)
DEFAULT_CLASSES = ["short=0:1000", "medium=2000:5000", "cross=15000:40000"]
_UNITS = {"b": 1, "kib": 1024, "mib": 1024**2, "gib": 1024**3, "kb": 1000, "mb": 1000**2, "gb": 1000**3}


# ---------------------------------------------------------------------------------------- utils
def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(math.sqrt(h))


def parse_bytes(s: str) -> int | None:
    m = re.match(r"\s*([\d.]+)\s*([A-Za-z]+)", s)
    if not m:
        return None
    unit = _UNITS.get(m.group(2).lower())
    return int(float(m.group(1)) * unit) if unit else None


def pct(values: list[float], p: float) -> float:
    """Nearest-rank percentile (no interpolation): the value at rank ceil(p/100 * n)."""
    s = sorted(values)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def mib(n: int | None) -> str:
    return "n/a" if n is None else f"{n / 1024**2:.1f} MiB"


def docker(*args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    # Dev tool: argv is built from the operator's own CLI flags; "docker" resolved from PATH on purpose.
    return subprocess.run(["docker", *args], check=check, capture_output=capture, text=True)  # noqa: S603, S607


# ---------------------------------------------------------------------------------------- pairs
def random_pairs(bbox, classes, n, seed, max_tries=200_000):
    rng = random.Random(seed)  # noqa: S311 — reproducible benchmark sampling, not security
    w, s, e, nn = bbox
    diag = haversine_m((w, s), (e, nn))
    out = []
    for name, (lo, hi) in classes.items():
        if lo > diag:
            msg = f"WARN class {name}: min {lo} m exceeds bbox diagonal {diag:.0f} m — skipped"
            print(msg, file=sys.stderr)
            continue
        got = 0
        for _ in range(max_tries):
            o = (rng.uniform(w, e), rng.uniform(s, nn))
            d = (rng.uniform(w, e), rng.uniform(s, nn))
            if lo <= haversine_m(o, d) < hi:
                out.append(
                    {
                        "class": name,
                        "origin": {"lon": round(o[0], 6), "lat": round(o[1], 6)},
                        "destination": {"lon": round(d[0], 6), "lat": round(d[1], 6)},
                    }
                )
                got += 1
                if got == n:
                    break
        if got < n:
            print(f"WARN class {name}: only {got}/{n} pairs found in bbox", file=sys.stderr)
    return out


def node_pairs(nodes_geojson: Path, classes, n, seed, max_tries=200_000):
    """Pairs of graph node coordinates per distance band: every endpoint is ON the network."""
    feats = json.loads(Path(nodes_geojson).read_text())["features"]
    pts = [tuple(f["geometry"]["coordinates"][:2]) for f in feats if f["geometry"]["type"] == "Point"]
    rng = random.Random(seed)  # noqa: S311 — reproducible benchmark sampling, not security
    out = []
    for name, (lo, hi) in classes.items():
        got = 0
        for _ in range(max_tries):
            o, d = rng.choice(pts), rng.choice(pts)
            if o != d and lo <= haversine_m(o, d) < hi:
                out.append(
                    {
                        "class": name,
                        "origin": {"lon": o[0], "lat": o[1]},
                        "destination": {"lon": d[0], "lat": d[1]},
                    }
                )
                got += 1
                if got == n:
                    break
        if got < n:
            print(f"WARN class {name}: only {got}/{n} node pairs in band", file=sys.stderr)
    return out


# ------------------------------------------------------------------------------------- sampling
class MemSampler(threading.Thread):
    def __init__(self, name: str, every: float):
        super().__init__(daemon=True)
        self.name_, self.every, self.peak, self.last, self.samples = name, every, None, None, 0
        self._halt = threading.Event()

    def run(self):
        while not self._halt.is_set():
            r = docker("stats", "--no-stream", "--format", "{{.MemUsage}}", self.name_, check=False)
            if r.returncode == 0 and r.stdout.strip():
                v = parse_bytes(r.stdout.split("/")[0])
                if v is not None:
                    self.last, self.samples = v, self.samples + 1
                    self.peak = v if self.peak is None else max(self.peak, v)
            self._halt.wait(self.every)

    def stop(self):
        self._halt.set()
        self.join(timeout=10)


def cgroup_peak(name: str) -> int | None:
    for path in ("/sys/fs/cgroup/memory.peak", "/sys/fs/cgroup/memory/memory.max_usage_in_bytes"):
        r = docker("exec", name, "cat", path, check=False)
        if r.returncode == 0 and r.stdout.strip().isdigit():
            return int(r.stdout.strip())
    return None


# ------------------------------------------------------------------------------------------ http
def http(method: str, url: str, body: dict | None = None, timeout: float = 120.0):
    data = json.dumps(body).encode() if body is not None else None
    # url is always the harness's own http://127.0.0.1:<port>/api/v1/... (never user-supplied scheme)
    hdrs = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)  # noqa: S310
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            payload = r.read()
            return r.status, (time.perf_counter() - t0) * 1000, payload
    except urllib.error.HTTPError as e:
        return e.code, (time.perf_counter() - t0) * 1000, e.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return None, (time.perf_counter() - t0) * 1000, str(e).encode()


def error_code(payload: bytes) -> str:
    try:
        return json.loads(payload).get("code", "?")
    except (ValueError, AttributeError):
        return "?"


# ------------------------------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True)
    ap.add_argument("--cpus", default="0.1")
    ap.add_argument("--memory", default="512m")
    ap.add_argument("--port", type=int, default=18190, help="host port (127.0.0.1 only)")
    ap.add_argument("--container-port", type=int, default=10000)
    ap.add_argument("--name", default="wp-bench")
    ap.add_argument("--network", help="docker network, e.g. winterpath_default to reach the shared db")
    ap.add_argument("-e", "--env", action="append", default=[], help="KEY=VALUE passed to the container")
    ap.add_argument("--env-file", help="docker --env-file (keep it outside the repo; values never printed)")
    ap.add_argument("--boot-timeout", type=float, default=300)
    ap.add_argument("--bbox", default=",".join(map(str, PILOT_BBOX)), help="west,south,east,north")
    ap.add_argument("--classes", nargs="+", default=DEFAULT_CLASSES, help="name=min_m:max_m ...")
    ap.add_argument("--n", type=int, default=100, help="measured requests per class")
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20261111)
    ap.add_argument("--pairs", help="JSON file of explicit pairs (overrides --bbox/--classes)")
    ap.add_argument("--nodes", help="GeoJSON of graph nodes: draw on-network pairs per class")
    ap.add_argument(
        "--keep-rate-limit",
        action="store_true",
        help="do NOT raise API_RATE_LIMIT_PER_MINUTE (default raises it: measure routing, not the limiter)",
    )
    ap.add_argument("--profile", default=None, help="RouteProfile for every request (contract enum)")
    ap.add_argument("--request-timeout", type=float, default=120)
    ap.add_argument("--sample-s", type=float, default=0.5)
    ap.add_argument("--json-out")
    ap.add_argument("--keep", action="store_true", help="leave the container running afterwards")
    a = ap.parse_args(argv)

    if a.pairs:
        pairs = json.loads(Path(a.pairs).read_text())
    elif a.nodes:
        classes = _classes(a.classes)
        pairs = node_pairs(Path(a.nodes), classes, a.n, a.seed)
    else:
        classes = _classes(a.classes)
        bbox = tuple(float(x) for x in a.bbox.split(","))
        pairs = random_pairs(bbox, classes, a.n, a.seed)
    if not pairs:
        print("ERROR: no route pairs to run", file=sys.stderr)
        return 2

    docker("rm", "-f", a.name, check=False)
    run = [
        "run",
        "-d",
        "--name",
        a.name,
        f"--cpus={a.cpus}",
        f"--memory={a.memory}",
        f"--memory-swap={a.memory}",
        "-p",
        f"127.0.0.1:{a.port}:{a.container_port}",
    ]
    if a.network:
        run += ["--network", a.network]
    if a.env_file:
        run += ["--env-file", a.env_file]
    env = list(a.env)
    if not a.keep_rate_limit and not any(kv.startswith("API_RATE_LIMIT_PER_MINUTE=") for kv in env):
        env.append("API_RATE_LIMIT_PER_MINUTE=1000000")
    for kv in env:
        run += ["-e", kv]
    base = f"http://127.0.0.1:{a.port}/api/v1"
    result: dict = {
        "image": a.image,
        "image_id": docker("image", "inspect", "--format", "{{.Id}}", a.image, check=False).stdout.strip()
        or None,
        "limits": {"cpus": a.cpus, "memory": a.memory},
        "env_names": sorted({kv.split("=", 1)[0] for kv in env}),
        "rate_limit_raised": not a.keep_rate_limit,
        "env_file_used": bool(a.env_file),
        "network": a.network,
        "seed": a.seed,
        "pairs_source": a.pairs or (f"graph nodes {a.nodes}" if a.nodes else f"random in bbox {a.bbox}"),
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    t0 = time.perf_counter()
    docker(*run, a.image)
    sampler = MemSampler(a.name, a.sample_s)
    sampler.start()
    rc = 0
    try:
        boot = None
        while time.perf_counter() - t0 < a.boot_timeout:
            st, _, _ = http("GET", f"{base}/health", timeout=5)
            if st == 200:
                boot = time.perf_counter() - t0
                break
            if docker("inspect", "-f", "{{.State.Running}}", a.name, check=False).stdout.strip() != "true":
                break
            time.sleep(0.5)
        result["boot_s"] = None if boot is None else round(boot, 2)
        if boot is None:
            logs = docker("logs", "--tail", "40", a.name, check=False)
            print(f"ERROR: not healthy within {a.boot_timeout}s\n{logs.stdout}{logs.stderr}", file=sys.stderr)
            result["error"] = "boot_timeout_or_exit"
            rc = 1
            return rc
        st, _, body = http("GET", f"{base}/health")
        result["health"] = json.loads(body) if st == 200 else {"status_code": st}
        result["rss_after_boot"] = sampler.last

        for p in pairs[: a.warmup]:
            http("POST", f"{base}/routes/compare", _body(p, a.profile), timeout=a.request_timeout)

        per_class: dict = {}
        for p in pairs:
            st, ms, body = http(
                "POST", f"{base}/routes/compare", _body(p, a.profile), timeout=a.request_timeout
            )
            c = per_class.setdefault(p.get("class", "all"), {"ok_ms": [], "non_200": {}})
            if st == 200:
                c["ok_ms"].append(ms)
            else:
                key = f"{st}:{error_code(body)}" if st else "transport_error"
                c["non_200"][key] = c["non_200"].get(key, 0) + 1
        result["classes"] = {}
        for name, c in per_class.items():
            ok = c["ok_ms"]
            result["classes"][name] = {
                "requests": len(ok) + sum(c["non_200"].values()),
                "ok": len(ok),
                "non_200": c["non_200"],
                "p50_ms": round(pct(ok, 50), 1) if ok else None,
                "p95_ms": round(pct(ok, 95), 1) if ok else None,
                "max_ms": round(max(ok), 1) if ok else None,
                "mean_ms": round(statistics.fmean(ok), 1) if ok else None,
            }
    finally:
        sampler.stop()
        result["mem_peak_sampled"] = sampler.peak
        result["mem_samples"] = sampler.samples
        result["mem_cgroup_peak"] = cgroup_peak(a.name)
        result["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not a.keep:
            docker("rm", "-f", a.name, check=False)
        _print(result)
        if a.json_out:
            Path(a.json_out).write_text(json.dumps(result, indent=2))
            print(f"json: {a.json_out}")
    return rc


def _classes(specs: list[str]) -> dict[str, tuple[float, float]]:
    out = {}
    for c in specs:
        name, band = c.split("=", 1)
        lo, hi = (float(v) for v in band.split(":"))
        out[name] = (lo, hi)
    return out


def _body(p: dict, profile: str | None) -> dict:
    b = {"origin": p["origin"], "destination": p["destination"]}
    if profile:
        b["profile"] = profile
    return b


def _print(r: dict) -> None:
    lim = r["limits"]
    print(
        f"image {r['image']} ({(r.get('image_id') or '')[:19]})  "
        f"limits cpus={lim['cpus']} memory={lim['memory']}"
    )
    print(f"boot to healthy: {r.get('boot_s')} s   health: {(r.get('health') or {}).get('status')}")
    print(
        f"memory: after boot {mib(r.get('rss_after_boot'))}, peak sampled {mib(r.get('mem_peak_sampled'))} "
        f"({r.get('mem_samples')} samples), cgroup peak {mib(r.get('mem_cgroup_peak'))}"
    )
    for name, c in (r.get("classes") or {}).items():
        print(
            f"  {name:<8} n={c['requests']:<4} ok={c['ok']:<4} p50={c['p50_ms']} ms  p95={c['p95_ms']} ms  "
            f"max={c['max_ms']} ms  non-200={c['non_200'] or '{}'}"
        )


if __name__ == "__main__":
    sys.exit(main())
