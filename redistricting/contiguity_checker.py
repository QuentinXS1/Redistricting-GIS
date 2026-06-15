"""
contiguity_checker.py
======================
Verifies that every legislative district in a plan is geographically
contiguous — a constitutional requirement in most U.S. states.

Flags:
  - Districts composed of more than one disconnected polygon (MultiPolygon)
  - Islands: parts connected only by a single point (rook vs queen contiguity)
  - Near-misses: parts separated by < configurable distance threshold

Output:
  - Pass/fail summary per district
  - CSV of flagged non-contiguous districts with geometry details
  - Optional: fixed shapefile with contiguity issues highlighted

Author: Quentin Sprauve
Dependencies: geopandas, pandas, shapely, libpysal (optional, for queen/rook)
Usage:
    python contiguity_checker.py --input districts.shp --id-col DISTRICT
    python contiguity_checker.py --input plan.shp --id-col GEOID --gap-tolerance 10
"""

import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

EQUAL_AREA_CRS  = "EPSG:5070"
METERS_PER_MILE = 1609.344


# ---------------------------------------------------------------------------
# Contiguity checks
# ---------------------------------------------------------------------------

def check_multipart(geom, district_id) -> list[dict]:
    """Flag any district that is a MultiPolygon (most obvious non-contiguity)."""
    issues = []
    if isinstance(geom, MultiPolygon):
        parts = list(geom.geoms)
        areas = [p.area * 3.861e-7 for p in parts]  # sq miles
        issues.append({
            "district_id":   district_id,
            "issue_type":    "MULTIPART",
            "num_parts":     len(parts),
            "largest_part_sqmi":  round(max(areas), 3),
            "smallest_part_sqmi": round(min(areas), 3),
            "description":   f"{len(parts)} disconnected polygon(s)",
        })
    return issues


def check_point_contiguity(geom, district_id, tolerance_m: float = 1.0) -> list[dict]:
    """
    Detect parts that touch only at a single point (queen contiguity issue).
    These may pass a naive MultiPolygon test if they share a boundary point
    but are still effectively non-contiguous for redistricting purposes.
    """
    issues = []
    if not isinstance(geom, MultiPolygon):
        return issues

    parts = list(geom.geoms)
    for i, a in enumerate(parts):
        for j, b in enumerate(parts):
            if j <= i:
                continue
            intersection = a.intersection(b)
            # If the shared boundary is only a point or very short line
            if intersection.geom_type in ("Point", "MultiPoint"):
                issues.append({
                    "district_id": district_id,
                    "issue_type":  "POINT_TOUCH",
                    "num_parts":   len(parts),
                    "largest_part_sqmi":  None,
                    "smallest_part_sqmi": None,
                    "description": f"Parts {i} and {j} touch only at a point",
                })
            elif intersection.geom_type in ("LineString", "MultiLineString"):
                shared_length_m = intersection.length
                if shared_length_m < tolerance_m:
                    issues.append({
                        "district_id": district_id,
                        "issue_type":  "NEAR_POINT_TOUCH",
                        "num_parts":   len(parts),
                        "largest_part_sqmi":  None,
                        "smallest_part_sqmi": None,
                        "description": f"Parts {i} and {j} share only {shared_length_m:.1f}m of boundary",
                    })
    return issues


def check_gap(geom, district_id, gap_tolerance_m: float) -> list[dict]:
    """
    Detect parts that are very close but not touching — a common digitizing error.
    Buffers each part by the tolerance and checks for overlap.
    """
    issues = []
    if not isinstance(geom, MultiPolygon):
        return issues

    parts = list(geom.geoms)
    for i, a in enumerate(parts):
        for j, b in enumerate(parts):
            if j <= i:
                continue
            if not a.touches(b) and not a.intersects(b):
                gap = a.distance(b)
                if 0 < gap <= gap_tolerance_m:
                    issues.append({
                        "district_id": district_id,
                        "issue_type":  "NEAR_MISS_GAP",
                        "num_parts":   len(parts),
                        "largest_part_sqmi":  None,
                        "smallest_part_sqmi": None,
                        "description": f"Parts {i} and {j} have a {gap:.1f}m gap (possible digitizing error)",
                    })
    return issues


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def run_contiguity_checks(
    gdf: gpd.GeoDataFrame,
    id_col: str,
    gap_tolerance_m: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns:
        district_summary  — one row per district with pass/fail
        issues_detail     — one row per issue found
    """
    log.info("Projecting to %s …", EQUAL_AREA_CRS)
    gdf_ea = gdf[[id_col, "geometry"]].to_crs(EQUAL_AREA_CRS).copy()

    all_issues = []
    summary_rows = []

    for _, row in gdf_ea.iterrows():
        did  = row[id_col]
        geom = row.geometry

        issues = []
        issues += check_multipart(geom, did)
        issues += check_point_contiguity(geom, did)
        issues += check_gap(geom, did, gap_tolerance_m)

        all_issues.extend(issues)
        summary_rows.append({
            id_col:         did,
            "is_contiguous": len(issues) == 0,
            "num_issues":    len(issues),
            "issue_types":   ", ".join(sorted({i["issue_type"] for i in issues})) or "None",
            "area_sq_miles": round(geom.area * 3.861e-7, 2),
            "num_parts":     len(geom.geoms) if isinstance(geom, MultiPolygon) else 1,
        })

    summary = pd.DataFrame(summary_rows).sort_values("num_issues", ascending=False)
    issues  = pd.DataFrame(all_issues) if all_issues else pd.DataFrame()

    return summary, issues


def print_report(summary: pd.DataFrame, id_col: str) -> None:
    total     = len(summary)
    passed    = summary["is_contiguous"].sum()
    failed    = total - passed

    print("\n" + "=" * 55)
    print("CONTIGUITY CHECK REPORT")
    print("=" * 55)
    print(f"  Districts checked : {total}")
    print(f"  Contiguous (pass) : {passed}")
    print(f"  Non-contiguous    : {failed}")

    if failed > 0:
        print(f"\n  ⚠  Flagged districts:\n")
        flagged = summary[~summary["is_contiguous"]]
        for _, r in flagged.iterrows():
            print(f"    {r[id_col]:<20}  {r['num_parts']} parts  |  issues: {r['issue_types']}")
    else:
        print("\n  ✓ All districts are contiguous.")
    print("=" * 55 + "\n")


# ---------------------------------------------------------------------------
# Optional: export flagged geometries
# ---------------------------------------------------------------------------

def export_flagged_shapefile(
    gdf: gpd.GeoDataFrame,
    summary: pd.DataFrame,
    id_col: str,
    output_path: str,
) -> None:
    flagged_ids = summary.loc[~summary["is_contiguous"], id_col].tolist()
    gdf_flagged = gdf[gdf[id_col].isin(flagged_ids)].copy()
    gdf_flagged["CONTIGUOUS"] = 0
    gdf_flagged.to_file(output_path)
    log.info("Flagged geometries saved to %s", output_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Check district contiguity for redistricting plans."
    )
    p.add_argument("--input",          required=True,              help="District shapefile")
    p.add_argument("--id-col",         default="DISTRICT",         help="District ID column (default: DISTRICT)")
    p.add_argument("--gap-tolerance",  type=float, default=10.0,   help="Gap threshold in meters for near-miss detection (default: 10)")
    p.add_argument("--output-csv",     default="contiguity_issues.csv", help="Output issues CSV")
    p.add_argument("--output-shp",     default=None,               help="Optional: export flagged districts as shapefile")
    return p.parse_args()


def main():
    args = parse_args()

    if not Path(args.input).exists():
        log.error("File not found: %s", args.input)
        sys.exit(1)

    log.info("Loading %s …", args.input)
    gdf = gpd.read_file(args.input)

    summary, issues = run_contiguity_checks(gdf, args.id_col, args.gap_tolerance)
    print_report(summary, args.id_col)

    if not issues.empty:
        issues.to_csv(args.output_csv, index=False)
        log.info("Issue details saved to %s", args.output_csv)

    if args.output_shp:
        export_flagged_shapefile(gdf, summary, args.id_col, args.output_shp)

    # Exit code: 1 if any non-contiguous districts found (useful in CI pipelines)
    failed = (~summary["is_contiguous"]).sum()
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
