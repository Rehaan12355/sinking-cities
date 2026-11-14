"""Step 4: GPS ground truth. Vertical velocities from the Nevada Geodetic
Laboratory MIDAS solution (IGS14 frame), for stations in and around the study area."""
import json

from common import fetch, record_source
from config import CITY, WORK

URL = "https://geodesy.unr.edu/velocities/midas.IGS14.txt"
MIN_YEARS = 4.0  # shorter records give unreliable vertical rates
PAD_DEG = 0.25   # include stations just outside the map to tie the radar frame


def main():
    path = fetch(URL, "midas.IGS14.txt")
    record_source(
        "ngl_midas_gps",
        title="Nevada Geodetic Laboratory MIDAS GPS velocities (IGS14)",
        url=URL,
        licence="Open; cite Blewitt et al. 2016, doi:10.1002/2015JB012552",
        path=path,
    )
    w, s, e, n = CITY["bbox"]
    out = []
    for line in path.read_text().splitlines():
        p = line.split()
        if len(p) < 27:
            continue
        lat, lon = float(p[24]), float(p[25])
        lon = lon + 360 if lon < -180 else lon
        if not (s - PAD_DEG <= lat <= n + PAD_DEG and w - PAD_DEG <= lon <= e + PAD_DEG):
            continue
        dur = float(p[4])
        if dur < MIN_YEARS:
            continue
        out.append({
            "id": p[0], "lat": round(lat, 5), "lon": round(lon, 5),
            "start": float(p[2]), "end": float(p[3]), "years": round(dur, 1),
            "up_mm_yr": round(float(p[10]) * 1000, 2),
            "up_sigma_mm_yr": round(float(p[13]) * 1000, 2),
        })
    (WORK / "gps.json").write_text(json.dumps(out, indent=1))
    for g in out:
        print(g)
    print(len(out), "stations")


if __name__ == "__main__":
    main()
