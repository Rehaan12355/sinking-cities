# Sinking Cities

**NASA Space Apps Challenge 2026 · Seattle · "Dancing with the SARs"**

Sinking Cities uses NASA radar to show which parts of a US coastal city are quietly
sinking, roughly when those areas could start flooding regularly, and how many people
live there, so leaders can protect people before it happens.

Seven study areas, chosen with the picker at the top of the site:

- **Norfolk and Hampton Roads, Virginia**: seven cities, 366 census-tract neighborhoods, about 1.36 million residents.
- **Charleston, South Carolina**: 95 neighborhoods, about 0.41 million residents.
- **Miami and Miami Beach, Florida**: 322 neighborhoods, about 1.14 million residents.
- **Galveston Bay, Texas**: 101 neighborhoods, about 0.35 million residents.
- **Seattle, Washington**: 190 neighborhoods, about 0.79 million residents.
- **Aberdeen and Hoquiam, Washington**: 7 neighborhoods, about 28,000 residents.
- **Olympia, Washington**: 19 neighborhoods, about 95,000 residents.

Each city has three map views: sinking ground, flood timing, and which radar (NISAR or the older Sentinel-1) can measure each piece of land.

## What it found in Hampton Roads

- Neighborhoods are sinking at a median of about 2.2 mm a year (most between 1 and
  3.3), measured from 248 usable dates of NASA OPERA DISP-S1 radar data, September
  2016 to February 2026.
- Radar and GPS vertical rates agree to about 1.4 mm a year at the nine GPS stations
  inside the map. That disagreement is carried into every rate's uncertainty.
- About 18,000 people already live on land that floods regularly at high tide. In the
  middle scenario that grows to about 55,000 by 2100 with sinking included, against
  about 42,000 from sea level rise alone.
- NISAR's first four months (June to October 2026) are too noisy to confirm or
  contradict the long-term rates. The site says so plainly.

## What it found in Charleston

- Neighborhoods are sinking at a median of about 2.2 mm a year (most between 1 and
  3.6), from 243 usable dates of OPERA DISP-S1 data, October 2016 to November 2025.
- Only four GPS stations sit inside the map, so each rate's uncertainty uses the GPS
  stations' own uncertainty, about 0.8 mm a year.
- About 16,700 people already live on land that floods regularly at high tide. In the
  middle scenario that grows to about 50,800 by 2100 with sinking included, against
  about 40,800 from sea level rise alone.

## What it found in Miami

- The ground is barely sinking: a median of about 0.6 mm a year.
- About 3,800 people live on regularly flooded land today. In the middle scenario
  that grows to about 93,000 by 2100, almost all of it from sea level rise: sinking
  accounts for about 1,300 of them.
- With nearly eleven months of NISAR data, the noise between neighborhoods is about
  6 mm, lower than in the cities with four months, but still too high to set rates.

## What it found in Galveston Bay

- The fastest sinking of the five: a median of about 2.4 mm a year, and about 11 in
  the fastest neighborhood.
- About 1,300 people live on regularly flooded land today. By 2100 in the middle
  scenario that is about 15,400 with sinking, against about 10,400 from sea level alone.
- Radar and GPS agree less well here, to about 3.3 mm a year across 15 stations, so
  each neighborhood's rate carries a wide uncertainty.

## What it found in Seattle

- Neighborhoods are sinking at a median of about 1.5 mm a year (most between 1 and
  1.9), from 160 usable dates of OPERA DISP-S1 data, August 2016 to September 2025.
- Only four GPS stations sit inside the map, so each rate's uncertainty uses the GPS
  stations' own uncertainty, about 0.5 mm a year.
- Few people live on Seattle's low ground: about 200 today, and about 400 by 2100 in
  the middle scenario with sinking included. The low ground here is mostly port and
  industrial land, which this people-count does not capture.

## What it found in Aberdeen, Hoquiam and Olympia

- Aberdeen and Hoquiam: about 2,900 people, one in ten, live on land that floods
  regularly today, rising to about 13,700 by 2100 in the middle scenario. The ground
  is not sinking, so sea level does the work. Radar and GPS agree poorly here (about
  3.6 mm a year), older levees are not modelled, and the flood threshold is worked
  out with NOAA's formula because the local gauge has none, so treat these as rough.
- NISAR measures 99% of the land around Aberdeen where the older radar reaches 29%,
  the largest gain of any city.
- Olympia: very little regular flooding (about 19 people today, about 45 by 2100)
  and almost no sinking. Its threshold is also formula-derived.

Every figure above is produced by the pipeline from the sources in `DATA_SOURCES.md`.

## How it is put together

- `pipeline/`: Python steps that download public data and precompute everything.
- `site/`: a static website (no server, no login) that reads the precomputed files in `site/data/`.
- `DATA_SOURCES.md`: every dataset's URL, retrieval date, size and licence.

| Step | What it does |
|---|---|
| `s01_boundaries.py`, `s01b_blocks.py` | Census tracts, blocks and 2020 population |
| `s02_elevation.py` | USGS 3DEP lidar elevation on a 10 m grid |
| `s03_water.py` | NOAA tide datums and flood threshold, NASA AR6 sea level projections |
| `s04_gps.py` | GPS vertical rates from the Nevada Geodetic Laboratory |
| `s05a_opera_fetch.py` | Reads the study-area part of 269 NASA OPERA DISP-S1 files |
| `s05b_sinking.py` | Sinking rate per 90 m cell and per neighborhood, tied to GPS |
| `s06_flood.py` | First year of regular flooding per 10 m cell, with and without sinking |
| `s07_nisar.py` | Adds up nine NISAR interferograms, compares them with the long-term rates, and maps which radar can measure each piece of ground |
| `s08_build.py` | Packages everything for the website |

## Run it

```
python -m venv .venv && .venv/bin/pip install earthaccess geopandas rasterio h5py scipy pillow requests
cd pipeline
export SC_CITY=hampton-roads   # or charleston, miami, galveston, seattle, aberdeen, olympia; cities are defined in pipeline/config.py
for s in s01_boundaries s01b_blocks s02_elevation s03_water s04_gps s05a_opera_fetch s06_flood s05b_sinking s06_flood s07_nisar s08_build; do ../.venv/bin/python $s.py; done
cd ../site && python -m http.server 8000
```

Steps 5a and 7 need a free NASA Earthdata login stored in `~/.netrc`, and the Alaska
Satellite Facility data-use agreement accepted once in the browser. Credentials are
never stored in this repository. Step 5a transfers about 3.2 GB for Hampton Roads, 0.9 GB for Charleston and 0.6 GB for Seattle. Step 6 runs twice: once for sea level alone (step 5b needs its water map), then again with sinking.

## Limits

This is a screening tool, not a flood forecast. It compares ground height with tide
height and does not model storms, rain, drainage or flood defences. The full list is
on the site's "How it works" page (`site/methods.html`).

## AI disclosure

This project was built with help from Claude (Anthropic) for code and text drafting.
All data comes from the public sources listed in `DATA_SOURCES.md`; no values are AI-generated.
