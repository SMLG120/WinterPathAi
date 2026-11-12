# API Docker benchmark harness

`bench_api.py` uses only the Python standard library. It runs **one** container of the API image under explicit limits (default: Render Free, `--cpus=0.1 --memory=512m`) and reports:

| Metric | How it is measured |
|---|---|
| boot to healthy | Wall clock from `docker run` to the first HTTP 200 on `/api/v1/health` |
| memory | `docker stats` sampled every 0.5 s (after boot, sampled peak), plus the kernel's cgroup v2 `memory.peak` (authoritative peak; `n/a` if not exposed) |
| latency | `POST /api/v1/routes/compare`, sequential, after `--warmup` unmeasured requests. p50/p95/max over **HTTP 200 only**. Every non-200 is counted by `status:code` (e.g. `422:OFF_NETWORK`), never folded into the latency figures |

The JSON written by `--json-out` records image id, limits, env var **names** (never values), seed, pair source and UTC start/finish times, so a run can be reproduced.

## Route pairs
- `--nodes nodes.geojson`: endpoints are drawn from graph node coordinates, so every point is on the network. Pairs fall in each class's straight-line distance band. **Use this for latency.**
- `--pairs pairs.json`: an explicit list of `{"class", "origin":{lon,lat}, "destination":{lon,lat}}`, e.g. curated cross-island pairs such as Pointe-Claire → Montréal-Nord.
- Default: uniform random points in `--bbox`. Many will be `OFF_NETWORK`, which shows coverage rather than latency.

Classes are `name=min_m:max_m` (default `short=0:1000 medium=2000:5000 cross=15000:40000`). Sampling is seeded (`--seed`), so pairs are identical across runs and images.

By default the harness sets `API_RATE_LIMIT_PER_MINUTE=1000000` in the container, because the API's 60/min limiter would otherwise be what gets measured. `--keep-rate-limit` turns this off. The JSON records `rate_limit_raised`.

## Reading results at 0.1 CPU
`--cpus=0.1` is enforced by the CFS quota: 10 ms of CPU per 100 ms period. Latencies are quantised: a request either fits in the remaining quota or waits roughly 90 ms for the next period. Two identical local runs of the pilot fixture gave p50 6.5 ms and 87.7 ms, and boot times of 23.7–54.6 s. **Run each configuration at least 3 times and report every run (or the median of runs), never a single best run.** Absolute numbers on an Apple-silicon laptop are not Render's; compare configurations relative to each other on the same machine.

## Examples
```bash
# Pilot fixture graph, Render-Free limits (no DB)
make bench BENCH_ARGS='-e ROUTING_GRAPH_SOURCE=fixture -e API_STORE_BACKEND=memory -e WEATHER_SOURCE=none -e RISK_PROVIDER=none --nodes data/fixtures/pilot_mini/nodes.geojson --classes short=0:1000 --n 100'

# Island graph in the shared local DB `wp_island`. DATABASE_URL goes in an env file OUTSIDE the
# repo; the container joins the compose network, so the host is `db`, not localhost.
python3 infra/bench/bench_api.py --image winterpath-api:bench --network winterpath_default \
  --env-file ../wp-island-bench.env --nodes /tmp/wp_island_nodes.geojson \
  --classes short=0:1000 medium=2000:5000 cross=15000:40000 --n 50 \
  --boot-timeout 900 --json-out /tmp/island-run1.json
```
To export island nodes for `--nodes`, run `ogr2ogr` or `psql … ST_AsGeoJSON` on `wp.node` in `wp_island` (Data/Routing). The harness reads only Point features.

## Safety
- Binds `127.0.0.1` only.
- Removes its container afterwards unless `--keep` is given.
- Never prints env values.
- Writes nothing to any database itself; whatever the API does with its own `DATABASE_URL` is the API's behaviour, and the island DB is local.
