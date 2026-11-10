"""Runtime configuration from env (`.env.local` at repo root). No hard-coded secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[4]
load_dotenv(REPO_ROOT / ".env.local", override=False)

# docs/architecture.md §3 — west, south, east, north (EPSG:4326)
PILOT_BBOX: tuple[float, float, float, float] = (-73.5880, 45.4960, -73.5620, 45.5130)

WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:32188"  # NAD83 / MTM zone 8

DEFAULT_USER_AGENT = "WinterPathAI-ingestion/0.1"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    user_agent: str

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def fixtures_dir(self) -> Path:
        return self.data_dir / "fixtures"


def get_settings() -> Settings:
    data_dir = os.environ.get("DATA_DIR") or str(REPO_ROOT / "data")
    p = Path(data_dir)
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    return Settings(data_dir=p, user_agent=os.environ.get("HTTP_USER_AGENT") or DEFAULT_USER_AGENT)
