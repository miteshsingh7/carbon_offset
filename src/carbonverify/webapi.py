"""Pure Python standard library HTTP API and static file server for CarbonVerify web frontend.

Provides read-only JSON endpoints for project reports, spatial geometries (GeoJSON),
and static UI assets from the web/ directory. Uses ThreadingHTTPServer.
"""

from __future__ import annotations

import csv
import json
import logging
import mimetypes
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import unquote, urlparse

from carbonverify.viewer import (
    list_output_projects,
    load_extraction_report_json,
    load_imagery_qc_data,
    load_project_geometries,
    load_report_json,
)

logger = logging.getLogger(__name__)

REASON_PREFIX_MAP: Dict[str, str] = {
    "Observation band width": "Band width",
    "Forest allowance": "Forest allowance from the project document",
    "Upper thresholds near NDVI saturation": "NDVI saturation",
    "Reference ring non-stationarity": "Reference ring changed",
    "Dry-season QC-pass scenes": "Dry-season scenes per year",
    "Without ring normalisation": "Without ring normalisation",
}


def compute_crossing_t(grid_estimates: Dict[str, Dict[str, float]], claim: float) -> Optional[float]:
    """Linearly interpolate threshold T where observed planted area equals claim.

    Args:
        grid_estimates: Mapping of threshold string to obs dict with obs_ha.
        claim: Claimed planted area in hectares.

    Returns:
        Interpolated T rounded to 3 decimal places, or None if claim not crossed.
    """
    if not grid_estimates or claim is None:
        return None

    # Parse and sort grid points by threshold
    points: List[Tuple[float, float]] = []
    for k, v in grid_estimates.items():
        try:
            t_val = float(k)
            raw_obs = v.get("obs_ha")
            if raw_obs is None:
                continue
            obs_val = float(raw_obs)
            points.append((t_val, obs_val))
        except (ValueError, TypeError):
            continue

    points.sort(key=lambda p: p[0])
    if len(points) < 2:
        return None

    # Find adjacent pair crossing claim
    for i in range(len(points) - 1):
        t1, y1 = points[i]
        t2, y2 = points[i + 1]
        min_y, max_y = min(y1, y2), max(y1, y2)
        if min_y <= claim <= max_y and y1 != y2:
            fraction = (claim - y1) / (y2 - y1)
            t_star = t1 + fraction * (t2 - t1)
            return round(t_star, 3)

    return None


def get_first_high_year_areas(
    project_id: str,
    data_dir: Union[str, Path] = "data/projects",
) -> Optional[Dict[str, float]]:
    """Retrieve or compute first high-NDVI year areas (qm >= 0.70) in hectares.

    Args:
        project_id: Project identifier.
        data_dir: Base directory for project data.

    Returns:
        Dict with keys '2019', '2020', '2021', '2022', 'never' or None.
    """
    proj_dir = Path(data_dir) / project_id
    est_file = proj_dir / "estimate.json"

    # Check if pre-computed in estimate.json
    if est_file.exists():
        try:
            with open(est_file, "r", encoding="utf-8") as f:
                est_data = json.load(f)
            sat_est = est_data.get("satellite_estimate", est_data)
            if "first_high_year_areas" in sat_est and sat_est["first_high_year_areas"]:
                return sat_est["first_high_year_areas"]
            if "first_high_year_areas" in est_data and est_data["first_high_year_areas"]:
                return est_data["first_high_year_areas"]
        except Exception as exc:
            logger.warning("Error reading estimate.json for project '%s': %s", project_id, exc)

    # Compute on the fly if raster data exists
    comp_dir = proj_dir / "imagery" / "composites"
    bound_path = proj_dir / "imagery" / "project_boundary.geojson"
    if not bound_path.exists():
        bound_path = proj_dir / "boundary.geojson"

    years = ["2019", "2020", "2021", "2022"]
    rasters_exist = all((comp_dir / f"ndvi_qm_{y}.tif").exists() for y in years)
    if rasters_exist and bound_path.exists():
        try:
            import geopandas as gpd
            import numpy as np
            import rasterio
            from rasterio.features import rasterize

            with rasterio.open(comp_dir / "ndvi_qm_2019.tif") as src:
                crs = src.crs
                transform = src.transform
                shape = src.shape

            gdf = gpd.read_file(bound_path).to_crs(crs)
            proj_mask = rasterize(
                [(gdf.geometry.iloc[0], 1)],
                out_shape=shape,
                transform=transform,
                fill=0,
                dtype=np.uint8,
            )
            proj_px = proj_mask == 1

            qm = {}
            for y in years:
                with rasterio.open(comp_dir / f"ndvi_qm_{y}.tif") as src:
                    qm[y] = src.read(1)

            pixel_ha = 0.01  # 10m x 10m
            h19 = (qm["2019"] >= 0.70) & proj_px
            h20 = (qm["2020"] >= 0.70) & proj_px & (~h19)
            h21 = (qm["2021"] >= 0.70) & proj_px & (~(qm["2019"] >= 0.70)) & (~(qm["2020"] >= 0.70))
            h22 = (
                (qm["2022"] >= 0.70)
                & proj_px
                & (~(qm["2019"] >= 0.70))
                & (~(qm["2020"] >= 0.70))
                & (~(qm["2021"] >= 0.70))
            )
            never = (
                proj_px
                & (~(qm["2019"] >= 0.70))
                & (~(qm["2020"] >= 0.70))
                & (~(qm["2021"] >= 0.70))
                & (~(qm["2022"] >= 0.70))
            )

            res = {
                "2019": round(float(np.sum(h19) * pixel_ha), 2),
                "2020": round(float(np.sum(h20) * pixel_ha), 2),
                "2021": round(float(np.sum(h21) * pixel_ha), 2),
                "2022": round(float(np.sum(h22) * pixel_ha), 2),
                "never": round(float(np.sum(never) * pixel_ha), 2),
            }

            # Cache back to estimate.json if possible
            if est_file.exists():
                try:
                    with open(est_file, "r", encoding="utf-8") as f:
                        edata = json.load(f)
                    if "satellite_estimate" in edata:
                        edata["satellite_estimate"]["first_high_year_areas"] = res
                    edata["first_high_year_areas"] = res
                    with open(est_file, "w", encoding="utf-8") as f:
                        json.dump(edata, f, indent=2)
                except Exception:
                    pass

            return res
        except Exception as exc:
            logger.warning("Failed on-the-fly first_high_year_areas calculation: %s", exc)

    return None


def build_imagery_payload(
    project_id: str,
    output_dir: Union[str, Path] = "output",
    data_dir: Union[str, Path] = "data/projects",
) -> Optional[Dict[str, Any]]:
    """Build structured imagery quality and screening payload.

    Args:
        project_id: Project identifier.
        output_dir: Output base directory.
        data_dir: Data base directory.

    Returns:
        Structured imagery dictionary or None if project does not exist.
    """
    report_data = load_report_json(output_dir, project_id)
    if not report_data:
        return None

    # Candidate paths for qc_scenes.csv
    qc_candidates = [
        Path(output_dir) / project_id / "qc_scenes.csv",
        Path(data_dir) / project_id / "imagery" / "qc_scenes.csv",
        Path(data_dir) / project_id / "qc_scenes.csv",
    ]
    qc_csv_path: Optional[Path] = None
    for cand in qc_candidates:
        if cand.exists():
            qc_csv_path = cand
            break

    # Candidate paths for stac_items.json
    stac_candidates = [
        Path(data_dir) / project_id / "imagery" / "stac_items.json",
        Path(data_dir) / project_id / "stac_items.json",
        Path(output_dir) / project_id / "stac_items.json",
    ]
    stac_path: Optional[Path] = None
    for cand in stac_candidates:
        if cand.exists():
            stac_path = cand
            break

    total = 0
    passed = 0
    exact_counts: Dict[str, int] = {}
    dry_season_counts: Dict[str, int] = {}
    time_series: List[Dict[str, Any]] = []
    exclusions_log: List[Dict[str, Any]] = []

    if qc_csv_path:
        try:
            with open(qc_csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    total += 1
                    d_str = row.get("date", "") or ""
                    is_pass = str(row.get("qc_pass", "")).strip().lower() in ("true", "1")
                    reasons_raw = row.get("qc_reasons", "") or ""

                    p_ndvi: Optional[float] = None
                    r_ndvi: Optional[float] = None
                    try:
                        raw_p = row.get("proj_ndvi_median")
                        if raw_p and raw_p.strip():
                            p_ndvi = round(float(raw_p), 4)
                    except (ValueError, TypeError):
                        pass
                    try:
                        raw_r = row.get("ring_ndvi_median")
                        if raw_r and raw_r.strip():
                            r_ndvi = round(float(raw_r), 4)
                    except (ValueError, TypeError):
                        pass

                    if is_pass:
                        passed += 1
                        if len(d_str) >= 7:
                            try:
                                month = int(d_str[5:7])
                                if month in (6, 7, 8):
                                    year_str = d_str[:4]
                                    if year_str in dry_season_counts:
                                        dry_season_counts[year_str] += 1
                                    else:
                                        dry_season_counts[year_str] = 1
                            except ValueError:
                                pass
                    else:
                        r_key = reasons_raw.strip()
                        if not r_key:
                            r_key = "unspecified"
                        if r_key in exact_counts:
                            exact_counts[r_key] += 1
                        else:
                            exact_counts[r_key] = 1
                        exclusions_log.append(
                            {
                                "date": d_str,
                                "scene_id": row.get("scene_id"),
                                "reason": reasons_raw,
                            }
                        )

                    time_series.append(
                        {
                            "date": d_str,
                            "project_ndvi": p_ndvi,
                            "ring_ndvi": r_ndvi,
                            "pass": is_pass,
                            "reason": reasons_raw if not is_pass else None,
                        }
                    )
        except Exception as exc:
            logger.warning("Error reading qc_scenes.csv for project '%s': %s", project_id, exc)

    # Ingest-excluded dates from stac_items.json
    ingest_excluded_dates: Optional[List[str]] = None
    fetched_s: Optional[int] = None
    excl_ingest: Optional[int] = None
    if stac_path:
        try:
            with open(stac_path, "r", encoding="utf-8") as sf:
                stac_items = json.load(sf)
            if isinstance(stac_items, list):
                stac_dates = {
                    item["datetime"][:10]
                    for item in stac_items
                    if isinstance(item, dict) and "datetime" in item
                }
                if len(stac_dates) >= total:
                    fetched_s = len(stac_dates)
                    excl_ingest = fetched_s - total
                    qc_dates = {rec["date"] for rec in time_series if rec.get("date")}
                    diff_dates = sorted(stac_dates - qc_dates)
                    if diff_dates:
                        ingest_excluded_dates = diff_dates
        except Exception as exc:
            logger.warning("Error parsing stac_items.json for project '%s': %s", project_id, exc)

    funnel: Optional[Dict[str, Optional[int]]] = None
    if qc_csv_path:
        funnel = {
            "fetched": fetched_s,
            "excluded_ingest": excl_ingest,
            "in_timeseries": total,
            "excluded_qc": total - passed,
            "passed": passed,
        }

    claims_raw = report_data.get("claims") or {}
    rep_start = claims_raw.get("reporting_period_start")
    rep_end = claims_raw.get("reporting_period_end")

    excl_list: Optional[List[Dict[str, Any]]] = None
    if qc_csv_path:
        excl_list = [
            {
                "flags": [p.strip() for p in raw_k.split(";") if p.strip()] if raw_k != "unspecified" else ["unspecified"],
                "count": cnt,
            }
            for raw_k, cnt in exact_counts.items()
        ]

    return {
        "funnel": funnel,
        "exclusion_counts_by_reason": excl_list,
        "ingest_excluded_dates": ingest_excluded_dates,
        "dry_season_qc_pass_per_year": dry_season_counts if qc_csv_path else None,
        "time_series": time_series if qc_csv_path else None,
        "reporting_period_start": rep_start,
        "reporting_period_end": rep_end,
        "exclusions_log": exclusions_log if qc_csv_path else None,
    }


def build_canopy_payload(
    project_id: str,
    output_dir: Union[str, Path] = "output",
    data_dir: Union[str, Path] = "data/projects",
) -> Optional[Dict[str, Any]]:
    """Build structured canopy and biomass payload.

    Args:
        project_id: Project identifier.
        output_dir: Output base directory.
        data_dir: Data base directory.

    Returns:
        Structured canopy dictionary or None if project does not exist.
    """
    report_data = load_report_json(output_dir, project_id)
    if not report_data:
        return None

    estimate_data = report_data.get("estimate") or {}
    cb = estimate_data.get("canopy_biomass")

    # If missing in report, look for estimate.json in data_dir
    est_file = Path(data_dir) / project_id / "estimate.json"
    est_file_data: Dict[str, Any] = {}
    if est_file.exists():
        try:
            with open(est_file, "r", encoding="utf-8") as f:
                est_file_data = json.load(f)
                if not cb:
                    cb = est_file_data.get("canopy_biomass") or est_file_data.get("satellite_estimate", {}).get("canopy_biomass")
        except Exception:
            pass

    if not cb or not isinstance(cb, dict):
        return None

    canopy_payload = dict(cb)
    sat_share = (
        estimate_data.get("saturation_share_pct")
        if estimate_data.get("saturation_share_pct") is not None
        else est_file_data.get("saturation_share_pct")
    )
    canopy_payload["saturation_share_pct"] = sat_share

    # Saturation counts
    sat_px = (
        estimate_data.get("saturation_pixel_count")
        if estimate_data.get("saturation_pixel_count") is not None
        else est_file_data.get("saturation_pixel_count", est_file_data.get("satellite_estimate", {}).get("saturation_pixel_count"))
    )
    sat_tot = (
        estimate_data.get("saturation_total_count")
        if estimate_data.get("saturation_total_count") is not None
        else est_file_data.get("saturation_total_count", est_file_data.get("satellite_estimate", {}).get("saturation_total_count"))
    )
    canopy_payload["saturation_pixel_count"] = sat_px
    canopy_payload["saturation_total_count"] = sat_tot

    # Claimed canopy change pct from claims
    claims_dict = report_data.get("claims") or {}
    canopy_payload["claimed_canopy_change_pct"] = claims_dict.get("claimed_canopy_change_pct")

    return canopy_payload


def build_limitations_payload(
    project_id: str,
    output_dir: Union[str, Path] = "output",
    data_dir: Union[str, Path] = "data/projects",
) -> Optional[Dict[str, Any]]:
    """Build structured methodology limitations and evidence provenance payload.

    Args:
        project_id: Project identifier.
        output_dir: Output base directory.
        data_dir: Data base directory.

    Returns:
        Structured limitations and provenance dictionary or None if project does not exist.
    """
    report_data = load_report_json(output_dir, project_id)
    if not report_data:
        return None

    estimate_data = report_data.get("estimate") or {}
    ext_rep = load_extraction_report_json(output_dir, project_id) or {}

    # Stored limitations list (stored under confidence_reasons or limitations)
    limitations_list = report_data.get("confidence_reasons")
    if limitations_list is None:
        limitations_list = report_data.get("limitations")

    # Hashes from estimate_data or estimate.json
    file_hashes = estimate_data.get("file_hashes")
    est_file_data: Dict[str, Any] = {}
    est_file = Path(data_dir) / project_id / "estimate.json"
    if est_file.exists():
        try:
            with open(est_file, "r", encoding="utf-8") as f:
                est_file_data = json.load(f)
                if not file_hashes:
                    file_hashes = est_file_data.get("file_hashes") or est_file_data.get("satellite_estimate", {}).get("file_hashes")
        except Exception:
            pass

    extractor = ext_rep.get("extractor")
    pdf_sha256 = ext_rep.get("pdf_sha256")
    source_notes = ext_rep.get("source_notes")
    imagery_source = None

    pdf_sha256_document: Optional[str] = None
    if pdf_sha256:
        doc_stats = ext_rep.get("document_stats")
        if isinstance(doc_stats, dict):
            for doc_name, stats in doc_stats.items():
                if isinstance(stats, dict) and stats.get("sha256") == pdf_sha256:
                    pdf_sha256_document = doc_name
                    break

    # Imagery source if stored in provenance.json
    imagery_source = None
    prov_file = Path(data_dir) / project_id / "provenance.json"
    if prov_file.exists():
        try:
            with open(prov_file, "r", encoding="utf-8") as pf:
                prov_data = json.load(pf)
                imagery_source = prov_data.get("imagery_source")
        except Exception:
            pass

    # Hansen file names/hashes if stored
    hansen = estimate_data.get("hansen_crosscheck") or est_file_data.get("satellite_estimate", {}).get("hansen_crosscheck") or {}
    hansen_file_hashes = hansen.get("file_hashes")

    # Config thresholds
    grid_t = estimate_data.get("grid_thresholds") or est_file_data.get("grid_thresholds")
    if isinstance(grid_t, dict):
        grid_t = [float(k) for k in grid_t.keys()]
    elif isinstance(grid_t, list):
        grid_t = [float(x) for x in grid_t]

    cfg_thresh = None
    project_root = Path(__file__).resolve().parents[2]
    cfg_file = project_root / "config.yaml"
    if cfg_file.exists():
        try:
            import yaml
            with open(cfg_file, "r", encoding="utf-8") as yf:
                cfg = yaml.safe_load(yf)
                if isinstance(cfg, dict):
                    cfg_thresh = cfg.get("scoring", {}).get("thresholds")
        except Exception:
            pass

    thresholds = None
    if grid_t is not None or cfg_thresh is not None:
        thresholds = {
            "minor_discrepancy_pct": cfg_thresh.get("minor_discrepancy_pct") if isinstance(cfg_thresh, dict) else None,
            "major_discrepancy_pct": cfg_thresh.get("major_discrepancy_pct") if isinstance(cfg_thresh, dict) else None,
            "grid_thresholds": grid_t,
        }

    return {
        "limitations": limitations_list,
        "file_hashes": file_hashes,
        "extractor": extractor,
        "pdf_sha256": pdf_sha256,
        "pdf_sha256_document": pdf_sha256_document,
        "source_notes": source_notes,
        "imagery_source": imagery_source,
        "hansen_file_hashes": hansen_file_hashes,
        "thresholds": thresholds,
    }


def build_project_payload(
    project_id: str,
    output_dir: Union[str, Path] = "output",
    data_dir: Union[str, Path] = "data/projects",
) -> Optional[Dict[str, Any]]:
    """Build unified flat API payload merging report, estimate, extraction, and QC data.

    Args:
        project_id: Project identifier.
        output_dir: Base directory containing run outputs.
        data_dir: Base directory containing source project data.

    Returns:
        Structured API response dict, or None if project does not exist.
    """
    report_data = load_report_json(output_dir, project_id)
    if not report_data:
        return None

    is_demo = bool(report_data.get("demo", False))
    estimate_data = report_data.get("estimate") or {}
    claims_raw = report_data.get("claims") or {}

    # Extraction report for quotes & source pages
    ext_rep = load_extraction_report_json(output_dir, project_id) or {}
    ext_fields = ext_rep.get("fields") or {}
    source_notes = ext_rep.get("source_notes") or []

    # Status & Confidence
    status = str(report_data.get("status", "INCONCLUSIVE"))
    confidence = str(report_data.get("confidence", "LOW"))

    # Band & Claim
    obs_low = estimate_data.get("planted_area_obs_low")
    obs_high = estimate_data.get("planted_area_obs_high")
    obs_central = estimate_data.get("planted_area_obs_central")
    band: Optional[List[float]] = (
        [float(obs_low), float(obs_high)]
        if obs_low is not None and obs_high is not None
        else None
    )

    claimed_area = claims_raw.get("claimed_area_ha")
    claim_val = float(claimed_area) if claimed_area is not None else None

    # Span % and Detection limit %
    span_pct: Optional[float] = None
    detection_limit_pct: Optional[float] = None
    if band is not None and claim_val is not None and claim_val > 0:
        span_pct = round(((band[1] - band[0]) / claim_val) * 100.0, 1)
        detection_limit_pct = round(((claim_val - band[0]) / claim_val) * 100.0, 1)

    # Scenes funnel
    qc_data = load_imagery_qc_data(output_dir, project_id, data_dir)
    scenes: Optional[Dict[str, Any]] = None
    if qc_data.get("available"):
        total_s = int(qc_data["total_scenes"])
        pass_s = int(qc_data["pass_scenes"])
        excl_s = int(qc_data["excluded_scenes"])
        stac_path = Path(data_dir) / project_id / "imagery" / "stac_items.json"
        fetched_s: Optional[int] = None
        excl_ingest: Optional[int] = None
        if stac_path.exists():
            try:
                with open(stac_path, "r", encoding="utf-8") as sf:
                    stac_items = json.load(sf)
                if isinstance(stac_items, list):
                    unique_dates = {
                        item["datetime"][:10]
                        for item in stac_items
                        if isinstance(item, dict) and "datetime" in item
                    }
                    if len(unique_dates) >= total_s:
                        fetched_s = len(unique_dates)
                        excl_ingest = fetched_s - total_s
            except Exception:
                pass

        scenes = {
            "fetched": fetched_s,
            "excluded_ingest": excl_ingest,
            "in_timeseries": total_s,
            "excluded_qc": excl_s,
            "passed": pass_s,
        }

    # Grid estimates & Crossing T
    grid_estimates = estimate_data.get("grid_estimates") or {}
    crossing_t = compute_crossing_t(grid_estimates, claim_val) if claim_val else None

    # Break even analysis
    break_even: Optional[Dict[str, Any]] = None
    fac = estimate_data.get("forest_allowance_check")
    if fac and isinstance(fac, dict):
        target_raw = fac.get("claimed_planted_ha")
        if target_raw is None and claim_val is not None:
            target_raw = claim_val
        nat_raw = fac.get("claimed_forest_allowance_ha")
        if nat_raw is None:
            nat_raw = claims_raw.get("natural_forest_ha")

        if target_raw is not None and nat_raw is not None:
            target_ha = float(target_raw)
            nat_forest_ha = float(nat_raw)

            thresh_grid_source = fac.get("break_even_allowance", {}).get("by_threshold") if isinstance(fac.get("break_even_allowance"), dict) else None
            by_threshold: List[Dict[str, float]] = []
            all_valid = True

            for t_val in [0.60, 0.65, 0.70, 0.75]:
                a_2022_val: Optional[float] = None

                # Check grid_estimates first
                for k, v in grid_estimates.items():
                    try:
                        if abs(float(k) - t_val) < 1e-4 and isinstance(v, dict):
                            val_raw = v.get("a_2022_ha")
                            if val_raw is not None:
                                a_2022_val = float(val_raw)
                                break
                    except (ValueError, TypeError):
                        pass

                # Fallback to fac break_even_allowance if not in grid_estimates
                if a_2022_val is None and thresh_grid_source and isinstance(thresh_grid_source, dict):
                    for k, v in thresh_grid_source.items():
                        try:
                            if abs(float(k) - t_val) < 1e-4 and isinstance(v, dict):
                                val_raw = v.get("a_2022_ha")
                                if val_raw is not None:
                                    a_2022_val = float(val_raw)
                                    break
                        except (ValueError, TypeError):
                            pass

                if a_2022_val is None:
                    all_valid = False
                    break

                a_2022_rounded = round(a_2022_val, 2)
                f_star = round(a_2022_rounded - target_ha, 2)
                margin = round(f_star - nat_forest_ha, 2)
                by_threshold.append(
                    {
                        "t": t_val,
                        "a_2022_ha": a_2022_rounded,
                        "f_star_ha": f_star,
                        "margin_ha": margin,
                    }
                )

            if all_valid and len(by_threshold) == 4:
                entry_06 = by_threshold[0]
                entry_low = by_threshold[3]
                break_even = {
                    "target_ha": target_ha,
                    "natural_forest_ha": nat_forest_ha,
                    "f_star_06_ha": entry_06["f_star_ha"],
                    "f_star_low_end_ha": entry_low["f_star_ha"],
                    "margin_06_ha": entry_06["margin_ha"],
                    "margin_low_end_ha": entry_low["margin_ha"],
                    "by_threshold": by_threshold,
                }

    # First high year areas
    first_high_year_areas = get_first_high_year_areas(project_id, data_dir)

    # Confidence reasons structured
    raw_reasons = report_data.get("confidence_reasons") or []
    confidence_reasons_list: List[Dict[str, Any]] = []
    for r in raw_reasons:
        matched_title = "Other"
        for pfx, title in REASON_PREFIX_MAP.items():
            if r.startswith(pfx):
                matched_title = title
                break

        # Extract contribution_pct if present (e.g. span / claimed = 37.72%, share is 44.12%, detection limit 13.65%)
        c_pct: Optional[float] = None
        m = re.search(r"=\s*([0-9.]+)%", r) or re.search(r"is\s*([0-9.]+)%", r) or re.search(r"limit\s*([0-9.]+)%", r)
        if m:
            try:
                c_pct = float(m.group(1))
            except ValueError:
                pass

        confidence_reasons_list.append(
            {
                "title": matched_title,
                "description": r,
                "contribution_pct": c_pct,
                "raw_text": r,
            }
        )

    # Area test ledger & sensitivity
    grid_rows: List[Dict[str, Any]] = []
    if grid_estimates:
        for k_t in sorted(grid_estimates.keys(), key=lambda x: float(x)):
            row = grid_estimates[k_t]
            t_num = float(k_t)
            obs_raw = row.get("obs_ha")
            if obs_raw is None:
                continue
            obs_h = float(obs_raw)
            c_val = claim_val if claim_val is not None else 0.0
            shortfall = max(0.0, round(c_val - obs_h, 2))
            disc_pct = round((shortfall / c_val) * 100.0, 2) if c_val > 0 else 0.0
            a2022_raw = row.get("a_2022_ha")
            a2022_h = float(a2022_raw) if a2022_raw is not None else 0.0
            fa_raw = row.get("forest_allowance_ha")
            fa_h = float(fa_raw) if fa_raw is not None else 0.0
            grid_rows.append(
                {
                    "t": t_num,
                    "a_2022_ha": a2022_h,
                    "forest_allowance_ha": fa_h,
                    "obs_ha": obs_h,
                    "claimed_ha": c_val,
                    "shortfall_ha": shortfall,
                    "discrepancy_pct": disc_pct,
                    "is_primary": (round(t_num, 2) == 0.70),
                }
            )

    norm_sens = estimate_data.get("normalization_sensitivity") or {}
    area_test_obj = {
        "grid_rows": grid_rows,
        "raw_sensitivity": norm_sens,
        "break_even": break_even,
        "crossing_t": crossing_t,
        "primary_threshold": 0.70,
    }

    # Format claims with evidence quotes & page numbers
    claims_formatted: Dict[str, Any] = {}
    claim_keys = [
        "project_id",
        "registry",
        "methodology",
        "claimed_area_ha",
        "estate_area_ha",
        "reporting_period_start",
        "reporting_period_end",
        "crediting_period_start",
        "crediting_period_end",
        "project_start_date",
        "credits_issued",
        "net_ghg_removals_tco2e",
        "buffer_credits_tco2e",
        "canopy_cover_pct",
        "min_area_ha",
        "min_height_m",
        "natural_forest_ha",
    ]

    for k in claim_keys:
        val = claims_raw.get(k)
        field_detail = ext_fields.get(k) or {}
        quote = field_detail.get("evidence_quote") or ""
        page = field_detail.get("page")
        if page is None:
            page = claims_raw.get("source_pages", {}).get(k)
        source_doc = field_detail.get("source_doc") or "project documentation"

        # Special source note check (e.g. credits inconsistency)
        s_note: Optional[str] = None
        if k == "credits_issued" and source_notes:
            s_note = source_notes[0]

        claims_formatted[k] = {
            "value": val,
            "source": source_doc,
            "page": page,
            "quote": quote,
            "source_note": s_note,
        }

    # Planting schedule
    ps_raw = claims_raw.get("planting_schedule") or []
    planting_schedule: List[Dict[str, Any]] = []
    for item in ps_raw:
        area_raw = item.get("area_ha")
        dens_raw = item.get("density")
        area_h = float(area_raw) if area_raw is not None else 0.0
        dens = int(dens_raw) if dens_raw is not None else 0
        trees_count = int(dens * area_h) if dens and area_h else None
        planting_schedule.append(
            {
                "stratum": item.get("stratum", "not available"),
                "year": item.get("planting_year", "not available"),
                "density": dens,
                "area_ha": area_h,
                "trees": trees_count,
                "source": item.get("source_doc", "not available"),
                "page": item.get("page", "not available"),
                "evidence_quote": item.get("evidence_quote", ""),
            }
        )

    ps_check = claims_raw.get("check") or {}
    schedule_summary = {
        "sum_area_ha": ps_check.get("sum_area_ha"),
        "stated_total_ha": ps_check.get("stated_total_ha"),
        "discrepancy_ha": ps_check.get("discrepancy_ha"),
        "is_consistent": ps_check.get("is_consistent"),
    }

    # File hashes
    file_hashes = estimate_data.get("file_hashes") or {}

    payload: Dict[str, Any] = {
        "project_id": project_id,
        "demo": is_demo,
        "status": status,
        "confidence": confidence,
        "confidence_reasons": confidence_reasons_list,
        "band": band,
        "claim": claim_val,
        "span_pct": span_pct,
        "detection_limit_pct": detection_limit_pct,
        "scenes": scenes,
        "crossing_t": crossing_t,
        "break_even": break_even,
        "first_high_year_areas": first_high_year_areas,
        "area_test": area_test_obj,
        "claims": claims_formatted,
        "planting_schedule": planting_schedule,
        "schedule_summary": schedule_summary,
        "file_hashes": file_hashes,
        "recorded_files_count": len(file_hashes),
        "imagery": build_imagery_payload(project_id, output_dir, data_dir),
        "canopy": build_canopy_payload(project_id, output_dir, data_dir),
        "limitations": build_limitations_payload(project_id, output_dir, data_dir),
    }

    return payload


class CarbonVerifyHandler(BaseHTTPRequestHandler):
    """HTTP request handler for CarbonVerify API and web frontend."""

    output_dir: Path = Path("output")
    data_dir: Path = Path("data/projects")
    web_dir: Path = Path("web")

    def _send_json(self, data: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: int = HTTPStatus.NOT_FOUND) -> None:
        self._send_json({"error": message}, status=status)

    def _send_file(self, file_path: Path, content_type: Optional[str] = None) -> None:
        if not file_path.exists() or not file_path.is_file():
            self._send_error_json("File not found", HTTPStatus.NOT_FOUND)
            return

        try:
            with open(file_path, "rb") as f:
                content = f.read()
            if not content_type:
                content_type, _ = mimetypes.guess_type(str(file_path))
            if not content_type:
                content_type = "application/octet-stream"

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        except Exception as exc:
            logger.error("Error serving file %s: %s", file_path, exc)
            self._send_error_json("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_GET(self) -> None:
        """Route incoming HTTP GET requests."""
        parsed = urlparse(self.path)
        path = unquote(parsed.path).strip()

        # Reject path traversal attempts immediately
        if ".." in path or "\\" in path:
            self._send_error_json("Invalid path: traversal rejected", HTTPStatus.FORBIDDEN)
            return

        # 1. API: List projects
        if path == "/api/projects":
            projects = list_output_projects(self.output_dir)
            self._send_json(projects)
            return

        # 2. API: Project payload
        m_proj = re.match(r"^/api/project/([^/]+)$", path)
        if m_proj:
            pid = m_proj.group(1)
            payload = build_project_payload(pid, self.output_dir, self.data_dir)
            if payload is None:
                self._send_error_json(f"Project '{pid}' not found", HTTPStatus.NOT_FOUND)
            else:
                self._send_json(payload)
            return

        # 2b. API: Imagery payload
        m_img = re.match(r"^/api/project/([^/]+)/imagery$", path)
        if m_img:
            pid = m_img.group(1)
            img_payload = build_imagery_payload(pid, self.output_dir, self.data_dir)
            if img_payload is None:
                if not load_report_json(self.output_dir, pid):
                    self._send_error_json(f"Project '{pid}' not found", HTTPStatus.NOT_FOUND)
                else:
                    self._send_json(None)
            else:
                self._send_json(img_payload)
            return

        # 2c. API: Canopy payload
        m_can = re.match(r"^/api/project/([^/]+)/canopy$", path)
        if m_can:
            pid = m_can.group(1)
            can_payload = build_canopy_payload(pid, self.output_dir, self.data_dir)
            if can_payload is None:
                if not load_report_json(self.output_dir, pid):
                    self._send_error_json(f"Project '{pid}' not found", HTTPStatus.NOT_FOUND)
                else:
                    self._send_json(None)
            else:
                self._send_json(can_payload)
            return

        # 2d. API: Limitations payload
        m_lim = re.match(r"^/api/project/([^/]+)/limitations$", path)
        if m_lim:
            pid = m_lim.group(1)
            lim_payload = build_limitations_payload(pid, self.output_dir, self.data_dir)
            if lim_payload is None:
                if not load_report_json(self.output_dir, pid):
                    self._send_error_json(f"Project '{pid}' not found", HTTPStatus.NOT_FOUND)
                else:
                    self._send_json(None)
            else:
                self._send_json(lim_payload)
            return

        # 3. API: GeoJSON boundary & ring
        m_geo = re.match(r"^/api/project/([^/]+)/geo/(boundary|ring)$", path)
        if m_geo:
            pid = m_geo.group(1)
            geo_type = m_geo.group(2)
            geoms = load_project_geometries(self.output_dir, pid, self.data_dir)
            target_key = "boundary" if geo_type == "boundary" else "reference_ring"
            geo_dict = geoms.get(target_key)
            if geo_dict is None:
                self._send_error_json(f"{geo_type.capitalize()} GeoJSON not found for '{pid}'", HTTPStatus.NOT_FOUND)
            else:
                self._send_json(geo_dict)
            return

        # 4. Direct report download endpoints
        m_rep_html = re.match(r"^/report/([^/]+)/report\.html$", path)
        if m_rep_html:
            pid = m_rep_html.group(1)
            f_path = self.output_dir / pid / "report.html"
            self._send_file(f_path, "text/html; charset=utf-8")
            return

        m_rep_json = re.match(r"^/report/([^/]+)/report\.json$", path)
        if m_rep_json:
            pid = m_rep_json.group(1)
            f_path = self.output_dir / pid / "report.json"
            self._send_file(f_path, "application/json; charset=utf-8")
            return

        # 5. Static UI files from web/
        if path in ("", "/", "/index.html"):
            self._send_file(self.web_dir / "index.html", "text/html; charset=utf-8")
            return

        # Check relative file in web_dir
        rel_path = path.lstrip("/")
        static_file = (self.web_dir / rel_path).resolve()
        web_root = self.web_dir.resolve()

        # Strict containment check
        try:
            static_file.relative_to(web_root)
        except ValueError:
            self._send_error_json("Access denied", HTTPStatus.FORBIDDEN)
            return

        if static_file.exists() and static_file.is_file():
            self._send_file(static_file)
            return

        self._send_error_json("Endpoint not found", HTTPStatus.NOT_FOUND)


def create_server(
    output_dir: Union[str, Path] = "output",
    data_dir: Union[str, Path] = "data/projects",
    web_dir: Union[str, Path] = "web",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    """Create a configured ThreadingHTTPServer instance.

    Args:
        output_dir: Directory containing project outputs.
        data_dir: Directory containing project data.
        web_dir: Directory containing static web assets.
        host: Host address to bind to.
        port: Port to listen on.

    Returns:
        Configured ThreadingHTTPServer.
    """
    handler_class = type(
        "CustomCarbonVerifyHandler",
        (CarbonVerifyHandler,),
        {
            "output_dir": Path(output_dir),
            "data_dir": Path(data_dir),
            "web_dir": Path(web_dir),
        },
    )
    server = ThreadingHTTPServer((host, port), handler_class)
    return server


def run_server(
    output_dir: Union[str, Path] = "output",
    data_dir: Union[str, Path] = "data/projects",
    web_dir: Union[str, Path] = "web",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Run the CarbonVerify HTTP server and block until interrupted.

    Args:
        output_dir: Directory containing project outputs.
        data_dir: Directory containing project data.
        web_dir: Directory containing static web assets.
        host: Host address to bind to.
        port: Port to listen on.
    """
    server = create_server(output_dir, data_dir, web_dir, host, port)
    print(f"CarbonVerify evidence workbench server running on http://{host}:{port}")
    print(f"Serving outputs from: {Path(output_dir).resolve()}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        server.server_close()
