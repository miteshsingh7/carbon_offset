"""Decline and first-high cohort spatial analysis for carbon-offset projects."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from scipy.ndimage import label

from carbonverify.analysis.composites import classify_hysteresis_cohorts
from carbonverify.schemas import ProjectClaims

logger = logging.getLogger(__name__)


def compute_components_summary(
    mask: np.ndarray,
    pixel_ha: float = 0.01,
) -> Dict[str, Any]:
    """Label 8-connected components and compute size distribution and largest components."""
    structure = np.ones((3, 3), dtype=int)
    labeled, n_comp = label(mask, structure=structure)
    total_px = int(np.sum(mask))
    total_ha = round(total_px * pixel_ha, 4)

    if n_comp == 0 or total_px == 0:
        return {
            "n_components": 0,
            "total_ha": 0.0,
            "share_lt_1ha_pct": 0.0,
            "share_1_to_5ha_pct": 0.0,
            "share_gt_5ha_pct": 0.0,
            "area_lt_1ha": 0.0,
            "area_1_to_5ha": 0.0,
            "area_gt_5ha": 0.0,
            "components_gt_5ha": [],
            "largest_component_ha": 0.0,
            "largest_component_mask": np.zeros_like(mask, dtype=bool),
        }

    counts = np.bincount(labeled.ravel())[1:]
    areas = counts * pixel_ha

    sorted_indices = np.argsort(-areas)
    sorted_areas = areas[sorted_indices]
    sorted_comp_ids = sorted_indices + 1

    lt1 = float(np.sum(areas[areas < 1.0]))
    b1_5 = float(np.sum(areas[(areas >= 1.0) & (areas <= 5.0)]))
    gt5 = float(np.sum(areas[areas > 5.0]))

    gt5_areas = [round(float(a), 2) for a in sorted_areas if a > 5.0]
    largest_id = int(sorted_comp_ids[0])
    largest_mask = labeled == largest_id

    return {
        "n_components": int(n_comp),
        "total_ha": round(total_ha, 2),
        "share_lt_1ha_pct": round(lt1 / total_ha * 100.0, 2) if total_ha > 0 else 0.0,
        "share_1_to_5ha_pct": round(b1_5 / total_ha * 100.0, 2) if total_ha > 0 else 0.0,
        "share_gt_5ha_pct": round(gt5 / total_ha * 100.0, 2) if total_ha > 0 else 0.0,
        "area_lt_1ha": round(lt1, 2),
        "area_1_to_5ha": round(b1_5, 2),
        "area_gt_5ha": round(gt5, 2),
        "components_gt_5ha": gt5_areas,
        "largest_component_ha": round(float(sorted_areas[0]), 2),
        "largest_component_mask": largest_mask,
    }


def compute_component_raw_means(
    comp_mask: np.ndarray,
    raw_dict: Dict[str, np.ndarray],
    years: List[str],
) -> Dict[str, float]:
    """Compute mean raw NDVI over component mask across monitoring years."""
    means: Dict[str, float] = {}
    for yr in years:
        arr = raw_dict[yr][comp_mask]
        means[yr] = round(float(np.nanmean(arr)), 4) if len(arr) > 0 else 0.0
    return means


def _load_rasters_and_mask(
    project_dir: Path,
    years: List[str],
) -> Tuple[np.ndarray, Dict[str, np.ndarray], Dict[str, np.ndarray]]:
    """Load project boundary mask and annual raw and quantile-mapped composites."""
    comp_dir = project_dir / "imagery" / "composites"
    proj_gdf = gpd.read_file(project_dir / "imagery" / "project_boundary.geojson")

    with rasterio.open(comp_dir / "ndvi_qm_2019.tif") as src:
        crs = src.crs
        transform = src.transform
        shape = src.shape

    proj_utm = proj_gdf.to_crs(crs).iloc[0].geometry
    mask_proj = rasterize(
        [(proj_utm, 1)],
        out_shape=shape,
        transform=transform,
        fill=0,
        all_touched=False,
        dtype=np.uint8,
    )
    proj_px = mask_proj == 1

    qm_dict: Dict[str, np.ndarray] = {}
    raw_dict: Dict[str, np.ndarray] = {}
    for yr in years:
        with rasterio.open(comp_dir / f"ndvi_qm_{yr}.tif") as src:
            qm_dict[yr] = src.read(1)
        with rasterio.open(comp_dir / f"raw_composite_{yr}.tif") as src:
            raw_dict[yr] = src.read(1)

    return proj_px, qm_dict, raw_dict


def compute_decline_set_d(
    proj_px: np.ndarray,
    qm_dict: Dict[str, np.ndarray],
    raw_dict: Dict[str, np.ndarray],
    years: List[str],
    pixel_ha: float = 0.01,
) -> Dict[str, Any]:
    """Compute metrics and connected components for decline set D."""
    high_19_21 = (qm_dict["2019"] >= 0.70) | (qm_dict["2020"] >= 0.70) | (qm_dict["2021"] >= 0.70)
    mask_D = proj_px & high_19_21 & (qm_dict["2022"] < 0.60)
    area_D_ha = round(float(np.sum(mask_D) * pixel_ha), 2)

    # First high year split
    fh_19 = proj_px & (qm_dict["2019"] >= 0.70) & (qm_dict["2022"] < 0.60)
    fh_20 = proj_px & (qm_dict["2019"] < 0.70) & (qm_dict["2020"] >= 0.70) & (qm_dict["2022"] < 0.60)
    fh_21 = (
        proj_px
        & (qm_dict["2019"] < 0.70)
        & (qm_dict["2020"] < 0.70)
        & (qm_dict["2021"] >= 0.70)
        & (qm_dict["2022"] < 0.60)
    )

    area_fh_19 = round(float(np.sum(fh_19) * pixel_ha), 2)
    area_fh_20 = round(float(np.sum(fh_20) * pixel_ha), 2)
    area_fh_21 = round(float(np.sum(fh_21) * pixel_ha), 2)

    # Moderate decline: high in 19-21 and in [0.60, 0.70) in 2022
    mask_mod_decline = (
        proj_px
        & high_19_21
        & (qm_dict["2022"] >= 0.60)
        & (qm_dict["2022"] < 0.70)
    )
    area_mod_decline = round(float(np.sum(mask_mod_decline) * pixel_ha), 2)

    # Connected components of D
    stats_D = compute_components_summary(mask_D, pixel_ha=pixel_ha)
    raw_means = compute_component_raw_means(
        stats_D["largest_component_mask"], raw_dict, years
    )

    return {
        "area_ha": area_D_ha,
        "first_high_split": {
            "2019": area_fh_19,
            "2020": area_fh_20,
            "2021": area_fh_21,
        },
        "moderate_decline_60_70_ha": area_mod_decline,
        "components": {
            "count": stats_D["n_components"],
            "share_lt_1ha_pct": stats_D["share_lt_1ha_pct"],
            "share_1_to_5ha_pct": stats_D["share_1_to_5ha_pct"],
            "share_gt_5ha_pct": stats_D["share_gt_5ha_pct"],
            "area_lt_1ha": stats_D["area_lt_1ha"],
            "area_1_to_5ha": stats_D["area_1_to_5ha"],
            "area_gt_5ha": stats_D["area_gt_5ha"],
            "largest_component_ha": stats_D["largest_component_ha"],
            "largest_component_raw_means": raw_means,
        },
    }


def compute_g22_cohort(
    proj_px: np.ndarray,
    qm_dict: Dict[str, np.ndarray],
    raw_dict: Dict[str, np.ndarray],
    years: List[str],
    pixel_ha: float = 0.01,
) -> Dict[str, Any]:
    """Compute metrics and connected components for G22 first-high cohort."""
    mask_G22 = (
        proj_px
        & (qm_dict["2019"] < 0.70)
        & (qm_dict["2020"] < 0.70)
        & (qm_dict["2021"] < 0.70)
        & (qm_dict["2022"] >= 0.70)
    )
    area_G22_ha = round(float(np.sum(mask_G22) * pixel_ha), 2)

    stats_G22 = compute_components_summary(mask_G22, pixel_ha=pixel_ha)
    raw_means = compute_component_raw_means(
        stats_G22["largest_component_mask"], raw_dict, years
    )

    return {
        "area_ha": area_G22_ha,
        "components": {
            "count": stats_G22["n_components"],
            "share_lt_1ha_pct": stats_G22["share_lt_1ha_pct"],
            "share_1_to_5ha_pct": stats_G22["share_1_to_5ha_pct"],
            "share_gt_5ha_pct": stats_G22["share_gt_5ha_pct"],
            "components_gt_5ha": stats_G22["components_gt_5ha"],
            "count_gt_5ha": len(stats_G22["components_gt_5ha"]),
            "largest_component_ha": stats_G22["largest_component_ha"],
            "largest_component_raw_means": raw_means,
        },
    }


def compute_strict_2022_cohort(
    proj_px: np.ndarray,
    qm_dict: Dict[str, np.ndarray],
    pixel_ha: float = 0.01,
) -> Dict[str, Any]:
    """Compute strict (0.6, 0.7) 2022 cohort area and component size breakdown."""
    c_res = classify_hysteresis_cohorts(
        qm_dict["2019"][proj_px],
        qm_dict["2020"][proj_px],
        qm_dict["2021"][proj_px],
        qm_dict["2022"][proj_px],
        0.60,
        0.70,
    )
    mask_2d = np.zeros_like(proj_px, dtype=bool)
    mask_2d[proj_px] = c_res["cohort_2022"]
    area_c22_ha = round(float(np.sum(mask_2d) * pixel_ha), 2)

    stats_c22 = compute_components_summary(mask_2d, pixel_ha=pixel_ha)
    return {
        "area_ha": area_c22_ha,
        "share_lt_1ha_pct": stats_c22["share_lt_1ha_pct"],
        "share_lt_1ha_round_pct": int(round(stats_c22["share_lt_1ha_pct"])),
        "n_components": stats_c22["n_components"],
    }


def extract_latest_planting_year(claims: Optional[ProjectClaims]) -> int:
    """Extract latest planting year from claims schedule or return fallback."""
    if claims is not None:
        if claims.planting_schedule:
            years = [
                st.planting_year
                for st in claims.planting_schedule
                if st.planting_year is not None
            ]
            if years:
                return int(max(years))
        if claims.planted_area_by_year:
            years_str = [int(y) for y in claims.planted_area_by_year.keys() if y.isdigit()]
            if years_str:
                return int(max(years_str))
    return 2020


def run_decline_analysis(
    project_dir: Union[str, Path],
    forest_allowance_ha: float,
    claims: Optional[ProjectClaims] = None,
    pixel_ha: float = 0.01,
) -> Dict[str, Any]:
    """Execute complete reproducible decline, G22, and cohort spatial analysis."""
    proj_p = Path(project_dir)
    years = ["2019", "2020", "2021", "2022"]

    proj_px, qm_dict, raw_dict = _load_rasters_and_mask(proj_p, years)

    # 1. Decline set D
    decline_d = compute_decline_set_d(proj_px, qm_dict, raw_dict, years, pixel_ha=pixel_ha)

    # 2. G22 first-high cohort
    g22 = compute_g22_cohort(proj_px, qm_dict, raw_dict, years, pixel_ha=pixel_ha)

    # 3. Sensitivity: T = 0.70 observed area excluding G22
    a2022_070 = round(float(np.sum(proj_px & (qm_dict["2022"] >= 0.70)) * pixel_ha), 2)
    obs_excl_g22 = round(a2022_070 - g22["area_ha"] - forest_allowance_ha, 2)
    sensitivity_g22 = {
        "threshold": 0.70,
        "a_2022_ha": a2022_070,
        "g22_area_ha": g22["area_ha"],
        "forest_allowance_ha": forest_allowance_ha,
        "observed_area_excl_g22_ha": obs_excl_g22,
    }

    # 4. Strict (0.6, 0.7) 2022 cohort
    strict_c22 = compute_strict_2022_cohort(proj_px, qm_dict, pixel_ha=pixel_ha)

    # 5. Endpoint gain mask: qm2019 < 0.60 and qm2022 >= 0.70
    gain_mask = proj_px & (qm_dict["2019"] < 0.60) & (qm_dict["2022"] >= 0.70)
    endpoint_gain_mask_ha = round(float(np.sum(gain_mask) * pixel_ha), 2)

    # 6. Latest planting year
    latest_yr = extract_latest_planting_year(claims)

    return {
        "decline_set_d": decline_d,
        "g22_cohort": g22,
        "sensitivity_t70_excl_g22": sensitivity_g22,
        "strict_2022_cohort": strict_c22,
        "endpoint_gain_mask_ha": endpoint_gain_mask_ha,
        "latest_planting_year": latest_yr,
    }
