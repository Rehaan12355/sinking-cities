"""Step 3: water levels.

- NOAA tide gauge datums and the high-tide-flood threshold (fixed elevation).
- NOAA observed high-tide-flood days per year (how often that threshold is hit today).
- NASA Sea Level Projection Tool (IPCC AR6) at the same gauge, split into
  total and the vertical-land-motion part, so we can swap the single gauge
  land-motion value for the per-neighborhood radar measurement.
"""
import json

import numpy as np

from common import fetch, record_source
from config import BASE_YEAR, CITY, END_YEAR, WORK

MD = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/{st}/{what}.json"
HTF = "https://api.tidesandcurrents.noaa.gov/dpapi/prod/webapi/htf/htf_annual.json"
AR6 = "https://d3qt3aobtsas2h.cloudfront.net/edge/ws/search/projection"
SCENARIOS = {"low": "ssp126", "mid": "ssp245", "high": "ssp585"}
QUANTILE = {"low": 17, "mid": 50, "high": 83}
PD = "US Government work, public domain"


def main():
    st = CITY["tide_station"]
    p_dat = fetch(MD.format(st=st, what="datums"), "noaa_datums.json", params={"units": "metric"})
    try:
        p_fl = fetch(MD.format(st=st, what="floodlevels"), "noaa_floodlevels.json", params={"units": "metric"})
    except RuntimeError:        # small gauges have no flood-level page at all
        p_fl = None
    # Small gauges have no flood-day count of their own; a named nearby gauge stands in for that one figure.
    htf_st = CITY.get("htf_station", st)
    p_htf = fetch(HTF, "noaa_htf_annual.json", params={"station": htf_st})
    p_ar6 = fetch(AR6, "nasa_ar6_projection.json", params={"psmsl_id": CITY["psmsl_id"]})
    record_source("noaa_datums", title=f"NOAA tidal datums, station {st}", url=MD.format(st=st, what="datums"), licence=PD, path=p_dat)
    if p_fl is not None:
        record_source("noaa_floodlevels", title=f"NOAA high-tide-flood thresholds, station {st}", url=MD.format(st=st, what="floodlevels"), licence=PD, path=p_fl)
    record_source("noaa_htf_annual", title=f"NOAA observed annual high-tide-flood days, station {htf_st}", url=f"{HTF}?station={htf_st}", licence=PD, path=p_htf)
    record_source("nasa_ar6_sea_level", title=f"NASA Sea Level Projection Tool (IPCC AR6), PSMSL {CITY['psmsl_id']}",
                  url=f"{AR6}?psmsl_id={CITY['psmsl_id']}", licence="CC BY 4.0 (IPCC AR6 sea level projections, Garner et al. 2021)", path=p_ar6,
                  note="Data service behind sealevel.nasa.gov/ipcc-ar6-sea-level-projection-tool. Medium-confidence projections, relative to 1995-2014.")

    dat = {d["name"]: d["value"] for d in json.loads(p_dat.read_text())["datums"]}
    fl = json.loads(p_fl.read_text()) if p_fl is not None else {}
    navd = dat["NAVD88"]
    notes = []
    if fl.get("nos_minor") is not None:
        minor, moderate = fl["nos_minor"], fl["nos_moderate"]
    else:
        # NOAA publishes no threshold for this gauge, so we apply NOAA's own formula
        # (Sweet et al. 2018, NOAA Technical Report NOS CO-OPS 086): the minor level is
        # 0.50 m plus 4% of the tide range above mean higher high water.
        tide_range = dat["MHHW"] - dat["MLLW"]
        minor = dat["MHHW"] + 0.50 + 0.04 * tide_range
        moderate = dat["MHHW"] + 0.80 + 0.03 * tide_range
        notes.append(f"NOAA lists no flood threshold for the {CITY['tide_station_name']} gauge, so the threshold here is worked out from that gauge's tide range "
                     "with NOAA's published formula (Sweet et al. 2018).")
    if htf_st != st:
        notes.append(f"The count of flood days a year comes from the nearest gauge that has one, {CITY['htf_station_name']}.")
    if CITY.get("projection_note"):
        notes.append(CITY["projection_note"])
    out = {
        "station": st,
        "station_name": CITY["tide_station_name"],
        "htf_station_name": CITY.get("htf_station_name", CITY["tide_station_name"]),
        "notes": " ".join(notes),
        "mhhw_navd88_m": round(dat["MHHW"] - navd, 3),
        "msl_navd88_m": round(dat["MSL"] - navd, 3),
        "htf_minor_navd88_m": round(minor - navd, 3),
        "htf_moderate_navd88_m": round(moderate - navd, 3),
    }

    # The current year is still in progress, so it is left out of the counts.
    htf = [r for r in json.loads(p_htf.read_text())["AnnualFloodCount"]
           if r["minCount"] is not None and r["year"] < BASE_YEAR]
    out["htf_days"] = [{"year": r["year"], "days": r["minCount"]} for r in htf if r["year"] >= 1950]
    recent = [r["minCount"] for r in htf[-5:]]
    out["htf_recent_years"] = [htf[-5]["year"], htf[-1]["year"]]
    out["htf_recent_mean_days"] = round(float(np.mean(recent)), 1)

    # Sea level: total minus the gauge's vertical land motion = the ocean's share.
    rows = [r for r in json.loads(p_ar6.read_text()) if r["confidence"] == "medium"]
    years = np.arange(BASE_YEAR, END_YEAR + 1)

    def series(proc, scen, q):
        r = next(x for x in rows if x["process"] == proc and x["scenario"] == scen)
        return np.interp(years, r["year"], r[f"height_{q}"])

    out["years"] = years.tolist()
    out["ocean_rise_m"] = {}  # rise since BASE_YEAR, land motion removed
    for key, scen in SCENARIOS.items():
        vlm = series("verticallandmotion", scen, 50)
        ocean = series("total", scen, QUANTILE[key]) - vlm
        out["ocean_rise_m"][key] = np.round(ocean - ocean[0], 4).tolist()
    vlm = series("verticallandmotion", "ssp245", 50)
    out["ar6_gauge_vlm_mm_yr"] = round(float((vlm[-1] - vlm[0]) / (years[-1] - years[0]) * 1000), 2)
    out["scenarios"] = {
        "low": "SSP1-2.6, 17th percentile",
        "mid": "SSP2-4.5, median",
        "high": "SSP5-8.5, 83rd percentile",
    }
    (WORK / "water.json").write_text(json.dumps(out))
    print({k: v for k, v in out.items() if not isinstance(v, (list, dict))})
    for k in SCENARIOS:
        o = out["ocean_rise_m"][k]
        print(k, "ocean rise by 2050/2100:", o[2050 - BASE_YEAR], o[2100 - BASE_YEAR])
    print("recent flood days:", out["htf_days"][-6:])


if __name__ == "__main__":
    main()
