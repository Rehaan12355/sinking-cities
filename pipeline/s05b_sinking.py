"""Step 5b: turn the OPERA DISP-S1 history into sinking rates.

1. Chain the displacement files into one history per 90 m cell. Each file gives
   motion since a reference date, and the reference date moves forward every few
   months, so each file is added to the history at its own reference date.
2. Remove the study-area median from every date. Radar measures motion relative
   to a reference, and this also removes most of the weather signal a date shares.
3. Convert line-of-sight motion to vertical, assuming the ground moves straight
   up or down, using NASA's line-of-sight geometry layer for the same frame.
   Dates far noisier than the rest are dropped.
4. Fit a straight line through each cell's history: the slope is the rate.
5. Tie the rates to GPS: one constant is added so the radar matches the median of
   the GPS stations inside the study area that have a well-determined rate. What
   is left over is reported as the radar-GPS disagreement and is folded into
   every rate's uncertainty. Stations outside the study area are listed too, but
   not used: step 2 references the radar to this area only, so it drifts further out.

Outputs (data/work): sink_rate.tif and sink_sigma.tif on the flood-model grid
(mm/yr, positive = sinking), radar.json (per-neighborhood rates and the GPS
check) and series.json (monthly ground height per neighborhood).
"""
import json
import warnings

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from scipy import ndimage

from config import CITY, RAW, WORK

OPERA = WORK / "opera"
BLOCK = 3
MIN_EPOCH_SHARE = 0.8      # a cell needs data on this share of dates to get a rate
REF_EPOCH_SHARE = 0.98     # cells used for the per-date median
GPS_MIN_PIXELS = 20        # good 30 m pixels needed around a GPS station
GPS_MAX_SIGMA = 1.5        # mm/yr; GPS rates less certain than this are listed but not used for the tie
EPOCH_REJECT = 3.0         # dates with more than this many times the typical scatter are dropped
SMOOTH_PX = 3              # 270 m Gaussian used for the flood-model rate grid
FILL_PX = 15               # 1.35 km Gaussian used to bridge radar gaps
MIN_TRACT_COVERAGE = 0.05  # below this a neighborhood is reported as "no radar measurement"


def decimal_year(d):
    d = np.datetime64(f"{d[:4]}-{d[4:6]}-{d[6:]}")
    y = d.astype("datetime64[Y]")
    return 1970 + y.astype(int) + (d - y).astype("timedelta64[D]").astype(int) / 365.25


def fit_rate(t, y):
    """Least-squares slope and its formal standard error along axis 0 (NaN-aware)."""
    ok = np.isfinite(y)
    n = ok.sum(axis=0)
    tt = np.where(ok, t.reshape(-1, *[1] * (y.ndim - 1)), 0.0)
    yy = np.where(ok, y, 0.0)
    nn = np.maximum(n, 1)
    tm, ym = tt.sum(0) / nn, yy.sum(0) / nn
    dt = np.where(ok, tt - tm, 0.0)
    sxx = (dt**2).sum(0)
    with np.errstate(invalid="ignore", divide="ignore"):
        slope = (dt * np.where(ok, yy - ym, 0.0)).sum(0) / sxx
        resid = np.where(ok, yy - ym - slope * dt, 0.0)
        se = np.sqrt((resid**2).sum(0) / np.maximum(n - 2, 1) / sxx)
    return slope, se, n


def smooth_fill(a, sigma):
    """Gaussian average that ignores gaps (normalised convolution)."""
    ok = np.isfinite(a)
    num = ndimage.gaussian_filter(np.where(ok, a, 0.0), sigma, mode="constant")
    den = ndimage.gaussian_filter(ok.astype("float64"), sigma, mode="constant")
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0.05, num / den, np.nan), den


def main():
    files = sorted(OPERA.glob("*.npz"))
    meta = [np.load(f) for f in files]
    orbit = json.loads(str(meta[0]["ident"])).get("orbit_pass_direction", "").lower()
    win = json.loads(str(meta[0]["window"]))
    sec = [str(m["sec_date"]) for m in meta]
    ref = [str(m["ref_date"]) for m in meta]
    t = np.array([decimal_year(d) for d in sec])
    nt = len(files)
    h, w = meta[0]["disp"].shape
    gps = json.loads((WORK / "gps.json").read_text())
    print(f"{nt} dates, {sec[0]} to {sec[-1]}, 90 m grid {w}x{h}")

    # --- 1. chain files into one history (metres, line of sight) ------------
    cum = np.full((nt, h, w), np.nan, "float32")
    gcum = np.full((nt, len(gps)), np.nan)
    count = np.zeros((h, w), "float32")
    gpx = np.zeros(len(gps))
    index = {d: i for i, d in enumerate(sec)}
    first_ref = ref[0]
    for i, m in enumerate(meta):
        if ref[i] == first_ref:
            base, gbase = 0.0, 0.0
        elif ref[i] in index:
            base, gbase = cum[index[ref[i]]], gcum[index[ref[i]]]
        else:
            raise SystemExit(f"{sec[i]}: reference date {ref[i]} is missing from the stack")
        cum[i] = m["disp"] + base
        gcum[i] = m["gps"].astype("float64") + gbase
        count += m["n"]
        gpx += m["gps_n"]
    count /= nt
    gpx /= nt

    # --- 2. remove the study-area median on every date ----------------------
    valid_share = np.isfinite(cum).mean(axis=0)
    ref_cells = valid_share >= REF_EPOCH_SHARE
    print(f"cells with data on >= {MIN_EPOCH_SHARE:.0%} of dates: {(valid_share >= MIN_EPOCH_SHARE).sum():,}; reference cells: {ref_cells.sum():,}")
    med = np.array([np.nanmedian(c[ref_cells]) for c in cum])
    cum -= med[:, None, None].astype("float32")
    gcum -= med[:, None]

    # Drop dates that are far noisier than the rest (storms, processing glitches):
    # a date is rejected when its scatter about a first straight-line fit is more
    # than EPOCH_REJECT times the typical date's scatter.
    sample = cum[:, ref_cells]
    v0, _, _ = fit_rate(t, sample)
    r0 = sample - np.nanmean(sample, axis=0) - v0 * (t[:, None] - t.mean())
    scatter = 1.4826 * np.nanmedian(np.abs(r0 - np.nanmedian(r0, axis=1, keepdims=True)), axis=1)
    bad = scatter > EPOCH_REJECT * np.median(scatter)
    rejected = [f"{sec[i][:4]}-{sec[i][4:6]}-{sec[i][6:]}" for i in np.flatnonzero(bad)]
    print(f"typical scatter of one date {np.median(scatter) * 1000:.1f} mm (line of sight); rejected {bad.sum()} noisy dates: {rejected}")
    cum[bad] = np.nan
    gcum[bad] = np.nan
    del sample, r0

    # --- 3. line of sight -> vertical ---------------------------------------
    with rasterio.open(RAW / f"opera_{CITY['opera_frame']}_los_enu.tif") as src:
        assert (src.transform.c, src.transform.f) == (win["x0"], win["y0"]), "geometry layer is on a different grid"
        up = src.read(3, window=((win["r0"], win["r1"]), (win["c0"], win["c1"])))
    up = np.where(up > 0, up, np.nan)
    up3 = np.nanmean(up.reshape(h, BLOCK, w, BLOCK), axis=(1, 3)).astype("float32")
    up3 = np.where(np.isfinite(up3), up3, np.nanmedian(up3))
    print(f"line-of-sight vertical component over the area: {np.nanmin(up3):.3f} to {np.nanmax(up3):.3f} (incidence {np.degrees(np.arccos(np.nanmax(up3))):.1f} to {np.degrees(np.arccos(np.nanmin(up3))):.1f} deg)")
    x0, y0, px = win["x0"] + win["c0"] * win["dx"], win["y0"] + win["r0"] * win["dy"], win["dx"] * BLOCK
    tf90 = from_origin(x0, y0, px, px)
    crs = f"EPSG:{win['epsg']}"

    def cell_of(g):
        from pyproj import Transformer
        x, y = Transformer.from_crs(4326, win["epsg"], always_xy=True).transform(g["lon"], g["lat"])
        c, r = int((x - x0) / px), int((y0 - y) / px)
        return (r, c) if 0 <= r < h and 0 <= c < w else None

    # --- 4. rates (mm/yr, vertical, positive = up for now) ------------------
    v, se, n = fit_rate(t, cum)
    keep = n >= MIN_EPOCH_SHARE * (nt - bad.sum())
    v_up = np.where(keep, v / up3 * 1000, np.nan)
    se_up = np.where(keep, se / up3 * 1000, np.nan)

    # --- 5. GPS tie ----------------------------------------------------------
    up_med = float(np.nanmedian(up3))
    check = []
    for k, g in enumerate(gps):
        if gpx[k] < GPS_MIN_PIXELS or np.isfinite(gcum[:, k]).sum() < MIN_EPOCH_SHARE * (nt - bad.sum()):
            continue
        cell = cell_of(g)
        u = float(up3[cell]) if cell else up_med
        gv, gse, _ = fit_rate(t, gcum[:, k:k + 1])
        bw, bs, be, bn = CITY["bbox"]
        used = bool(bw <= g["lon"] <= be and bs <= g["lat"] <= bn and g["up_sigma_mm_yr"] <= GPS_MAX_SIGMA)
        check.append({"id": g["id"], "gps_mm_yr": g["up_mm_yr"], "gps_sigma": g["up_sigma_mm_yr"], "used": used,
                      "raw": float(gv[0] / u * 1000), "years": f"{g['start']:.0f}-{g['end']:.0f}", "pixels": round(float(gpx[k]))})
    diffs = np.array([c["gps_mm_yr"] - c["raw"] for c in check])
    used = np.array([c["used"] for c in check])
    offset = float(np.median(diffs[used]))
    resid = diffs - offset
    rms = float(np.sqrt(np.mean(resid[used] ** 2)))
    rms_all = float(np.sqrt(np.mean(resid**2)))
    mad = float(1.4826 * np.median(np.abs(resid[used])))
    # With only a few stations the leftover scatter can look better than it is.
    # The tie is never treated as more certain than the GPS rates themselves.
    gps_own = float(np.median([c["gps_sigma"] for c, u in zip(check, used) if u]))
    tie_sigma = max(rms, gps_own)
    for c in check:
        c["insar_mm_yr"] = round(c.pop("raw") + offset, 2)
    print(f"GPS tie: {used.sum()} of {len(check)} stations, offset {offset:+.2f} mm/yr, RMS difference {rms:.2f} (all stations {rms_all:.2f}), robust spread {mad:.2f} mm/yr")
    for c in check:
        print("  ", c)

    sink = -(v_up + offset)                       # positive = sinking
    sigma = np.sqrt(se_up**2 + tie_sigma**2)

    # --- flood-model grid ----------------------------------------------------
    sm, _ = smooth_fill(sink, SMOOTH_PX)
    wide, _ = smooth_fill(sink, FILL_PX)
    area_median = float(np.nanmedian(sink))
    spread = float(1.4826 * np.nanmedian(np.abs(sink - area_median)))
    filled = np.where(np.isfinite(sm), sm, np.where(np.isfinite(wide), wide, area_median))
    sig_sm, _ = smooth_fill(sigma, SMOOTH_PX)
    # Where the radar has a gap the rate is borrowed from nearby ground, so the
    # uncertainty there also carries the spread of rates across the area.
    sig_filled = np.where(np.isfinite(sm), sig_sm, np.sqrt(tie_sigma**2 + spread**2))
    with rasterio.open(WORK / "dem.tif") as dem:
        prof = dem.profile
        for name, arr in (("sink_rate", filled), ("sink_sigma", sig_filled)):
            out = np.zeros((dem.height, dem.width), "float32")
            reproject(arr.astype("float32"), out, src_transform=tf90, src_crs=crs, dst_transform=dem.transform, dst_crs=dem.crs,
                      resampling=Resampling.bilinear, dst_nodata=np.nan)
            out = np.where(np.isfinite(out), out, area_median if name == "sink_rate" else np.sqrt(tie_sigma**2 + spread**2)).astype("float32")
            p = dict(prof, dtype="float32", nodata=None, compress="deflate", tiled=True, count=1)
            with rasterio.open(WORK / f"{name}.tif", "w", **p) as dst:
                dst.write(out, 1)
    p90 = dict(driver="GTiff", height=h, width=w, count=1, dtype="float32", crs=crs, transform=tf90, nodata=np.nan, compress="deflate")
    with rasterio.open(WORK / "sink_rate_measured.tif", "w", **p90) as dst:   # measured cells only, for the map picture
        dst.write(np.where(np.isfinite(sm) & (ndimage.gaussian_filter(np.isfinite(sink).astype("float32"), 1) > 0.2), sm, np.nan).astype("float32"), 1)

    # --- neighborhoods -------------------------------------------------------
    tracts = gpd.read_file(WORK / "tracts.geojson").to_crs(crs)
    tr = rasterize(((g, i + 1) for i, g in enumerate(tracts.geometry)), out_shape=(h, w), transform=tf90, dtype="int32")
    with rasterio.open(WORK / "sea.tif") as sea_src:   # 1 = open water on the flood grid
        landfrac = np.zeros((h, w), "float32")
        reproject((1 - sea_src.read(1)).astype("float32"), landfrac, src_transform=sea_src.transform, src_crs=sea_src.crs,
                  dst_transform=tf90, dst_crs=crs, resampling=Resampling.average)
    land = landfrac > 0.5
    months = np.array([f"{d[:4]}-{d[4:6]}" for d in sec])
    all_months = [str(m) for m in np.arange(np.datetime64(months[0], "M"), np.datetime64(months[-1], "M") + 1)]
    mt = np.array([int(m[:4]) + (int(m[5:]) - 0.5) / 12 for m in all_months])
    out_tracts, series = {}, {}
    vert = cum / up3 * 1000        # mm, relative to the area median
    for i, geoid in enumerate(tracts["GEOID"]):
        cells = tr == i + 1
        n_land = int((cells & land).sum())
        good = cells & np.isfinite(sink)
        cov = float(good.sum() / max(n_land, 1)) if n_land else 0.0
        if good.sum() < 3 or cov < MIN_TRACT_COVERAGE:
            out_tracts[geoid] = {"rate_mm_yr": None, "sigma_mm_yr": None, "coverage": round(min(cov, 1.0), 2)}
            continue
        wts = count[good]
        rate = float(np.average(sink[good], weights=wts))
        # Formal error shrinks with many cells; the GPS disagreement does not.
        sig = float(np.sqrt(np.mean(se_up[good] ** 2) / max(good.sum() / 9, 1) + tie_sigma**2))
        out_tracts[geoid] = {"rate_mm_yr": round(rate, 2), "sigma_mm_yr": round(sig, 2), "coverage": round(min(cov, 1.0), 2), "cells": int(good.sum())}
        # Monthly ground height: neighborhood mean on each date, GPS tie added back, then monthly means.
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)   # rejected dates are all-NaN
            s = np.nanmean(vert[:, good], axis=1) + offset * (t - t[0])
        monthly = np.array([np.nanmean(s[months == m]) if (months == m).any() else np.nan for m in all_months])
        okm = np.isfinite(monthly)
        monthly = np.interp(mt, mt[okm], monthly[okm])
        # Five-month running median (shorter at the ends): steadies single noisy months without moving the trend.
        monthly = np.array([np.median(monthly[max(0, j - 2): j + 3]) for j in range(len(monthly))])
        series[geoid] = monthly
    # The first month is noisy on its own, so anchor each history on its fitted line there.
    for geoid, m in series.items():
        a = np.polyfit(mt, m, 1)
        m = m - np.polyval(a, mt[0])
        series[geoid] = [round(float(x), 1) for x in m]
    rates = np.array([d["rate_mm_yr"] for d in out_tracts.values() if d["rate_mm_yr"] is not None])
    print(f"neighborhoods with a rate: {len(rates)} of {len(tracts)}; median {np.median(rates):.2f}, 5th-95th pct {np.percentile(rates, 5):.2f} to {np.percentile(rates, 95):.2f} mm/yr (positive = sinking)")

    n_used = int(used.sum())
    in_tracts = land & (tr > 0)
    radar = {
        "product": "NASA OPERA L3 DISP-S1 v1", "frame": CITY["opera_frame"], "orbit": orbit, "band": "C", "polarization": "VV",
        "source_satellite": "Copernicus Sentinel-1 (ESA)",
        "n_dates": nt, "dates_rejected": rejected, "first_date": f"{sec[0][:4]}-{sec[0][4:6]}-{sec[0][6:]}", "last_date": f"{sec[-1][:4]}-{sec[-1][4:6]}-{sec[-1][6:]}",
        "reference_date": f"{first_ref[:4]}-{first_ref[4:6]}-{first_ref[6:]}",
        "span_years": round(float(t[-1] - t[0]), 2),
        "cells_measured": int(np.isfinite(sink).sum()), "land_coverage": round(float((np.isfinite(sink) & in_tracts).sum() / in_tracts.sum()), 3),
        "area_median_mm_yr": round(area_median, 2), "area_spread_mm_yr": round(spread, 2),
        "gps_offset_mm_yr": round(offset, 2), "gps_rms_mm_yr": round(rms, 2), "tie_sigma_mm_yr": round(tie_sigma, 2), "gps_rms_all_mm_yr": round(rms_all, 2), "gps_robust_spread_mm_yr": round(mad, 2), "gps_n_used": n_used,
        "gps_check": check,
        "gps_summary": (f"One constant ties the radar to the {n_used} GPS stations inside the map that have a well-determined rate. After that, radar and GPS "
                        f"vertical rates differ by {rms:.1f} mm a year (root mean square). "
                        + (f"That disagreement is included in every rate's uncertainty. " if tie_sigma == rms else
                           f"With so few stations that figure flatters the radar, so every rate's uncertainty uses the GPS stations' own uncertainty instead, {tie_sigma:.1f} mm a year. ")
                        + 
                        f"Counting all {len(check)} stations, including those outside the map or with a very uncertain GPS rate (marked *), the difference is {rms_all:.1f} mm a year. "
                        f"Some GPS records ended before the radar record began in {sec[0][:4]}, so part of the difference is the two instruments measuring different years."),
        "tracts": out_tracts,
    }
    (WORK / "radar.json").write_text(json.dumps(radar, indent=1))
    (WORK / "series.json").write_text(json.dumps({"dates": all_months, "span_years": round(float(mt[-1] - mt[0]), 2), "tracts": series}, separators=(",", ":")))


if __name__ == "__main__":
    main()
