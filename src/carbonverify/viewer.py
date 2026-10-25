"""Data loaders and summaries for the CarbonVerify Streamlit viewer.

This module contains pure Python loaders and data normalization routines for
inspecting pipeline run outputs. It does not import Streamlit so that all loader
logic and edge cases (e.g. missing keys, demo fixture) can be thoroughly tested.
"""

import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


def list_output_projects(output_dir: Union[str, Path] = "output") -> List[str]:
    """Scan the output directory and return sorted list of project IDs with a report.json.

    Args:
        output_dir: Directory containing project output subfolders.

    Returns:
        List of project ID strings.
    """
    out_path = Path(output_dir)
    if not out_path.exists() or not out_path.is_dir():
        return []

    projects: List[str] = []
    for item in sorted(out_path.iterdir()):
        if item.is_dir() and (item / "report.json").exists():
            projects.append(item.name)
    return projects


def load_report_json(output_dir: Union[str, Path], project_id: str) -> Dict[str, Any]:
    """Load and parse report.json for a given project.

    Args:
        output_dir: Directory containing project output subfolders.
        project_id: Project identifier.

    Returns:
        Parsed JSON dictionary, or empty dict if not found.
    """
    report_file = Path(output_dir) / project_id / "report.json"
    if not report_file.exists():
        logger.warning("report.json not found for project '%s' at %s", project_id, report_file)
        return {}

    try:
        with open(report_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Failed to parse %s: %s", report_file, exc)
        return {}


def load_extraction_report_json(
    output_dir: Union[str, Path], project_id: str
) -> Optional[Dict[str, Any]]:
    """Load and parse extraction_report.json if present in output or data directories.

    Args:
        output_dir: Directory containing project output subfolders.
        project_id: Project identifier.

    Returns:
        Parsed extraction report dictionary, or None if not found.
    """
    candidates = [
        Path(output_dir) / project_id / "extraction_report.json",
        Path("data/projects") / project_id / "extraction_report.json",
    ]
    for cand in candidates:
        if cand.exists():
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning("Failed to parse extraction report at %s: %s", cand, exc)
    return None


def load_report_html(output_dir: Union[str, Path], project_id: str) -> str:
    """Load the rendered report.html string if present.

    Args:
        output_dir: Directory containing project output subfolders.
        project_id: Project identifier.

    Returns:
        HTML string content, or empty string if not found.
    """
    html_file = Path(output_dir) / project_id / "report.html"
    if not html_file.exists():
        return ""
    try:
        return html_file.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to read HTML report at %s: %s", html_file, exc)
        return ""


def load_project_geometries(
    output_dir: Union[str, Path],
    project_id: str,
    data_dir: Union[str, Path] = "data/projects",
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Load GeoJSON dictionaries for project boundary and reference ring without rasterising.

    Args:
        output_dir: Output base directory.
        project_id: Project identifier.
        data_dir: Data base directory.

    Returns:
        Dict with keys 'boundary' and 'reference_ring', each containing parsed GeoJSON or None.
    """
    out_p = Path(output_dir) / project_id
    data_p = Path(data_dir) / project_id

    boundary_candidates = [
        out_p / "boundary.geojson",
        data_p / "boundary.geojson",
        data_p / "project_boundary.geojson",
        data_p / "imagery" / "project_boundary.geojson",
    ]

    ring_candidates = [
        out_p / "reference_ring.geojson",
        data_p / "imagery" / "reference_ring.geojson",
        data_p / "reference_ring.geojson",
    ]

    boundary_geojson: Optional[Dict[str, Any]] = None
    for cand in boundary_candidates:
        if cand.exists():
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    boundary_geojson = json.load(f)
                break
            except Exception:
                pass

    ring_geojson: Optional[Dict[str, Any]] = None
    for cand in ring_candidates:
        if cand.exists():
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    ring_geojson = json.load(f)
                break
            except Exception:
                pass

    return {
        "boundary": boundary_geojson,
        "reference_ring": ring_geojson,
    }


def load_imagery_qc_data(
    output_dir: Union[str, Path],
    project_id: str,
    data_dir: Union[str, Path] = "data/projects",
) -> Dict[str, Any]:
    """Load imagery quality control funnel and excluded scene records.

    Args:
        output_dir: Output base directory.
        project_id: Project identifier.
        data_dir: Data base directory.

    Returns:
        Dict containing funnel counts and excluded scene list.
    """
    candidates = [
        Path(output_dir) / project_id / "qc_scenes.csv",
        Path(data_dir) / project_id / "imagery" / "qc_scenes.csv",
        Path(data_dir) / project_id / "qc_scenes.csv",
    ]

    qc_csv_path: Optional[Path] = None
    for cand in candidates:
        if cand.exists():
            qc_csv_path = cand
            break

    if not qc_csv_path:
        return {
            "available": False,
            "total_scenes": "not available",
            "pass_scenes": "not available",
            "excluded_scenes": "not available",
            "reasons_breakdown": {},
            "excluded_records": [],
        }

    total = 0
    passed = 0
    excluded_records: List[Dict[str, str]] = []
    reasons_breakdown: Dict[str, int] = {}

    try:
        with open(qc_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total += 1
                is_pass = str(row.get("qc_pass", "")).strip().lower() in ("true", "1")
                if is_pass:
                    passed += 1
                else:
                    reason = str(row.get("qc_reasons", "")).strip() or "unspecified"
                    for r_part in [p.strip() for p in reason.split(";") if p.strip()]:
                        reasons_breakdown[r_part] = reasons_breakdown.get(r_part, 0) + 1
                    excluded_records.append(
                        {
                            "scene_id": row.get("scene_id", "not available"),
                            "date": row.get("date", "not available"),
                            "qc_reasons": reason,
                        }
                    )

        return {
            "available": True,
            "total_scenes": total,
            "pass_scenes": passed,
            "excluded_scenes": total - passed,
            "reasons_breakdown": reasons_breakdown,
            "excluded_records": excluded_records,
        }
    except Exception as exc:
        logger.warning("Failed to parse qc_scenes.csv for project '%s': %s", project_id, exc)
        return {
            "available": False,
            "total_scenes": "not available",
            "pass_scenes": "not available",
            "excluded_scenes": "not available",
            "reasons_breakdown": {},
            "excluded_records": [],
        }


def get_verdict_summary(report_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract verdict status, confidence, reasons, and summary metadata.

    Args:
        report_data: Parsed report.json dictionary.

    Returns:
        Structured verdict dictionary with 'not available' fallbacks for missing keys.
    """
    claims = report_data.get("claims") or {}
    est = report_data.get("estimate") or {}

    status = report_data.get("status") or "not available"
    confidence = report_data.get("confidence") or "not available"
    confidence_reasons = report_data.get("confidence_reasons") or []
    summary_notes = report_data.get("notes") or "not available"
    is_demo = bool(report_data.get("demo", False) or claims.get("demo", False))

    claimed_area = claims.get("claimed_area_ha")
    estate_area = claims.get("estate_area_ha")
    registry = claims.get("registry") or "not available"
    methodology = claims.get("methodology") or "not available"

    obs_low = est.get("planted_area_obs_low")
    obs_central = est.get("planted_area_obs_central")
    obs_high = est.get("planted_area_obs_high")

    shortfall_central = report_data.get("shortfall_central_ha")
    shortfall_low = report_data.get("shortfall_low_ha")
    discrepancy_pct = report_data.get("planted_area_discrepancy_pct")

    return {
        "project_id": report_data.get("project_id", "not available"),
        "status": status,
        "confidence": confidence,
        "confidence_reasons": confidence_reasons,
        "summary": summary_notes,
        "is_demo": is_demo,
        "registry": registry,
        "methodology": methodology,
        "claimed_area_ha": claimed_area if claimed_area is not None else "not available",
        "estate_area_ha": estate_area if estate_area is not None else "not available",
        "obs_low": obs_low if obs_low is not None else "not available",
        "obs_central": obs_central if obs_central is not None else "not available",
        "obs_high": obs_high if obs_high is not None else "not available",
        "shortfall_central_ha": shortfall_central if shortfall_central is not None else "not available",
        "shortfall_low_ha": shortfall_low if shortfall_low is not None else "not available",
        "planted_area_discrepancy_pct": (
            discrepancy_pct if discrepancy_pct is not None else "not available"
        ),
    }


def get_claims_table(
    report_data: Dict[str, Any], extraction_data: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Build normalized claims table with value, source document, page, and evidence quote.

    Args:
        report_data: Parsed report.json dictionary.
        extraction_data: Optional parsed extraction_report.json dictionary.

    Returns:
        List of claim row dictionaries.
    """
    rows: List[Dict[str, Any]] = []
    claims = report_data.get("claims") or {}

    # If extraction report has detailed fields, use them
    if extraction_data and "fields" in extraction_data:
        fields = extraction_data["fields"]
        for key, info in fields.items():
            if not isinstance(info, dict):
                continue
            val = info.get("value")
            src = info.get("source_doc") or "not available"
            pg = info.get("page")
            pg_str = str(pg) if pg is not None else "not available"
            quote = info.get("evidence_quote") or "not available"
            rows.append(
                {
                    "parameter": key,
                    "value": str(val) if val is not None else "not available",
                    "source_doc": src,
                    "page": pg_str,
                    "evidence_quote": quote,
                }
            )
        if rows:
            return rows

    # Fallback: construct from claims object in report.json
    source_pages = claims.get("source_pages") or {}
    evidence_quotes = claims.get("evidence_quotes") or {}

    field_order = [
        ("project_id", "Project ID"),
        ("registry", "Registry"),
        ("methodology", "Methodology"),
        ("claimed_area_ha", "Claimed Area (ha)"),
        ("estate_area_ha", "Estate Area (ha)"),
        ("natural_forest_ha", "Natural Forest Allowance (ha)"),
        ("reporting_period_start", "Reporting Period Start"),
        ("reporting_period_end", "Reporting Period End"),
        ("crediting_period_start", "Crediting Period Start"),
        ("crediting_period_end", "Crediting Period End"),
        ("project_start_date", "Project Start Date"),
        ("credits_issued", "Credits Issued"),
        ("net_ghg_removals_tco2e", "Net GHG Removals (tCO2e)"),
        ("buffer_credits_tco2e", "Buffer Credits (tCO2e)"),
    ]

    for f_key, label in field_order:
        val = claims.get(f_key)
        pg = source_pages.get(f_key)
        quote = evidence_quotes.get(f_key, "not available")
        rows.append(
            {
                "parameter": label,
                "value": str(val) if val is not None else "not available",
                "source_doc": "registry documentation" if pg is not None else "not available",
                "page": str(pg) if pg is not None else "not available",
                "evidence_quote": str(quote) if quote else "not available",
            }
        )

    return rows


def get_area_test_data(report_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract area test data including grid estimates, band, raw sensitivity, and break-even.

    Args:
        report_data: Parsed report.json dictionary.

    Returns:
        Structured area test dictionary.
    """
    claims = report_data.get("claims") or {}
    est = report_data.get("estimate") or {}

    claimed_area = claims.get("claimed_area_ha")
    f_allowance = est.get("forest_allowance_ha") or claims.get("natural_forest_ha")

    obs_low = est.get("planted_area_obs_low")
    obs_central = est.get("planted_area_obs_central")
    obs_high = est.get("planted_area_obs_high")

    grid = est.get("grid_estimates") or {}
    grid_rows: List[Dict[str, Any]] = []

    for t_str, vals in sorted(grid.items(), key=lambda x: float(x[0])):
        if not isinstance(vals, dict):
            continue
        a22 = vals.get("a_2022_ha")
        fa = vals.get("forest_allowance_ha") if vals.get("forest_allowance_ha") is not None else f_allowance
        obs = vals.get("obs_ha")
        sf = round(claimed_area - obs, 2) if (claimed_area is not None and obs is not None) else "not available"
        grid_rows.append(
            {
                "threshold": t_str,
                "a_2022_ha": a22 if a22 is not None else "not available",
                "forest_allowance_ha": fa if fa is not None else "not available",
                "obs_ha": obs if obs is not None else "not available",
                "shortfall_ha": sf,
            }
        )

    norm_sens = est.get("normalization_sensitivity") or {}
    forest_check = est.get("forest_allowance_check") or {}

    return {
        "claimed_area_ha": claimed_area,
        "forest_allowance_ha": f_allowance,
        "obs_low": obs_low,
        "obs_central": obs_central,
        "obs_high": obs_high,
        "grid_rows": grid_rows,
        "normalization_sensitivity": norm_sens if norm_sens else None,
        "forest_allowance_check": forest_check if forest_check else None,
    }


def get_canopy_biomass_data(report_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract canopy-cover and biomass-proxy tables and chart timeseries.

    Args:
        report_data: Parsed report.json dictionary.

    Returns:
        Structured canopy and biomass dictionary.
    """
    est = report_data.get("estimate") or {}
    cb = est.get("canopy_biomass") or {}

    if not cb or not isinstance(cb, dict) or "table" not in cb:
        return {
            "available": False,
            "thresholds": [],
            "years": [],
            "table_rows": [],
            "canopy_change_pct": "not available",
            "biomass_proxy_change_pct": "not available",
            "reference_buffer_change_pct": "not available",
            "chart_data": {},
            "p90_sentence": "not available",
        }

    thresholds: List[str] = cb.get("thresholds", [])
    years: List[str] = cb.get("years", [])
    tbl: Dict[str, Any] = cb.get("table", {})
    bio_by_yr: Dict[str, Any] = cb.get("biomass_proxy_by_year", {})
    ring_medians: Dict[str, Any] = cb.get("reference_buffer_raw_medians", {})
    ranks: Dict[str, Any] = cb.get("p90_ring_ranks", {})

    table_rows: List[Dict[str, Any]] = []
    for y in years:
        row: Dict[str, Any] = {"year": y}
        b_info = bio_by_yr.get(y, {})
        row["mean_ndvi"] = b_info.get("mean", "not available")
        row["p90_ndvi"] = b_info.get("p90", "not available")
        row["raw_ring_median"] = ring_medians.get(y, "not available")
        for t in thresholds:
            cell = tbl.get(t, {}).get(y, {})
            area = cell.get("area_ha")
            share = cell.get("share_pct")
            row[f"t_{t}_area_ha"] = area if area is not None else "not available"
            row[f"t_{t}_share_pct"] = share if share is not None else "not available"
        table_rows.append(row)

    # Note sentence on p90 coincidence if ranks available
    p90_sentence = "not available"
    if len(years) >= 3 and ranks:
        y20 = years[1]
        y21 = years[2]
        p90_v = bio_by_yr.get(y20, {}).get("p90")
        rank_v = ranks.get(y20)
        if p90_v is not None and rank_v is not None:
            p90_sentence = (
                f"The {y20} and {y21} p90 values coincide ({p90_v:.4f}) because the project p90 "
                f"sits at nearly the same rank of the reference ring in both years "
                f"(about the {rank_v:.2f}th percentile, computed from the data); "
                f"this is a coincidence of ranks, not a ceiling."
            )

    return {
        "available": True,
        "thresholds": thresholds,
        "years": years,
        "table_rows": table_rows,
        "canopy_change_pct": cb.get("canopy_change_pct", "not available"),
        "canopy_change_min_pct": cb.get("canopy_change_min_pct", "not available"),
        "canopy_change_max_pct": cb.get("canopy_change_max_pct", "not available"),
        "biomass_proxy_change_pct": cb.get("biomass_proxy_change_pct", "not available"),
        "reference_buffer_change_pct": cb.get("reference_buffer_change_pct", "not available"),
        "table": tbl,
        "biomass_proxy_by_year": bio_by_yr,
        "p90_sentence": p90_sentence,
    }


def load_project_figures(
    output_dir: Union[str, Path],
    project_id: str,
    data_dir: Union[str, Path] = "data/projects",
) -> Dict[str, Optional[Path]]:
    """Locate precomputed figure PNGs for a given project without recomputation.

    Args:
        output_dir: Directory containing project output subfolders.
        project_id: Project identifier.
        data_dir: Base directory for project source data.

    Returns:
        Dict mapping figure keys ('cohort_maps', 'zone_timeseries', 'decline_map')
        to their existing Path on disk, or None if missing.
    """
    out_p = Path(output_dir) / project_id
    data_p = Path(data_dir) / project_id

    keys = ["cohort_maps", "zone_timeseries", "decline_map"]
    result: Dict[str, Optional[Path]] = {}

    for key in keys:
        filename = f"{key}.png"
        candidates = [
            out_p / filename,
            out_p / "figures" / filename,
            data_p / "imagery" / "composites" / filename,
            data_p / filename,
        ]
        found_path: Optional[Path] = None
        for cand in candidates:
            if cand.exists():
                found_path = cand
                break
        result[key] = found_path

    return result
