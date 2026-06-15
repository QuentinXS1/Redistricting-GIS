# =============================================================================
# district_comparison_map.R
# =============================================================================
# Generates side-by-side before/after district maps for redistricting
# plan comparisons, plus standalone thematic maps for any district attribute.
#
# Charts included:
#   1. Side-by-side plan comparison (old vs. new districts)
#   2. Minority VAP choropleth by district
#   3. Population deviation map (district deviation from ideal)
#   4. Compactness score map
#
# Author: Quentin Sprauve
# Dependencies: tidyverse, sf, ggplot2, patchwork, scales, ggrepel
#
# Input files:
#   - old_districts.shp   : previous district plan shapefile
#   - new_districts.shp   : proposed district plan shapefile
#   - district_data.csv   : district_id, minority_vap_pct, pop_deviation,
#                           compactness_score, district_name
# =============================================================================

library(tidyverse)
library(sf)
library(patchwork)
library(scales)
library(ggrepel)

# Shared map theme — clean, minimal, suitable for reports
theme_map <- function(base_size = 11) {
  theme_void(base_size = base_size) +
    theme(
      plot.title      = element_text(face = "bold", size = base_size + 1, hjust = 0.5),
      plot.subtitle   = element_text(color = "gray40", size = base_size - 1, hjust = 0.5),
      plot.caption    = element_text(color = "gray50", size = base_size - 3, hjust = 0),
      legend.position = "bottom",
      legend.title    = element_text(size = base_size - 1),
      legend.text     = element_text(size = base_size - 2),
      plot.margin     = margin(8, 8, 8, 8)
    )
}

output_dir <- "maps"
dir.create(output_dir, showWarnings = FALSE)


# =============================================================================
# 1. Side-by-Side Plan Comparison
# =============================================================================

plot_plan_comparison <- function(
    old_shp   = "old_districts.shp",
    new_shp   = "new_districts.shp",
    id_col    = "DISTRICT",
    old_label = "Current Plan",
    new_label = "Proposed Plan"
) {
  old <- st_read(old_shp, quiet = TRUE) |> st_transform(5070)
  new <- st_read(new_shp, quiet = TRUE) |> st_transform(5070)

  # Generate a color per district (up to 12 districts; cycles for more)
  n_districts <- max(
    length(unique(old[[id_col]])),
    length(unique(new[[id_col]]))
  )
  district_colors <- setNames(
    scales::hue_pal()(min(n_districts, 12)),
    sort(unique(c(old[[id_col]], new[[id_col]])))
  )

  make_panel <- function(sf_obj, plan_label) {
    # Centroids for district labels
    centroids <- sf_obj |>
      st_centroid() |>
      mutate(
        lon = st_coordinates(geometry)[, 1],
        lat = st_coordinates(geometry)[, 2]
      )

    ggplot(sf_obj) +
      geom_sf(aes(fill = .data[[id_col]]), color = "white", linewidth = 0.4) +
      geom_label_repel(
        data       = centroids,
        aes(x = lon, y = lat, label = .data[[id_col]]),
        size       = 2.8,
        fontface   = "bold",
        fill       = alpha("white", 0.7),
        label.size = 0,
        max.overlaps = 20,
      ) +
      scale_fill_manual(values = district_colors, guide = "none") +
      labs(title = plan_label) +
      theme_map()
  }

  p_old <- make_panel(old, old_label)
  p_new <- make_panel(new, new_label)

  combined <- p_old + p_new +
    plot_annotation(
      title   = "District Plan Comparison",
      caption = "Source: District shapefiles. Projected: Conus Albers (EPSG:5070).",
      theme   = theme(plot.title = element_text(face = "bold", size = 13, hjust = 0.5))
    )

  out <- file.path(output_dir, "plan_comparison.png")
  ggsave(out, combined, width = 14, height = 7, dpi = 150)
  message("Saved: ", out)
  return(combined)
}


# =============================================================================
# 2. Minority VAP Choropleth
# =============================================================================

plot_minority_vap <- function(
    shapefile     = "new_districts.shp",
    data_csv      = "district_data.csv",
    id_col        = "district_id",
    vap_col       = "minority_vap_pct",
    vra_threshold = 0.50    # Section 2 / majority-minority threshold
) {
  shp  <- st_read(shapefile, quiet = TRUE) |> st_transform(5070)
  data <- read_csv(data_csv, show_col_types = FALSE)

  shp_joined <- shp |>
    left_join(data, by = setNames(id_col, id_col)) |>
    mutate(
      majority_minority = .data[[vap_col]] >= vra_threshold,
      label = paste0(
        district_name, "\n",
        scales::percent(.data[[vap_col]], accuracy = 1)
      )
    )

  centroids <- shp_joined |>
    st_centroid() |>
    mutate(
      lon = st_coordinates(geometry)[, 1],
      lat = st_coordinates(geometry)[, 2]
    )

  p <- ggplot(shp_joined) +
    geom_sf(aes(fill = .data[[vap_col]]), color = "white", linewidth = 0.5) +
    geom_sf(
      data = filter(shp_joined, majority_minority),
      fill = NA, color = "black", linewidth = 1.2, linetype = "dashed"
    ) +
    geom_label_repel(
      data     = centroids,
      aes(x = lon, y = lat, label = label),
      size     = 2.5, fill = alpha("white", 0.8), label.size = 0,
      max.overlaps = 15,
    ) +
    scale_fill_distiller(
      palette  = "YlOrBr",
      direction = 1,
      labels   = percent_format(accuracy = 1),
      name     = "Minority VAP %",
      limits   = c(0, 1),
      breaks   = c(0, 0.25, 0.50, 0.75, 1.0)
    ) +
    labs(
      title    = "Minority Voting-Age Population by District",
      subtitle = "Dashed border = majority-minority district (≥50% minority VAP)",
      caption  = "Source: ACS 5-Year CVAP estimates joined to district shapefile."
    ) +
    theme_map() +
    theme(legend.key.width = unit(1.5, "cm"))

  out <- file.path(output_dir, "minority_vap_map.png")
  ggsave(out, p, width = 9, height = 7, dpi = 150)
  message("Saved: ", out)
  return(p)
}


# =============================================================================
# 3. Population Deviation Map
# =============================================================================

plot_pop_deviation <- function(
    shapefile = "new_districts.shp",
    data_csv  = "district_data.csv",
    id_col    = "district_id",
    dev_col   = "pop_deviation_pct"   # signed: positive = overpopulated
) {
  shp  <- st_read(shapefile, quiet = TRUE) |> st_transform(5070)
  data <- read_csv(data_csv, show_col_types = FALSE)

  shp_joined <- shp |>
    left_join(data, by = setNames(id_col, id_col))

  max_abs <- max(abs(shp_joined[[dev_col]]), na.rm = TRUE)

  centroids <- shp_joined |>
    st_centroid() |>
    mutate(
      lon   = st_coordinates(geometry)[, 1],
      lat   = st_coordinates(geometry)[, 2],
      label = paste0(
        district_name, "\n",
        ifelse(.data[[dev_col]] >= 0, "+", ""),
        scales::percent(.data[[dev_col]], accuracy = 0.1)
      )
    )

  p <- ggplot(shp_joined) +
    geom_sf(aes(fill = .data[[dev_col]]), color = "white", linewidth = 0.5) +
    geom_label_repel(
      data = centroids,
      aes(x = lon, y = lat, label = label),
      size = 2.5, fill = alpha("white", 0.8), label.size = 0, max.overlaps = 15
    ) +
    scale_fill_distiller(
      palette   = "RdBu",
      direction = 1,
      limits    = c(-max_abs, max_abs),
      labels    = function(x) paste0(ifelse(x >= 0, "+", ""), scales::percent(x, accuracy = 0.1)),
      name      = "Pop. Deviation"
    ) +
    labs(
      title    = "Population Deviation from Ideal District Size",
      subtitle = "Blue = underpopulated  |  Red = overpopulated",
      caption  = "Source: P.L. 94-171 redistricting data."
    ) +
    theme_map() +
    theme(legend.key.width = unit(1.5, "cm"))

  out <- file.path(output_dir, "population_deviation_map.png")
  ggsave(out, p, width = 9, height = 7, dpi = 150)
  message("Saved: ", out)
  return(p)
}


# =============================================================================
# 4. Compactness Score Map
# =============================================================================

plot_compactness <- function(
    shapefile      = "new_districts.shp",
    data_csv       = "district_data.csv",
    id_col         = "district_id",
    compactness_col = "compactness_score"
) {
  shp  <- st_read(shapefile, quiet = TRUE) |> st_transform(5070)
  data <- read_csv(data_csv, show_col_types = FALSE)

  shp_joined <- shp |>
    left_join(data, by = setNames(id_col, id_col)) |>
    mutate(
      compactness_tier = cut(
        .data[[compactness_col]],
        breaks = c(0, 0.20, 0.35, 0.50, 1.0),
        labels = c("Low (<0.20)", "Below Avg (0.20–0.35)",
                   "Average (0.35–0.50)", "High (>0.50)"),
        include.lowest = TRUE
      )
    )

  centroids <- shp_joined |>
    st_centroid() |>
    mutate(
      lon   = st_coordinates(geometry)[, 1],
      lat   = st_coordinates(geometry)[, 2],
      label = paste0(district_name, "\n", round(.data[[compactness_col]], 2))
    )

  tier_colors <- c(
    "Low (<0.20)"           = "#d73027",
    "Below Avg (0.20–0.35)" = "#fc8d59",
    "Average (0.35–0.50)"   = "#91bfdb",
    "High (>0.50)"          = "#1a9641"
  )

  p <- ggplot(shp_joined) +
    geom_sf(aes(fill = compactness_tier), color = "white", linewidth = 0.5) +
    geom_label_repel(
      data = centroids,
      aes(x = lon, y = lat, label = label),
      size = 2.5, fill = alpha("white", 0.8), label.size = 0, max.overlaps = 15
    ) +
    scale_fill_manual(values = tier_colors, name = "Compactness (Polsby-Popper)", na.value = "gray80") +
    labs(
      title    = "District Compactness Scores",
      subtitle = "Polsby-Popper metric: higher = more compact (max = 1.0)",
      caption  = "Source: Computed from district shapefile using equal-area projection."
    ) +
    theme_map()

  out <- file.path(output_dir, "compactness_map.png")
  ggsave(out, p, width = 9, height = 7, dpi = 150)
  message("Saved: ", out)
  return(p)
}


# =============================================================================
# Main — run all maps
# =============================================================================

main <- function() {
  message("Generating district maps...\n")

  # Uncomment as you have the relevant input files:
  # plot_plan_comparison("old_districts.shp", "new_districts.shp")
  # plot_minority_vap("new_districts.shp", "district_data.csv")
  # plot_pop_deviation("new_districts.shp", "district_data.csv")
  # plot_compactness("new_districts.shp",   "district_data.csv")

  message("All maps saved to /maps")
}

# main()
