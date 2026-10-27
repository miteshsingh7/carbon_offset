"""Tests ensuring no project-2469 specific data or strings leak into other projects."""

from datetime import date
from pathlib import Path
import pytest

from carbonverify.report.render import render
from carbonverify.schemas import (
    ConfidenceLevel,
    DiscrepancyReport,
    ProjectClaims,
    Registry,
    SatelliteEstimate,
    VerificationStatus,
)
from carbonverify.scoring.discrepancy import score


HANDOVER_2469_STRINGS = [
    "0.3937",
    "0.2931",
    "1,300",
    "541",
    "1,265.00",
    "956.0",
    "310.0",
]

FORBIDDEN_FINDING_STRINGS = [
    "depressed",
    "elevated",
    "ring land use changed",
    "four components",
    "Table 5",
    "stationary apart from",
]


@pytest.mark.parametrize("n_components,components_gt_5ha", [
    (0, []),
    (2, [14.25, 7.80]),
])
def test_no_project_2469_leakage_in_rendered_report(
    tmp_path: Path,
    n_components: int,
    components_gt_5ha: list,
) -> None:
    """Build a synthetic project differing completely from 2469 and verify no leakage."""
    proj_dir = tmp_path / f"proj_test_c{n_components}"
    proj_dir.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / f"out_test_c{n_components}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Claims differing from 2469 (claimed area = 750.0 ha, natural forest = 120.0 ha)
    claims = ProjectClaims(
        project_id=f"TEST-VCS-999{n_components}",
        registry=Registry.VERRA,
        methodology="VM0007",
        claimed_area_ha=750.0,
        natural_forest_ha=120.0,
        reporting_period_start=date(2020, 1, 1),
        reporting_period_end=date(2023, 12, 31),
        source_pages={"claimed_area_ha": 5, "natural_forest_ha": 12},
    )

    # Satellite estimate differing completely from 2469:
    # No scheduled plantings, no ring p5 values, different year counts, different component list
    sat_est = SatelliteEstimate(
        area_ha=1100.0,
        ndvi_mean_start=0.55,
        ndvi_mean_end=0.72,
        canopy_change_pct=12.0,
        biomass_proxy_change_pct=10.5,
        reference_buffer_change_pct=-0.1,
        valid_observation_count=35,
        mean_cloud_cover_pct=8.5,
        planted_area_obs_low=620.0,
        planted_area_obs_central=710.0,
        planted_area_obs_high=810.0,
        forest_allowance_ha=120.0,
        grid_estimates={
            "0.6": {"a_2022_ha": 930.0, "forest_allowance_ha": 120.0, "obs_ha": 810.0},
            "0.65": {"a_2022_ha": 880.0, "forest_allowance_ha": 120.0, "obs_ha": 760.0},
            "0.7": {"a_2022_ha": 830.0, "forest_allowance_ha": 120.0, "obs_ha": 710.0},
            "0.75": {"a_2022_ha": 740.0, "forest_allowance_ha": 120.0, "obs_ha": 620.0},
        },
        cohort_breakdown={
            "cohort_lower_bound_total_range_ha": [250.0, 480.0],
            "cohort_2021_lower_bound_range_ha": [90.0, 160.0],
            "label": "lower bound",
            "scheduled_2019_2020_ha": None,
            "scheduled_2020_ha": None,
        },
        pre_existing_decline_ha=18.5,
        saturation_share_pct=15.0,
        saturation_pixel_count=1500,
        saturation_total_count=10000,
        ring_p5_2019=None,
        ring_p5_2022_raw=None,
        ring_p5_2022_qm=None,
        dry_season_qc_scenes={"2020": 4, "2021": 7, "2022": 6},
        decline_analysis={
            "decline_set_d": {
                "area_ha": 18.5,
                "first_high_split": {"2020": 10.0, "2021": 8.5},
                "moderate_decline_60_70_ha": 12.0,
                "components": {
                    "count": 3,
                    "share_lt_1ha_pct": 20.0,
                    "share_1_to_5ha_pct": 30.0,
                    "share_gt_5ha_pct": 50.0,
                    "largest_component_ha": 9.25,
                    "largest_component_raw_means": {"2020": 0.52, "2021": 0.61, "2022": 0.58},
                },
            },
            "g22_cohort": {
                "area_ha": 85.0,
                "components": {
                    "share_gt_5ha_pct": 60.0 if n_components > 0 else 0.0,
                    "share_lt_1ha_pct": 40.0 if n_components > 0 else 100.0,
                    "components_gt_5ha": components_gt_5ha,
                    "largest_component_raw_means": {"2019": 0.45, "2020": 0.50, "2022": 0.76},
                },
            },
            "sensitivity_t70_excl_g22": {
                "observed_area_excl_g22_ha": 625.0,
                "a_2022_ha": 830.0,
                "g22_area_ha": 85.0,
            },
            "strict_2022_cohort": {
                "area_ha": 45.0,
                "share_lt_1ha_pct": 55.0,
            },
            "endpoint_gain_mask_ha": 520.0,
            "latest_planting_year": 2021,
        },
    )

    report = score(claims=claims, estimate=sat_est)

    # Render report without raising
    json_path, html_path = render(report=report, out_dir=out_dir)

    assert json_path.exists()
    assert html_path.exists()

    json_text = json_path.read_text(encoding="utf-8")
    html_text = html_path.read_text(encoding="utf-8")

    combined_text = json_text + "\n" + html_text

    # 1. Must not contain any forbidden fixed finding strings
    for s in FORBIDDEN_FINDING_STRINGS:
        assert s not in combined_text, f"Forbidden string '{s}' leaked into rendered output for n_components={n_components}"

    # 2. Must not contain any project 2469 handover values
    for val in HANDOVER_2469_STRINGS:
        assert val not in combined_text, f"Project 2469 handover value '{val}' leaked into rendered output for n_components={n_components}"
