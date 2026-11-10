"""Fixed configuration for the winter 311 report-risk pipeline.

Everything that affects labels, splits or the gate lives here so it is versioned with the code.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[2]  # services/ml
REPO_ROOT = PKG_ROOT.parents[1]
CACHE_DIR = Path(os.environ.get("WP_ML_CACHE_DIR", PKG_ROOT / ".cache"))
RAW_DIR = CACHE_DIR / "raw"
INTERIM_DIR = CACHE_DIR / "interim"
MODELS_DIR = REPO_ROOT / "models"
ARTIFACT_DIR = Path(os.environ.get("MODEL_ARTIFACT_DIR", MODELS_DIR / "artifacts"))
if not ARTIFACT_DIR.is_absolute():
    ARTIFACT_DIR = REPO_ROOT / ARTIFACT_DIR
REGISTRY_PATH = MODELS_DIR / "registry.json"

# --- 311 source (Ville de Montréal, CC BY 4.0) ---------------------------------------------
URL_311_2022_PRESENT = (
    "https://donnees.montreal.ca/dataset/5866f832-676d-4b07-be6a-e99c21eb17e4/resource/"
    "2cfa0e06-9be4-49a6-b7f1-ee9f2363a872/download/requetes311.csv"
)
RAW_311_CSV = RAW_DIR / "requetes311.csv"

# Winter categories: ACTI_NOM value -> normalised category. Only NATURE in REPORT_NATURES counts.
WINTER_CATEGORIES: dict[str, str] = {
    "Trottoir glissant": "slippery_sidewalk",
    "Chaussée glissante": "slippery_roadway",
    "Opération déneigement": "snow_clearing",
    "Dépôt Illégal - Neige": "illegal_snow_dump",
}
REPORT_NATURES = ("Requete", "Plainte")  # 'Information' and 'Commentaire' are not reports of a condition

# The 311 file covers only the 19 boroughs of the City of Montréal. Demerged municipalities
# (Westmount, Mont-Royal, Côte-Saint-Luc, ...) run their own services and have ~no rows, so
# their cells are OUT of coverage (unknown), never "low".
CITY_BOROUGHS = frozenset(
    {
        "Ahuntsic-Cartierville",
        "Anjou",
        "Côte-des-Neiges-Notre-Dame-de-Grâce",
        "Lachine",
        "LaSalle",
        "Le Plateau-Mont-Royal",
        "Le Sud-Ouest",
        "L'Île-Bizard-Sainte-Geneviève",
        "Mercier-Hochelaga-Maisonneuve",
        "Montréal-Nord",
        "Outremont",
        "Pierrefonds-Roxboro",
        "Rivière-des-Prairies-Pointe-aux-Trembles",
        "Rosemont-La Petite-Patrie",
        "Saint-Laurent",
        "Saint-Léonard",
        "Verdun",
        "Ville-Marie",
        "Villeray-Saint-Michel-Parc-Extension",
    }
)


def normalise_borough(name: str) -> str:
    return name.replace(" - ", "-").strip()


H3_RES = 9
SPATIAL_BLOCK_RES = 6
SPATIAL_HOLDOUT_FRACTION = 0.2
SEED = 20261110

# Montréal agglomeration rough envelope used only to reject geocoding failures (EPSG:4326).
MTL_ENVELOPE = (-74.0, 45.38, -73.45, 45.72)  # west, south, east, north

# --- Weather (ECCC climate-daily, ECCC Data Servers End-use Licence) ------------------------
ECCC_API = "https://api.weather.gc.ca"
STATION_PRIMARY = "7025251"  # MONTREAL INTL A (has TOTAL_SNOW / SNOW_ON_GROUND)
STATION_FALLBACK = "702S006"  # MONTREAL/PIERRE ELLIOTT TRUDEAU INTL (temps/precip only)

# --- Seasons ---------------------------------------------------------------------------------
SEASON_MONTHS = (11, 12, 1, 2, 3, 4)  # Nov–Apr: the only months the layer is defined for


def winter_of(d: date) -> int | None:
    """Winter label = year in which the winter starts (Nov 2024–Apr 2025 -> 2024)."""
    if d.month >= 11:
        return d.year
    if d.month <= 4:
        return d.year - 1
    return None


# Panel starts after the 28-day lag window is fully inside the 311 file (which begins 2022-01-01).
PANEL_START = date(2022, 2, 1)
TRAIN_WINTERS = (2021, 2022, 2023)  # 2021 = partial (Feb–Apr 2022)
VALID_WINTER = 2024  # calibration only
TEST_WINTER = 2025  # most recent complete winter (Nov 2025 – Apr 2026); scored once

TARGET = "P(>=1 winter-related 311 report in H3 res-9 cell within next 24h)"
