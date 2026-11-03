#!/usr/bin/env python3
"""Validate district population equality from a simple tabular export.

This companion tool accepts a CSV with one district column and one population
column, aggregates split records, and reports deviations from the ideal district
population. It is useful before a map is circulated for stakeholder review.

Usage:
    python plan_population_report.py district_population.csv \
        --district-column district_id --population-column total_population
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def build_report(frame: pd.DataFrame, district_column: str, population_column: str) -> pd.DataFrame:
    """Aggregate district populations and calculate deviation from ideal."""
    required = {district_column, population_column}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Input is missing required columns: {', '.join(sorted(missing))}")

    work = frame[[district_column, population_column]].copy()
    work[population_column] = pd.to_numeric(work[population_column], errors="coerce")
    if work[population_column].isna().any():
        raise ValueError("Population values must be numeric and nonblank.")

    report = (
        work.groupby(district_column, dropna=False, as_index=False)[population_column]
        .sum()
        .rename(columns={population_column: "population"})
        .sort_values(district_column, kind="stable")
    )
    if report[district_column].isna().any() or (report[district_column].astype(str).str.strip() == "").any():
        raise ValueError("District identifiers must be present for every record.")

    ideal = report["population"].sum() / len(report)
    report["ideal_population"] = ideal
    report["deviation"] = report["population"] - ideal
    report["deviation_percent"] = (report["deviation"] / ideal * 100).round(3)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Report district population equality from a CSV.")
    parser.add_argument("input", type=Path, help="CSV containing district and population fields")
    parser.add_argument("--district-column", required=True)
    parser.add_argument("--population-column", required=True)
    parser.add_argument("--threshold", type=float, default=5.0, help="Absolute percent threshold (default: 5)")
    parser.add_argument("--output", type=Path, help="Optional output CSV path")
    args = parser.parse_args()

    report = build_report(pd.read_csv(args.input), args.district_column, args.population_column)
    report["within_threshold"] = report["deviation_percent"].abs() <= args.threshold
    rendered = report.to_csv(index=False)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Wrote {len(report)} district records to {args.output}")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()

