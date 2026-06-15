"""
compactness_scores.py
======================
Calculates district compactness scores used in redistricting litigation
and academic analysis.

Metrics computed:
  - Polsby-Popper  : 4π × Area / Perimeter²  (range 0–1; 1 = perfect circle)
  - Reock          : Area / Area of minimum bounding circle  (range 0–1)
  - Convex Hull    : Area / Area of convex hull  (range 0–1)
  - Schwartzberg   : 1 / (Perimeter / Circumference of equal-area circle)

Higher scores = more compact. Courts have referenced Polsby-Popper and
Reock in gerrymandering cases (e.g. Rucho v. Common Cause).

Author: Quentin Sprauve
Dependencies: geopandas, pandas, shapely, numpy
Usage:
    python compactness_scores.py --input districts.shp --id-col DISTRICT
    python compactness_scores.py --input districts.shp --id-col GEOID --output scores.csv
"""

import argparse
import logging
import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Use equal-area projection for accurate area/perimeter measurements
EQUAL_AREA_CRS = "EPSG:5070"   # Conus Albers Equal Area


# ---------------------------------------------------------------------------
# Metric functions (all expect shapely geometries in equal-area CRS)
# ---------------------------------------------------------------------------

def polsby_popper(geom) -> float:
    """4π × Area / Perimeter²"""
    if geom is None or geom.is_empty:
        return np.nan
    return (4 * math.pi * geom.area) / (geom.length ** 2)


def reock(geom) -> float:
    """Area / Area of minimum bounding circle"""
    if geom is None or geom.is_empty:
        return np.nan
    mbr = geom.minimum_bounding_circle()
    return geom.area / mbr.area if mbr.area > 0 else np.nan


def convex_hull_score(geom) -> float:
    """Area / Area of convex hull"""
    if geom is None or geom.is_empty:
        return np.nan
    hull = geom.convex_hull
    return geom.area / hull.area if hull.area > 0 else np.nan


def schwartzberg(geom) -> float:
    """1 / (Perimeter / Circumference of circle with same area)"""
    if geom is None or geom.is_empty:
        return np.nan
    circle_circumference = 2 * math.pi * math.sqrt(geom.area / math.pi)
    return circle_circumference / geom.length if geom.length > 0 else np.nan


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def compute_compactness(gdf: gpd.GeoDataFrame, id_col: str) -> pd.DataFrame:
    if id_col not in gdf.columns:
        log.error("ID column '%s' not found. Available: %s", id_col, list(gdf.columns))
        sys.exit(1)

    log.info("Projecting to %s for accurate measurements …", EQUAL_AREA_CRS)
    gdf_ea = gdf[[id_col, "geometry"]].to_crs(EQUAL_AREA_CRS).copy()

    log.info("Computing compactness scores for %d districts …", len(gdf_ea))

    results = []
    for _, row in gdf_ea.iterrows():
        geom = row.geometry
        results.append({
            id_col:           row[id_col],
            "polsby_popper":  round(polsby_popper(geom),       4),
            "reock":          round(reock(geom),                4),
            "convex_hull":    round(convex_hull_score(geom),    4),
            "schwartzberg":   round(schwartzberg(geom),         4),
            "area_sq_miles":  round(geom.area * 3.861e-7,       2),
            "perimeter_miles":round(geom.length * 6.2137e-4,    2),
            "num_parts":      len(geom.geoms) if isinstance(geom, MultiPolygon) else 1,
        })

    df = pd.DataFrame(results)

    # Composite score (equal-weight average of four metrics)
    score_cols = ["polsby_popper", "reock", "convex_hull", "schwartzberg"]
    df["composite_score"] = df[score_cols].mean(axis=1).round(4)

    # Rank (1 = most compact)
    df["compactness_rank"] = df["composite_score"].rank(ascending=False, method="min").astype(int)

    df.sort_values("compactness_rank", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def print_summary(df: pd.DataFrame, id_col: str) -> None:
    print("\n" + "=" * 65)
    print("COMPACTNESS SCORE SUMMARY")
    print("=" * 65)
    print(f"  Districts analyzed : {len(df)}")
    print()

    metrics = [
        ("Polsby-Popper",  "polsby_popper"),
        ("Reock",          "reock"),
        ("Convex Hull",    "convex_hull"),
        ("Schwartzberg",   "schwartzberg"),
        ("Composite",      "composite_score"),
    ]
    print(f"  {'Metric':<18} {'Mean':>6}  {'Min':>6}  {'Max':>6}")
    print(f"  {'-'*18} {'-'*6}  {'-'*6}  {'-'*6}")
    for label, col in metrics:
        print(f"  {label:<18} {df[col].mean():>6.3f}  {df[col].min():>6.3f}  {df[col].max():>6.3f}")

    print()
    print(f"  Most compact  : {df.iloc[0][id_col]}  (composite = {df.iloc[0]['composite_score']:.3f})")
    print(f"  Least compact : {df.iloc[-1][id_col]}  (composite = {df.iloc[-1]['composite_score']:.3f})")

    non_contiguous = df[df["num_parts"] > 1]
    if not non_contiguous.empty:
        print(f"\n  ⚠  {len(non_contiguous)} district(s) have multiple parts (non-contiguous):")
        for _, r in non_contiguous.iterrows():
            print(f"     {r[id_col]}  ({r['num_parts']} parts)")
    print("=" * 65 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Compute redistricting compactness scores for district shapefiles."
    )
    p.add_argument("--input",  required=True,              help="District shapefile path")
    p.add_argument("--id-col", default="DISTRICT",         help="District ID column (default: DISTRICT)")
    p.add_argument("--output", default="compactness_scores.csv", help="Output CSV path")
    return p.parse_args()


def main():
    args = parse_args()
    if not Path(args.input).exists():
        log.error("File not found: %s", args.input)
        sys.exit(1)

    log.info("Loading %s …", args.input)
    gdf = gpd.read_file(args.input)

    scores = compute_compactness(gdf, id_col=args.id_col)
    print_summary(scores, id_col=args.id_col)

    scores.to_csv(args.output, index=False)
    log.info("Scores saved to %s", args.output)


if __name__ == "__main__":
    main()
