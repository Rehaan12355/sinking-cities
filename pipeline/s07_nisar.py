"""Step 7: the newest look, from NISAR.

NISAR (NASA-ISRO, L-band) has imaged the study area every 12 days since June 2026.
We read the Geocoded Unwrapped Interferograms (GUNW) of one track that covers
the whole study area and add the consecutive pairs into one measurement of
ground motion over the summer and autumn of 2026.

Each file is about 2.2 GB; only the study-area window of five layers is read,
straight from the archive.

Four months is far too short to measure sinking of a few millimetres a year, so
this step does not produce rates. It answers two honest questions:
- Is what NISAR saw consistent with the long-term OPERA rates?
- How much more of the ground can L-band NISAR measure than C-band Sentinel-1?

Needs a free NASA Earthdata login in ~/.netrc (never committed).
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import earthaccess
import geopandas as gpd
import h5py
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import from_origin
from PIL import Image
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds

from common import record_source
from config import CITY, SITE_DATA, WORK

SHORT_NAME = "NISAR_L2_GUNW_PROVISIONAL_V1"
TRACK_FRAME = CITY["nisar_track_frame"]   # one track and frame that covers the whole study area
POL = "HH"
C = 299_792_458.0
OUT = WORK / "nisar"
OUT.mkdir(parents=True, exist_ok=True)


def pair_dates(url):
    m = re.search(r"_(\d{8})T\d{6}_\d{8}T\d{6}_(\d{8})T\d{6}_\d{8}T\d{6}_", url)
    return m.group(1), m.group(2)


def fetch_pair(url, fs):
    ref, sec = pair_dates(url)
    out = OUT / f"{ref}_{sec}.npz"
    if out.exists():
        return out
    with fs.open(url, block_size=4 * 1024 * 1024, cache_type="blockcache") as f, h5py.File(f, "r") as h:
        g = h["science/LSAR/GUNW/grids/frequencyA"]
        u = g[f"unwrappedInterferogram/{POL}"]
        epsg = int(u["projection"][()])
        x, y = u["xCoordinates"][:], u["yCoordinates"][:]
        w, s, e, n = CITY["bbox"]
        xs, ys = Transformer.from_crs(4326, epsg, always_xy=True).transform([w, e, w, e], [s, s, n, n])
        c0, c1 = np.searchsorted(x, [min(xs), max(xs)])
        r0, r1 = np.searchsorted(-y, [-max(ys), -min(ys)])
        sl = (slice(r0, r1), slice(c0, c1))
        rg = h["science/LSAR/GUNW/metadata/radarGrid"]
        gx, gy, hts = rg["xCoordinates"][:], rg["yCoordinates"][:], rg["heightAboveEllipsoid"][:]
        k = int(np.argmin(np.abs(hts)))   # the height layer nearest the ground of a coastal city
        gc = slice(*np.searchsorted(gx, [min(xs), max(xs)]))
        gr = slice(*np.searchsorted(-gy, [-max(ys), -min(ys)]))
        ident = h["science/LSAR/identification"]
        np.savez_compressed(
            out,
            phase=u["unwrappedPhase"][sl], coherence=u["coherenceMagnitude"][sl], components=u["connectedComponents"][sl],
            ionosphere=u["ionospherePhaseScreen"][sl], mask=g["unwrappedInterferogram/mask"][sl],
            incidence=float(np.nanmean(rg["incidenceAngle"][k, gr, gc])),
            frequency=float(g["centerFrequency"][()]), epsg=epsg, x0=float(x[c0] - 40), y0=float(y[r0] + 40), px=80.0,
            ref=ref, sec=sec, granule=ident["granuleId"][()].decode(), doi=ident["productDoi"][()].decode(),
        )
    return out


def main():
    earthaccess.login(strategy="netrc")
    res = earthaccess.search_data(short_name=SHORT_NAME, bounding_box=CITY["bbox"], count=2000)
    urls = sorted({g.data_links()[0] for g in res if TRACK_FRAME in g.data_links()[0]}, key=pair_dates)
    # Keep one continuous chain of pairs: each pair starts where the last one ended.
    chain = []
    for u in urls:
        r, s = pair_dates(u)
        if not chain or pair_dates(chain[-1])[1] == r:
            chain.append(u)
        elif pair_dates(chain[-1]) == (r, s):
            chain[-1] = u            # a reprocessed copy of the same pair: keep the newest
    print(len(urls), "interferograms on this track;", len(chain), "form a continuous chain", pair_dates(chain[0])[0], "to", pair_dates(chain[-1])[1])
    fs = earthaccess.get_fsspec_https_session()
    with ThreadPoolExecutor(3) as ex:
        files = list(ex.map(lambda u: fetch_pair(u, fs), chain))
    pairs = [np.load(f) for f in files]
    p0 = pairs[0]
    h, w = p0["phase"].shape
    tf = from_origin(float(p0["x0"]), float(p0["y0"]), 80.0, 80.0)
    crs = f"EPSG:{int(p0['epsg'])}"
    wavelength = C / float(p0["frequency"])
    cos_inc = float(np.cos(np.radians(np.mean([float(p["incidence"]) for p in pairs]))))
    print(f"window {w}x{h} at 80 m, wavelength {wavelength * 100:.1f} cm, incidence {np.degrees(np.arccos(cos_inc)):.1f} deg")

    with rasterio.open(WORK / "sea.tif") as sea:
        landfrac = np.zeros((h, w), "float32")
        reproject((1 - sea.read(1)).astype("float32"), landfrac, src_transform=sea.transform, src_crs=sea.crs, dst_transform=tf, dst_crs=crs, resampling=Resampling.average)
    tracts = gpd.read_file(WORK / "tracts.geojson").to_crs(crs)
    tr = rasterize(((g, i + 1) for i, g in enumerate(tracts.geometry)), out_shape=(h, w), transform=tf, dtype="int32")
    # Lakes and other non-tidal water are not in the tidal water map, so NISAR's own
    # water mask (first digit of the low byte of its mask layer) removes them as well.
    nisar_water = ((p0["mask"] & 0xFF) // 100) == 1
    land = (landfrac > 0.5) & (tr > 0) & ~nisar_water
    with rasterio.open(WORK / "sink_measured.tif") as src:     # 1 = the cell has its own long-term Sentinel-1 rate
        s1 = np.zeros((h, w), "uint8")
        reproject(rasterio.band(src, 1), s1, dst_transform=tf, dst_crs=crs, resampling=Resampling.nearest)
    s1_meas = (s1 == 1) & land
    s1_share = float(s1_meas.sum() / land.sum())

    # Each pair: phase -> millimetres of vertical motion. The ionosphere screen that
    # ships with the product is removed, then a flat tilted plane, which takes out
    # most of the leftover atmosphere and orbit error (and any real region-wide tilt).
    yy, xx = np.mgrid[0:h, 0:w]
    total = np.zeros((h, w))
    n_ok = np.zeros((h, w), int)
    n_flag = np.zeros((h, w), int)
    coh_sum = np.zeros((h, w))
    info = []
    for p in pairs:
        phase = p["phase"] - p["ionosphere"]
        flagged = np.isfinite(p["phase"]) & (p["components"] > 0) & (p["components"] != 65535) & land   # the product's own "unwrapped" flag
        # The ionosphere screen sometimes carries its own unwrapping jump (tens of
        # radians). Cells where it sits far from the area's typical value are dropped.
        io = p["ionosphere"]
        io_med = np.nanmedian(io[flagged])
        io_mad = 1.4826 * np.nanmedian(np.abs(io[flagged] - io_med))
        ok = flagged & np.isfinite(io) & (np.abs(io - io_med) <= 5 * io_mad)
        # Positive phase is a longer path to the satellite, so motion towards it is negative phase.
        up = -phase * wavelength / (4 * np.pi) / cos_inc * 1000
        plane, *_ = np.linalg.lstsq(np.c_[xx[ok], yy[ok], np.ones(ok.sum())], up[ok], rcond=None)
        up = up - (plane[0] * xx + plane[1] * yy + plane[2])
        up = up - np.median(up[ok])
        total += np.where(ok, up, 0)
        n_ok += ok
        n_flag += flagged
        coh_sum += np.where(np.isfinite(p["coherence"]), p["coherence"], 0)
        info.append({"reference": str(p["ref"]), "secondary": str(p["sec"]), "granule": str(p["granule"]),
                     "land_measured": round(float(flagged.sum() / land.sum()), 3), "ionosphere_screen_rejected": round(float((flagged & ~ok).sum() / flagged.sum()), 3), "scatter_mm": round(float(1.4826 * np.median(np.abs(up[ok]))), 1)})
        print(info[-1]["reference"], info[-1]["secondary"], "land measured", info[-1]["land_measured"], "screen rejected", info[-1]["ionosphere_screen_rejected"], "scatter mm", info[-1]["scatter_mm"])
    full = n_ok == len(pairs)
    motion = np.where(full, total, np.nan)
    motion -= np.nanmedian(motion)
    d0, d1 = info[0]["reference"], info[-1]["secondary"]
    days = int((np.datetime64(f"{d1[:4]}-{d1[4:6]}-{d1[6:]}") - np.datetime64(f"{d0[:4]}-{d0[4:6]}-{d0[6:]}")).astype(int))

    # Compare with what the long-term OPERA rates predict for the same number of days.
    radar = json.loads((WORK / "radar.json").read_text())
    rows = []
    for i, geoid in enumerate(tracts["GEOID"]):
        cells = (tr == i + 1) & land
        good = cells & full
        r = radar["tracts"].get(geoid, {})
        if cells.sum() == 0:
            continue
        rows.append({"id": geoid, "nisar_cov": float(good.sum() / cells.sum()), "opera_cov": r.get("coverage", 0.0),
                     "nisar_mm": float(np.mean(motion[good])) if good.sum() >= 5 else None, "opera_rate": r.get("rate_mm_yr")})
    both = [r for r in rows if r["nisar_mm"] is not None and r["opera_rate"] is not None]
    nis = np.array([r["nisar_mm"] for r in both])
    exp = -(np.array([r["opera_rate"] for r in both]) - radar["area_median_mm_yr"]) * days / 365.25   # mm, relative to the area median
    diff = nis - exp
    spread = float(1.4826 * np.median(np.abs(nis - np.median(nis))))
    exp_range = float(np.percentile(exp, 95) - np.percentile(exp, 5))
    corr = float(np.corrcoef(nis, exp)[0, 1])
    nis_land = float(full.sum() / land.sum())
    per_pair = [i["land_measured"] for i in info]
    typical = float(np.median(per_pair))
    print(f"{days} days; NISAR neighborhood scatter {spread:.1f} mm; OPERA-expected range (5-95%) {exp_range:.2f} mm; correlation {corr:.2f}")
    print(f"land measured: NISAR typical pair {typical:.1%} (range {min(per_pair):.1%} to {max(per_pair):.1%}), every pair {nis_land:.1%}; OPERA {s1_share:.1%}")

    def month(d):
        return ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"][int(d[4:6]) - 1] + " " + d[:4]

    summary = (
        f"NISAR's L-band radar passed over {CITY['short_name']} {len(pairs) + 1} times between {month(d0)} and {month(d1)}. "
        f"Adding its {len(pairs)} consecutive interferograms gives the ground motion over those {days} days. "
        f"Over that time the long-term rates predict that neighborhoods should differ from each other by only about {exp_range:.1f} mm. "
        f"NISAR's neighborhood values scatter by about {spread:.0f} mm. That scatter is the atmosphere and ionosphere delaying the radar signal, not the ground moving, "
        f"so NISAR cannot yet confirm or contradict the long-term rates. It needs a longer record before the noise averages down to millimeters. "
    )
    if typical > s1_share + 0.10:   # only call it a gain when it clearly is one
        summary += (
            f"What NISAR shows already is reach. In a typical 12-day pair it returned a measurement over {typical:.0%} of the land in these neighborhoods "
            f"(between {min(per_pair):.0%} and {max(per_pair):.0%}), where the Sentinel-1 record gives a reliable long-term rate over {s1_share:.0%}. "
            f"Each figure uses its own product's quality flags, so this is not a like-for-like test, but it points to NISAR filling in marsh edges and wooded ground that are blank today."
        )
    else:
        summary += (
            f"In a typical 12-day pair NISAR returned a measurement over {typical:.0%} of the land in these neighborhoods, "
            f"and the Sentinel-1 record gives a reliable long-term rate over {s1_share:.0%}. Each figure uses its own product's quality flags, "
            f"so the two are about level here: in a built-up city both radars see most of the ground."
        )
    out = {
        "ok": True, "summary": summary, "product": "NISAR L2 GUNW (provisional)", "doi": str(p0["doi"]), "track_frame": TRACK_FRAME.strip("_"),
        "band": "L", "polarization": POL, "first_date": d0, "last_date": d1, "days": days, "n_pairs": len(pairs),
        "neighborhood_scatter_mm": round(spread, 1), "expected_range_mm": round(exp_range, 2), "correlation": round(corr, 2),
        "land_measured_typical_pair": round(typical, 3), "land_measured_every_pair": round(nis_land, 3), "opera_land_measured": round(s1_share, 3),
        "n_neighborhoods_compared": len(both),
        "pairs": info,
    }

    # --- where each radar can measure the ground -----------------------------
    # NISAR: the product returned an unwrapped measurement in at least two thirds of
    # its pairs. Sentinel-1: the cell has its own long-term rate from step 5b.
    need = int(np.ceil(len(pairs) * 2 / 3))
    nis_meas = (n_flag >= need) & land
    cls = np.zeros((h, w), "uint8")           # 0 = not land in these neighborhoods
    cls[land] = 4                             # neither
    cls[s1_meas & ~nis_meas] = 3              # Sentinel-1 only
    cls[nis_meas & ~s1_meas] = 2              # NISAR only
    cls[nis_meas & s1_meas] = 1               # both
    n_land = int(land.sum())
    share = {k: round(float((cls == v).sum() / n_land), 3) for k, v in (("both", 1), ("nisar_only", 2), ("sentinel1_only", 3), ("neither", 4))}
    print("land by radar:", share, f"(NISAR counted when measured in {need} of {len(pairs)} pairs)")
    tract_cov = {}
    for i, geoid in enumerate(tracts["GEOID"]):
        cells = (tr == i + 1) & land
        if cells.sum():
            tract_cov[geoid] = [round(float((nis_meas & cells).sum() / cells.sum()), 2), round(float((s1_meas & cells).sum() / cells.sum()), 2)]
    tfw, ww, hw = calculate_default_transform(crs, "EPSG:3857", w, h, *rasterio.transform.array_bounds(h, w, tf))
    web = np.zeros((hw, ww), "uint8")
    reproject(cls, web, src_transform=tf, src_crs=crs, dst_transform=tfw, dst_crs="EPSG:3857", resampling=Resampling.nearest)
    colours = {1: (63, 160, 150), 2: (255, 200, 87), 3: (120, 135, 160), 4: (58, 63, 69)}   # both, NISAR only, Sentinel-1 only, neither
    rgba = np.zeros((hw, ww, 4), np.uint8)
    for v, c in colours.items():
        rgba[web == v] = (*c, 255)
    Image.fromarray(rgba, "RGBA").save(SITE_DATA / "nisar.png", optimize=True)
    out["coverage"] = dict(share, pairs_needed=need, colours={k: "#%02x%02x%02x" % colours[v] for k, v in (("both", 1), ("nisar_only", 2), ("sentinel1_only", 3), ("neither", 4))})
    out["coverage_bounds"] = [round(v, 6) for v in transform_bounds("EPSG:3857", "EPSG:4326", *rasterio.transform.array_bounds(hw, ww, tfw))]
    out["tract_coverage"] = tract_cov

    (WORK / "nisar.json").write_text(json.dumps(out, indent=1))
    record_source(
        "nisar_gunw",
        title=f"NISAR L2 Geocoded Unwrapped Interferograms (provisional), track/frame {TRACK_FRAME.strip("_")}, {len(pairs)} pairs {d0} to {d1}, study-area subset",
        url="https://search.asf.alaska.edu/#/?dataset=NISAR&productTypes=GUNW",
        licence="NASA open data (CC0); NASA-ISRO NISAR mission",
        path=None,
        note=f"Short name {SHORT_NAME} at the Alaska Satellite Facility DAAC (Earthdata login), doi:{p0['doi']}. Only the study-area window of five layers was read "
             f"from each ~2.2 GB file ({sum(f.stat().st_size for f in files) / 1e6:.0f} MB kept in data/work/{CITY['id']}/nisar/). Granules: " + "; ".join(i["granule"] for i in info),
    )
    print(summary)


if __name__ == "__main__":
    main()
