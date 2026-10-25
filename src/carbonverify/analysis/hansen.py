"""Hansen Global Forest Change (GFC) cross-check analysis.

Evaluates pre-existing high-NDVI decline pixels (qm(2019) >= 0.7 and qm(2022) < 0.6)
and controls against Hansen treecover2000 and lossyear layers at 30 m resolution.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds

logger = logging.getLogger(__name__)

# WGS84 ellipsoid constants
_WGS84_A = 6378137.0
_WGS84_E2 = 0.00669437999014


def _compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def find_hansen_tiles(bounds_4326: Tuple[float, float, float, float]) -> List[str]:
    """Identify Hansen 10x10 degree tile IDs covering the given bounds.

    Args:
        bounds_4326: Bounding box tuple (minx, miny, maxx, maxy) in EPSG:4326.

    Returns:
        List of Hansen tile ID strings (e.g. ['20S_060W']).
    """
    minx, miny, maxx, maxy = bounds_4326
    tiles: List[str] = []

    # Hansen tiles are indexed by their upper-left (northwest) corner
    # Latitude: in southern hemisphere, tile spanning -30 to -20 has top at -20 (20S)
    lat_start = int(np.ceil(maxy / 10.0) * 10)
    lat_end = int(np.floor(miny / 10.0) * 10)
    lon_start = int(np.floor(minx / 10.0) * 10)
    lon_end = int(np.ceil(maxx / 10.0) * 10)

    for lat in range(lat_end + 10, lat_start + 10, 10):
        lat_str = f"{abs(lat):02d}N" if lat >= 0 else f"{abs(lat):02d}S"
        for lon in range(lon_start, lon_end, 10):
            lon_str = f"{abs(lon):03d}E" if lon >= 0 else f"{abs(lon):03d}W"
            tiles.append(f"{lat_str}_{lon_str}")

    return sorted(list(dict.fromkeys(tiles)))


def _compute_row_pixel_areas_ha(
    lats_deg: np.ndarray,
    res_deg: float = 0.00025,
) -> np.ndarray:
    """Compute ellipsoidal pixel area in hectares per latitude row."""
    lats_rad = np.radians(lats_deg)
    res_rad = np.radians(res_deg)
    m = _WGS84_A * (1.0 - _WGS84_E2) / ((1.0 - _WGS84_E2 * np.sin(lats_rad) ** 2) ** 1.5)
    n = _WGS84_A / np.sqrt(1.0 - _WGS84_E2 * np.sin(lats_rad) ** 2)
    area_m2 = (m * res_rad) * (n * np.cos(lats_rad) * res_rad)
    return area_m2 / 10000.0


def run_hansen_crosscheck(
    project_dir: Path | str,
    hansen_dir: Path | str = "data/external/hansen",
    gfc_version: str = "GFC-2022-v1.10",
    resampling_method: str = "nearest",
) -> Dict[str, Any]:
    """Execute Hansen GFC cross-check for project decline pixels and controls.

    Args:
        project_dir: Path to project directory (e.g. data/projects/2469).
        hansen_dir: Path to directory containing downloaded Hansen GeoTIFF tiles.
        gfc_version: Hansen GFC release version string.
        resampling_method: 'nearest' (nearest-neighbor sampling) or 'fractional_weighted'.

    Returns:
        Structured cross-check dictionary conforming to schemas.SatelliteEstimate.hansen_crosscheck.
    """
    proj_p = Path(project_dir).resolve()
    img_dir = proj_p / "imagery" if (proj_p / "imagery").exists() else proj_p
    comp_dir = img_dir / "composites" if (img_dir / "composites").exists() else proj_p / "composites"
    hansen_p = Path(hansen_dir).resolve()

    # Locate boundary vectors
    proj_bound_path = img_dir / "project_boundary.geojson"
    if not proj_bound_path.exists():
        proj_bound_path = proj_p / "boundary.geojson"
    ring_bound_path = img_dir / "reference_ring.geojson"

    if not proj_bound_path.exists() or not ring_bound_path.exists():
        raise FileNotFoundError(f"Missing boundary vectors in {img_dir}")

    proj_gdf = gpd.read_file(proj_bound_path)
    ring_gdf = gpd.read_file(ring_bound_path)

    # 1. Tile discovery from 4326 bounds
    proj_4326 = proj_gdf.to_crs(epsg=4326)
    ring_4326 = ring_gdf.to_crs(epsg=4326)
    bounds_4326 = tuple(proj_4326.total_bounds)
    tiles = find_hansen_tiles(bounds_4326)
    tile_id = tiles[0] if tiles else "20S_060W"

    # Locate Hansen files
    tc_file = hansen_p / f"Hansen_{gfc_version}_treecover2000_{tile_id}.tif"
    ly_file = hansen_p / f"Hansen_{gfc_version}_lossyear_{tile_id}.tif"

    if not tc_file.exists() or not ly_file.exists():
        # Fallback without version prefix in filename if renamed
        candidate_tc = list(hansen_p.glob(f"*treecover2000*{tile_id}*.tif"))
        candidate_ly = list(hansen_p.glob(f"*lossyear*{tile_id}*.tif"))
        if candidate_tc and candidate_ly:
            tc_file = candidate_tc[0]
            ly_file = candidate_ly[0]
        else:
            raise FileNotFoundError(f"Hansen tiles for {tile_id} not found in {hansen_p}")

    hansen_hashes = {
        tc_file.name: _compute_sha256(tc_file),
        ly_file.name: _compute_sha256(ly_file),
    }

    # 2. Load S2 composites and create 10m masks
    with rasterio.open(comp_dir / "ndvi_qm_2019.tif") as s2_src:
        s2_crs = s2_src.crs
        s2_transform = s2_src.transform
        s2_shape = s2_src.shape
        qm19 = s2_src.read(1)

    with rasterio.open(comp_dir / "ndvi_qm_2020.tif") as s2_20:
        qm20 = s2_20.read(1)
    with rasterio.open(comp_dir / "ndvi_qm_2021.tif") as s2_21:
        qm21 = s2_21.read(1)
    with rasterio.open(comp_dir / "ndvi_qm_2022.tif") as s2_22:
        qm22 = s2_22.read(1)

    proj_utm = proj_gdf.to_crs(s2_crs)
    ring_utm = ring_gdf.to_crs(s2_crs)

    proj_mask_10m = rasterize(
        [(proj_utm.geometry.iloc[0], 1)],
        out_shape=s2_shape,
        transform=s2_transform,
        fill=0,
        dtype=np.uint8,
    )
    ring_mask_10m = rasterize(
        [(ring_utm.geometry.iloc[0], 1)],
        out_shape=s2_shape,
        transform=s2_transform,
        fill=0,
        dtype=np.uint8,
    )

    decline_10m = ((qm19 >= 0.7) & (qm22 < 0.6) & (proj_mask_10m == 1)).astype(np.float32)
    high_all4_10m = (
        (qm19 >= 0.7) & (qm20 >= 0.7) & (qm21 >= 0.7) & (qm22 >= 0.7) & (proj_mask_10m == 1)
    ).astype(np.float32)
    boundary_10m = (proj_mask_10m == 1).astype(np.float32)
    ring_10m = (ring_mask_10m == 1).astype(np.float32)

    # 3. Read window from Hansen rasters covering ring + buffer
    with rasterio.open(tc_file) as tc_src, rasterio.open(ly_file) as ly_src:
        tc_crs = tc_src.crs
        tc_transform = tc_src.transform
        ring_bounds = ring_4326.total_bounds
        buf_deg = 0.005
        win = from_bounds(
            ring_bounds[0] - buf_deg,
            ring_bounds[1] - buf_deg,
            ring_bounds[2] + buf_deg,
            ring_bounds[3] + buf_deg,
            tc_transform,
        )
        win = win.round_offsets().round_lengths()
        win_transform = rasterio.windows.transform(win, tc_transform)
        win_shape = (int(win.height), int(win.width))

        tc_arr = tc_src.read(1, window=win)
        ly_arr = ly_src.read(1, window=win)

    # Ellipsoidal pixel area grid
    rows = np.arange(win_shape[0])
    lats_deg = win_transform.f + (rows + 0.5) * win_transform.e
    row_areas = _compute_row_pixel_areas_ha(lats_deg, res_deg=abs(win_transform.e))
    pixel_area_grid = np.tile(row_areas[:, np.newaxis], (1, win_shape[1]))

    # 4. Resample 10m masks to Hansen grid
    masks_10m = {
        "decline_43ha": decline_10m,
        "high_all4": high_all4_10m,
        "project_boundary": boundary_10m,
        "reference_ring": ring_10m,
    }

    use_nearest = resampling_method == "nearest"
    r_mode = Resampling.nearest if use_nearest else Resampling.average

    resampled_metrics: Dict[str, Any] = {}

    for mname, m10 in masks_10m.items():
        dst = np.zeros(win_shape, dtype=np.float32)
        reproject(
            source=m10,
            destination=dst,
            src_transform=s2_transform,
            src_crs=s2_crs,
            dst_transform=win_transform,
            dst_crs=tc_crs,
            resampling=r_mode,
        )

        if use_nearest:
            bool_mask = dst >= 0.5
            total_n = int(bool_mask.sum())
            total_ha = float((bool_mask * pixel_area_grid).sum())
            if total_n == 0:
                continue
            tc25_share = float((bool_mask & (tc_arr >= 25)).sum() / total_n)
            tc50_share = float((bool_mask & (tc_arr >= 50)).sum() / total_n)

            loss_shares: Dict[str, float] = {}
            loss_ha_dict: Dict[str, float] = {}
            for y_code, y_str in [(19, "2019"), (20, "2020"), (21, "2021"), (22, "2022")]:
                sub_m = bool_mask & (ly_arr == y_code)
                loss_shares[y_str] = float(sub_m.sum() / total_n)
                loss_ha_dict[y_str] = float((sub_m * pixel_area_grid).sum())

            tot_loss_m = bool_mask & (ly_arr >= 19) & (ly_arr <= 22)
            tot_loss_share = float(tot_loss_m.sum() / total_n)
            tot_loss_ha = float((tot_loss_m * pixel_area_grid).sum())
            count_val = total_n
        else:
            w = dst
            total_w = float(w.sum())
            total_ha = float((w * pixel_area_grid).sum())
            if total_w <= 0:
                continue
            tc25_share = float((w * (tc_arr >= 25)).sum() / total_w)
            tc50_share = float((w * (tc_arr >= 50)).sum() / total_w)

            loss_shares = {}
            loss_ha_dict = {}
            for y_code, y_str in [(19, "2019"), (20, "2020"), (21, "2021"), (22, "2022")]:
                w_yr = w * (ly_arr == y_code)
                loss_shares[y_str] = float(w_yr.sum() / total_w)
                loss_ha_dict[y_str] = float((w_yr * pixel_area_grid).sum())

            w_tot = w * ((ly_arr >= 19) & (ly_arr <= 22))
            tot_loss_share = float(w_tot.sum() / total_w)
            tot_loss_ha = float((w_tot * pixel_area_grid).sum())
            count_val = float(round(total_w, 1))

        resampled_metrics[mname] = {
            "sample_size": count_val,
            "area_ha": round(total_ha, 2),
            "treecover2000_ge_25_share": round(tc25_share, 4),
            "treecover2000_ge_50_share": round(tc50_share, 4),
            "loss_share_2019": round(loss_shares["2019"], 4),
            "loss_share_2020": round(loss_shares["2020"], 4),
            "loss_share_2021": round(loss_shares["2021"], 4),
            "loss_share_2022": round(loss_shares["2022"], 4),
            "loss_share_2019_2022_total": round(tot_loss_share, 4),
            "loss_ha_by_year": {k: round(v, 2) for k, v in loss_ha_dict.items()},
            "loss_ha_total": round(tot_loss_ha, 2),
        }

    boundary_loss_ha = resampled_metrics.get("project_boundary", {}).get("loss_ha_by_year", {})
    boundary_loss_total_ha = resampled_metrics.get("project_boundary", {}).get("loss_ha_total")

    # 5. Assemble structured result
    decline_stats = resampled_metrics.get("decline_43ha", {})
    controls_stats = {
        "high_all4": resampled_metrics.get("high_all4", {}),
        "project_boundary": resampled_metrics.get("project_boundary", {}),
        "reference_ring": resampled_metrics.get("reference_ring", {}),
    }

    result: Dict[str, Any] = {
        "gfc_version": gfc_version,
        "tiles": tiles,
        "primary_tile": tile_id,
        "file_hashes": hansen_hashes,
        "resampling_description": (
            "10 m binary masks in EPSG:32721 are resampled to the Hansen GFC 30 m grid "
            "in EPSG:4326 using nearest-neighbor centroid sampling (rasterio.warp.reproject "
            "with Resampling.nearest)."
            if use_nearest
            else "10 m binary masks in EPSG:32721 are resampled to the Hansen GFC 30 m grid "
            "in EPSG:4326 using fractional area weighting (rasterio.warp.reproject with "
            "Resampling.average)."
        ),
        "decline_43ha": decline_stats,
        "controls": controls_stats,
        "boundary_loss_ha_by_year": boundary_loss_ha,
        "boundary_loss_ha_total": boundary_loss_total_ha,
    }

    logger.info("Computed Hansen GFC cross-check for project %s (tile %s)", proj_p.name, tile_id)
    return result


def run_forest_allowance_check(
    project_dir: Path | str,
    claimed_planted_ha: float,
    claimed_forest_allowance_ha: float,
    hansen_dir: Path | str = "data/external/hansen",
    gfc_version: str = "GFC-2022-v1.10",
    resampling_method: str = "nearest",
) -> Dict[str, Any]:
    """Execute forest allowance break-even analysis and Hansen persistence check.

    Computes:
      1. Break-even natural forest allowance F*(T) = A2022(T) - claimed_planted_ha
         for T in {0.6, 0.65, 0.7, 0.75}, decisive F*(0.6), margin F*(0.6) - claimed_forest_allowance_ha,
         and corresponding low-end value F*(0.75).
      2. Hansen persistence check inside project boundary at 30 m grid:
         area with treecover2000 >= {25, 50, 75} and no loss through 2018 (lossyear == 0 or >= 19),
         and same sets intersected with qm(2019) >= 0.6 and qm(2019) >= 0.7.

    Args:
        project_dir: Project directory path.
        claimed_planted_ha: Claimed plantation area in ha.
        claimed_forest_allowance_ha: Claimed natural forest allowance in ha.
        hansen_dir: Directory containing downloaded Hansen GeoTIFF tiles.
        gfc_version: Hansen release version string.
        resampling_method: 'nearest' (nearest-neighbor sampling).

    Returns:
        Structured dictionary for satellite_estimate.forest_allowance_check.
    """
    proj_p = Path(project_dir).resolve()
    img_dir = proj_p / "imagery" if (proj_p / "imagery").exists() else proj_p
    comp_dir = img_dir / "composites" if (img_dir / "composites").exists() else proj_p / "composites"
    hansen_p = Path(hansen_dir).resolve()

    # Locate boundary vectors
    proj_bound_path = img_dir / "project_boundary.geojson"
    if not proj_bound_path.exists():
        proj_bound_path = proj_p / "boundary.geojson"
    ring_bound_path = img_dir / "reference_ring.geojson"

    proj_gdf = gpd.read_file(proj_bound_path)
    ring_gdf = gpd.read_file(ring_bound_path)

    proj_4326 = proj_gdf.to_crs(epsg=4326)
    ring_4326 = ring_gdf.to_crs(epsg=4326)
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

    hansen_hashes = {
        tc_file.name: _compute_sha256(tc_file),
        ly_file.name: _compute_sha256(ly_file),
    }

    # 1. Compute break-even allowances from S2 10m composites
    with rasterio.open(comp_dir / "ndvi_qm_2019.tif") as s2_19:
        s2_crs = s2_19.crs
        s2_transform = s2_19.transform
        s2_shape = s2_19.shape
        qm19 = s2_19.read(1)

    with rasterio.open(comp_dir / "ndvi_qm_2022.tif") as s2_22:
        qm22 = s2_22.read(1)

    proj_utm = proj_gdf.to_crs(s2_crs)
    proj_mask_10m = rasterize(
        [(proj_utm.geometry.iloc[0], 1)],
        out_shape=s2_shape,
        transform=s2_transform,
        fill=0,
        dtype=np.uint8,
    )
    p_mask_10m_bool = proj_mask_10m == 1

    thresholds = [0.6, 0.65, 0.7, 0.75]
    break_even_by_threshold: Dict[str, Dict[str, float]] = {}
    for t_val in thresholds:
        t_key = str(t_val)
        a_2022 = float(round(((qm22 >= t_val) & p_mask_10m_bool).sum() * 0.01, 2))
        f_star = float(round(a_2022 - claimed_planted_ha, 2))
        margin = float(round(f_star - claimed_forest_allowance_ha, 2))
        break_even_by_threshold[t_key] = {
            "a_2022_ha": a_2022,
            "f_star_ha": f_star,
            "margin_ha": margin,
        }

    f_star_06 = break_even_by_threshold["0.6"]["f_star_ha"]
    margin_06 = break_even_by_threshold["0.6"]["margin_ha"]
    f_star_low_end = break_even_by_threshold["0.75"]["f_star_ha"]
    margin_low_end = break_even_by_threshold["0.75"]["margin_ha"]

    # 2. Hansen Persistence Check inside project boundary at 30 m grid
    with rasterio.open(tc_file) as tc_src, rasterio.open(ly_file) as ly_src:
        tc_crs = tc_src.crs
        tc_transform = tc_src.transform
        ring_bounds = ring_4326.total_bounds
        buf_deg = 0.005
        win = from_bounds(
            ring_bounds[0] - buf_deg,
            ring_bounds[1] - buf_deg,
            ring_bounds[2] + buf_deg,
            ring_bounds[3] + buf_deg,
            tc_transform,
        )
        win = win.round_offsets().round_lengths()
        win_transform = rasterio.windows.transform(win, tc_transform)
        win_shape = (int(win.height), int(win.width))

        tc_arr = tc_src.read(1, window=win)
        ly_arr = ly_src.read(1, window=win)

    rows = np.arange(win_shape[0])
    lats_deg = win_transform.f + (rows + 0.5) * win_transform.e
    row_areas = _compute_row_pixel_areas_ha(lats_deg, res_deg=abs(win_transform.e))
    pixel_area_grid = np.tile(row_areas[:, np.newaxis], (1, win_shape[1]))

    # Resample project boundary, qm19 >= 0.6, qm19 >= 0.7
    proj_mask_30m = np.zeros(win_shape, dtype=np.float32)
    reproject(
        source=(proj_mask_10m == 1).astype(np.float32),
        destination=proj_mask_30m,
        src_transform=s2_transform,
        src_crs=s2_crs,
        dst_transform=win_transform,
        dst_crs=tc_crs,
        resampling=Resampling.nearest,
    )
    p_mask_30m = proj_mask_30m >= 0.5

    qm19_06_30m = np.zeros(win_shape, dtype=np.float32)
    qm19_07_30m = np.zeros(win_shape, dtype=np.float32)
    reproject(
        source=((qm19 >= 0.6) & p_mask_10m_bool).astype(np.float32),
        destination=qm19_06_30m,
        src_transform=s2_transform,
        src_crs=s2_crs,
        dst_transform=win_transform,
        dst_crs=tc_crs,
        resampling=Resampling.nearest,
    )
    reproject(
        source=((qm19 >= 0.7) & p_mask_10m_bool).astype(np.float32),
        destination=qm19_07_30m,
        src_transform=s2_transform,
        src_crs=s2_crs,
        dst_transform=win_transform,
        dst_crs=tc_crs,
        resampling=Resampling.nearest,
    )
    p_qm06 = qm19_06_30m >= 0.5
    p_qm07 = qm19_07_30m >= 0.5

    # No Hansen loss through 2018 (lossyear == 0 or lossyear >= 19)
    no_loss_thru_2018 = (ly_arr == 0) | (ly_arr >= 19)

    persistence_by_threshold: Dict[str, Dict[str, float]] = {}
    for cov_thresh in [25, 50, 75]:
        c_key = str(cov_thresh)
        tc_m = tc_arr >= cov_thresh
        m_2000 = p_mask_30m & tc_m
        m_pers = m_2000 & no_loss_thru_2018
        m_pers_06 = m_pers & p_qm06
        m_pers_07 = m_pers & p_qm07

        area_2000 = float(round((m_2000 * pixel_area_grid).sum(), 2))
        area_pers = float(round((m_pers * pixel_area_grid).sum(), 2))
        area_pers_06 = float(round((m_pers_06 * pixel_area_grid).sum(), 2))
        area_pers_07 = float(round((m_pers_07 * pixel_area_grid).sum(), 2))
        area_loss_01_18 = float(round(area_2000 - area_pers, 2))

        persistence_by_threshold[c_key] = {
            "treecover2000_ha": area_2000,
            "persistent_2018_ha": area_pers,
            "persistent_qm19_ge_06_ha": area_pers_06,
            "persistent_qm19_ge_07_ha": area_pers_07,
            "loss_2001_2018_ha": area_loss_01_18,
            "claimed_allowance_ha": claimed_forest_allowance_ha,
        }

    result: Dict[str, Any] = {
        "gfc_version": gfc_version,
        "tiles": tiles,
        "primary_tile": tile_id,
        "file_hashes": hansen_hashes,
        "claimed_planted_ha": claimed_planted_ha,
        "claimed_forest_allowance_ha": claimed_forest_allowance_ha,
        "break_even_allowance": {
            "by_threshold": break_even_by_threshold,
            "decisive_threshold": "0.6",
            "f_star_06_ha": f_star_06,
            "margin_06_ha": margin_06,
            "f_star_low_end_ha": f_star_low_end,
            "margin_low_end_ha": margin_low_end,
        },
        "f_star_06_ha": f_star_06,
        "margin_06_ha": margin_06,
        "f_star_low_end_ha": f_star_low_end,
        "margin_low_end_ha": margin_low_end,
        "persistence": persistence_by_threshold,
    }

    logger.info("Computed forest allowance check for %s (F*(0.6)=%.2f ha)", proj_p.name, f_star_06)
    return result
