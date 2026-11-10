"""wp.source rows (mirror /data-sources). Strings: docs/data-sources-and-licenses.md."""

MTL_ATTR = "Contient des données de la Ville de Montréal, sous licence CC BY 4.0"
CC_BY = "https://creativecommons.org/licenses/by/4.0/"

SOURCES: list[dict] = [
    {
        "source_id": "osm",
        "name": "OpenStreetMap pedestrian network (pilot bbox)",
        "publisher": "OpenStreetMap Foundation / contributors",
        "license": "ODbL-1.0",
        "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
        "commercial_use": "allowed_with_conditions",
        "attribution": "© OpenStreetMap contributors (https://www.openstreetmap.org/copyright), "
        "available under the ODbL",
        "url": "https://www.openstreetmap.org/copyright",
        "status": "active",
        "notes": "Fetched via Overpass API (overpass-api.de). Commercial use of the public "
        "instance is discouraged by its policy: switch to a Geofabrik extract or "
        "self-hosted Overpass before launch. Share-alike applies to derived databases.",
    },
    {
        "source_id": "mtl-voirie",
        "name": "Voirie — trottoirs et îlots",
        "publisher": "Ville de Montréal",
        "license": "CC BY 4.0",
        "license_url": CC_BY,
        "commercial_use": "allowed",
        "attribution": MTL_ATTR,
        "url": "https://donnees.montreal.ca/dataset/voirie-trottoir-ilot",
        "status": "active",
        "notes": "Edge enrichment only. Publisher: not necessarily up to date across the "
        "territory.",
    },
    {
        "source_id": "mtl-entraves",
        "name": "Entraves et travaux en cours",
        "publisher": "Ville de Montréal",
        "license": "CC BY 4.0",
        "license_url": CC_BY,
        "commercial_use": "allowed",
        "attribution": MTL_ATTR,
        "url": "https://donnees.montreal.ca/dataset/info-travaux",
        "status": "active",
        "notes": "blocks_passage true only when sidewalk_blockedtype = 'Barré'. Geometry is the "
        "permit point, not the affected segment.",
    },
    {
        "source_id": "mtl-311",
        "name": "Requêtes 311 (aggregated, winter categories)",
        "publisher": "Ville de Montréal",
        "license": "CC BY 4.0",
        "license_url": CC_BY,
        "commercial_use": "allowed",
        "attribution": MTL_ATTR,
        "url": "https://donnees.montreal.ca/dataset/requete-311",
        "status": "active",
        "notes": "Reports, not confirmed obstacles. Locations obfuscated by the publisher "
        "(nearest >45 m street-segment midpoint). Stored only as H3 res-9 daily counts.",
    },
    {
        "source_id": "eccc-geomet",
        "name": "ECCC MSC GeoMet (climate-hourly, swob-realtime)",
        "publisher": "Environment and Climate Change Canada",
        "license": "ECCC Data Servers End-use Licence",
        "license_url": "https://eccc-msc.github.io/open-data/licence/readme_en/",
        "commercial_use": "allowed",
        "attribution": "Data Source: Environment and Climate Change Canada",
        "url": "https://api.weather.gc.ca/",
        "status": "active",
        "notes": "Stations 7025251 (MONTREAL INTL A) and 702S006 (hourly precip, ends 2026-10-01).",
    },
]
