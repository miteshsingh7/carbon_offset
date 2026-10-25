"""Radiometric calibration, SCL cloud masking, and NDVI calculation."""

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

import numpy as np
import yaml

logger = logging.getLogger(__name__)

# Sentinel-2 Scene Classification (SCL) classes to keep
# 4: Vegetation, 5: Not-vegetated (bare soil), 6: Water, 7: Unclassified
VALID_SCL_CLASSES = {4, 5, 6, 7}


def _load_qc_offset_thresholds(
    config_path: Optional[Union[str, Path]] = None,
) -> Tuple[float, float]:
    """Read BOA offset DN thresholds from config.yaml."""
    if config_path is None:
        cwd_cfg = Path("config.yaml")
        repo_cfg = Path(__file__).resolve().parents[3] / "config.yaml"
        config_path = cwd_cfg if cwd_cfg.exists() else repo_cfg

    with open(config_path, "r", encoding="utf-8") as f:
        raw_cfg = yaml.safe_load(f) or {}

    qc_cfg = raw_cfg.get("analysis", {}).get("qc", {})
    min_present = float(qc_cfg["min_offset_present_red_p1"])
    max_absent = float(qc_cfg["max_offset_absent_red_p1"])
    return min_present, max_absent


def get_scale_and_offset(
    asset_extra_fields: Optional[Dict[str, Any]] = None,
    processing_baseline: Optional[str] = None,
) -> Tuple[float, float]:
    """Extract scale and offset from STAC raster:bands or fallback by baseline.

    Args:
        asset_extra_fields: Dict of STAC asset extra fields (e.g. raster:bands).
        processing_baseline: Sentinel-2 processing baseline string (e.g. '04.00', '02.11').

    Returns:
        Tuple of (scale, offset).
    """
    scale = 0.0001
    offset = 0.0

    if asset_extra_fields and "raster:bands" in asset_extra_fields:
        bands = asset_extra_fields["raster:bands"]
        if isinstance(bands, list) and len(bands) > 0 and isinstance(bands[0], dict):
            b_info = bands[0]
            if "scale" in b_info and b_info["scale"] is not None:
                scale = float(b_info["scale"])
            if "offset" in b_info and b_info["offset"] is not None:
                offset = float(b_info["offset"])
                return scale, offset

    # Fallback if offset was not explicitly specified in raster:bands
    if processing_baseline:
        try:
            # Baseline format e.g. "04.00", "05.09", "02.14"
            version_val = float(processing_baseline.strip())
            if version_val >= 4.0:
                offset = -0.1
        except (ValueError, TypeError):
            pass

    return scale, offset


def detect_boa_offset(
    red_dn: np.ndarray,
    scl: np.ndarray,
    config_path: Optional[Union[str, Path]] = None,
) -> Tuple[Optional[float], float, str]:
    """Detect Sentinel-2 BOA offset (-0.1 or 0.0) from raw red DN distribution.

    Evaluated over SCL-valid pixels (classes 4, 5, 6, 7) with DN > 0 over the whole
    read window (project + reference ring).

    Rules:
        - If red 1st percentile (p1) >= qc.min_offset_present_red_p1: offset = -0.1, flag = 'present'
        - If red 1st percentile (p1) < qc.max_offset_absent_red_p1: offset = 0.0, flag = 'absent'
        - Otherwise: offset = None, flag = 'ambiguous' (scene excluded from time series)

    Args:
        red_dn: Raw Red band Digital Numbers array.
        scl: Sentinel-2 Scene Classification Layer (SCL) array.
        config_path: Optional path to config.yaml.

    Returns:
        Tuple of (detected_offset, red_p1_dn, offset_flag).
    """
    min_present, max_absent = _load_qc_offset_thresholds(config_path)

    scl_mask = create_scl_mask(scl)
    valid_pixels = red_dn[scl_mask & (red_dn > 0)]

    if len(valid_pixels) == 0:
        return None, float("nan"), "ambiguous"

    red_p1 = float(np.percentile(valid_pixels, 1))

    if red_p1 >= min_present:
        return -0.1, red_p1, "present"
    elif red_p1 < max_absent:
        return 0.0, red_p1, "absent"
    else:
        return None, red_p1, "ambiguous"


def dn_to_reflectance(
    dn: np.ndarray,
    scale: float = 0.0001,
    offset: float = 0.0,
) -> np.ndarray:
    """Convert digital numbers (DN) to surface reflectance.

    Formula: reflectance = dn * scale + offset.
    Preserves nodata (dn == 0) as NaN.
    """
    float_dn = dn.astype(np.float32)
    # 0 is Sentinel-2 nodata
    nodata_mask = (dn == 0)
    reflectance = float_dn * scale + offset
    reflectance[nodata_mask] = np.nan
    return reflectance


def create_scl_mask(scl: np.ndarray) -> np.ndarray:
    """Create boolean mask of valid pixels from Sentinel-2 SCL band.

    Keeps classes:
        4: Vegetation
        5: Not-vegetated (bare soil)
        6: Water
        7: Unclassified

    Drops:
        0: No data
        1: Saturated or defective
        2: Dark area pixels
        3: Cloud shadows
        8: Cloud medium probability
        9: Cloud high probability
        10: Thin cirrus
        11: Snow / Ice
    """
    return np.isin(scl, list(VALID_SCL_CLASSES))


def compute_ndvi(
    red_refl: np.ndarray,
    nir_refl: np.ndarray,
    valid_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Calculate NDVI: (NIR - RED) / (NIR + RED) with validity masking.

    Returns:
        np.ndarray with float32 NDVI values between -1 and 1, invalid pixels as NaN.
    """
    denom = nir_refl + red_refl
    numer = nir_refl - red_refl

    # Safe division avoiding divide by zero or negative sum
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where(denom > 1e-6, numer / denom, np.nan).astype(np.float32)

    # Filter out unphysical NDVI values outside [-1.0, 1.0]
    unphysical = (ndvi < -1.0) | (ndvi > 1.0)
    ndvi[unphysical] = np.nan

    if valid_mask is not None:
        ndvi[~valid_mask] = np.nan

    return ndvi
