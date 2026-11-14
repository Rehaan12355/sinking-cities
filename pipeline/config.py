"""Study-area configuration. Change this file to point the pipeline at another city."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"          # downloads, not committed
WORK = ROOT / "data" / "work"        # intermediate products, not committed
SITE_DATA = ROOT / "site" / "data"   # what the website loads, committed
for _d in (RAW, WORK, SITE_DATA):
    _d.mkdir(parents=True, exist_ok=True)

CITY = {
    "id": "hampton-roads",
    "name": "Norfolk & Hampton Roads, Virginia",
    "short_name": "Hampton Roads",
    "state_fips": "51",
    # Independent cities of the Hampton Roads core (county-equivalent FIPS).
    "counties": {
        "710": "Norfolk",
        "740": "Portsmouth",
        "650": "Hampton",
        "700": "Newport News",
        "810": "Virginia Beach",
        "550": "Chesapeake",
        "735": "Poquoson",
    },
    # NOAA tide gauge and its PSMSL id (used by the NASA sea level tool).
    "tide_station": "8638610",
    "tide_station_name": "Sewells Point, VA",
    "psmsl_id": 299,
    "utm_epsg": 32618,
    # Analysis window (lon/lat). South Chesapeake / Virginia Beach farmland is
    # trimmed to keep rasters small; tracts are kept if their centroid is inside.
    "bbox": (-76.70, 36.66, -75.92, 37.22),
}

GRID_M = 10          # flood-model grid, metres
WEB_GRID_M = 20      # raster resolution shipped to the browser
BASE_YEAR = 2026
END_YEAR = 2150
SLIDER_END_YEAR = 2100
# A neighborhood counts as "regularly flooding" once this share of its
# currently-dry land is below the high-tide-flood waterline.
TRACT_FLOOD_SHARE = 0.10
