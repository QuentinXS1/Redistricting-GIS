"""
geo_format_converter.py
========================
Converts between common GIS file formats used in redistricting and
political data work.

Supported formats:
  - Shapefile (.shp)   ↔ GeoJSON (.geojson)
  - Shapefile (.shp)   ↔ GeoPackage (.gpkg)
  - Shapefile (.shp)   ↔ KML (.kml)
  - Any of the above   → CSV (with geometry as WKT or lat/lon centroid)
  - GeoJSON            → Shapefile / GeoPackage / KML

Also supports:
  - CRS reprojection on the fly
  - Column renaming / dropping for export
  - Filtering by attribute before conversion

Author: Quentin Sprauve
Dependencies: geopandas, pandas, fiona
Usage:
    # Shapefile → GeoJSON:
    python geo_format_converter.py --input districts.shp --output districts.geojson

    # Shapefile → KML, reprojected to WGS84:
    python geo_format_converter.py --input precincts.shp --output precincts.kml --crs EPSG:4326

    # Any format → CSV with WKT geometry:
    python geo_format_converter.py --input districts.geojson --output districts.csv --wkt

    # Shapefile → CSV with centroid lat/lon only (no geometry):
    python geo_format_converter.py --input districts.shp --output centroids.csv --centroids-only

    # Filter before converting:
    python geo_format_converter.py --input districts.shp --output state_house.shp \
        --filter-col DISTRICT_TYPE --filter-val STATE_HOUSE
"""

import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Format detection by extension
FORMAT_MAP = {
    ".shp":     "ESRI Shapefile",
    ".geojson": "GeoJSON",
    ".json":    "GeoJSON",
    ".gpkg":    "GPKG",
    ".kml":     "KML",
    ".kmz":     "KML",
}

# Formats that require WGS84 (EPSG:4326)
WGS84_REQUIRED = {".kml", ".kmz", ".geojson", ".json"}

WGS84 = "EPSG:4326"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def detect_format(path: str) -> str:
    ext = Path(path).suffix.lower()
    fmt = FORMAT_MAP.get(ext)
    if not fmt:
        log.error("Unsupported file extension: %s\nSupported: %s", ext, list(FORMAT_MAP.keys()))
        sys.exit(1)
    return fmt


def load_geodata(path: str, filter_col: str = None, filter_val: str = None) -> gpd.GeoDataFrame:
    log.info("Reading: %s", path)
    gdf = gpd.read_file(path)
    log.info("Loaded %d features | CRS: %s", len(gdf), gdf.crs)

    if filter_col and filter_val:
        if filter_col not in gdf.columns:
            log.error("Filter column '%s' not found. Available: %s", filter_col, list(gdf.columns))
            sys.exit(1)
        before = len(gdf)
        gdf = gdf[gdf[filter_col].astype(str) == filter_val].copy()
        log.info("Filtered '%s' == '%s': %d → %d features", filter_col, filter_val, before, len(gdf))

    return gdf


def reproject(gdf: gpd.GeoDataFrame, target_crs: str) -> gpd.GeoDataFrame:
    if str(gdf.crs).upper() != target_crs.upper():
        log.info("Reprojecting %s → %s", gdf.crs, target_crs)
        gdf = gdf.to_crs(target_crs)
    return gdf


# ---------------------------------------------------------------------------
# Output modes
# ---------------------------------------------------------------------------

def export_geo(gdf: gpd.GeoDataFrame, output: str, target_crs: str = None) -> None:
    out_path = Path(output)
    fmt = detect_format(output)
    ext = out_path.suffix.lower()

    # Force WGS84 for formats that require it
    if ext in WGS84_REQUIRED:
        gdf = reproject(gdf, WGS84)
    elif target_crs:
        gdf = reproject(gdf, target_crs)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Shapefile: column names truncated to 10 chars by ESRI spec
    if fmt == "ESRI Shapefile":
        original_cols = list(gdf.columns)
        gdf.columns = [c[:10] if c != "geometry" else c for c in gdf.columns]
        truncated = [(o, n) for o, n in zip(original_cols, gdf.columns) if o != n and o != "geometry"]
        if truncated:
            log.warning(
                "Shapefile column names truncated to 10 chars: %s",
                {o: n for o, n in truncated}
            )

    gdf.to_file(output, driver=fmt)
    log.info("Saved %d features to %s (%s)", len(gdf), output, fmt)


def export_csv_wkt(gdf: gpd.GeoDataFrame, output: str, target_crs: str = None) -> None:
    """Export all attributes + geometry as WKT column."""
    if target_crs:
        gdf = reproject(gdf, target_crs)

    df = gdf.copy()
    df["geometry_wkt"] = df.geometry.apply(lambda g: g.wkt if g else None)
    df = pd.DataFrame(df.drop(columns=["geometry"]))

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    log.info("Saved %d rows with WKT geometry to %s", len(df), output)


def export_csv_centroids(gdf: gpd.GeoDataFrame, output: str) -> None:
    """Export attributes + centroid lat/lon (no polygon geometry)."""
    gdf_wgs = gdf.to_crs(WGS84)
    df = pd.DataFrame(gdf.drop(columns=["geometry"]))
    df["centroid_lon"] = gdf_wgs.geometry.centroid.x.round(6)
    df["centroid_lat"] = gdf_wgs.geometry.centroid.y.round(6)

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    log.info("Saved %d rows with centroid coordinates to %s", len(df), output)


# ---------------------------------------------------------------------------
# Batch conversion
# ---------------------------------------------------------------------------

def batch_convert(
    input_dir:   str,
    output_dir:  str,
    input_ext:   str,
    output_ext:  str,
    target_crs:  str = None,
) -> None:
    """Convert all files of a given extension in a directory."""
    in_path  = Path(input_dir)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    files = list(in_path.glob(f"*{input_ext}"))
    if not files:
        log.error("No %s files found in %s", input_ext, input_dir)
        sys.exit(1)

    log.info("Batch converting %d files: %s → %s", len(files), input_ext, output_ext)
    for f in files:
        out_file = out_path / (f.stem + output_ext)
        gdf = load_geodata(str(f))
        if out_file.suffix.lower() == ".csv":
            export_csv_wkt(gdf, str(out_file), target_crs)
        else:
            export_geo(gdf, str(out_file), target_crs)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Convert GIS files between shapefile, GeoJSON, GeoPackage, KML, and CSV."
    )
    p.add_argument("--input",          required=True,  help="Input file path")
    p.add_argument("--output",         required=True,  help="Output file path (extension determines format)")
    p.add_argument("--crs",            default=None,   help="Target CRS for reprojection (e.g. EPSG:4326)")
    p.add_argument("--wkt",            action="store_true", help="CSV output: include geometry as WKT column")
    p.add_argument("--centroids-only", action="store_true", help="CSV output: export centroid lat/lon only")
    p.add_argument("--filter-col",     default=None,   help="Filter by this column before converting")
    p.add_argument("--filter-val",     default=None,   help="Keep only rows where --filter-col equals this value")
    # Batch mode
    p.add_argument("--batch",          action="store_true", help="Batch convert all files in --input directory")
    p.add_argument("--input-ext",      default=".shp", help="Input extension for batch mode (default: .shp)")
    p.add_argument("--output-ext",     default=".geojson", help="Output extension for batch mode (default: .geojson)")
    return p.parse_args()


def main():
    args = parse_args()

    if args.batch:
        batch_convert(args.input, args.output, args.input_ext, args.output_ext, args.crs)
        return

    if not Path(args.input).exists():
        log.error("Input file not found: %s", args.input)
        sys.exit(1)

    gdf = load_geodata(args.input, filter_col=args.filter_col, filter_val=args.filter_val)

    out_ext = Path(args.output).suffix.lower()

    if out_ext == ".csv":
        if args.centroids_only:
            export_csv_centroids(gdf, args.output)
        else:
            export_csv_wkt(gdf, args.output, target_crs=args.crs)
    else:
        export_geo(gdf, args.output, target_crs=args.crs)


if __name__ == "__main__":
    main()
