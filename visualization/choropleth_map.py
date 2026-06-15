"""
choropleth_map.py
==================
Generates publication-quality choropleth maps from a shapefile and a
data CSV, using GeoPandas + Matplotlib + mapclassify.

Features:
  - Auto-selects classification scheme (quantiles, equal interval, natural breaks)
  - Supports any diverging or sequential colormap
  - Adds scale bar, north arrow, and data source annotation
  - Outputs high-DPI PNG or PDF

Common use cases:
  - Voter turnout by precinct
  - Demographic share by district
  - Election margin map
  - Population density by Census tract

Author: Quentin Sprauve
Dependencies: geopandas, pandas, matplotlib, mapclassify, mpl_toolkits
Usage:
    python choropleth_map.py \
        --shapefile precincts.shp \
        --data turnout.csv \
        --join-col precinct_id \
        --value-col turnout_rate \
        --title "2024 General Election Turnout by Precinct" \
        --output turnout_map.png

    # Diverging map (e.g. DEM/REP margin):
    python choropleth_map.py --shapefile districts.shp --data margins.csv \
        --join-col district_id --value-col dem_margin \
        --scheme diverging --cmap RdBu --output margin_map.png
"""

import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from matplotlib.colors import TwoSlopeNorm, Normalize
from mpl_toolkits.axes_grid1 import make_axes_locatable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Default display CRS (good for continental US)
DISPLAY_CRS = "EPSG:5070"


# ---------------------------------------------------------------------------
# Classification schemes
# ---------------------------------------------------------------------------

def classify_data(series: pd.Series, scheme: str, k: int = 7):
    """Apply mapclassify scheme; return bin edges for colorbar."""
    try:
        import mapclassify as mc
    except ImportError:
        log.error("mapclassify not installed. Run: pip install mapclassify")
        sys.exit(1)

    scheme_map = {
        "quantiles":      mc.Quantiles,
        "equal_interval": mc.EqualInterval,
        "natural_breaks": mc.NaturalBreaks,
        "fisher_jenks":   mc.FisherJenks,
    }
    if scheme not in scheme_map:
        log.warning("Unknown scheme '%s', defaulting to quantiles.", scheme)
        scheme = "quantiles"

    classifier = scheme_map[scheme](series.dropna(), k=k)
    return classifier


# ---------------------------------------------------------------------------
# Map elements
# ---------------------------------------------------------------------------

def add_north_arrow(ax, x=0.97, y=0.97, size=0.04):
    """Add a minimal north arrow to the axes."""
    ax.annotate(
        "N", xy=(x, y), xycoords="axes fraction",
        fontsize=10, ha="center", va="center", fontweight="bold"
    )
    ax.annotate(
        "", xy=(x, y - size), xycoords="axes fraction",
        xytext=(x, y - size * 2.5),
        arrowprops=dict(arrowstyle="-|>", color="black", lw=1.2),
    )


def add_scale_bar(ax, gdf_plot, length_fraction=0.2):
    """Add a simple scale bar (approximate, works for equal-area projections)."""
    xmin, ymin, xmax, ymax = gdf_plot.total_bounds
    bar_length = (xmax - xmin) * length_fraction
    bar_x = xmin + (xmax - xmin) * 0.05
    bar_y = ymin + (ymax - ymin) * 0.03

    ax.plot(
        [bar_x, bar_x + bar_length],
        [bar_y, bar_y],
        color="black", linewidth=2, solid_capstyle="butt",
        transform=ax.transData,
    )
    miles = bar_length / METERS_PER_MILE if hasattr(sys.modules[__name__], "METERS_PER_MILE") else bar_length / 1609
    ax.text(
        bar_x + bar_length / 2, bar_y + (ymax - ymin) * 0.01,
        f"{miles:,.0f} mi", ha="center", va="bottom", fontsize=8, color="black",
    )

METERS_PER_MILE = 1609.344


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def make_choropleth(
    shapefile:   str,
    data_path:   str,
    join_col:    str,
    value_col:   str,
    title:       str,
    output:      str,
    scheme:      str  = "quantiles",
    cmap:        str  = "YlOrRd",
    k:           int  = 7,
    figsize:     tuple = (12, 9),
    dpi:         int  = 150,
    caption:     str  = "",
    diverging:   bool = False,
    label_fmt:   str  = "{:.0%}",
) -> None:

    # Load and join
    log.info("Loading shapefile: %s", shapefile)
    gdf = gpd.read_file(shapefile).to_crs(DISPLAY_CRS)

    log.info("Loading data: %s", data_path)
    df = pd.read_csv(data_path)
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")

    gdf = gdf.merge(df[[join_col, value_col]], left_on=join_col, right_on=join_col, how="left")
    missing = gdf[value_col].isna().sum()
    if missing:
        log.warning("%d features have no data — shown in gray.", missing)

    # Classification
    valid = gdf[value_col].dropna()
    vmin, vmax = valid.min(), valid.max()

    # Normalization
    if diverging:
        norm = TwoSlopeNorm(vmin=vmin, vcenter=0, vmax=vmax)
    else:
        classifier = classify_data(valid, scheme, k)
        norm = Normalize(vmin=vmin, vmax=vmax)

    # Figure
    fig, ax = plt.subplots(1, 1, figsize=figsize)
    ax.set_aspect("equal")

    # Base layer: missing data in light gray
    gdf[gdf[value_col].isna()].plot(ax=ax, color="#d9d9d9", edgecolor="white", linewidth=0.3)

    # Choropleth layer
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="3%", pad=0.1)

    gdf[gdf[value_col].notna()].plot(
        column=value_col,
        ax=ax,
        cmap=cmap,
        norm=norm,
        edgecolor="white",
        linewidth=0.3,
        legend=True,
        legend_kwds={"cax": cax, "label": value_col.replace("_", " ").title()},
    )

    # Map furniture
    add_north_arrow(ax)
    add_scale_bar(ax, gdf)
    ax.set_axis_off()

    # Titles
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    if caption:
        fig.text(0.02, 0.01, caption, fontsize=7, color="gray", ha="left")

    # Classification legend (optional for quantile maps)
    if not diverging and scheme in ("quantiles", "natural_breaks", "fisher_jenks"):
        try:
            classifier = classify_data(valid, scheme, k)
            bins = [vmin] + list(classifier.bins)
            patches = []
            cmap_obj = plt.get_cmap(cmap)
            for i in range(len(bins) - 1):
                color = cmap_obj((i + 0.5) / (len(bins) - 1))
                lo = label_fmt.format(bins[i])
                hi = label_fmt.format(bins[i + 1])
                patches.append(mpatches.Patch(color=color, label=f"{lo} – {hi}"))
            ax.legend(
                handles=patches,
                loc="lower left",
                fontsize=7,
                title=scheme.replace("_", " ").title(),
                title_fontsize=7,
                framealpha=0.85,
            )
        except Exception:
            pass  # Legend is optional — don't fail the whole map

    plt.tight_layout()
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output, dpi=dpi, bbox_inches="tight", facecolor="white")
    log.info("Map saved to %s", output)
    plt.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Generate a choropleth map from a shapefile + CSV.")
    p.add_argument("--shapefile",  required=True,            help="Input shapefile")
    p.add_argument("--data",       required=True,            help="CSV with values to map")
    p.add_argument("--join-col",   required=True,            help="Column to join shapefile and CSV on")
    p.add_argument("--value-col",  required=True,            help="Column to map (values)")
    p.add_argument("--title",      default="Choropleth Map", help="Map title")
    p.add_argument("--output",     default="map.png",        help="Output file path (.png or .pdf)")
    p.add_argument("--scheme",     default="quantiles",
                   choices=["quantiles", "equal_interval", "natural_breaks", "fisher_jenks", "diverging"],
                   help="Classification scheme (default: quantiles)")
    p.add_argument("--cmap",       default="YlOrRd",         help="Matplotlib colormap (default: YlOrRd)")
    p.add_argument("--k",          type=int, default=7,       help="Number of classes (default: 7)")
    p.add_argument("--caption",    default="",               help="Source/caption text")
    p.add_argument("--label-fmt",  default="{:.0%}",         help="Value label format string (default: percent)")
    p.add_argument("--dpi",        type=int, default=150,     help="Output DPI (default: 150)")
    return p.parse_args()


def main():
    args = parse_args()
    diverging = args.scheme == "diverging"
    make_choropleth(
        shapefile  = args.shapefile,
        data_path  = args.data,
        join_col   = args.join_col,
        value_col  = args.value_col,
        title      = args.title,
        output     = args.output,
        scheme     = args.scheme if not diverging else "quantiles",
        cmap       = args.cmap,
        k          = args.k,
        caption    = args.caption,
        diverging  = diverging,
        label_fmt  = args.label_fmt,
        dpi        = args.dpi,
    )


if __name__ == "__main__":
    main()
