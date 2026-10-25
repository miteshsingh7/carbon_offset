"""Independent canopy-cover and biomass-proxy change analysis.

Computes annual canopy cover area and boundary shares across NDVI thresholds,
primary canopy change (T = 0.70), biomass proxy (mean and p90 qm NDVI),
and external reference ring background changes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize

logger = logging.getLogger(__name__)


def compute_canopy_biomass_change(
    project_dir: Union[str, Path],
    years: Optional[List[str]] = None,
    thresholds: Optional[List[float]] = None,
    primary_threshold: float = 0.70,
    pixel_ha: float = 0.01,
) -> Dict[str, Any]:
    """Compute annual canopy cover, biomass proxy metrics, and reference ring changes.

    Args:
        project_dir: Path to project directory (e.g. data/projects/2469).
        years: List of year strings to evaluate (default: ['2019', '2020', '2021', '2022']).
        thresholds: List of NDVI thresholds (default: [0.60, 0.65, 0.70, 0.75]).
        primary_threshold: Primary evaluation threshold (default: 0.70).
        pixel_ha: Area per raster pixel in hectares (default: 0.01 for 10 m).

    Returns:
        Structured dictionary containing per-year, per-threshold table and change metrics.
    """
    proj_p = Path(project_dir).resolve()
    img_dir = proj_p / "imagery" if (proj_p / "imagery").exists() else proj_p
    comp_dir = img_dir / "composites" if (img_dir / "composites").exists() else proj_p / "composites"

    if years is None:
        years = ["2019", "2020", "2021", "2022"]
    if thresholds is None:
        thresholds = [0.60, 0.65, 0.70, 0.75]

    proj_bound_path = img_dir / "project_boundary.geojson"
    if not proj_bound_path.exists():
        proj_bound_path = proj_p / "boundary.geojson"
    ring_bound_path = img_dir / "reference_ring.geojson"

    if not proj_bound_path.exists():
        raise FileNotFoundError(f"Missing boundary file in {proj_p}")
    if not ring_bound_path.exists():
        raise FileNotFoundError(f"Missing reference ring file in {img_dir}")

    proj_gdf = gpd.read_file(proj_bound_path)
    ring_gdf = gpd.read_file(ring_bound_path)

    # Use first year composite for CRS and transform
    ref_raster_path = comp_dir / f"ndvi_qm_{years[0]}.tif"
    if not ref_raster_path.exists():
        ref_raster_path = comp_dir / f"raw_composite_{years[0]}.tif"

    with rasterio.open(ref_raster_path) as src:
        crs = src.crs
        transform = src.transform
        shape = src.shape

    proj_utm = proj_gdf.to_crs(crs)
    ring_utm = ring_gdf.to_crs(crs)

    proj_mask = (
        rasterize(
            [(proj_utm.geometry.iloc[0], 1)],
            out_shape=shape,
            transform=transform,
            fill=0,
            dtype=np.uint8,
            all_touched=False,
        )
        == 1
    )
    ring_mask = (
        rasterize(
            [(ring_utm.geometry.iloc[0], 1)],
            out_shape=shape,
            transform=transform,
            fill=0,
            dtype=np.uint8,
            all_touched=False,
        )
        == 1
    )

    total_px = int(np.sum(proj_mask))
    total_ha = float(round(total_px * pixel_ha, 2))

    qm_rasters: Dict[str, np.ndarray] = {}
    raw_rasters: Dict[str, np.ndarray] = {}
    for y in years:
        qm_path = comp_dir / f"ndvi_qm_{y}.tif"
        raw_path = comp_dir / f"raw_composite_{y}.tif"
        if not qm_path.exists():
            raise FileNotFoundError(f"Missing required composite raster: {qm_path}")
        if not raw_path.exists():
            raise FileNotFoundError(f"Missing required composite raster: {raw_path}")

        with rasterio.open(qm_path) as src:
            qm_rasters[y] = src.read(1)
        with rasterio.open(raw_path) as src:
            raw_rasters[y] = src.read(1)

    # Per-year, per-threshold canopy cover
    table: Dict[str, Dict[str, Dict[str, float]]] = {}
    for t in thresholds:
        t_key = f"{t:.2f}"
        table[t_key] = {}
        for y in years:
            arr = qm_rasters[y]
            area = float(round(float(np.sum((arr >= t) & proj_mask)) * pixel_ha, 2))
            share = float(round((area / total_ha) * 100.0, 2)) if total_ha > 0 else 0.0
            table[t_key][y] = {
                "area_ha": area,
                "share_pct": share,
            }

    # Relative canopy change from baseline to end year across threshold grid
    y_start = years[0]
    y_end = years[-1]
    canopy_change_by_t: Dict[str, float] = {}
    changes_list: List[float] = []
    for t in thresholds:
        t_key = f"{t:.2f}"
        a_start = table[t_key][y_start]["area_ha"]
        a_end = table[t_key][y_end]["area_ha"]
        chg = float(round(((a_end - a_start) / a_start) * 100.0, 2)) if a_start > 0 else 0.0
        canopy_change_by_t[t_key] = chg
        changes_list.append(chg)

    primary_key = f"{primary_threshold:.2f}"
    primary_canopy_change_pct = canopy_change_by_t.get(primary_key)
    min_canopy_change_pct = min(changes_list) if changes_list else None
    max_canopy_change_pct = max(changes_list) if changes_list else None

    # Biomass proxy: mean and p90 over project boundary per year
    biomass_by_year: Dict[str, Dict[str, float]] = {}
    for y in years:
        valid_vals = qm_rasters[y][proj_mask & np.isfinite(qm_rasters[y])]
        mean_v = float(round(float(np.mean(valid_vals)), 4)) if len(valid_vals) > 0 else 0.0
        p90_v = float(round(float(np.percentile(valid_vals, 90)), 4)) if len(valid_vals) > 0 else 0.0
        biomass_by_year[y] = {
            "mean": mean_v,
            "p90": p90_v,
        }

    m_start = biomass_by_year[y_start]["mean"]
    m_end = biomass_by_year[y_end]["mean"]
    biomass_proxy_change_pct = (
        float(round(((m_end - m_start) / m_start) * 100.0, 2)) if m_start > 0 else 0.0
    )

    # Reference buffer change: relative change of RAW reference-ring median 2019 -> 2022
    ring_raw_medians: Dict[str, float] = {}
    for y in years:
        r_vals = raw_rasters[y][ring_mask & np.isfinite(raw_rasters[y])]
        r_med = float(round(float(np.median(r_vals)), 4)) if len(r_vals) > 0 else 0.0
        ring_raw_medians[y] = r_med

    r_start = ring_raw_medians[y_start]
    r_end = ring_raw_medians[y_end]
    reference_buffer_change_pct = (
        float(round(((r_end - r_start) / r_start) * 100.0, 2)) if r_start > 0 else 0.0
    )

    # Rank of project RAW p90 in reference ring per year (for coincidence check)
    ring_p90_ranks: Dict[str, float] = {}
    for y in years:
        p_raw = raw_rasters[y][proj_mask & np.isfinite(raw_rasters[y])]
        r_raw = raw_rasters[y][ring_mask & np.isfinite(raw_rasters[y])]
        if len(p_raw) > 0 and len(r_raw) > 0:
            p90 = float(np.percentile(p_raw, 90))
            rank_val = float(round(float((r_raw <= p90).mean() * 100.0), 2))
        else:
            rank_val = 0.0
        ring_p90_ranks[y] = rank_val

    result: Dict[str, Any] = {
        "thresholds": [f"{t:.2f}" for t in thresholds],
        "years": years,
        "primary_threshold": primary_key,
        "baseline_year": y_start,
        "end_year": y_end,
        "estate_boundary_ha": total_ha,
        "table": table,
        "canopy_change_pct_by_threshold": canopy_change_by_t,
        "canopy_change_pct": primary_canopy_change_pct,
        "canopy_change_min_pct": min_canopy_change_pct,
        "canopy_change_max_pct": max_canopy_change_pct,
        "canopy_change_grid_range": (
            [min_canopy_change_pct, max_canopy_change_pct]
            if min_canopy_change_pct is not None and max_canopy_change_pct is not None
            else None
        ),
        "biomass_proxy_by_year": biomass_by_year,
        "biomass_proxy_change_pct": biomass_proxy_change_pct,
        "reference_buffer_raw_medians": ring_raw_medians,
        "reference_buffer_change_pct": reference_buffer_change_pct,
        "p90_ring_ranks": ring_p90_ranks,
    }

    logger.info(
        "Computed canopy and biomass changes for %s: primary canopy change=+%.2f%%, biomass=+%.2f%%, ring=+%.2f%%",
        proj_p.name,
        primary_canopy_change_pct,
        biomass_proxy_change_pct,
        reference_buffer_change_pct,
    )
    return result
