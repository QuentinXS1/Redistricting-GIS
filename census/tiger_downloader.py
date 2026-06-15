"""
tiger_downloader.py
====================
Downloads Census TIGER/Line shapefiles directly from the Census Bureau FTP,
extracts them, and optionally merges multi-state files into a single layer.

Supported geography types:
  - Congressional districts (cd)
  - State legislative districts upper/lower (sldu, sldl)
  - Counties (county)
  - Census tracts (tract)
  - Voting tabulation districts / precincts (vtd)
  - Places (place)
  - Block groups (bg)

Author: Quentin Sprauve
Dependencies: requests, geopandas, pandas, tqdm
Usage:
    # Download congressional districts for all states (2020 vintage):
    python tiger_downloader.py --geo cd --year 2020 --output data/

    # Download VTDs (precincts) for a specific state:
    python tiger_downloader.py --geo vtd --year 2020 --state 36 --output data/

    # Download and merge county files for several states:
    python tiger_downloader.py --geo county --year 2020 --state 36,34,42 --merge --output data/
"""

import argparse
import logging
import os
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

TIGER_BASE_URL = "https://www2.census.gov/geo/tiger/TIGER{year}"

# TIGER URL patterns per geography type
TIGER_PATHS = {
    "cd":     "CD/tl_{year}_us_cd{congress}.zip",          # congressional districts (national)
    "sldu":   "SLDU/tl_{year}_{state}_sldu.zip",           # state senate
    "sldl":   "SLDL/tl_{year}_{state}_sldl.zip",           # state house
    "county": "COUNTY/tl_{year}_us_county.zip",            # all counties (national)
    "tract":  "TRACT/tl_{year}_{state}_tract.zip",         # tracts by state
    "vtd":    "VTD/tl_{year}_{state}_vtd20.zip",           # voting districts by state
    "place":  "PLACE/tl_{year}_{state}_place.zip",         # census places by state
    "bg":     "BG/tl_{year}_{state}_bg.zip",               # block groups by state
}

# Congress number for CD files (based on census year)
CONGRESS_MAP = {2020: "118", 2022: "118", 2024: "119", 2018: "116", 2016: "115"}

# FIPS codes for all 50 states + DC
ALL_STATE_FIPS = [
    "01","02","04","05","06","08","09","10","11","12","13","15","16","17","18",
    "19","20","21","22","23","24","25","26","27","28","29","30","31","32","33",
    "34","35","36","37","38","39","40","41","42","44","45","46","47","48","49",
    "50","51","53","54","55","56",
]


# ---------------------------------------------------------------------------
# URL building
# ---------------------------------------------------------------------------

def build_url(geo: str, year: int, state_fips: str = None) -> str:
    if geo not in TIGER_PATHS:
        log.error("Unknown geography '%s'. Valid options: %s", geo, list(TIGER_PATHS.keys()))
        sys.exit(1)

    pattern = TIGER_PATHS[geo]
    congress = CONGRESS_MAP.get(year, "118")

    filename = pattern.format(
        year     = year,
        state    = state_fips or "us",
        congress = congress,
    )
    return f"{TIGER_BASE_URL.format(year=year)}/{filename}"


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def download_zip(url: str, timeout: int = 60) -> BytesIO:
    log.info("Downloading: %s", url)
    resp = requests.get(url, stream=True, timeout=timeout)

    if resp.status_code == 404:
        raise FileNotFoundError(f"File not found at Census server: {url}")
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    buf = BytesIO()

    if HAS_TQDM and total:
        with tqdm(total=total, unit="B", unit_scale=True, desc=Path(url).name) as pbar:
            for chunk in resp.iter_content(chunk_size=8192):
                buf.write(chunk)
                pbar.update(len(chunk))
    else:
        for chunk in resp.iter_content(chunk_size=8192):
            buf.write(chunk)

    buf.seek(0)
    return buf


def extract_zip(buf: BytesIO, dest_dir: Path) -> Path:
    """Extract zip contents and return the path to the .shp file."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(buf) as z:
        z.extractall(dest_dir)

    shp_files = list(dest_dir.glob("*.shp"))
    if not shp_files:
        raise FileNotFoundError(f"No .shp file found in extracted archive at {dest_dir}")
    return shp_files[0]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def download_tiger(
    geo:        str,
    year:       int,
    state_fips: list[str],
    output_dir: str,
    merge:      bool = False,
) -> gpd.GeoDataFrame | None:

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Geographies that are national files (no state loop needed)
    national_geos = {"cd", "county"}

    if geo in national_geos:
        url = build_url(geo, year)
        try:
            buf = download_zip(url)
            shp_path = extract_zip(buf, out / f"{geo}_{year}")
            gdf = gpd.read_file(shp_path)
            log.info("Loaded %d features from %s", len(gdf), shp_path.name)
            if merge:
                out_shp = out / f"{geo}_{year}_merged.shp"
                gdf.to_file(out_shp)
                log.info("Saved merged file: %s", out_shp)
            return gdf
        except Exception as e:
            log.error("Failed to download %s: %s", url, e)
            return None

    # State-level geographies
    states = state_fips if state_fips else ALL_STATE_FIPS
    gdfs = []

    for fips in states:
        url = build_url(geo, year, state_fips=fips)
        try:
            buf = download_zip(url)
            state_dir = out / f"{geo}_{year}_{fips}"
            shp_path = extract_zip(buf, state_dir)
            gdf = gpd.read_file(shp_path)
            log.info("State %s: %d features", fips, len(gdf))
            gdfs.append(gdf)
        except FileNotFoundError:
            log.warning("No %s file for state %s (may not exist for this vintage)", geo, fips)
        except Exception as e:
            log.error("State %s failed: %s", fips, e)

    if not gdfs:
        log.error("No files downloaded.")
        return None

    if merge and len(gdfs) > 1:
        log.info("Merging %d state files …", len(gdfs))
        merged = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs=gdfs[0].crs)
        out_shp = out / f"{geo}_{year}_{'_'.join(states)}_merged.shp"
        merged.to_file(out_shp)
        log.info("Merged shapefile saved: %s (%d features)", out_shp, len(merged))
        return merged

    return gdfs[0] if len(gdfs) == 1 else None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Download Census TIGER/Line shapefiles for redistricting and GIS work."
    )
    p.add_argument(
        "--geo", required=True,
        choices=list(TIGER_PATHS.keys()),
        help="Geography type to download"
    )
    p.add_argument("--year",   type=int, default=2020,  help="Census vintage year (default: 2020)")
    p.add_argument("--state",  default=None,            help="Comma-separated 2-digit state FIPS codes (omit for all states)")
    p.add_argument("--output", default="tiger_data",    help="Output directory (default: tiger_data/)")
    p.add_argument("--merge",  action="store_true",     help="Merge multi-state downloads into one shapefile")
    return p.parse_args()


def main():
    args = parse_args()
    state_list = [s.strip().zfill(2) for s in args.state.split(",")] if args.state else None

    download_tiger(
        geo        = args.geo,
        year       = args.year,
        state_fips = state_list,
        output_dir = args.output,
        merge      = args.merge,
    )


if __name__ == "__main__":
    main()
