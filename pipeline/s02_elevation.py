"""Step 2: ground elevation (NAVD88 metres) from the USGS 3DEP bare-earth DEM.

Pulled as GeoTIFF tiles from the 3DEP ImageServer and mosaicked onto the
UTM analysis grid shared by every later step.
"""
import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin

from common import fetch, record_source
from config import CITY, GRID_M, WORK

SVC = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
TILE = 2000  # pixels per request side


def grid():
    """Analysis grid: bounds of the tracts, snapped to GRID_M, in UTM."""
    tr = gpd.read_file(WORK / "tracts.geojson").to_crs(CITY["utm_epsg"])
    x0, y0, x1, y1 = tr.total_bounds
    pad = 500
    x0 = np.floor((x0 - pad) / GRID_M) * GRID_M
    y1 = np.ceil((y1 + pad) / GRID_M) * GRID_M
    w = int(np.ceil((x1 + pad - x0) / GRID_M))
    h = int(np.ceil((y1 - (y0 - pad)) / GRID_M))
    return from_origin(x0, y1, GRID_M, GRID_M), w, h


def main():
    transform, w, h = grid()
    x0, y1 = transform.c, transform.f
    dem = np.full((h, w), np.nan, dtype="float32")
    n = 0
    for r0 in range(0, h, TILE):
        for c0 in range(0, w, TILE):
            th, tw = min(TILE, h - r0), min(TILE, w - c0)
            bx0, by1 = x0 + c0 * GRID_M, y1 - r0 * GRID_M
            bbox = f"{bx0},{by1 - th * GRID_M},{bx0 + tw * GRID_M},{by1}"
            path = fetch(
                SVC,
                f"dem_{r0}_{c0}.tif",
                params={
                    "bbox": bbox,
                    "bboxSR": CITY["utm_epsg"],
                    "imageSR": CITY["utm_epsg"],
                    "size": f"{tw},{th}",
                    "format": "tiff",
                    "pixelType": "F32",
                    "interpolation": "RSP_BilinearInterpolation",
                    "f": "image",
                },
                timeout=300,
            )
            with rasterio.open(path) as src:
                a = src.read(1).astype("float32")
                nod = src.nodata
            if a.shape != (th, tw):
                raise RuntimeError(f"tile {r0},{c0} came back {a.shape}, expected {(th, tw)}")
            if nod is not None:
                a[a == nod] = np.nan
            a[a < -1000] = np.nan
            dem[r0:r0 + th, c0:c0 + tw] = a
            n += 1
    profile = dict(driver="GTiff", height=h, width=w, count=1, dtype="float32", crs=f"EPSG:{CITY['utm_epsg']}",
                   transform=transform, nodata=np.nan, compress="deflate", tiled=True)
    with rasterio.open(WORK / "dem.tif", "w", **profile) as dst:
        dst.write(dem, 1)
    record_source(
        "usgs_3dep_dem",
        title=f"USGS 3DEP bare-earth elevation, resampled to {GRID_M} m ({n} tiles)",
        url=SVC,
        licence="US Government work, public domain",
        path=WORK / "dem.tif",
        note="Heights are metres above NAVD88. Dynamic service mosaics the best available lidar-derived DEMs.",
    )
    print(f"dem {w}x{h} px, valid {np.isfinite(dem).mean():.1%}, "
          f"min {np.nanmin(dem):.2f} p50 {np.nanmedian(dem):.2f} max {np.nanmax(dem):.2f} m")


if __name__ == "__main__":
    main()
