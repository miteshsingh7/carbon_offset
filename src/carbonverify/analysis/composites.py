"""Pixel-level seasonal composites, reference ring normalization, and spatial transitions."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.windows import Window, from_bounds
from shapely.geometry import Polygon

from carbonverify.imagery.boundary import generate_reference_ring, select_project_polygon
from carbonverify.imagery.radiometry import compute_ndvi, create_scl_mask, dn_to_reflectance

logger = logging.getLogger(__name__)


def compute_annual_pixel_composite(
    scene_ids: List[str],
    cache_dir: Path,
    detected_offsets: Dict[str, float],
    expected_shape: Tuple[int, int],
    min_observations: int = 3,
) -> np.ndarray:
    """Compute per-pixel median NDVI across scenes for a single year with observation threshold.

    Args:
        scene_ids: List of Sentinel-2 scene IDs for the year.
        cache_dir: Directory containing cached .npz rasters.
        detected_offsets: Mapping of scene_id to detected radiometric offset.
        expected_shape: (height, width) of the raster grid.
        min_observations: Minimum number of valid observations required per pixel (default 3).

    Returns:
        np.ndarray: 2D array of median NDVI values with NaNs for < min_observations.
    """
    if not scene_ids:
        return np.full(expected_shape, np.nan, dtype=np.float32)

    scene_ndvis: List[np.ndarray] = []
    for sid in scene_ids:
        cache_path = cache_dir / f"{sid}.npz"
        if not cache_path.exists():
            logger.warning("Cache file not found for scene %s: %s", sid, cache_path)
            continue

        data = np.load(cache_path, allow_pickle=True)
        red = data["red"]
        nir = data["nir"]
        scl = data["scl"]

        det_off = detected_offsets.get(sid, 0.0)
        scl_valid = create_scl_mask(scl)
        red_refl = dn_to_reflectance(red, scale=0.0001, offset=det_off)
        nir_refl = dn_to_reflectance(nir, scale=0.0001, offset=det_off)

        ndvi = compute_ndvi(red_refl, nir_refl)

        # Retain valid pixels: SCL 4-7, finite, [-1, 1], and denominator > 0
        valid_px = (
            scl_valid
            & np.isfinite(ndvi)
            & (ndvi >= -1.0)
            & (ndvi <= 1.0)
            & ((red_refl + nir_refl) > 0)
        )
        scene_ndvi = np.where(valid_px, ndvi, np.nan).astype(np.float32)
        scene_ndvis.append(scene_ndvi)

    if not scene_ndvis:
        return np.full(expected_shape, np.nan, dtype=np.float32)

    stack = np.stack(scene_ndvis, axis=0)
    valid_counts = np.sum(~np.isnan(stack), axis=0)

    with np.errstate(all="ignore"):
        med_ndvi = np.nanmedian(stack, axis=0).astype(np.float32)

    # Require >= min_observations valid observations per pixel, else NaN
    med_ndvi[valid_counts < min_observations] = np.nan
    return med_ndvi


def normalize_composite_to_ring(
    raw_composite: np.ndarray,
    ring_mask: np.ndarray,
    ref_ring_median: float,
) -> Tuple[np.ndarray, float, float]:
    """Normalize composite to baseline reference ring median.

    ndvi_norm(y) = ndvi(y) - (ring_median(y) - ring_median(ref_year))

    Args:
        raw_composite: 2D array of raw median NDVI.
        ring_mask: Binary mask for reference ring (1 inside ring, 0 outside).
        ref_ring_median: Median NDVI of the reference ring in baseline year (e.g. 2019).

    Returns:
        Tuple of (normalized_composite, current_ring_median, shift_applied).
    """
    ring_pixels = raw_composite[ring_mask == 1]
    finite_ring = ring_pixels[~np.isnan(ring_pixels)]

    if len(finite_ring) == 0:
        cur_ring_med = 0.0
        shift = 0.0
    else:
        cur_ring_med = float(np.nanmedian(finite_ring))
        shift = cur_ring_med - ref_ring_median

    norm_composite = raw_composite - shift
    return norm_composite, cur_ring_med, shift


def quantile_map(
    x: np.ndarray,
    q_source: np.ndarray,
    q_target: np.ndarray,
) -> np.ndarray:
    """Monotone quantile mapping with constant-offset extrapolation outside ring range.

    Args:
        x: Array of values to map.
        q_source: Quantiles of source distribution (e.g. year y ring quantiles).
        q_target: Quantiles of target distribution (e.g. 2019 reference ring quantiles).

    Returns:
        np.ndarray: Monotonically mapped array with identical shape to x.
    """
    out = np.full_like(x, np.nan, dtype=np.float32)
    valid = np.isfinite(x)
    if not np.any(valid):
        return out

    xv = x[valid]
    yv = np.interp(xv, q_source, q_target)

    # Constant-offset extrapolation below lower boundary
    low_mask = xv < q_source[0]
    yv[low_mask] = xv[low_mask] + (q_target[0] - q_source[0])

    # Constant-offset extrapolation above upper boundary
    high_mask = xv > q_source[-1]
    yv[high_mask] = xv[high_mask] + (q_target[-1] - q_source[-1])

    out[valid] = yv
    return out


def classify_hysteresis_cohorts(
    q19: np.ndarray,
    q20: np.ndarray,
    q21: np.ndarray,
    q22: np.ndarray,
    t_low: float,
    t_high: float,
) -> Dict[str, np.ndarray]:
    """Classify pixels into hysteresis cohorts, pre-existing, or unclassified.

    A pixel is in cohort year y if:
    - qm(y) >= t_high
    - qm is < t_low in every earlier year
    - qm stays >= t_low in every later year

    Pixels with qm(2019) >= t_low are pre-existing and never in a cohort.

    Args:
        q19: Array of year 2019 values.
        q20: Array of year 2020 values.
        q21: Array of year 2021 values.
        q22: Array of year 2022 values.
        t_low: Lower hysteresis threshold.
        t_high: Upper threshold for crossing.

    Returns:
        Dict mapping 'pre_existing', 'cohort_2020', 'cohort_2021', 'cohort_2022',
        'unclassified' to boolean masks of same shape.
    """
    pre = q19 >= t_low
    c20 = (q19 < t_low) & (q20 >= t_high) & (q21 >= t_low) & (q22 >= t_low)
    c21 = (q19 < t_low) & (q20 < t_low) & (q21 >= t_high) & (q22 >= t_low)
    c22 = (q19 < t_low) & (q20 < t_low) & (q21 < t_low) & (q22 >= t_high)
    tot = c20 | c21 | c22
    unclass = (~pre) & (~tot)

    return {
        "pre_existing": pre,
        "cohort_2020": c20,
        "cohort_2021": c21,
        "cohort_2022": c22,
        "unclassified": unclass,
    }


def save_geotiff(
    data: np.ndarray,
    transform: rasterio.Affine,
    crs: rasterio.crs.CRS,
    output_path: Union[str, Path],
    nodata: float = np.nan,
) -> Path:
    """Save a 2D float32 array as a Cloud-Optimized GeoTIFF.

    Args:
        data: 2D numpy array.
        transform: Affine georeference transform.
        crs: Coordinate reference system.
        output_path: Target .tif file path.
        nodata: Nodata value to record in metadata.

    Returns:
        Path: Path to saved GeoTIFF.
    """
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    height, width = data.shape
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
        "compress": "deflate",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }

    with rasterio.open(out_p, "w", **profile) as dst:
        dst.write(data.astype(np.float32), 1)

    logger.info("Saved GeoTIFF composite to %s", out_p)
    return out_p


def generate_composites_2x2_plot(
    norm_composites: Dict[str, np.ndarray],
    proj_geom: Polygon,
    transform: rasterio.Affine,
    output_path: Union[str, Path],
    vmin: float = 0.0,
    vmax: float = 1.0,
    crop_padding_px: int = 50,
) -> Path:
    """Generate and save 2x2 PNG visualization of normalized composites with project boundary outline.

    Args:
        norm_composites: Dict mapping year ("2019", "2020", "2021", "2022") to 2D normalized NDVI.
        proj_geom: Project polygon in local UTM CRS.
        transform: Raster affine transform.
        output_path: Path to write PNG image.
        vmin: Minimum value for fixed color scale.
        vmax: Maximum value for fixed color scale.
        crop_padding_px: Pixel margin around project bounding box.

    Returns:
        Path: Path to saved plot PNG.
    """
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    minx, miny, maxx, maxy = proj_geom.bounds
    crop_win = from_bounds(minx, miny, maxx, maxy, transform)
    r_start = max(0, int(crop_win.row_off) - crop_padding_px)
    r_end = int(crop_win.row_off + crop_win.height) + crop_padding_px
    c_start = max(0, int(crop_win.col_off) - crop_padding_px)
    c_end = int(crop_win.col_off + crop_win.width) + crop_padding_px

    # Extract polygon boundary coordinates in pixel space
    coords = np.array(proj_geom.exterior.coords)
    inv_tf = ~transform
    px_coords = [inv_tf * (x, y) for x, y in coords]
    px_cols = [c - c_start for c, r in px_coords]
    px_rows = [r - r_start for c, r in px_coords]

    fig, axes = plt.subplots(2, 2, figsize=(14, 14), constrained_layout=True)
    years = ["2019", "2020", "2021", "2022"]

    im = None
    for idx, yr in enumerate(years):
        ax = axes[idx // 2, idx % 2]
        full_arr = norm_composites.get(yr)
        if full_arr is not None:
            sub_arr = full_arr[r_start:r_end, c_start:c_end]
            im = ax.imshow(
                sub_arr,
                origin="upper",
                vmin=vmin,
                vmax=vmax,
                cmap="viridis",
                interpolation="nearest",
            )
            # Draw project polygon outline
            ax.plot(px_cols, px_rows, color="red", linewidth=1.5, label="Project Boundary")

        ax.set_title(f"{yr} Dry-Season NDVI (Normalized)", fontsize=14, fontweight="bold")
        ax.set_axis_off()

    if im is not None:
        cbar = fig.colorbar(im, ax=axes, orientation="horizontal", fraction=0.046, pad=0.04)
        cbar.set_label("NDVI (Normalized to 2019 Reference Ring Level [0 - 1])", fontsize=12)

    fig.savefig(out_p, dpi=300)
    plt.close(fig)
    logger.info("Saved 2x2 composite plot to %s", out_p)
    return out_p


def calculate_transition_matrix(
    arr1: np.ndarray,
    arr2: np.ndarray,
    mask: np.ndarray,
    pixel_area_ha: float = 0.01,
) -> pd.DataFrame:
    """Compute class transition matrix in hectares between two composite rasters over a mask.

    Classes:
        low: < 0.5
        mid: 0.5 - 0.7
        high: >= 0.7
        NaN: NaN or invalid

    Args:
        arr1: Composite raster from year 1.
        arr2: Composite raster from year 2.
        mask: Binary mask of pixels to include.
        pixel_area_ha: Area per pixel in hectares (default 0.01).

    Returns:
        pd.DataFrame: Cross-tabulation table in hectares.
    """
    v1 = arr1[mask == 1]
    v2 = arr2[mask == 1]

    def _classify(v: np.ndarray) -> np.ndarray:
        res = np.empty_like(v, dtype=object)
        res[np.isnan(v)] = "NaN"
        res[~np.isnan(v) & (v < 0.5)] = "low (<0.5)"
        res[~np.isnan(v) & (v >= 0.5) & (v < 0.7)] = "mid (0.5-0.7)"
        res[~np.isnan(v) & (v >= 0.7)] = "high (>=0.7)"
        return res

    c1 = _classify(v1)
    c2 = _classify(v2)

    classes = ["low (<0.5)", "mid (0.5-0.7)", "high (>=0.7)", "NaN"]
    ctab = pd.crosstab(
        pd.Series(c1, name="From"),
        pd.Series(c2, name="To"),
        dropna=False,
    ).reindex(index=classes, columns=classes, fill_value=0)

    return ctab * pixel_area_ha
