"""Step 1: census tracts ("neighborhoods") with 2020 population, plus place names.

Source: US Census Bureau TIGERweb (2020 Census tracts, POP100 = 2020 population).
Names: OpenStreetMap place nodes, used only to give each tract a readable label.
"""
import json
import time

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point, box

from common import UA, fetch, record_source
from config import CITY, RAW, WORK

TIGER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/10/query"
OVERPASS = "https://overpass-api.de/api/interpreter"
OVERPASS_MIRROR = "https://overpass.kumi.systems/api/interpreter"


def get_tracts():
    frames = []
    for fips, city in CITY["counties"].items():
        path = fetch(
            TIGER,
            f"tracts_{fips}.geojson",
            params={
                "where": f"STATE='{CITY['state_fips']}' AND COUNTY='{fips}'",
                "outFields": "GEOID,BASENAME,POP100,HU100,AREALAND,AREAWATER",
                "outSR": 4326,
                "f": "geojson",
            },
        )
        g = gpd.read_file(path)
        g["city"] = city
        frames.append(g)
        record_source(
            f"census_tracts_{fips}",
            title=f"2020 Census tracts and population, {city}",
            url=f"{TIGER}?where=STATE='{CITY['state_fips']}' AND COUNTY='{fips}'&f=geojson",
            licence="US Government work, public domain",
            path=path,
        )
    tracts = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=4326)
    bb = box(*CITY["bbox"])
    tracts = tracts[tracts.geometry.representative_point().within(bb)]
    # Water-only tracts (no land) carry no people and no ground to measure.
    tracts = tracts[tracts["AREALAND"].astype(float) > 0].reset_index(drop=True)
    return tracts


def get_places():
    w, s, e, n = CITY["bbox"]
    q = f"""[out:json][timeout:90];
    (node["place"~"suburb|neighbourhood|quarter|village|hamlet"]["name"]({s},{w},{n},{e}););
    out;"""
    path = RAW / "osm_places.json"
    if not path.exists():
        last = None
        for url in (OVERPASS, OVERPASS_MIRROR, OVERPASS):   # the public server is often busy; try a mirror, then once more
            try:
                r = requests.post(url, data={"data": q}, headers=UA, timeout=180)
                r.raise_for_status()
                json.loads(r.content)["elements"]
                path.write_bytes(r.content)
                break
            except Exception as e:
                last = e
                time.sleep(5)
        else:
            raise RuntimeError(f"place-name service unavailable: {last}")
    record_source(
        "osm_places",
        title="OpenStreetMap neighbourhood names (labels only)",
        url=OVERPASS,
        licence="ODbL 1.0, (c) OpenStreetMap contributors",
        path=path,
        note="Used only to label census tracts with a familiar nearby place name.",
    )
    els = json.loads(path.read_text())["elements"]
    return gpd.GeoDataFrame(
        {"pname": [e["tags"]["name"] for e in els]},
        geometry=[Point(e["lon"], e["lat"]) for e in els],
        crs=4326,
    )


def main():
    tracts = get_tracts()
    try:
        places = get_places().to_crs(CITY["utm_epsg"])
        pts = tracts.to_crs(CITY["utm_epsg"]).copy()
        pts["geometry"] = pts.geometry.representative_point()
        near = gpd.sjoin_nearest(pts[["GEOID", "geometry"]], places, max_distance=2500, distance_col="d")
        near = near.sort_values("d").drop_duplicates("GEOID").set_index("GEOID")["pname"]
        tracts["place"] = tracts["GEOID"].map(near)
    except Exception as e:  # labels are a nicety; tract numbers still work
        print("place names unavailable:", e)
        tracts["place"] = None
    tracts["pop"] = tracts["POP100"].astype(int)
    out = tracts[["GEOID", "BASENAME", "city", "place", "pop", "AREALAND", "geometry"]]
    out.to_file(WORK / "tracts.geojson", driver="GeoJSON")
    print(f"{len(out)} tracts, {out['pop'].sum():,} people, bounds {out.total_bounds.round(3)}")
    print(out.groupby("city")["pop"].agg(["count", "sum"]))
    print("named:", out["place"].notna().sum())


if __name__ == "__main__":
    main()
