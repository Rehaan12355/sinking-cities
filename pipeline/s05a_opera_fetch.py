"""Step 5a: fetch NASA OPERA DISP-S1 ground motion over the study area.

Each OPERA file covers a whole Sentinel-1 frame (about 440 MB), and there are 269
of them. We never download whole files: every file has a small index of where
its 256 x 256 pixel chunks sit, so we request only the chunks over the city.

For each date we keep
- the line-of-sight displacement on a 90 m grid (3 x 3 average of good 30 m pixels)
- how many good pixels went into each 90 m cell
- the mean displacement in a small circle around each GPS station

Needs a free NASA Earthdata login in ~/.netrc (never committed).
"""
import base64
import gzip
import json
import re
import sys
import zlib
from concurrent.futures import ThreadPoolExecutor

import earthaccess
import numpy as np
from pyproj import Transformer

from common import record_source
from config import CITY, RAW, WORK

SHORT_NAME = "OPERA_L3_DISP-S1_V1"
FRAME = CITY["opera_frame"]   # Sentinel-1 frame that covers the whole study area
STATIC = "OPERA_L3_DISP-S1-STATIC_V1"
CHUNK = 256
BLOCK = 3              # 30 m -> 90 m
GPS_RADIUS_M = 300
MERGE_GAP = 256 * 1024  # join byte ranges closer than this into one request
OUT = WORK / "opera"
OUT.mkdir(parents=True, exist_ok=True)


def decode(buf, dtype, elemsize):
    raw = zlib.decompress(buf)
    a = np.frombuffer(raw, np.uint8).reshape(elemsize, -1).T  # undo HDF5 byte shuffle
    return np.ascontiguousarray(a).view(dtype).reshape(CHUNK, CHUNK)


def read_ranges(session, url, ranges):
    """Fetch many (offset, length) pieces of one remote file with few requests."""
    order = sorted(set(ranges))
    groups, cur = [], [order[0]]
    for r in order[1:]:
        if r[0] - (cur[-1][0] + cur[-1][1]) <= MERGE_GAP:
            cur.append(r)
        else:
            groups.append(cur)
            cur = [r]
    groups.append(cur)
    out = {}
    for g in groups:
        start, end = g[0][0], g[-1][0] + g[-1][1]
        for attempt in range(4):
            try:
                resp = session.get(url, headers={"Range": f"bytes={start}-{end - 1}"}, timeout=180)
                resp.raise_for_status()
                data = resp.content
                assert len(data) == end - start
                break
            except Exception:
                if attempt == 3:
                    raise
        for off, ln in g:
            out[(off, ln)] = data[off - start: off - start + ln]
    return out


def grid_window(refs):
    """Pixel window of the study bbox in this frame, snapped to whole 90 m blocks."""
    gt = [float(v) for v in json.loads(refs["spatial_ref/.zattrs"])["GeoTransform"].split()]
    x0, dx, y0, dy = gt[0], gt[1], gt[3], gt[5]
    shape = json.loads(refs["displacement/.zarray"])["shape"]
    epsg = int(re.search(r'ID\["EPSG",(\d+)\]\]$', json.loads(refs["spatial_ref/.zattrs"])["crs_wkt"]).group(1))
    tf = Transformer.from_crs(4326, epsg, always_xy=True)
    w, s, e, n = CITY["bbox"]
    xs, ys = tf.transform([w, e, w, e], [s, s, n, n])
    c0 = max(0, int((min(xs) - x0) / dx)) // BLOCK * BLOCK
    c1 = min(shape[1], int((max(xs) - x0) / dx) + 1)
    r0 = max(0, int((max(ys) - y0) / dy)) // BLOCK * BLOCK
    r1 = min(shape[0], int((min(ys) - y0) / dy) + 1)
    c1 -= (c1 - c0) % BLOCK
    r1 -= (r1 - r0) % BLOCK
    return dict(epsg=epsg, x0=x0, dx=dx, y0=y0, dy=dy, r0=r0, r1=r1, c0=c0, c1=c1, shape=shape), tf


def process(granule, gps, session):
    links = granule.data_links()
    nc = next(l for l in links if l.endswith(".nc"))
    m = re.search(r"_VV_(\d{8})T\d+Z_(\d{8})T", nc)
    ref_date, sec_date = m.group(1), m.group(2)
    out = OUT / f"{sec_date}.npz"
    if out.exists():
        return sec_date, 0
    idx = next(l for l in links if l.endswith(".zarr.json.gz") and "STACK" not in l)
    refs = json.loads(gzip.decompress(session.get(idx, timeout=120).content))
    refs = refs.get("refs", refs)
    win, tf = grid_window(refs)
    r0, r1, c0, c1 = win["r0"], win["r1"], win["c0"], win["c1"]

    # Chunks over the city, plus the chunk(s) around each GPS station.
    need = {(i, j) for i in range(r0 // CHUNK, (r1 - 1) // CHUNK + 1) for j in range(c0 // CHUNK, (c1 - 1) // CHUNK + 1)}
    k = int(np.ceil(GPS_RADIUS_M / win["dx"]))
    gpx = []
    for g in gps:
        x, y = tf.transform(g["lon"], g["lat"])
        col, row = int((x - win["x0"]) / win["dx"]), int((y - win["y0"]) / win["dy"])
        inside = k <= row < win["shape"][0] - k and k <= col < win["shape"][1] - k
        gpx.append((row, col) if inside else None)
        if inside:
            need |= {(i, j) for i in {(row - k) // CHUNK, (row + k) // CHUNK} for j in {(col - k) // CHUNK, (col + k) // CHUNK}}

    variables = {"displacement": ("<f8", 8), "recommended_mask": ("|u1", 1)}
    wanted, inline = {}, {}
    for v in variables:
        for (i, j) in need:
            ref = refs.get(f"{v}/{i}.{j}")
            if isinstance(ref, str):   # tiny chunks are stored inside the index itself
                inline[(v, i, j)] = base64.b64decode(ref[7:]) if ref.startswith("base64:") else ref.encode("latin-1")
            elif ref is not None:
                wanted[(v, i, j)] = (ref[1], ref[2])
    resp = session.get(nc, headers={"Range": "bytes=0-0"}, timeout=120)   # follow the login redirect once
    signed = resp.url
    blobs = read_ranges(session, signed, list(wanted.values()))
    nbytes = sum(ln for _, ln in set(wanted.values()))

    def chunk(v, i, j):
        if (v, i, j) in inline:
            return decode(inline[(v, i, j)], *variables[v])
        key = wanted.get((v, i, j))
        if key is None:
            return None
        return decode(blobs[key], *variables[v])

    def mosaic(v, rows, cols, fill, dtype):
        """Assemble the pixel window rows x cols (half-open) from chunks."""
        a = np.full((rows[1] - rows[0], cols[1] - cols[0]), fill, dtype)
        for i in range(rows[0] // CHUNK, (rows[1] - 1) // CHUNK + 1):
            for j in range(cols[0] // CHUNK, (cols[1] - 1) // CHUNK + 1):
                ch = chunk(v, i, j)
                if ch is None:
                    continue
                rs, re_ = max(rows[0], i * CHUNK), min(rows[1], (i + 1) * CHUNK)
                cs, ce = max(cols[0], j * CHUNK), min(cols[1], (j + 1) * CHUNK)
                a[rs - rows[0]: re_ - rows[0], cs - cols[0]: ce - cols[0]] = ch[rs - i * CHUNK: re_ - i * CHUNK, cs - j * CHUNK: ce - j * CHUNK]
        return a

    disp = mosaic("displacement", (r0, r1), (c0, c1), np.nan, "float32")
    good = (mosaic("recommended_mask", (r0, r1), (c0, c1), 0, "uint8") == 1) & np.isfinite(disp)
    h, w = disp.shape[0] // BLOCK, disp.shape[1] // BLOCK
    d3 = np.where(good, disp, 0).reshape(h, BLOCK, w, BLOCK).sum(axis=(1, 3))
    n3 = good.reshape(h, BLOCK, w, BLOCK).sum(axis=(1, 3)).astype("uint8")
    coarse = np.where(n3 > 0, d3 / np.maximum(n3, 1), np.nan).astype("float32")

    gvals, gcount = [], []
    yy, xx = np.mgrid[-k:k + 1, -k:k + 1]
    disc = (yy**2 + xx**2) * win["dx"]**2 <= GPS_RADIUS_M**2
    for p in gpx:
        if p is None:
            gvals.append(np.nan); gcount.append(0)
            continue
        row, col = p
        d = mosaic("displacement", (row - k, row + k + 1), (col - k, col + k + 1), np.nan, "float32")
        ok = (mosaic("recommended_mask", (row - k, row + k + 1), (col - k, col + k + 1), 0, "uint8") == 1) & np.isfinite(d) & disc
        gvals.append(float(d[ok].mean()) if ok.any() else np.nan)
        gcount.append(int(ok.sum()))

    ident = {key.split("/")[1]: refs[key] for key in refs if key.startswith("identification/") and key.endswith("/0") and isinstance(refs[key], str) and len(refs[key]) < 200}
    np.savez_compressed(out, disp=coarse, n=n3, gps=np.array(gvals, "float32"), gps_n=np.array(gcount),
                        ref_date=ref_date, sec_date=sec_date, window=json.dumps(win), ident=json.dumps(ident), source=nc.rsplit("/", 1)[-1])
    return sec_date, nbytes


def main(limit=None):
    earthaccess.login(strategy="netrc")
    session = earthaccess.get_requests_https_session()
    gps = json.loads((WORK / "gps.json").read_text())
    res = earthaccess.search_data(short_name=SHORT_NAME, bounding_box=CITY["bbox"], count=5000)
    granules = sorted((g for g in res if f"_{FRAME}_" in g.data_links()[0]), key=lambda g: re.search(r"Z_(\d{8})T", g.data_links()[0]).group(1))
    if limit:
        granules = granules[:limit]
    print(len(granules), "OPERA DISP-S1 files for frame", FRAME)
    # Line-of-sight geometry for the same frame (one small file, downloaded whole).
    los = RAW / f"opera_{FRAME}_los_enu.tif"
    los_url = next(l for g in earthaccess.search_data(short_name=STATIC, bounding_box=CITY["bbox"], count=50)
                   for l in g.data_links() if f"_{FRAME}_" in l and l.endswith("line_of_sight_enu.tif"))
    if not los.exists():
        los.write_bytes(session.get(los_url, timeout=300).content)
    record_source(
        "opera_disp_s1_static",
        title=f"NASA OPERA L3 DISP-S1-STATIC v1 line-of-sight geometry, frame {FRAME}",
        url=los_url,
        licence="NASA open data (CC0); contains modified Copernicus Sentinel-1 data, ESA",
        path=los,
        note="Used to convert line-of-sight motion to vertical. doi:10.5067/SNWG/OPL3DISPS1-V1",
    )
    total = 0
    with ThreadPoolExecutor(8) as ex:
        for i, (date, nbytes) in enumerate(ex.map(lambda g: process(g, gps, session), granules)):
            total += nbytes
            if nbytes:
                print(f"{i + 1:4d}/{len(granules)} {date} {nbytes / 1e6:6.1f} MB", flush=True)
    done = sorted(OUT.glob("*.npz"))
    print(len(done), "dates saved;", f"{total / 1e6:.0f} MB transferred this run")
    record_source(
        "opera_disp_s1",
        title=f"NASA OPERA L3 DISP-S1 v1 surface displacement, frame {FRAME} ({len(done)} dates, {done[0].stem} to {done[-1].stem}), study-area subset",
        url="https://search.asf.alaska.edu/#/?dataset=OPERA-S1&productTypes=DISP-S1",
        licence="NASA open data (CC0); contains modified Copernicus Sentinel-1 data, ESA",
        path=None,
        note=f"Short name {SHORT_NAME} at the Alaska Satellite Facility DAAC (Earthdata login). Only the chunks over the study area were read from each ~440 MB file; "
             f"subset stored on a 90 m grid in data/work/{CITY['id']}/opera/ ({sum(f.stat().st_size for f in done) / 1e6:.0f} MB).",
    )


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
