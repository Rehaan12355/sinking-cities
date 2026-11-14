"""Step 6: when does each piece of ground start flooding regularly?

For every 10 m cell we find the first year its ground height drops below the
high-tide-flood waterline:

    ground(year) = lidar height - sinking_rate * (year - 2026)     [NASA radar]
    water(year)  = NOAA flood threshold + ocean rise since 2026     [NASA / IPCC AR6]

"Regular flooding" therefore means: flooding at least as often as the NOAA
threshold elevation floods today (see htf_recent_mean_days in water.json).

A cell only counts once rising water can actually reach it overland from the
bay or ocean (connected cells), so isolated inland hollows do not fill up.

Three futures are run (low / mid / high sea level; sinking rate -1 sigma / best /
+1 sigma), each with and without sinking so the site can show what sinking adds.
"""
import json

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from scipy import ndimage

from config import BASE_YEAR, CITY, GRID_M, TRACT_FLOOD_SHARE, WORK

NEVER = 255
MIN_SEA_KM2 = 0.5   # tidal water bodies smaller than this are not treated as open water
SCEN = ("low", "mid", "high")
EIGHT = np.ones((3, 3), bool)


def first_flood_index(dem_c, sink_m_yr, waterline):
    """Index of the first year each candidate cell is at or below the waterline."""
    fy = np.full(dem_c.shape, NEVER, np.uint8)
    unset = np.ones(dem_c.shape, bool)
    for i, wl in enumerate(waterline):
        hit = unset & (dem_c - sink_m_yr * i <= wl)
        fy[hit] = i
        unset &= ~hit
    return fy


def connect(fy2d, sea, n_years):
    """Raise each cell's flood year to the year water can first reach it from the sea."""
    out = np.full(fy2d.shape, NEVER, np.uint8)
    reached = sea.copy()
    counts = np.bincount(fy2d.ravel(), minlength=256)
    for i in range(n_years):
        if counts[i] == 0:
            continue
        reached = ndimage.binary_propagation(reached, structure=EIGHT, mask=(fy2d <= i) | sea)
        new = reached & (out == NEVER) & ~sea
        out[new] = i
    return out


def main():
    water = json.loads((WORK / "water.json").read_text())
    years = np.array(water["years"])
    n = len(years)
    thr = water["htf_minor_navd88_m"]
    mhhw = water["mhhw_navd88_m"]

    with rasterio.open(WORK / "dem.tif") as src:
        dem = src.read(1)
        transform, crs = src.transform, src.crs
    h, w = dem.shape

    # Open water: cells at or below today's daily high tide (or no elevation data),
    # in bodies big enough to be the bay, rivers and ocean.
    wet = ~np.isfinite(dem) | (dem <= mhhw)
    lab, _ = ndimage.label(wet, structure=EIGHT)
    sizes = np.bincount(lab.ravel())
    big = sizes >= MIN_SEA_KM2 * 1e6 / GRID_M**2
    big[0] = False
    sea = big[lab]
    del lab
    land = np.isfinite(dem) & ~sea & (dem > mhhw)

    # Sinking rate (mm/yr, positive = down) from the radar step, if it has run.
    rate_path = WORK / "sink_rate.tif"
    have_rate = rate_path.exists()
    if have_rate:
        with rasterio.open(rate_path) as src:
            rate = src.read(1) / 1000.0
        with rasterio.open(WORK / "sink_sigma.tif") as src:
            sigma = src.read(1) / 1000.0
        assert rate.shape == dem.shape, "sinking raster is not on the analysis grid"
    modes = ("ocean", "sinking") if have_rate else ("ocean",)

    # Neighborhood and census-block index rasters, and people per cell.
    tracts = gpd.read_file(WORK / "tracts.geojson").to_crs(crs)
    blocks = gpd.read_file(WORK / "blocks.gpkg").to_crs(crs)
    tr_idx = rasterize(((g, i + 1) for i, g in enumerate(tracts.geometry)), out_shape=(h, w), transform=transform, dtype="int32")
    bl_idx = rasterize(((g, i + 1) for i, g in enumerate(blocks.geometry)), out_shape=(h, w), transform=transform, dtype="int32")
    # Spread each block's residents evenly over its dry-land cells.
    bl_land = np.where(land, bl_idx, 0)
    cells = np.bincount(bl_land.ravel(), minlength=len(blocks) + 1).astype("float64")
    bpop = np.concatenate([[0], blocks["pop"].to_numpy()]).astype("float64")
    per_cell = np.divide(bpop, cells, out=np.zeros_like(bpop), where=cells > 0)
    per_cell[0] = 0
    pop_px = per_cell[bl_land].astype("float32")
    placed = float(pop_px.sum())
    print(f"people placed on dry-land cells: {placed:,.0f} of {bpop.sum():,.0f}")

    max_rise = max(water["ocean_rise_m"]["high"])
    max_sink = float(np.nanpercentile(rate + sigma, 99.9)) * n if have_rate else 0.0
    cand = land & (dem <= thr + max_rise + max(max_sink, 0) + 0.05)
    ci = np.flatnonzero(cand.ravel())
    dem_c = dem.ravel()[ci]
    print(f"grid {w}x{h}, land cells {land.sum():,}, candidate cells {len(ci):,}, sea cells {sea.sum():,}")

    tr_flat = np.where(land, tr_idx, 0).ravel()
    tr_land_cells = np.bincount(tr_flat, minlength=len(tracts) + 1).astype("float64")
    tr_pop_placed = np.bincount(tr_flat, weights=pop_px.ravel(), minlength=len(tracts) + 1)
    nt = len(tracts) + 1

    result = {"years": years.tolist(), "modes": list(modes), "city": {}, "tracts": {}}
    grids = {}
    for mode in modes:
        for sc in SCEN:
            waterline = thr + np.array(water["ocean_rise_m"][sc])
            if mode == "ocean":
                sink = 0.0
            else:
                r, s = rate.ravel()[ci], sigma.ravel()[ci]
                sink = {"low": r - s, "mid": r, "high": r + s}[sc]
            fy = np.full(h * w, NEVER, np.uint8)
            fy[ci] = first_flood_index(dem_c, sink, waterline)
            cfy = connect(fy.reshape(h, w), sea, n)
            grids[(mode, sc)] = cfy
            flat = cfy.ravel()
            ok = (flat != NEVER) & (tr_flat > 0)
            key = tr_flat[ok].astype(np.int64) * n + flat[ok]
            cells_by = np.bincount(key, minlength=nt * n).reshape(nt, n).cumsum(axis=1)
            pop_by = np.bincount(key, weights=pop_px.ravel()[ok], minlength=nt * n).reshape(nt, n).cumsum(axis=1)
            share = cells_by / np.maximum(tr_land_cells[:, None], 1)
            result["city"][f"{mode}_{sc}"] = {
                "people": np.round(pop_by.sum(axis=0)).astype(int).tolist(),
                "land_km2": np.round(cells_by.sum(axis=0) * GRID_M**2 / 1e6, 2).tolist(),
            }
            for t in range(1, nt):
                geoid = tracts["GEOID"].iloc[t - 1]
                d = result["tracts"].setdefault(geoid, {"land_cells": int(tr_land_cells[t]), "pop_placed": round(float(tr_pop_placed[t]))})
                over = np.flatnonzero(share[t] >= TRACT_FLOOD_SHARE)
                d[f"{mode}_{sc}"] = {
                    "year": int(years[over[0]]) if len(over) else None,
                    "share": np.round(share[t, ::5], 3).tolist(),     # every 5 years
                    "people": np.round(pop_by[t, ::5]).astype(int).tolist(),
                }
            p = result["city"][f"{mode}_{sc}"]["people"]
            print(f"{mode:8s} {sc:4s} people on regularly flooded land: now {p[0]:,}  2050 {p[2050 - BASE_YEAR]:,}  2100 {p[2100 - BASE_YEAR]:,}")

    result["step_years"] = years[::5].tolist()
    result["people_placed"] = round(placed)
    (WORK / "flood.json").write_text(json.dumps(result))
    prof = dict(driver="GTiff", height=h, width=w, count=1, dtype="uint8", crs=crs, transform=transform, nodata=NEVER, compress="deflate", tiled=True)
    outside = tr_idx == 0
    for (mode, sc), g in grids.items():
        if sc == "mid" or mode == "sinking":
            g[outside] = NEVER  # the map only shows the neighborhoods we counted
            with rasterio.open(WORK / f"floodyear_{mode}_{sc}.tif", "w", **prof) as dst:
                dst.write(g, 1)
    with rasterio.open(WORK / "sea.tif", "w", **prof) as dst:
        dst.write(sea.astype("uint8"), 1)


if __name__ == "__main__":
    main()
