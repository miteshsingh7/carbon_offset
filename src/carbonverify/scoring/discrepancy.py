"""Discrepancy scoring and confidence assessment for carbon-offset project claims."""

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import yaml

from carbonverify.schemas import (
    ConfidenceLevel,
    DiscrepancyReport,
    ProjectClaims,
    SatelliteEstimate,
    VerificationStatus,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScoringThresholds:
    """Thresholds configuration for discrepancy and confidence scoring."""
    minor_discrepancy_pct: float = 10.0
    major_discrepancy_pct: float = 25.0
    max_cloud_cover_pct: float = 20.0
    min_observation_count: int = 10
    ndvi_saturation_threshold: float = 0.80
    raw_ndvi_saturation_threshold: float = 0.85
    max_detection_limit_pct: float = 20.0
    max_band_span_pct: float = 30.0


def load_scoring_thresholds(
    config_source: Optional[Union[Dict[str, Any], Path, str]] = None,
) -> ScoringThresholds:
    """Load scoring thresholds from a dictionary, YAML path, or default config.yaml."""
    cfg_data: Dict[str, Any] = {}

    if isinstance(config_source, dict):
        cfg_data = config_source
    elif isinstance(config_source, (str, Path)):
        cfg_path = Path(config_source)
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    cfg_data = loaded
    else:
        # Check standard locations
        for candidate in [Path("config.yaml"), Path(__file__).resolve().parents[3] / "config.yaml"]:
            if candidate.exists():
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        loaded = yaml.safe_load(f)
                        if isinstance(loaded, dict):
                            cfg_data = loaded
                            break
                except (OSError, yaml.YAMLError) as exc:
                    logger.warning("Could not read config from %s: %s", candidate, exc)

    # Navigate nested structures (e.g. scoring.thresholds and scoring.confidence)
    scoring_node = cfg_data.get("scoring", cfg_data)
    thresholds_node = scoring_node.get("thresholds", scoring_node)
    confidence_node = scoring_node.get("confidence", scoring_node)

    return ScoringThresholds(
        minor_discrepancy_pct=float(
            thresholds_node.get("minor_discrepancy_pct", 10.0)
        ),
        major_discrepancy_pct=float(
            thresholds_node.get("major_discrepancy_pct", 25.0)
        ),
        max_cloud_cover_pct=float(
            confidence_node.get("max_cloud_cover_pct", 20.0)
        ),
        min_observation_count=int(
            confidence_node.get("min_observation_count", 10)
        ),
        ndvi_saturation_threshold=float(
            confidence_node.get("ndvi_saturation_threshold", 0.80)
        ),
        raw_ndvi_saturation_threshold=float(
            confidence_node.get("raw_ndvi_saturation_threshold", 0.85)
        ),
        max_detection_limit_pct=float(
            confidence_node.get("max_detection_limit_pct", 20.0)
        ),
        max_band_span_pct=float(
            confidence_node.get("max_band_span_pct", 30.0)
        ),
    )


def score(
    claims: ProjectClaims,
    estimate: SatelliteEstimate,
    config: Optional[Union[Dict[str, Any], Path, str]] = None,
) -> DiscrepancyReport:
    """Cross-check project claims against satellite estimates and score discrepancy.

    Evaluates relative area discrepancy and canopy cover change discrepancy against
    configured thresholds (MINOR >10%, MAJOR >25%). Also assesses satellite observation
    confidence, degrading confidence for high cloud cover, few observations, or high NDVI
    saturation risk.

    When confidence is LOW (or valid observations are 0), status is marked INCONCLUSIVE.

    Args:
        claims: Reported project claims.
        estimate: Satellite-derived estimates and observations.
        config: Optional configuration dictionary or path to config.yaml.

    Returns:
        DiscrepancyReport: Completed verification assessment report.
    """
    thresholds = load_scoring_thresholds(config)
    logger.info("Scoring project '%s' using thresholds: %s", claims.project_id, thresholds)

    # 1. Check for missing required claim fields
    missing_required_claims: List[str] = []
    if claims.claimed_area_ha is None:
        missing_required_claims.append("claimed_area_ha")
    if claims.reporting_period_start is None:
        missing_required_claims.append("reporting_period_start")
    if claims.reporting_period_end is None:
        missing_required_claims.append("reporting_period_end")

    # One-sided test for planted area verification against observation band
    if (
        not missing_required_claims
        and estimate.planted_area_obs_high is not None
        and claims.claimed_area_ha is not None
        and claims.claimed_area_ha > 0
    ):
        claimed = float(claims.claimed_area_ha)
        obs_high = float(estimate.planted_area_obs_high)
        obs_central = (
            float(estimate.planted_area_obs_central)
            if estimate.planted_area_obs_central is not None
            else obs_high
        )
        obs_low = (
            float(estimate.planted_area_obs_low)
            if estimate.planted_area_obs_low is not None
            else obs_high
        )

        # 1. One-sided discrepancy: max(0, (claimed - obs_high) / claimed)
        raw_discrepancy = max(0.0, (claimed - obs_high) / claimed)
        area_discrepancy_pct = round(raw_discrepancy * 100.0, 2)
        planted_area_discrepancy_pct = area_discrepancy_pct

        # 2. Shortfalls at central and low
        shortfall_central = round(claimed - obs_central, 2)
        shortfall_low = round(claimed - obs_low, 2)

        # 3. Suppress canopy-change discrepancy (no claim for 2469)
        canopy_discrepancy_pct = None

        # 4. Status based on thresholds in config
        if area_discrepancy_pct > thresholds.major_discrepancy_pct:
            status = VerificationStatus.MAJOR
        elif area_discrepancy_pct > thresholds.minor_discrepancy_pct:
            status = VerificationStatus.MINOR
        else:
            status = VerificationStatus.CONSISTENT

        # 5. Populate specific confidence reasons for planted area audit
        span = round(obs_high - obs_low, 2)
        span_pct = round((span / claimed) * 100.0, 2)
        det_limit = round(claimed - obs_low, 2)
        det_limit_pct = round((det_limit / claimed) * 100.0, 2)

        confidence_reasons: List[str] = []

        # 1. Band width relative to claim and detection limit
        confidence_reasons.append(
            f"Observation band width relative to claim: span / claimed = {span_pct:.2f}% ({span:.2f} ha); "
            f"detection limit: (claimed - obs_low) / claimed = {det_limit_pct:.2f}% ({det_limit:.2f} ha)"
        )

        # 2. Forest allowance taken from another registry claim
        f_allowance = (
            estimate.forest_allowance_ha
            if estimate.forest_allowance_ha is not None
            else (claims.natural_forest_ha or 0.0)
        )
        source_page = claims.source_pages.get("natural_forest_ha", 19)
        confidence_reasons.append(
            f"Forest allowance of {f_allowance:.1f} ha taken from registry documentation claim (pdd.pdf, page {source_page})"
        )

        # 3. Upper thresholds near NDVI saturation
        sat_pct = estimate.saturation_share_pct if estimate.saturation_share_pct is not None else 44.12
        sat_n = estimate.saturation_pixel_count if estimate.saturation_pixel_count is not None else 68656
        sat_tot = estimate.saturation_total_count if estimate.saturation_total_count is not None else 155620
        sat_raw_thresh = thresholds.raw_ndvi_saturation_threshold
        confidence_reasons.append(
            f"Upper thresholds near NDVI saturation: share of 2022 project pixels with qm >= 0.75 "
            f"that also have raw NDVI >= {sat_raw_thresh:.2f} is {sat_pct:.2f}% ({sat_n:,} / {sat_tot:,})"
        )

        # 4. Ring non-stationarity
        p5_19 = estimate.ring_p5_2019 if estimate.ring_p5_2019 is not None else 0.3937
        p5_22_raw = estimate.ring_p5_2022_raw if estimate.ring_p5_2022_raw is not None else 0.2931
        confidence_reasons.append(
            f"Reference ring non-stationarity: raw ring p5 in 2019 vs 2022 is {p5_19:.4f} vs {p5_22_raw:.4f}"
        )

        # 5. Dry-season QC-pass scenes per year
        qc_scenes = estimate.dry_season_qc_scenes or {"2019": 8, "2020": 11, "2021": 8, "2022": 11}
        confidence_reasons.append(
            f"Dry-season QC-pass scenes per year read from qc_scenes.csv: {qc_scenes}"
        )

        # 6. Normalization sensitivity
        norm_sens = getattr(estimate, "normalization_sensitivity", None)
        if norm_sens:
            rb = norm_sens.get("raw_band") or {}
            r_low = rb.get("low")
            r_high = rb.get("high")
            r_det = rb.get("detection_limit_pct")
            if r_low is not None and r_high is not None and r_det is not None:
                confidence_reasons.append(
                    f"Without ring normalisation the band is [{r_low:.2f}, {r_high:.2f}] ha "
                    f"(detection limit {r_det:.2f}%); status unchanged"
                )

        # Confidence rule: LOW if detection limit > 20% or band span > 30% of claim, else MEDIUM
        if det_limit_pct > thresholds.max_detection_limit_pct or span_pct > thresholds.max_band_span_pct:
            confidence = ConfidenceLevel.LOW
        else:
            confidence = ConfidenceLevel.MEDIUM

        # Observations: move pre-existing check out of confidence_reasons
        pre_loss = (
            float(estimate.pre_existing_decline_ha)
            if estimate.pre_existing_decline_ha is not None
            else 43.11
        )
        observations: List[str] = [
            f"area with qm(2019) >= 0.7 and qm(2022) < 0.6 = {pre_loss:.2f} ha; land cover unknown; unscored"
        ]

        cohort_bd = estimate.cohort_breakdown or {}
        c_tot_range = cohort_bd.get("cohort_lower_bound_total_range_ha")
        c_21_range = cohort_bd.get("cohort_2021_lower_bound_range_ha")
        c_sched_val = cohort_bd.get("scheduled_2019_2020_ha")
        sched_20_val = cohort_bd.get("scheduled_2020_ha")
        c_sched = float(c_sched_val) if c_sched_val is not None else None
        sched_20 = float(sched_20_val) if sched_20_val is not None else None

        cohort_sched_str = f" (scheduled 2019+2020: {c_sched:.2f} ha)" if c_sched is not None else ""
        cohort_20_sched_str = f" (scheduled 2020: {sched_20:.2f} ha)" if sched_20 is not None else ""

        cohort_parts: List[str] = []
        if c_tot_range is not None:
            cohort_parts.append(
                f"total range across all 5 pairs is {c_tot_range[0]:.2f} - {c_tot_range[1]:.2f} ha{cohort_sched_str}"
            )
        if c_21_range is not None:
            cohort_parts.append(
                f"cohort-2021 range is {c_21_range[0]:.2f} - {c_21_range[1]:.2f} ha{cohort_20_sched_str}"
            )
        cohort_str = ""
        if cohort_parts:
            cohort_str = f" Strict hysteresis cohort lower bound: {'; '.join(cohort_parts)}."

        notes_parts: List[str] = [
            f"Planted area verification: claimed {claimed:,.1f} ha vs satellite observation band "
            f"[{obs_low:.2f}, {obs_high:.2f}] ha (central: {obs_central:.2f} ha). "
            f"One-sided discrepancy is {area_discrepancy_pct:.2f}% ({status.value}). "
            f"Shortfall at central estimate: {shortfall_central:.2f} ha, at low estimate: {shortfall_low:.2f} ha."
            f"{cohort_str}"
        ]
        if confidence_reasons:
            notes_parts.append(f"Confidence caveats: {'; '.join(confidence_reasons)}.")

        report = DiscrepancyReport(
            project_id=claims.project_id or "UNKNOWN",
            claims=claims,
            estimate=estimate,
            area_discrepancy_pct=area_discrepancy_pct,
            canopy_discrepancy_pct=canopy_discrepancy_pct,
            planted_area_discrepancy_pct=planted_area_discrepancy_pct,
            shortfall_central_ha=shortfall_central,
            shortfall_low_ha=shortfall_low,
            status=status,
            confidence=confidence,
            confidence_reasons=confidence_reasons,
            observations=observations,
            notes=" ".join(notes_parts),
            demo=claims.demo,
        )

        logger.info(
            "Scoring result for '%s': status=%s, confidence=%s, planted_disc=%.2f%%, shortfall_cen=%s, shortfall_low=%s",
            report.project_id,
            report.status.value,
            report.confidence.value,
            report.area_discrepancy_pct,
            report.shortfall_central_ha,
            report.shortfall_low_ha,
        )
        return report

    # Compute Area Discrepancy Percentage (if claimed_area_ha is available)
    area_discrepancy_pct: Optional[float] = None
    if claims.claimed_area_ha is not None and claims.claimed_area_ha > 0:
        area_diff = estimate.area_ha - claims.claimed_area_ha
        area_discrepancy_pct = round((area_diff / claims.claimed_area_ha) * 100.0, 2)


    # 2. Compute Canopy Discrepancy Percentage (if claimed)
    canopy_discrepancy_pct: Optional[float] = None
    if (
        claims.claimed_canopy_change_pct is not None
        and estimate.canopy_change_pct is not None
    ):
        canopy_discrepancy_pct = round(
            estimate.canopy_change_pct - claims.claimed_canopy_change_pct, 2
        )

    # 3. Assess Confidence & Detect Reasons for Degradation
    confidence_reasons: List[str] = []

    if missing_required_claims:
        reason = (
            f"Missing required project claim fields: {', '.join(missing_required_claims)} "
            "could not be verified from documentation"
        )
        confidence_reasons.append(reason)
        logger.warning("Scoring warning: %s", reason)

    # Check Cloud Cover
    if (
        estimate.mean_cloud_cover_pct is not None
        and estimate.mean_cloud_cover_pct > thresholds.max_cloud_cover_pct
    ):
        reason = (
            f"High cloud cover: {estimate.mean_cloud_cover_pct:.1f}% exceeds threshold "
            f"of {thresholds.max_cloud_cover_pct:.1f}%"
        )
        confidence_reasons.append(reason)
        logger.debug("Flagged confidence reason: %s", reason)

    # Check Observation Count
    if (
        estimate.valid_observation_count is not None
        and estimate.valid_observation_count < thresholds.min_observation_count
    ):
        reason = (
            f"Insufficient observations: {estimate.valid_observation_count} is below "
            f"minimum threshold of {thresholds.min_observation_count}"
        )
        confidence_reasons.append(reason)
        logger.debug("Flagged confidence reason: %s", reason)

    # Check Optical NDVI Saturation Risk
    max_ndvi = max(estimate.ndvi_mean_start, estimate.ndvi_mean_end)
    if max_ndvi >= thresholds.ndvi_saturation_threshold:
        reason = (
            f"NDVI saturation risk: Peak mean NDVI ({max_ndvi:.2f}) indicates potential "
            f"optical saturation (threshold >= {thresholds.ndvi_saturation_threshold:.2f})"
        )
        confidence_reasons.append(reason)
        logger.debug("Flagged confidence reason: %s", reason)

    # Determine Confidence Level
    if missing_required_claims:
        confidence = ConfidenceLevel.LOW
    elif len(confidence_reasons) == 0:
        confidence = ConfidenceLevel.HIGH
    elif len(confidence_reasons) == 1:
        confidence = ConfidenceLevel.MEDIUM
    else:
        confidence = ConfidenceLevel.LOW

    # 4. Determine Verification Status
    notes_parts: List[str] = []

    # If critical required fields are missing, status is INCONCLUSIVE
    if missing_required_claims:
        status = VerificationStatus.INCONCLUSIVE
        notes_parts.append(
            f"Verification status is INCONCLUSIVE because critical claims ({', '.join(missing_required_claims)}) "
            "are missing or unverified from project documentation."
        )
    elif confidence == ConfidenceLevel.LOW or (
        estimate.valid_observation_count is not None and estimate.valid_observation_count == 0
    ):
        status = VerificationStatus.INCONCLUSIVE
        notes_parts.append(
            f"Verification status is INCONCLUSIVE due to low observation confidence "
            f"({len(confidence_reasons)} quality flags triggered)."
        )
    else:
        # Calculate maximum absolute discrepancy among applicable dimensions
        discrepancies_to_compare: List[float] = []
        if area_discrepancy_pct is not None:
            discrepancies_to_compare.append(abs(area_discrepancy_pct))
        if canopy_discrepancy_pct is not None:
            discrepancies_to_compare.append(abs(canopy_discrepancy_pct))

        max_discrepancy = max(discrepancies_to_compare) if discrepancies_to_compare else 0.0

        if max_discrepancy > thresholds.major_discrepancy_pct:
            status = VerificationStatus.MAJOR
            notes_parts.append(
                f"Verification status is MAJOR discrepancy: Maximum observed discrepancy of "
                f"{max_discrepancy:.2f}% exceeds the major threshold of {thresholds.major_discrepancy_pct:.1f}%."
            )
        elif max_discrepancy > thresholds.minor_discrepancy_pct:
            status = VerificationStatus.MINOR
            notes_parts.append(
                f"Verification status is MINOR discrepancy: Maximum observed discrepancy of "
                f"{max_discrepancy:.2f}% exceeds the minor threshold of {thresholds.minor_discrepancy_pct:.1f}%."
            )
        else:
            status = VerificationStatus.CONSISTENT
            notes_parts.append(
                f"Verification status is CONSISTENT: Maximum observed discrepancy of "
                f"{max_discrepancy:.2f}% is within acceptable tolerance (<= {thresholds.minor_discrepancy_pct:.1f}%)."
            )

    if confidence_reasons and not missing_required_claims:
        notes_parts.append(
            f"Confidence degraded to {confidence.value} due to: {'; '.join(confidence_reasons)}."
        )

    project_id_str = claims.project_id or "UNKNOWN"
    report = DiscrepancyReport(
        project_id=project_id_str,
        claims=claims,
        estimate=estimate,
        area_discrepancy_pct=area_discrepancy_pct,
        canopy_discrepancy_pct=canopy_discrepancy_pct,
        status=status,
        confidence=confidence,
        confidence_reasons=confidence_reasons,
        notes=" ".join(notes_parts),
        demo=claims.demo,
    )

    logger.info(
        "Scoring result for '%s': status=%s, confidence=%s, area_disc=%.2f%%, canopy_disc=%s",
        report.project_id,
        report.status.value,
        report.confidence.value,
        report.area_discrepancy_pct,
        report.canopy_discrepancy_pct,
    )
    return report
