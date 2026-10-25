"""Figure generation routines for carbon-offset project verification.

Produces publication-grade visual audit artifacts:
1. Sentinel-2 Zone NDVI time series with QC pass/fail markers, dry season shading,
   reporting period span, and outlier annotations.
2. Two-panel high-NDVI decline set D map:
   - Panel (a): First-high year cohorts with largest connected component outlined and annotated.
   - Panel (b): Hansen GFC 30 m grid classification (treecover2000 and lossyear 2019-2022).
3. Hysteresis cohort maps across multiple threshold combinations.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import geopandas as gpd
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds
from scipy.ndimage import center_of_mass, label

from carbonverify.analysis.hansen import _compute_row_pixel_areas_ha, find_hansen_tiles

logger = logging.getLogger(__name__)


def generate_zone_timeseries_figure(
    qc_csv_path: Union[str, Path],
    output_png_path: Union[str, Path],
    reporting_period_start: Optional[str] = None,
    reporting_period_end: Optional[str] = None,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate zone_timeseries.png with below-axes legend, reporting period, and outlier annotation.

    Args:
        qc_csv_path: Path to qc_scenes.csv.
        output_png_path: Destination path for rendered PNG.
        reporting_period_start: Start date string (YYYY-MM-DD) from claims.
        reporting_period_end: End date string (YYYY-MM-DD) from claims.
        project_id: Project identifier for the plot title.

    Returns:
        Metadata dictionary summarizing the generated figure.
    """
    csv_p = Path(qc_csv_path)
    out_p = Path(output_png_path)
    if not csv_p.exists():
        raise FileNotFoundError(f"QC scenes CSV not found at {csv_p}")

    df = pd.read_csv(csv_p)
    df["dt"] = pd.to_datetime(df["date"])
    df = df.sort_values("dt").reset_index(drop=True)

    pass_df = df[df["qc_pass"] == True].copy()
    fail_df = df[df["qc_pass"] == False].copy()

    plt.style.use(
        "seaborn-v0_8-whitegrid"
        if "seaborn-v0_8-whitegrid" in plt.style.available
        else "default"
    )
    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=150)

    # 1. Plot QC-pass scenes
    ax.plot(
        pass_df["dt"],
        pass_df["proj_ndvi_median"],
        color="#10b981",
        linestyle="-",
        linewidth=1.8,
        marker="o",
        markersize=4,
        alpha=0.9,
        label=f"Project Zone (QC Pass, n={len(pass_df)})",
    )
    ax.plot(
        pass_df["dt"],
        pass_df["ring_ndvi_median"],
        color="#3b82f6",
        linestyle="--",
        linewidth=1.5,
        marker="s",
        markersize=3.5,
        alpha=0.8,
        label=f"Reference Ring (QC Pass, n={len(pass_df)})",
    )

    # 2. Plot excluded scenes
    if len(fail_df) > 0:
        ax.scatter(
            fail_df["dt"],
            fail_df["proj_ndvi_median"],
            color="#ef4444",
            marker="x",
            s=45,
            linewidth=1.8,
            zorder=5,
            label=f"Excluded Scenes (Project, n={len(fail_df)})",
        )
        ax.scatter(
            fail_df["dt"],
            fail_df["ring_ndvi_median"],
            color="#f97316",
            marker="+",
            s=45,
            linewidth=1.8,
            zorder=5,
            label=f"Excluded Scenes (Ring, n={len(fail_df)})",
        )

    # 3. Highlight dry seasons (Jun-Aug of 2019, 2020, 2021, 2022)
    for yr in [2019, 2020, 2021, 2022]:
        start_d = pd.to_datetime(f"{yr}-06-01")
        end_d = pd.to_datetime(f"{yr}-08-31")
        ax.axvspan(
            start_d,
            end_d,
            color="#fef3c7",
            alpha=0.35,
            label="Dry Season (Jun-Aug)" if yr == 2019 else "",
        )

    # 4. Shaded span for reporting period with dates from extracted claims
    legend_rp_label = ""
    if reporting_period_start and reporting_period_end:
        rp_start = pd.to_datetime(reporting_period_start)
        rp_end = pd.to_datetime(reporting_period_end)
        legend_rp_label = f"Reporting Period ({reporting_period_start} to {reporting_period_end})"
        ax.axvspan(
            rp_start,
            rp_end,
            color="#c7d2fe",
            alpha=0.30,
            label=legend_rp_label,
        )

    # 5. Annotate the NDVI = 1.0 excluded scene with its exclusion reason from qc_scenes.csv
    near_one = fail_df[
        (fail_df["ring_ndvi_median"] >= 0.98) | (fail_df["proj_ndvi_median"] >= 0.98)
    ]
    annotated_reason = ""
    if not near_one.empty:
        row = near_one.iloc[0]
        y_val = (
            float(row["ring_ndvi_median"])
            if pd.notnull(row["ring_ndvi_median"]) and row["ring_ndvi_median"] >= 0.98
            else float(row["proj_ndvi_median"])
        )
        annotated_reason = str(row.get("qc_reasons", "excluded"))
        d_str = str(row["date"])
        dt_val = row["dt"]
        ax.annotate(
            f"Excluded scene (NDVI ≈ 1.0):\n{annotated_reason}\n({d_str})",
            xy=(dt_val, y_val),
            xytext=(dt_val - pd.Timedelta(days=130), y_val - 0.20),
            arrowprops=dict(facecolor="#b91c1c", edgecolor="#b91c1c", arrowstyle="->", lw=1.5),
            fontsize=9,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#fee2e2", edgecolor="#ef4444", alpha=0.9),
            zorder=10,
        )

    proj_label = f"Project {project_id}: " if project_id else ""
    ax.set_title(
        f"{proj_label}Sentinel-2 Zone NDVI Time Series (2019–2022)",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )
    ax.set_xlabel("Acquisition Date", fontsize=11, labelpad=8)
    ax.set_ylabel("NDVI Median", fontsize=11, labelpad=8)
    ax.set_ylim(-0.02, 1.05)

    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_formatter(mdates.DateFormatter("%b"))

    ax.grid(True, linestyle=":", alpha=0.6)

    # Move legend outside axes (below the plot) so it covers no data
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.15),
        ncol=3,
        frameon=True,
        framealpha=0.95,
        facecolor="white",
        edgecolor="#cbd5e1",
        fontsize=9,
    )

    out_p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_p, dpi=150, bbox_inches="tight")
    plt.close(fig)

    file_size = out_p.stat().st_size
    logger.info("Generated zone timeseries plot at %s (%d bytes)", out_p, file_size)

    return {
        "output_path": str(out_p),
        "file_size": file_size,
        "pass_count": len(pass_df),
        "fail_count": len(fail_df),
        "annotated_reason": annotated_reason,
        "reporting_period_label": legend_rp_label,
    }


def generate_decline_map_figure(
    project_dir: Union[str, Path],
    output_png_path: Union[str, Path],
    hansen_dir: Union[str, Path] = "data/external/hansen",
    gfc_version: str = "GFC-2022-v1.10",
) -> Dict[str, Any]:
    """Generate decline_map.png containing two panels at the same extent as cohort_maps.png.

    Panel (a): Decline set D (qm >= 0.70 in some year 2019-2021 and qm2022 < 0.60) coloured by
    first-high year, with the largest component outlined and labelled with its area.
    Panel (b): Same pixels classified at the Hansen 30 m grid:
      - treecover2000 < 25
      - treecover2000 >= 25 with no loss in 2019-2022
      - treecover2000 >= 25 with loss in 2019-2022
    Legends carry the computed areas.

    Args:
        project_dir: Project directory (e.g. data/projects/2469).
        output_png_path: Target PNG output path.
        hansen_dir: Directory containing Hansen GeoTIFF tiles.
        gfc_version: Hansen GFC version string.

    Returns:
        Dictionary of computed metrics, areas, and legend texts.
    """
    proj_p = Path(project_dir).resolve()
    out_p = Path(output_png_path)
    hansen_p = Path(hansen_dir).resolve()

    comp_dir = proj_p / "imagery" / "composites" if (proj_p / "imagery" / "composites").exists() else proj_p
    boundary_path = proj_p / "imagery" / "project_boundary.geojson"
    if not boundary_path.exists():
        boundary_path = proj_p / "boundary.geojson"
    if not boundary_path.exists():
        raise FileNotFoundError(f"Project boundary not found in {proj_p}")

    proj_gdf = gpd.read_file(boundary_path)

    # 1. Load S2 composites
    with rasterio.open(comp_dir / "ndvi_qm_2019.tif") as s2_src:
        crs = s2_src.crs
        transform = s2_src.transform
        shape = s2_src.shape

    proj_utm = proj_gdf.to_crs(crs).iloc[0].geometry
    proj_mask = rasterize([(proj_utm, 1)], out_shape=shape, transform=transform, fill=0, dtype=np.uint8) == 1

    years = ["2019", "2020", "2021", "2022"]
    qm = {}
    for y in years:
        with rasterio.open(comp_dir / f"ndvi_qm_{y}.tif") as src:
            qm[y] = src.read(1)

    # 2. Decline set D and first-high year cohorts
    high_19_21 = (qm["2019"] >= 0.70) | (qm["2020"] >= 0.70) | (qm["2021"] >= 0.70)
    mask_D = proj_mask & high_19_21 & (qm["2022"] < 0.60)
    pixel_ha = 0.01
    area_D_ha = round(float(np.sum(mask_D) * pixel_ha), 2)

    fh_19 = proj_mask & (qm["2019"] >= 0.70) & (qm["2022"] < 0.60)
    fh_20 = proj_mask & (~fh_19) & (qm["2020"] >= 0.70) & (qm["2022"] < 0.60)
    fh_21 = proj_mask & (~fh_19) & (~fh_20) & (qm["2021"] >= 0.70) & (qm["2022"] < 0.60)

    ha_19 = round(float(np.sum(fh_19) * pixel_ha), 2)
    ha_20 = round(float(np.sum(fh_20) * pixel_ha), 2)
    ha_21 = round(float(np.sum(fh_21) * pixel_ha), 2)

    # 3. Connected components of D
    struct = np.ones((3, 3), dtype=int)
    labeled, n_comp = label(mask_D, structure=struct)
    if n_comp > 0:
        counts = np.bincount(labeled.ravel())[1:]
        areas = counts * pixel_ha
        sorted_idx = np.argsort(-areas)
        largest_id = int(sorted_idx[0]) + 1
        largest_mask = labeled == largest_id
        largest_ha = round(float(areas[sorted_idx[0]]), 2)
    else:
        largest_mask = np.zeros_like(mask_D, dtype=bool)
        largest_ha = 0.0

    # 4. Crop extent matching cohort_maps.png (UTM bounding box + pad=30)
    p_minx, p_miny, p_maxx, p_maxy = proj_utm.bounds
    p_win = from_bounds(p_minx, p_miny, p_maxx, p_maxy, transform)
    pad = 30
    r_start = max(0, int(p_win.row_off) - pad)
    r_end = int(p_win.row_off + p_win.height) + pad
    c_start = max(0, int(p_win.col_off) - pad)
    c_end = int(p_win.col_off + p_win.width) + pad

    coords = np.array(proj_utm.exterior.coords)
    inv_tf = ~transform
    px_coords = [inv_tf @ (x, y) for x, y in coords]
    px_cols = [c - c_start for c, r in px_coords]
    px_rows = [r - r_start for c, r in px_coords]

    # Panel (a) raster: 0=outside, 1=other proj, 2=2021, 3=2020, 4=2019 (darkest)
    p_a_full = np.zeros(shape, dtype=np.uint8)
    p_a_full[proj_mask] = 1
    p_a_full[fh_21] = 2
    p_a_full[fh_20] = 3
    p_a_full[fh_19] = 4
    p_a_crop = p_a_full[r_start:r_end, c_start:c_end]
    largest_crop = largest_mask[r_start:r_end, c_start:c_end]

    # 5. Hansen GFC 30 m grid classification
    proj_4326 = proj_gdf.to_crs(epsg=4326)
    bounds_4326 = tuple(proj_4326.total_bounds)
    tiles = find_hansen_tiles(bounds_4326)
    tile_id = tiles[0] if tiles else "20S_060W"

    tc_file = hansen_p / f"Hansen_{gfc_version}_treecover2000_{tile_id}.tif"
    ly_file = hansen_p / f"Hansen_{gfc_version}_lossyear_{tile_id}.tif"
    if not tc_file.exists() or not ly_file.exists():
        candidate_tc = list(hansen_p.glob(f"*treecover2000*{tile_id}*.tif"))
        candidate_ly = list(hansen_p.glob(f"*lossyear*{tile_id}*.tif"))
        if candidate_tc and candidate_ly:
            tc_file = candidate_tc[0]
            ly_file = candidate_ly[0]
        else:
            raise FileNotFoundError(f"Hansen tiles for {tile_id} not found in {hansen_p}")

    ring_bound_path = proj_p / "imagery" / "reference_ring.geojson"
    if ring_bound_path.exists():
        ring_gdf = gpd.read_file(ring_bound_path)
        ring_4326 = ring_gdf.to_crs(epsg=4326)
        extent_bounds = tuple(ring_4326.total_bounds)
    else:
        extent_bounds = bounds_4326

    with rasterio.open(tc_file) as tc_src, rasterio.open(ly_file) as ly_src:
        tc_crs = tc_src.crs
        tc_transform = tc_src.transform
        buf_deg = 0.005
        win = from_bounds(
            extent_bounds[0] - buf_deg,
            extent_bounds[1] - buf_deg,
            extent_bounds[2] + buf_deg,
            extent_bounds[3] + buf_deg,
            tc_transform,
        ).round_offsets().round_lengths()
        win_tf = rasterio.windows.transform(win, tc_transform)
        win_shape = (int(win.height), int(win.width))
        tc_win = tc_src.read(1, window=win)
        ly_win = ly_src.read(1, window=win)

    # Ellipsoidal pixel areas
    rows = np.arange(win_shape[0])
    lats_deg = win_tf.f + (rows + 0.5) * win_tf.e
    row_areas = _compute_row_pixel_areas_ha(lats_deg, res_deg=abs(win_tf.e))
    pixel_area_grid = np.tile(row_areas[:, np.newaxis], (1, win_shape[1]))

    mask_D_30m = np.zeros(win_shape, dtype=np.float32)
    reproject(
        source=mask_D.astype(np.float32),
        destination=mask_D_30m,
        src_transform=transform,
        src_crs=crs,
        dst_transform=win_tf,
        dst_crs=tc_crs,
        resampling=Resampling.nearest,
    )
    d_30m = mask_D_30m >= 0.5

    c1_30m = d_30m & (tc_win < 25)
    c2_30m = d_30m & (tc_win >= 25) & ((ly_win == 0) | (ly_win < 19) | (ly_win > 22))
    c3_30m = d_30m & (tc_win >= 25) & (ly_win >= 19) & (ly_win <= 22)

    area_c1 = round(float((c1_30m * pixel_area_grid).sum()), 2)
    area_c2 = round(float((c2_30m * pixel_area_grid).sum()), 2)
    area_c3 = round(float((c3_30m * pixel_area_grid).sum()), 2)

    # Reproject 30 m classification map back to S2 10 m grid for display
    cat_30m = np.zeros(win_shape, dtype=np.uint8)
    cat_30m[c1_30m] = 1
    cat_30m[c2_30m] = 2
    cat_30m[c3_30m] = 3

    cat_10m = np.zeros(shape, dtype=np.uint8)
    reproject(
        source=cat_30m,
        destination=cat_10m,
        src_transform=win_tf,
        src_crs=tc_crs,
        dst_transform=transform,
        dst_crs=crs,
        resampling=Resampling.nearest,
    )

    p_b_full = np.zeros(shape, dtype=np.uint8)
    p_b_full[proj_mask] = 4  # other project area
    p_b_full[mask_D & (cat_10m == 1)] = 1
    p_b_full[mask_D & (cat_10m == 2)] = 2
    p_b_full[mask_D & (cat_10m == 3)] = 3
    p_b_crop = p_b_full[r_start:r_end, c_start:c_end]

    # 6. Render two-panel figure
    fig, axes = plt.subplots(1, 2, figsize=(16, 9), constrained_layout=True)

    # Panel (a)
    cmap_a = ListedColormap(["#ffffff", "#e0e0e0", "#fc9272", "#ef3b2c", "#67000d"])
    norm_a = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5, 4.5], cmap_a.N)
    axes[0].imshow(p_a_crop, origin="upper", cmap=cmap_a, norm=norm_a, interpolation="nearest")
    axes[0].plot(px_cols, px_rows, color="black", linewidth=1.5)

    if np.any(largest_crop):
        axes[0].contour(largest_crop.astype(float), levels=[0.5], colors=["#00e5ff"], linewidths=1.8)
        cy, cx = center_of_mass(largest_crop)
        axes[0].annotate(
            f"Largest component\n({largest_ha:,.2f} ha)",
            xy=(cx, cy),
            xytext=(cx + 35, cy - 40),
            arrowprops=dict(facecolor="black", edgecolor="black", arrowstyle="->", lw=1.5),
            fontsize=9.5,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="black", alpha=0.9),
        )

    axes[0].set_title(
        f"(a) Decline Set D ({area_D_ha:,.2f} ha) by First-High Year",
        fontsize=12,
        fontweight="bold",
    )
    axes[0].set_axis_off()

    legend_a = [
        mpatches.Patch(color="#67000d", label=f"First high 2019 ({ha_19:,.2f} ha)"),
        mpatches.Patch(color="#ef3b2c", label=f"First high 2020 ({ha_20:,.2f} ha)"),
        mpatches.Patch(color="#fc9272", label=f"First high 2021 ({ha_21:,.2f} ha)"),
        mpatches.Patch(
            facecolor="none",
            edgecolor="#00e5ff",
            linewidth=1.8,
            label=f"Largest component ({largest_ha:,.2f} ha, outlined)",
        ),
        mpatches.Patch(color="#e0e0e0", label="Other Project Area"),
        mpatches.Patch(color="black", label="Project Boundary"),
    ]
    axes[0].legend(
        handles=legend_a,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.02),
        ncol=2,
        fontsize=9.5,
        framealpha=0.95,
    )

    # Panel (b)
    # 0: white, 1: amber (tc<25), 2: green (tc>=25 no loss), 3: red (tc>=25 loss), 4: grey (other)
    cmap_b = ListedColormap(["#ffffff", "#fdae61", "#2ca25f", "#d73027", "#e0e0e0"])
    norm_b = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5, 4.5], cmap_b.N)
    axes[1].imshow(p_b_crop, origin="upper", cmap=cmap_b, norm=norm_b, interpolation="nearest")
    axes[1].plot(px_cols, px_rows, color="black", linewidth=1.5)
    axes[1].set_title(
        "(b) Decline Pixels at Hansen 30 m Grid Classification",
        fontsize=12,
        fontweight="bold",
    )
    axes[1].set_axis_off()

    legend_b = [
        mpatches.Patch(color="#fdae61", label=f"treecover2000 < 25 ({area_c1:,.2f} ha)"),
        mpatches.Patch(
            color="#2ca25f",
            label=f"treecover2000 >= 25, no loss 2019-2022 ({area_c2:,.2f} ha)",
        ),
        mpatches.Patch(
            color="#d73027",
            label=f"treecover2000 >= 25, loss in 2019-2022 ({area_c3:,.2f} ha)",
        ),
        mpatches.Patch(color="#e0e0e0", label="Other Project Area"),
        mpatches.Patch(color="black", label="Project Boundary"),
    ]
    axes[1].legend(
        handles=legend_b,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.02),
        ncol=1,
        fontsize=9.5,
        framealpha=0.95,
    )

    out_p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_p, dpi=300, bbox_inches="tight")
    plt.close(fig)

    file_size = out_p.stat().st_size
    logger.info("Generated decline map figure at %s (%d bytes)", out_p, file_size)

    return {
        "output_path": str(out_p),
        "file_size": file_size,
        "area_D_ha": area_D_ha,
        "ha_19": ha_19,
        "ha_20": ha_20,
        "ha_21": ha_21,
        "largest_ha": largest_ha,
        "area_c1": area_c1,
        "area_c2": area_c2,
        "area_c3": area_c3,
        "legend_labels_a": [p.get_label() for p in legend_a],
        "legend_labels_b": [p.get_label() for p in legend_b],
    }


def generate_cohort_maps_figure(
    project_dir: Union[str, Path],
    output_png_path: Union[str, Path],
) -> Dict[str, Any]:
    """Generate cohort_maps.png matching standard publication layout.

    Args:
        project_dir: Path to project directory.
        output_png_path: Path to write PNG.

    Returns:
        Summary dictionary with computed areas and path.
    """
    proj_p = Path(project_dir).resolve()
    out_p = Path(output_png_path)
    comp_dir = proj_p / "imagery" / "composites" if (proj_p / "imagery" / "composites").exists() else proj_p

    boundary_path = proj_p / "imagery" / "project_boundary.geojson"
    if not boundary_path.exists():
        boundary_path = proj_p / "boundary.geojson"

    proj_gdf = gpd.read_file(boundary_path)
    with rasterio.open(comp_dir / "ndvi_qm_2019.tif") as src:
        crs = src.crs
        win_transform = src.transform
        expected_shape = src.shape

    proj_utm = proj_gdf.to_crs(crs).iloc[0].geometry
    mask_proj = rasterize(
        [(proj_utm, 1)],
        out_shape=expected_shape,
        transform=win_transform,
        fill=0,
        all_touched=False,
        dtype="uint8",
    )

    years = ["2019", "2020", "2021", "2022"]
    qm_composites = {}
    for yr in years:
        with rasterio.open(comp_dir / f"ndvi_qm_{yr}.tif") as src:
            qm_composites[yr] = src.read(1)

    p_minx, p_miny, p_maxx, p_maxy = proj_utm.bounds
    p_win = from_bounds(p_minx, p_miny, p_maxx, p_maxy, win_transform)
    pad = 30
    r_start = max(0, int(p_win.row_off) - pad)
    r_end = int(p_win.row_off + p_win.height) + pad
    c_start = max(0, int(p_win.col_off) - pad)
    c_end = int(p_win.col_off + p_win.width) + pad

    coords = np.array(proj_utm.exterior.coords)
    inv_tf = ~win_transform
    px_coords = [inv_tf @ (x, y) for x, y in coords]
    px_cols = [c - c_start for c, r in px_coords]
    px_rows = [r - r_start for c, r in px_coords]

    pixel_ha = 0.01
    proj_px = mask_proj == 1
    total_proj_ha = float(np.sum(proj_px) * pixel_ha)

    p1_data = qm_composites["2022"][r_start:r_end, c_start:c_end].copy()

    gain_full = np.zeros(expected_shape, dtype=np.float32)
    gain_full[proj_px] = 1.0
    is_gain = proj_px & (qm_composites["2022"] >= 0.7) & (qm_composites["2019"] < 0.6)
    gain_full[is_gain] = 2.0
    p2_data = gain_full[r_start:r_end, c_start:c_end]

    gain_ha = float(np.sum(is_gain) * pixel_ha)
    other_ha = float(np.sum(proj_px & (~is_gain)) * pixel_ha)

    fhy_full = np.zeros(expected_shape, dtype=np.float32)
    t = 0.7
    is_p19 = proj_px & (qm_composites["2019"] >= t)
    is_p20 = proj_px & (~is_p19) & (qm_composites["2020"] >= t)
    is_p21 = proj_px & (~is_p19) & (~is_p20) & (qm_composites["2021"] >= t)
    is_p22 = proj_px & (~is_p19) & (~is_p20) & (~is_p21) & (qm_composites["2022"] >= t)
    is_never = proj_px & (~is_p19) & (~is_p20) & (~is_p21) & (~is_p22)

    fhy_full[is_p19] = 1
    fhy_full[is_p20] = 2
    fhy_full[is_p21] = 3
    fhy_full[is_p22] = 4
    fhy_full[is_never] = 5
    p3_data = fhy_full[r_start:r_end, c_start:c_end]

    ha_19 = float(np.sum(is_p19) * pixel_ha)
    ha_20 = float(np.sum(is_p20) * pixel_ha)
    ha_21 = float(np.sum(is_p21) * pixel_ha)
    ha_22 = float(np.sum(is_p22) * pixel_ha)
    ha_never = float(np.sum(is_never) * pixel_ha)

    pct_19 = (ha_19 / total_proj_ha) * 100.0 if total_proj_ha > 0 else 0.0
    pct_20 = (ha_20 / total_proj_ha) * 100.0 if total_proj_ha > 0 else 0.0
    pct_21 = (ha_21 / total_proj_ha) * 100.0 if total_proj_ha > 0 else 0.0
    pct_22 = (ha_22 / total_proj_ha) * 100.0 if total_proj_ha > 0 else 0.0
    pct_never = (ha_never / total_proj_ha) * 100.0 if total_proj_ha > 0 else 0.0

    fig, axes = plt.subplots(1, 3, figsize=(22, 9.5), constrained_layout=True)

    im1 = axes[0].imshow(p1_data, origin="upper", vmin=0.0, vmax=1.0, cmap="viridis", interpolation="nearest")
    axes[0].plot(px_cols, px_rows, color="red", linewidth=1.5, label="Project Boundary")
    axes[0].set_title("(a) 2022 NDVI (Quantile Mapped)", fontsize=13, fontweight="bold")
    axes[0].set_axis_off()
    cbar1 = fig.colorbar(im1, ax=axes[0], orientation="horizontal", fraction=0.046, pad=0.04)
    cbar1.set_label("NDVI [0 - 1]", fontsize=11)

    cmap_gain = ListedColormap(["#ffffff", "#e0e0e0", "#2ca25f"])
    norm_gain = BoundaryNorm([-0.5, 0.5, 1.5, 2.5], cmap_gain.N)
    axes[1].imshow(p2_data, origin="upper", cmap=cmap_gain, norm=norm_gain, interpolation="nearest")
    axes[1].plot(px_cols, px_rows, color="black", linewidth=1.5)
    axes[1].set_title("(b) Endpoint gain: qm2019 < 0.60 and qm2022 >= 0.70", fontsize=13, fontweight="bold")
    axes[1].set_axis_off()
    patch_gain = mpatches.Patch(color="#2ca25f", label=f"Endpoint gain ({gain_ha:,.2f} ha, no stability test)")
    patch_other = mpatches.Patch(color="#e0e0e0", label=f"Other Project Area ({other_ha:,.2f} ha)")
    patch_bnd = mpatches.Patch(color="black", label="Project Boundary")
    axes[1].legend(
        handles=[patch_gain, patch_other, patch_bnd],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.02),
        ncol=1,
        fontsize=10,
        framealpha=0.9,
    )

    cmap_fhy = ListedColormap(["#ffffff", "#005a32", "#41ab5d", "#fee391", "#fe9929", "#bdbdbd"])
    norm_fhy = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5, 4.5, 5.5], cmap_fhy.N)
    axes[2].imshow(p3_data, origin="upper", cmap=cmap_fhy, norm=norm_fhy, interpolation="nearest")
    axes[2].plot(px_cols, px_rows, color="black", linewidth=1.5)
    axes[2].set_title("(c) First year qm >= 0.70", fontsize=13, fontweight="bold")
    axes[2].set_axis_off()
    fhy_patches = [
        mpatches.Patch(color="#005a32", label=f"2019 ({ha_19:,.2f} ha, {pct_19:.1f}%)"),
        mpatches.Patch(color="#41ab5d", label=f"2020 ({ha_20:,.2f} ha, {pct_20:.1f}%)"),
        mpatches.Patch(color="#fee391", label=f"2021 ({ha_21:,.2f} ha, {pct_21:.1f}%)"),
        mpatches.Patch(color="#fe9929", label=f"2022 ({ha_22:,.2f} ha, {pct_22:.1f}%)"),
        mpatches.Patch(color="#bdbdbd", label=f"Never ({ha_never:,.2f} ha, {pct_never:.1f}%)"),
    ]
    axes[2].legend(
        handles=fhy_patches,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.02),
        ncol=2,
        fontsize=10,
        framealpha=0.9,
    )

    out_p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_p, dpi=300, bbox_inches="tight")
    plt.close(fig)

    file_size = out_p.stat().st_size
    logger.info("Generated cohort maps at %s (%d bytes)", out_p, file_size)

    return {
        "output_path": str(out_p),
        "file_size": file_size,
        "gain_ha": gain_ha,
        "other_ha": other_ha,
        "ha_19": ha_19,
        "ha_20": ha_20,
        "ha_21": ha_21,
        "ha_22": ha_22,
        "ha_never": ha_never,
    }
