"""Study-area configuration. Add a city to CITIES and run the pipeline with
SC_CITY=<id> to build it; the website lists every city that has been built."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CITIES = {
    "hampton-roads": {
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
        # Radar coverage: the OPERA DISP-S1 frame and the NISAR track/frame that
        # cover the whole window.
        "opera_frame": "F00833",
        "nisar_track_frame": "_069_D_070_",
        "why": "Hampton Roads has one of the highest rates of relative sea level rise on the US Atlantic coast. The region is open to the tide "
               "rather than walled off by levees, which makes a ground-height comparison a fair first estimate.",
    },
    "seattle": {
        "name": "Seattle, Washington",
        "short_name": "Seattle",
        "state_fips": "53",
        # King County tracts whose centre falls inside the window below.
        "counties": {"033": "Seattle area"},
        "tide_station": "9447130",
        "tide_station_name": "Seattle, WA",
        "psmsl_id": 127,
        "utm_epsg": 32610,
        "bbox": (-122.44, 47.495, -122.235, 47.735),
        "opera_frame": "F03321",
        "nisar_track_frame": "_106_A_026_",
        "why": "Seattle hosts this Space Apps event, and its industrial waterfront, the Duwamish valley and parts of the shoreline are built on "
               "fill and river sediment only a little above high tide. Lake Washington and Lake Union sit behind the Ballard Locks, above "
               "the tide, so only the Puget Sound and Duwamish shorelines are treated as open to the sea.",
    },
    "charleston": {
        "name": "Charleston, South Carolina",
        "short_name": "Charleston",
        "state_fips": "45",
        # Tracts of the three counties whose centre falls inside the window below.
        "counties": {"019": "Charleston County", "015": "Berkeley County", "035": "Dorchester County"},
        "tide_station": "8665530",
        "tide_station_name": "Charleston, SC",
        "psmsl_id": 234,
        "utm_epsg": 32617,
        "bbox": (-80.15, 32.65, -79.75, 32.95),
        "opera_frame": "F40029",
        "nisar_track_frame": "_098_D_072_",
        "why": "Charleston is one of the most frequently flooded cities on the US Atlantic coast. Much of the historic peninsula and the "
               "neighborhoods along its tidal rivers and marshes are built on low, filled ground that the tide can reach directly.",
    },
    "miami": {
        "name": "Miami & Miami Beach, Florida",
        "short_name": "Miami",
        "state_fips": "12",
        # Miami-Dade tracts whose centre falls inside the window below.
        "counties": {"086": "Miami-Dade County"},
        "tide_station": "8723214",
        "tide_station_name": "Virginia Key, FL",
        "psmsl_id": 1858,
        "utm_epsg": 32617,
        "bbox": (-80.32, 25.70, -80.11, 25.93),
        "opera_frame": "F12638",
        "nisar_track_frame": "_170_D_075_",
        "why": "Miami and Miami Beach sit on low, porous limestone barely above the tide, and high-tide flooding on dry, sunny days is already "
               "familiar there. Water can rise through the ground as well as over it, which this map does not capture.",
    },
    "galveston": {
        "name": "Galveston Bay, Texas",
        "short_name": "Galveston",
        "state_fips": "48",
        # Galveston County: the island, Texas City, League City and the west shore of the bay.
        "counties": {"167": "Galveston County"},
        "tide_station": "8771450",
        "tide_station_name": "Galveston Pier 21, TX",
        "psmsl_id": 161,
        "utm_epsg": 32615,
        "bbox": (-95.22, 29.10, -94.72, 29.56),
        "opera_frame": "F08882",
        "nisar_track_frame": "_012_D_074_",
        "why": "The Galveston Bay shore sank substantially during the twentieth century as groundwater, oil and gas were pumped from beneath it, "
               "and the island and bay towns sit only a little above the tide. Storm surge, the larger danger here, is not part of this map.",
    },
    "aberdeen": {
        "name": "Aberdeen & Hoquiam, Washington",
        "short_name": "Aberdeen",
        "state_fips": "53",
        "counties": {"027": "Grays Harbor County"},
        "tide_station": "9441187",
        "tide_station_name": "Aberdeen, WA",
        # The Aberdeen gauge has no flood-day count, so the nearest gauge that does supplies it.
        "htf_station": "9440910",
        "htf_station_name": "Toke Point, WA",
        "psmsl_id": 1354,
        "projection_note": "Sea level projections are for the Toke Point gauge on Willapa Bay, 31 km away, the nearest one in NASA's projection tool.",
        "utm_epsg": 32610,
        "bbox": (-124.00, 46.93, -123.72, 47.03),
        "opera_frame": "F09164",
        "nisar_track_frame": "_172_D_065_",
        "why": "Aberdeen and Hoquiam are built on filled tide flats where the Chehalis, Wishkah and Hoquiam rivers meet Grays Harbor, only a little "
               "above high tide. River floods and storm surge add to the tidal risk here and are not part of this map.",
    },
    "olympia": {
        "name": "Olympia, Washington",
        "short_name": "Olympia",
        "state_fips": "53",
        "counties": {"067": "Thurston County"},
        "tide_station": "9446969",
        "tide_station_name": "Olympia, WA",
        "htf_station": "9447130",
        "htf_station_name": "Seattle, WA",
        "psmsl_id": 127,
        "projection_note": "Sea level projections are for the Seattle gauge, 75 km away, the nearest one in NASA's projection tool.",
        "utm_epsg": 32610,
        "bbox": (-122.98, 46.98, -122.82, 47.10),
        "opera_frame": "F03322",
        "nisar_track_frame": "_172_D_065_",
        "why": "Downtown Olympia sits on fill at the head of Budd Inlet, where Puget Sound's tides are at their largest, and the city already plans "
               "for sea level rise. Capitol Lake is held back by a tide gate that this map does not model.",
    },
}

CITY_ID = os.environ.get("SC_CITY", "hampton-roads")
CITY = dict(CITIES[CITY_ID], id=CITY_ID)

RAW = ROOT / "data" / "raw" / CITY_ID          # downloads, not committed
WORK = ROOT / "data" / "work" / CITY_ID        # intermediate products, not committed
SITE_DATA = ROOT / "site" / "data" / CITY_ID   # what the website loads, committed
for _d in (RAW, WORK, SITE_DATA):
    _d.mkdir(parents=True, exist_ok=True)

GRID_M = 10          # flood-model grid, metres
WEB_GRID_M = 20      # raster resolution shipped to the browser
BASE_YEAR = 2026
END_YEAR = 2150
SLIDER_END_YEAR = 2100
# A neighborhood counts as "regularly flooding" once this share of its
# currently-dry land is below the high-tide-flood waterline.
TRACT_FLOOD_SHARE = 0.10
