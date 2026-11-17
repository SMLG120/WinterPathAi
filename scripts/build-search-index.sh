#!/usr/bin/env bash
# Build the self-hosted place-search index into apps/web/public/search (git-ignored), then check it.
# Run before `npm run build:pages` (docs/DEPLOYMENT.md §3); build:pages refuses a bundle without it.
#
#   scripts/build-search-index.sh <RQA_CSV.zip> <quebec-YYMMDD.osm.pbf>
#
# Inputs (raw data, never in Git): RQA from Données Québec (CC BY 4.0), Geofabrik Québec extract
# (ODbL). Their versions and sha256 are written into the manifest. Needs a few GB of RAM.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rqa="${1:?usage: $0 <RQA_CSV.zip> <quebec.osm.pbf>}"
pbf="${2:?usage: $0 <RQA_CSV.zip> <quebec.osm.pbf>}"
[[ -f "$rqa" ]] || { echo "RQA input not found: $rqa" >&2; exit 1; }
[[ -f "$pbf" ]] || { echo "OSM input not found: $pbf" >&2; exit 1; }
rqa="$(cd "$(dirname "$rqa")" && pwd)/$(basename "$rqa")"
pbf="$(cd "$(dirname "$pbf")" && pwd)/$(basename "$pbf")"
out="$root/apps/web/public/search"
report="$(mktemp "${TMPDIR:-/tmp}/search-index-report.XXXXXX")"

(cd "$root/services/ingestion" && uv run python -m winterpath_ingestion.search_index \
  --rqa "$rqa" --osm "$pbf" --out "$out" --report "$report")
(cd "$root/apps/web" && node build/pagesCheck.ts search public)
python3 - "$out/manifest.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
print(f"search index {m['build_id']}: {len(m['shards'])} shards; counts {m['counts']}")
for s in m["sources"]:
    print(f"  {s['id']}: {s.get('version', '?')} {s.get('input_file', '')} sha256 {s.get('input_sha256', '?')[:12]}")
PY
echo "build report: $report"
