"""Step 1b: 2020 Census blocks with population.

Blocks are the smallest census unit (roughly a city block). We use them to place
people on the map far more precisely than a whole-tract average would.
"""
import geopandas as gpd
import pandas as pd

from common import fetch, record_source
from config import CITY, WORK

TIGER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/12/query"
PAGE = 1000


def main():
    frames = []
    for fips, city in CITY["counties"].items():
        offset, n_city = 0, 0
        while True:
            path = fetch(
                TIGER,
                f"blocks_{fips}_{offset}.geojson",
                params={
                    # Unpopulated blocks add nothing to a people count.
                    "where": f"STATE='{CITY['state_fips']}' AND COUNTY='{fips}' AND POP100>0",
                    "outFields": "GEOID,POP100",
                    "outSR": 4326,
                    "orderByFields": "GEOID",
                    "resultOffset": offset,
                    "resultRecordCount": PAGE,
                    "f": "geojson",
                },
                timeout=300,
            )
            g = gpd.read_file(path)
            if len(g) == 0:
                break
            frames.append(g[["GEOID", "POP100", "geometry"]])
            n_city += len(g)
            if len(g) < PAGE:
                break
            offset += PAGE
        print(city, n_city, "populated blocks")
    blocks = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=4326)
    blocks = blocks.drop_duplicates("GEOID")
    blocks["pop"] = blocks["POP100"].astype(int)
    blocks["tract"] = blocks["GEOID"].str[:11]
    tracts = gpd.read_file(WORK / "tracts.geojson")
    blocks = blocks[blocks["tract"].isin(set(tracts["GEOID"]))]
    blocks[["GEOID", "tract", "pop", "geometry"]].to_file(WORK / "blocks.gpkg", driver="GPKG")
    record_source(
        "census_blocks",
        title="2020 Census blocks and population (populated blocks only)",
        url=TIGER,
        licence="US Government work, public domain",
        path=WORK / "blocks.gpkg",
        note="Queried per city from TIGERweb layer 'Census 2020 > Census Blocks', field POP100.",
    )
    # Acceptance check: block population must add up to tract population.
    bp, tp = int(blocks["pop"].sum()), int(tracts["pop"].sum())
    print(f"{len(blocks)} blocks, {bp:,} people; tracts say {tp:,}")
    assert bp == tp, "block and tract populations disagree"


if __name__ == "__main__":
    main()
