"""End-to-end verification pipeline chaining all carbonverify steps."""

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union

from carbonverify.analysis.estimate import estimate_change
from carbonverify.claims.extractor import extract_claims
from carbonverify.imagery.fetch import fetch_timeseries
from carbonverify.report.render import render
from carbonverify.schemas import DiscrepancyReport, SatelliteEstimate, VerificationStatus
from carbonverify.scoring.discrepancy import score

logger = logging.getLogger(__name__)


def run(
    project_dir: Union[str, Path],
    out_dir: Optional[Union[str, Path]] = None,
    config: Optional[Union[Dict[str, Any], Path, str]] = None,
) -> DiscrepancyReport:
    """Execute end-to-end carbon offset verification pipeline on a project directory.

    Pipeline steps:
    1. Extract project claims from project documentation / claims.json with anti-hallucination validation.
    2. Check for required claims: if claimed_area_ha or reporting period is missing, mark INCONCLUSIVE without crashing.
    3. Fetch satellite imagery timeseries over project boundary.
    4. Estimate satellite-observed canopy and NDVI change metrics.
    5. Cross-check claims vs estimates to score discrepancy and assess confidence.
    6. Render structured audit reports (report.json, report.html, and extraction_report.json).

    Args:
        project_dir: Directory containing project boundary and claims.
        out_dir: Directory to save generated reports (defaults to output/<project_id_or_name>).
        config: Optional configuration dictionary or path to config.yaml.

    Returns:
        DiscrepancyReport: Completed verification report.
    """
    proj_path = Path(project_dir).resolve()
    if not proj_path.exists():
        raise FileNotFoundError(f"Project path does not exist: {proj_path}")

    # Determine destination output directory early
    if out_dir is None:
        target_name = proj_path.name if proj_path.is_dir() else "unnamed_project"
        resolved_out_dir = Path("output") / target_name
    else:
        resolved_out_dir = Path(out_dir).resolve()

    resolved_out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Starting carbonverify pipeline for: %s (output: %s)", proj_path, resolved_out_dir)

    # 1. Claims extraction
    claims = extract_claims(proj_path, config=config, out_dir=resolved_out_dir)

    # 2. Check for missing critical claim fields
    is_critical_missing = (
        claims.claimed_area_ha is None
        or claims.reporting_period_start is None
        or claims.reporting_period_end is None
    )

    if is_critical_missing:
        logger.warning(
            "Project '%s' is missing critical claim fields (area=%s, start=%s, end=%s). "
            "Flagging status as INCONCLUSIVE without crashing.",
            claims.project_id,
            claims.claimed_area_ha,
            claims.reporting_period_start,
            claims.reporting_period_end,
        )
        # Create minimal placeholder estimate for scoring
        placeholder_estimate = SatelliteEstimate(
            area_ha=0.1,
            ndvi_mean_start=0.0,
            ndvi_mean_end=0.0,
            canopy_change_pct=0.0,
            biomass_proxy_change_pct=0.0,
            reference_buffer_change_pct=0.0,
            valid_observation_count=0,
            mean_cloud_cover_pct=0.0,
        )
        report = score(claims=claims, estimate=placeholder_estimate, config=config)
        render(report=report, out_dir=resolved_out_dir)
        return report

    # 3. Resolve boundary path
    boundary_path_str = claims.boundary_path or str(proj_path / "boundary.geojson")
    boundary_path = Path(boundary_path_str)
    if not boundary_path.exists():
        candidate = proj_path / boundary_path.name
        if candidate.exists():
            boundary_path = candidate
        else:
            candidate_geojson = proj_path / "boundary.geojson"
            if candidate_geojson.exists():
                boundary_path = candidate_geojson

    if not boundary_path.exists():
        raise FileNotFoundError(
            f"Could not resolve boundary file '{boundary_path_str}' for project directory '{proj_path}'"
        )

    # 4. Fetch satellite timeseries
    timeseries = fetch_timeseries(
        boundary_path=boundary_path,
        start=claims.reporting_period_start,
        end=claims.reporting_period_end,
    )

    # 5. Estimate change from satellite observations
    estimate = estimate_change(timeseries=timeseries, boundary=boundary_path, claims=claims)

    # 6. Score discrepancy and confidence
    report = score(claims=claims, estimate=estimate, config=config)

    # 6b. Generate publication figures if composites and QC data exist
    try:
        from carbonverify.analysis.figures import (
            generate_cohort_maps_figure,
            generate_decline_map_figure,
            generate_zone_timeseries_figure,
        )

        comp_dir = proj_path / "imagery" / "composites"
        qc_csv = proj_path / "imagery" / "qc_scenes.csv"
        if comp_dir.exists() and (comp_dir / "ndvi_qm_2019.tif").exists():
            if qc_csv.exists():
                generate_zone_timeseries_figure(
                    qc_csv_path=qc_csv,
                    output_png_path=comp_dir / "zone_timeseries.png",
                    reporting_period_start=(
                        str(claims.reporting_period_start)
                        if claims.reporting_period_start
                        else None
                    ),
                    reporting_period_end=(
                        str(claims.reporting_period_end)
                        if claims.reporting_period_end
                        else None
                    ),
                    project_id=str(claims.project_id),
                )
            generate_decline_map_figure(
                project_dir=proj_path,
                output_png_path=comp_dir / "decline_map.png",
            )
            cohort_fig = comp_dir / "cohort_maps.png"
            if not cohort_fig.exists():
                generate_cohort_maps_figure(
                    project_dir=proj_path,
                    output_png_path=cohort_fig,
                )
    except Exception as exc:
        logger.warning("Automatic figure generation skipped: %s", exc)

    # 7. Render reports
    json_path, html_path = render(report=report, out_dir=resolved_out_dir)
    logger.info("Pipeline completed successfully. Artifacts rendered to %s", resolved_out_dir)

    return report
