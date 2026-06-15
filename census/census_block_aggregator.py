"""
census_block_aggregator.py
===========================
Aggregates Census P.L. 94-171 block-level redistricting data to
custom district boundaries using a precinct-to-district crosswalk.

P.L. 94-171 data (used in redistricting) includes:
  - Total population (TOTPOP)
  - Voting-age population (VAP) — 18+
  - Race/ethnicity breakdowns for both total pop and VAP
  - Group quarters population

This script supports two aggregation modes:
  1. Direct join  : blocks already assigned to districts (one block = one district)
  2. Crosswalk    : blocks split across districts (weighted by area or population)

Author: Quentin Sprauve
Dependencies: geopandas, pandas, numpy
Usage:
    # Direct join (block already has district assignment):
    python census_block_aggregator.py \
        --blocks blocks_with_data.csv \
        --block-id GEOID20 \
        --district-col DISTRICT \
        --output district_pop.csv

    # Weighted aggregation via crosswalk:
    python census_block_aggregator.py \
        --blocks blocks_with_data.csv \
        --crosswalk block_district_crosswalk.csv \
        --block-id GEOID20 \
        --district-id DISTRICT \
        --output district_pop.csv
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Standard P.L. 94-171 population fields
# (These match the Census Bureau's Demographic and Housing Characteristics file)
PL_FIELDS = {
    # Total population
    "TOTPOP":   "total_population",
    # Voting-age population (18+)
    "VAP":      "vap_total",
    # Race — total population
    "NH_WHITE": "pop_white_nh",
    "NH_BLACK": "pop_black_nh",
    "NH_AIAN":  "pop_aian_nh",
    "NH_ASIAN": "pop_asian_nh",
    "NH_NHPI":  "pop_nhpi_nh",
    "NH_OTHER": "pop_other_nh",
    "NH_2MORE": "pop_two_more_nh",
    "HISP":     "pop_hispanic",
    # Voting-age — race breakdown
    "VAP_WHITE": "vap_white_nh",
    "VAP_BLACK": "vap_black_nh",
    "VAP_AIAN":  "vap_aian_nh",
    "VAP_ASIAN": "vap_asian_nh",
    "VAP_HISP":  "vap_hispanic",
    # Group quarters
    "GQPOP":    "group_quarters_pop",
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_blocks(path: str, block_id_col: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={block_id_col: str}, low_memory=False)

    # Identify which PL fields are present
    available = {k: v for k, v in PL_FIELDS.items() if k in df.columns}
    if not available:
        log.error(
            "No P.L. 94-171 population columns found.\n"
            "Expected any of: %s\nFound: %s",
            list(PL_FIELDS.keys()), list(df.columns)
        )
        sys.exit(1)

    log.info("Found %d population fields: %s", len(available), list(available.keys()))

    # Convert to numeric
    for col in available:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    return df, available


# ---------------------------------------------------------------------------
# Aggregation modes
# ---------------------------------------------------------------------------

def aggregate_direct(
    blocks: pd.DataFrame,
    block_id_col: str,
    district_col: str,
    available_fields: dict,
) -> pd.DataFrame:
    """Simple groupby when each block is fully assigned to one district."""
    log.info("Aggregating %d blocks → districts (direct join) …", len(blocks))

    agg_cols = {k: "sum" for k in available_fields}
    result = (
        blocks.groupby(district_col)
        .agg({**agg_cols, block_id_col: "count"})
        .rename(columns={**available_fields, block_id_col: "num_blocks"})
        .reset_index()
    )
    return result


def aggregate_crosswalk(
    blocks: pd.DataFrame,
    crosswalk: pd.DataFrame,
    block_id_col: str,
    district_id_col: str,
    available_fields: dict,
    weight_col: str = "pct_of_block",
) -> pd.DataFrame:
    """
    Weighted aggregation for split blocks.
    Each block can appear multiple times in the crosswalk (once per district it touches),
    with a weight indicating what fraction of the block belongs to each district.
    """
    log.info(
        "Aggregating %d blocks via crosswalk (%d rows) …",
        len(blocks), len(crosswalk)
    )

    if weight_col not in crosswalk.columns:
        log.warning(
            "'%s' column not found in crosswalk — defaulting to equal weight.",
            weight_col
        )
        crosswalk = crosswalk.copy()
        crosswalk[weight_col] = (
            1.0 / crosswalk.groupby(block_id_col)[block_id_col].transform("count")
        )

    # Join block data to crosswalk
    joined = crosswalk.merge(
        blocks[[block_id_col] + list(available_fields.keys())],
        on=block_id_col,
        how="left",
    )

    missing = joined[list(available_fields.keys())[0]].isna().sum()
    if missing:
        log.warning("%d crosswalk rows had no matching block data.", missing)

    # Apply weights
    for col in available_fields:
        joined[col] = joined[col] * joined[weight_col]

    # Aggregate to district
    result = (
        joined.groupby(district_id_col)
        .agg({**{k: "sum" for k in available_fields}, block_id_col: "nunique"})
        .rename(columns={**available_fields, block_id_col: "num_blocks"})
        .reset_index()
    )

    # Round population counts to integers (weighted splits may produce decimals)
    pop_cols = [v for v in available_fields.values() if "pop" in v or "vap" in v]
    result[pop_cols] = result[pop_cols].round(0).astype(int)

    return result


# ---------------------------------------------------------------------------
# Derived fields
# ---------------------------------------------------------------------------

def add_derived_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Compute pct columns and minority VAP once aggregation is complete."""

    def safe_pct(num, denom):
        return (num / denom.replace(0, np.nan) * 100).round(2)

    if "total_population" in df.columns and "pop_hispanic" in df.columns:
        # Minority population = everyone except non-Hispanic white
        if "pop_white_nh" in df.columns:
            df["pop_minority"] = df["total_population"] - df["pop_white_nh"]
            df["pct_minority"]  = safe_pct(df["pop_minority"], df["total_population"])

        df["pct_hispanic"] = safe_pct(df["pop_hispanic"], df["total_population"])

    if "pop_black_nh" in df.columns and "total_population" in df.columns:
        df["pct_black_nh"] = safe_pct(df["pop_black_nh"], df["total_population"])

    if "vap_total" in df.columns:
        if "vap_hispanic" in df.columns:
            df["pct_hisp_vap"] = safe_pct(df["vap_hispanic"], df["vap_total"])
        if "vap_black_nh" in df.columns:
            df["pct_black_vap"] = safe_pct(df["vap_black_nh"], df["vap_total"])
        if "vap_white_nh" in df.columns:
            df["minority_vap"]     = df["vap_total"] - df["vap_white_nh"]
            df["pct_minority_vap"] = safe_pct(df["minority_vap"], df["vap_total"])

    return df


def add_population_equality(df: pd.DataFrame, pop_col: str = "total_population") -> pd.DataFrame:
    """Append ideal population and deviation columns."""
    if pop_col not in df.columns:
        return df
    ideal = df[pop_col].sum() / len(df)
    df["ideal_population"]  = round(ideal, 2)
    df["pop_deviation"]     = df[pop_col] - ideal
    df["pop_deviation_pct"] = (df["pop_deviation"] / ideal * 100).round(4)
    df["pop_deviation_abs_pct"] = df["pop_deviation_pct"].abs()
    return df


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(df: pd.DataFrame, district_id_col: str) -> None:
    print("\n" + "=" * 60)
    print("AGGREGATION SUMMARY")
    print("=" * 60)
    print(f"  Districts          : {len(df)}")

    if "total_population" in df.columns:
        print(f"  Total population   : {df['total_population'].sum():,.0f}")
        print(f"  Ideal pop/district : {df['ideal_population'].iloc[0]:,.1f}")
        print(f"  Max deviation      : {df['pop_deviation_abs_pct'].max():.2f}%")

    if "pct_minority_vap" in df.columns:
        mmds = (df["pct_minority_vap"] >= 50).sum()
        print(f"  Majority-minority  : {mmds} district(s) (≥50% minority VAP)")

    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Aggregate Census P.L. 94-171 block data to district level."
    )
    p.add_argument("--blocks",       required=True,              help="Block-level data CSV")
    p.add_argument("--crosswalk",    default=None,               help="Block-to-district crosswalk CSV (omit for direct join)")
    p.add_argument("--block-id",     default="GEOID20",          help="Block ID column (default: GEOID20)")
    p.add_argument("--district-col", default="DISTRICT",         help="District column in blocks file (direct join mode)")
    p.add_argument("--district-id",  default="DISTRICT",         help="District ID column in crosswalk (crosswalk mode)")
    p.add_argument("--weight-col",   default="pct_of_block",     help="Weight column in crosswalk (default: pct_of_block)")
    p.add_argument("--output",       default="district_pop.csv", help="Output CSV path")
    return p.parse_args()


def main():
    args = parse_args()

    if not Path(args.blocks).exists():
        log.error("Block file not found: %s", args.blocks)
        sys.exit(1)

    blocks, available_fields = load_blocks(args.blocks, args.block_id)

    if args.crosswalk:
        if not Path(args.crosswalk).exists():
            log.error("Crosswalk file not found: %s", args.crosswalk)
            sys.exit(1)
        crosswalk = pd.read_csv(args.crosswalk, dtype={args.block_id: str})
        result = aggregate_crosswalk(blocks, crosswalk, args.block_id,
                                     args.district_id, available_fields, args.weight_col)
        district_id_col = args.district_id
    else:
        result = aggregate_direct(blocks, args.block_id, args.district_col, available_fields)
        district_id_col = args.district_col

    result = add_derived_fields(result)
    result = add_population_equality(result)

    print_summary(result, district_id_col)
    result.to_csv(args.output, index=False)
    log.info("District population data saved to %s", args.output)


if __name__ == "__main__":
    main()
