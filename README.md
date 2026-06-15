# Redistricting-GIS

GIS and mapping tools for redistricting, political geography, and Census data analysis — built from work at HaystaqDNA and Redistricting Data Hub.

## About

This repository contains Python and R scripts for the full redistricting workflow: downloading raw Census geographies, validating district plans for legal compliance, analyzing minority representation, generating publication-quality maps, and converting between GIS file formats.

---

## Redistricting Tools

| Script | Description |
|--------|-------------|
| [`redistricting/compactness_scores.py`](redistricting/compactness_scores.py) | Computes four compactness metrics — Polsby-Popper, Reock, Convex Hull, and Schwartzberg — used in redistricting litigation. Outputs a ranked CSV with a composite score and flags multi-part (non-contiguous) districts. |
| [`redistricting/contiguity_checker.py`](redistricting/contiguity_checker.py) | Verifies that every district in a plan is geographically contiguous, a constitutional requirement in most states. Detects MultiPolygon breaks, point-only touches, and near-miss gaps from digitizing errors. Exits with code 1 if failures found (CI-pipeline compatible). |

---

## Visualization

| Script | Description |
|--------|-------------|
| [`visualization/choropleth_map.py`](visualization/choropleth_map.py) | Generates publication-quality choropleth maps from a shapefile + CSV. Supports quantiles, natural breaks, equal interval, and diverging classification. Adds north arrow, scale bar, and source annotation. Outputs high-DPI PNG or PDF. |
| [`visualization/district_comparison_map.R`](visualization/district_comparison_map.R) | Four ggplot2 + sf maps for redistricting reports: side-by-side old vs. new plan comparison, minority VAP choropleth (with majority-minority district callouts), population deviation map, and compactness tier map. |

---

## Census Geography Tools

| Script | Description |
|--------|-------------|
| [`census/tiger_downloader.py`](census/tiger_downloader.py) | Downloads Census TIGER/Line shapefiles directly from the Census Bureau FTP. Supports congressional districts, state legislative districts, counties, tracts, VTDs (precincts), places, and block groups. Can merge multi-state downloads into a single shapefile. |
| [`census/census_block_aggregator.py`](census/census_block_aggregator.py) | Aggregates P.L. 94-171 block-level redistricting data (total population, VAP, race/ethnicity) to custom district boundaries. Supports direct join and weighted crosswalk modes for split blocks. Computes minority VAP percentages and population deviation from ideal. |

---

## Data Format Converters

| Script | Description |
|--------|-------------|
| [`converters/geo_format_converter.py`](converters/geo_format_converter.py) | Converts between Shapefile, GeoJSON, GeoPackage, KML, and CSV (with WKT geometry or centroid lat/lon). Supports on-the-fly CRS reprojection, attribute filtering, and batch directory conversion. Handles ESRI's 10-character column name limit automatically. |

---

## Skills & Tools

**Python** — GeoPandas, Shapely, Fiona, Matplotlib, Mapclassify, Requests

**R** — sf, ggplot2, patchwork, scales, ggrepel

**GIS** — ArcGIS, QGIS, Maptitude, TIGER/Line files, Census geographies, shapefiles, GeoJSON, KML, GeoPackage

**Data** — P.L. 94-171 redistricting data, ACS 5-Year estimates, CVAP, FIPS codes

**Projections** — EPSG:4326 (WGS84), EPSG:5070 (Conus Albers Equal Area)

---

## Related Repository

For voter file processing, SQL analytics, and newsletter analysis, see [Projects-and-Scripts](https://github.com/QuentinXS1/Projects-and-Scripts).

---

## Contact

- **LinkedIn:** [linkedin.com/in/quentin-sprauve-5b819893](https://www.linkedin.com/in/quentin-sprauve-5b819893/)
- **Email:** sprauveq@gmail.com
