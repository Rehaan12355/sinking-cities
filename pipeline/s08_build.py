"""Step 8: package everything the website needs into site/data/.

Outputs
- city.json        city-wide numbers, water levels, validation, data status
- tracts.geojson   one feature per neighborhood with its card values
- series.json      monthly sinking history per neighborhood (if radar step ran)
- flood.png        per-cell first flood year (R = with sinking, G = sea level only)
- sinking.png      coloured sinking-rate picture (if radar step ran)
"""
import json

import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds

from common import write_sources_md
from config import BASE_YEAR, CITY, SITE_DATA, SLIDER_END_YEAR, TRACT_FLOOD_SHARE, WEB_GRID_M, WORK

NEVER = 255
MM_YR_TO_IN_DECADE = 10 / 25.4
# Sinking colour ramp, mm/yr (positive = sinking): stable teal -> yellow -> red.
RAMP = [(-1.0, (38, 132, 124)), (1.0, (120, 182, 150)), (2.0, (236, 214, 120)), (3.0, (240, 150, 70)), (4.5, (212, 60, 50)), (6.0, (140, 20, 50))]


def to_web(path, resampling, dst_nodata):
    """Reproject an analysis-grid raster to Web Mercator for the map overlay."""
    with rasterio.open(path) as src:
        res = WEB_GRID_M / np.cos(np.deg2rad(36.9))
        tf, w, h = calculate_default_transform(src.crs, "EPSG:3857", src.width, src.height, *src.bounds, resolution=res)
        out = np.full((h, w), dst_nodata, dtype=src.dtypes[0])
        reproject(rasterio.band(src, 1), out, dst_transform=tf, dst_crs="EPSG:3857", resampling=resampling,
                  src_nodata=src.nodata, dst_nodata=dst_nodata)
        bounds = rasterio.transform.array_bounds(h, w, tf)
        ll = transform_bounds("EPSG:3857", "EPSG:4326", *bounds)
    return out, [round(v, 6) for v in ll]


def colourise(rate):
    xs = [r[0] for r in RAMP]
    rgba = np.zeros(rate.shape + (4,), np.uint8)
    ok = np.isfinite(rate)
    for c in range(3):
        rgba[..., c][ok] = np.interp(rate[ok], xs, [r[1][c] for r in RAMP]).astype(np.uint8)
    rgba[..., 3][ok] = 255
    return rgba


def label(row):
    place = row["place"]
    if isinstance(place, str) and place:
        return f"{place} area"
    return f"Tract {row['BASENAME']}"


def main():
    water = json.loads((WORK / "water.json").read_text())
    flood = json.loads((WORK / "flood.json").read_text())
    gps = json.loads((WORK / "gps.json").read_text())
    have_sink = "sinking" in flood["modes"]
    radar = json.loads((WORK / "radar.json").read_text()) if (WORK / "radar.json").exists() else None
    nisar = json.loads((WORK / "nisar.json").read_text()) if (WORK / "nisar.json").exists() else None
    years = flood["years"]
    main_mode = "sinking" if have_sink else "ocean"

    # --- flood raster -------------------------------------------------------
    ocean, bounds = to_web(WORK / "floodyear_ocean_mid.tif", Resampling.nearest, NEVER)
    sink = to_web(WORK / "floodyear_sinking_mid.tif", Resampling.nearest, NEVER)[0] if have_sink else ocean
    rgba = np.zeros(ocean.shape + (4,), np.uint8)
    rgba[..., 0], rgba[..., 1], rgba[..., 3] = sink, ocean, 255
    Image.fromarray(rgba, "RGBA").save(SITE_DATA / "flood.png", optimize=True)

    if have_sink:
        rate_web, _ = to_web(WORK / "sink_rate.tif", Resampling.bilinear, np.nan)
        Image.fromarray(colourise(rate_web), "RGBA").save(SITE_DATA / "sinking.png", optimize=True)

    # --- neighborhoods ------------------------------------------------------
    tracts = gpd.read_file(WORK / "tracts.geojson")
    simp = tracts.to_crs(CITY["utm_epsg"]).geometry.simplify(15).to_crs(4326)
    rstats = radar["tracts"] if radar else {}
    feats = []
    for (_, row), geom in zip(tracts.iterrows(), simp):
        f = flood["tracts"][row["GEOID"]]
        m = f[f"{main_mode}_mid"]
        p = {
            "id": row["GEOID"], "name": label(row), "city": row["city"], "tract": row["BASENAME"],
            "pop": int(row["pop"]),
            "fy_low": f[f"{main_mode}_low"]["year"], "fy_mid": m["year"], "fy_high": f[f"{main_mode}_high"]["year"],
            "fy_ocean": f["ocean_mid"]["year"],
            "share": m["share"], "people": m["people"],
            "people_ocean": f["ocean_mid"]["people"],
        }
        r = rstats.get(row["GEOID"])
        if r and r.get("rate_mm_yr") is not None:
            p["rate"] = r["rate_mm_yr"]
            p["rate_sigma"] = r["sigma_mm_yr"]
            p["rate_in_decade"] = round(r["rate_mm_yr"] * MM_YR_TO_IN_DECADE, 2)
            p["coverage"] = r["coverage"]
            # Share of the relative water-level rise at the flood year that is sinking.
            fy = p["fy_mid"]
            if fy is not None and fy > BASE_YEAR:
                land = r["rate_mm_yr"] / 1000 * (fy - BASE_YEAR)
                sea = water["ocean_rise_m"]["mid"][fy - BASE_YEAR]
                if land > 0 and land + sea > 0:
                    p["sink_share"] = round(land / (land + sea), 2)
            if p["fy_mid"] is not None and p["fy_ocean"] is not None:
                p["years_sooner"] = p["fy_ocean"] - p["fy_mid"]
        feats.append({"type": "Feature", "properties": p, "geometry": json.loads(gpd.GeoSeries([geom]).to_json())["features"][0]["geometry"]})

    def rnd(o):
        if isinstance(o, float):
            return round(o, 5)
        if isinstance(o, list):
            return [rnd(x) for x in o]
        if isinstance(o, dict):
            return {k: rnd(v) for k, v in o.items()}
        return o

    (SITE_DATA / "tracts.geojson").write_text(json.dumps(rnd({"type": "FeatureCollection", "features": feats}), separators=(",", ":")))

    if radar and (WORK / "series.json").exists():
        (SITE_DATA / "series.json").write_text((WORK / "series.json").read_text())

    # --- city summary -------------------------------------------------------
    n_slider = SLIDER_END_YEAR - BASE_YEAR + 1
    city = {
        "id": CITY["id"], "name": CITY["name"], "short_name": CITY["short_name"],
        "base_year": BASE_YEAR, "slider_end_year": SLIDER_END_YEAR,
        "population": int(tracts["pop"].sum()), "n_tracts": len(tracts),
        "tract_flood_share": TRACT_FLOOD_SHARE,
        "flood_bounds": bounds,
        "status": {"sinking": have_sink, "nisar": bool(nisar and nisar.get("ok"))},
        "water": {k: water[k] for k in ("station", "station_name", "mhhw_navd88_m", "htf_minor_navd88_m", "htf_recent_mean_days",
                                         "htf_recent_years", "htf_days", "ar6_gauge_vlm_mm_yr", "scenarios")},
        "ocean_rise_m": {k: v[:n_slider] for k, v in water["ocean_rise_m"].items()},
        "people": {k: v["people"][:n_slider] for k, v in flood["city"].items()},
        "land_km2": {k: v["land_km2"][:n_slider] for k, v in flood["city"].items()},
        "step_years": flood["step_years"],
        "ramp": [[v, "#%02x%02x%02x" % c] for v, c in RAMP],
        "gps": gps,
        "radar": {k: v for k, v in radar.items() if k != "tracts"} if radar else None,
        "nisar": nisar,
    }
    (SITE_DATA / "city.json").write_text(json.dumps(rnd(city), separators=(",", ":")))
    write_sources_md()
    for f in sorted(SITE_DATA.iterdir()):
        print(f"{f.name:16s} {f.stat().st_size / 1e6:6.2f} MB")
    with_year = sum(1 for f in feats if f["properties"]["fy_mid"] is not None)
    print(f"{len(feats)} neighborhoods, {with_year} reach regular flooding by 2150 (mid); sinking data: {have_sink}")


if __name__ == "__main__":
    main()
