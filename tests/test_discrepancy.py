"""Unit tests for carbonverify discrepancy and confidence scoring."""

from datetime import date
from pathlib import Path
import pytest

from carbonverify.schemas import (
    ConfidenceLevel,
    ProjectClaims,
    Registry,
    SatelliteEstimate,
    VerificationStatus,
)
from carbonverify.scoring.discrepancy import (
    ScoringThresholds,
    load_scoring_thresholds,
    score,
)


@pytest.fixture
def base_claims() -> ProjectClaims:
    """Fixture providing standard valid project claims."""
    return ProjectClaims(
        project_id="TEST-VCS-001",
        registry=Registry.VERRA,
        methodology="VM0007",
        claimed_area_ha=10000.0,
        reporting_period_start=date(2020, 1, 1),
        reporting_period_end=date(2023, 12, 31),
        claimed_canopy_change_pct=5.0,
        credits_issued=100000,
        boundary_path="data/projects/demo/boundary.geojson",
        source_pages={"project_id": 1, "claimed_area_ha": 3},
    )


@pytest.fixture
def base_estimate() -> SatelliteEstimate:
    """Fixture providing high-quality baseline satellite estimate."""
    return SatelliteEstimate(
        area_ha=10000.0,
        ndvi_mean_start=0.65,
        ndvi_mean_end=0.68,
        canopy_change_pct=5.0,
        biomass_proxy_change_pct=4.8,
        reference_buffer_change_pct=-0.2,
        valid_observation_count=20,
        mean_cloud_cover_pct=10.0,
    )


class TestVerificationStatus:
    """Tests covering all 4 verification statuses: CONSISTENT, MINOR, MAJOR, INCONCLUSIVE."""

    def test_status_consistent(self, base_claims: ProjectClaims, base_estimate: SatelliteEstimate) -> None:
        """Test status CONSISTENT when area & canopy discrepancy are within 10%."""
        # 10,200 ha vs 10,000 ha -> +2.0% area discrepancy
        # 4.5% vs 5.0% -> -0.5% canopy discrepancy
        estimate = base_estimate.model_copy(
            update={"area_ha": 10200.0, "canopy_change_pct": 4.5}
        )
        report = score(base_claims, estimate)

        assert report.status == VerificationStatus.CONSISTENT
        assert report.confidence == ConfidenceLevel.HIGH
        assert report.area_discrepancy_pct == 2.0
        assert report.canopy_discrepancy_pct == -0.5
        assert len(report.confidence_reasons) == 0
        assert "CONSISTENT" in report.notes

    def test_status_minor_discrepancy(self, base_claims: ProjectClaims, base_estimate: SatelliteEstimate) -> None:
        """Test status MINOR when discrepancy is > 10% and <= 25%."""
        # 8,700 ha vs 10,000 ha -> -13.0% area discrepancy (between 10% and 25%)
        estimate = base_estimate.model_copy(update={"area_ha": 8700.0})
        report = score(base_claims, estimate)

        assert report.status == VerificationStatus.MINOR
        assert report.confidence == ConfidenceLevel.HIGH
        assert report.area_discrepancy_pct == -13.0
        assert "MINOR" in report.notes

    def test_status_minor_via_canopy_discrepancy(
        self, base_claims: ProjectClaims, base_estimate: SatelliteEstimate
    ) -> None:
        """Test status MINOR triggered by canopy change discrepancy > 10%."""
        # Claimed canopy +5.0%, observed -6.5% -> discrepancy -11.5%
        estimate = base_estimate.model_copy(update={"canopy_change_pct": -6.5})
        report = score(base_claims, estimate)

        assert report.status == VerificationStatus.MINOR
        assert report.canopy_discrepancy_pct == -11.5

    def test_status_major_discrepancy_area(
        self, base_claims: ProjectClaims, base_estimate: SatelliteEstimate
    ) -> None:
        """Test status MAJOR when area discrepancy exceeds 25%."""
        # 6,800 ha vs 10,000 ha -> -32.0% area discrepancy (> 25%)
        estimate = base_estimate.model_copy(update={"area_ha": 6800.0})
        report = score(base_claims, estimate)

        assert report.status == VerificationStatus.MAJOR
        assert report.area_discrepancy_pct == -32.0
        assert "MAJOR" in report.notes

    def test_status_major_discrepancy_canopy(
        self, base_claims: ProjectClaims, base_estimate: SatelliteEstimate
    ) -> None:
        """Test status MAJOR when canopy change discrepancy exceeds 25%."""
        # Claimed canopy +5.0%, observed -22.0% -> discrepancy -27.0%
        estimate = base_estimate.model_copy(update={"canopy_change_pct": -22.0})
        report = score(base_claims, estimate)

        assert report.status == VerificationStatus.MAJOR
        assert report.canopy_discrepancy_pct == -27.0

    def test_status_inconclusive_due_to_low_confidence(
        self, base_claims: ProjectClaims, base_estimate: SatelliteEstimate
    ) -> None:
        """Test status INCONCLUSIVE when observation confidence is LOW."""
        # High cloud cover (35% > 20%) AND low observations (4 < 10) -> LOW confidence
        estimate = base_estimate.model_copy(
            update={
                "mean_cloud_cover_pct": 35.0,
                "valid_observation_count": 4,
            }
        )
        report = score(base_claims, estimate)

        assert report.status == VerificationStatus.INCONCLUSIVE
        assert report.confidence == ConfidenceLevel.LOW
        assert len(report.confidence_reasons) == 2
        assert "INCONCLUSIVE" in report.notes

    def test_status_inconclusive_zero_observations(
        self, base_claims: ProjectClaims, base_estimate: SatelliteEstimate
    ) -> None:
        """Test status INCONCLUSIVE when zero valid observations are available."""
        estimate = base_estimate.model_copy(update={"valid_observation_count": 0})
        report = score(base_claims, estimate)

        assert report.status == VerificationStatus.INCONCLUSIVE


class TestConfidenceReasons:
    """Tests covering all satellite observation confidence degradation reasons."""

    def test_high_cloud_cover_reason(
        self, base_claims: ProjectClaims, base_estimate: SatelliteEstimate
    ) -> None:
        """Test confidence degradation due to cloud cover exceeding threshold."""
        estimate = base_estimate.model_copy(update={"mean_cloud_cover_pct": 28.5})
        report = score(base_claims, estimate)

        assert report.confidence == ConfidenceLevel.MEDIUM
        assert len(report.confidence_reasons) == 1
        assert "cloud cover" in report.confidence_reasons[0].lower()
        assert "28.5%" in report.confidence_reasons[0]

    def test_few_observations_reason(
        self, base_claims: ProjectClaims, base_estimate: SatelliteEstimate
    ) -> None:
        """Test confidence degradation due to insufficient observation count."""
        estimate = base_estimate.model_copy(update={"valid_observation_count": 5})
        report = score(base_claims, estimate)

        assert report.confidence == ConfidenceLevel.MEDIUM
        assert len(report.confidence_reasons) == 1
        assert "insufficient observations" in report.confidence_reasons[0].lower()
        assert "5" in report.confidence_reasons[0]

    def test_ndvi_saturation_reason(
        self, base_claims: ProjectClaims, base_estimate: SatelliteEstimate
    ) -> None:
        """Test confidence degradation due to NDVI optical saturation risk."""
        estimate = base_estimate.model_copy(
            update={"ndvi_mean_start": 0.85, "ndvi_mean_end": 0.86}
        )
        report = score(base_claims, estimate)

        assert report.confidence == ConfidenceLevel.MEDIUM
        assert len(report.confidence_reasons) == 1
        assert "saturation" in report.confidence_reasons[0].lower()
        assert "0.86" in report.confidence_reasons[0]

    def test_all_confidence_reasons_combined(
        self, base_claims: ProjectClaims, base_estimate: SatelliteEstimate
    ) -> None:
        """Test all three degradation reasons triggered simultaneously."""
        estimate = base_estimate.model_copy(
            update={
                "mean_cloud_cover_pct": 40.0,
                "valid_observation_count": 3,
                "ndvi_mean_start": 0.82,
            }
        )
        report = score(base_claims, estimate)

        assert report.confidence == ConfidenceLevel.LOW
        assert len(report.confidence_reasons) == 3
        # Check presence of each distinct reason
        reason_text = " ".join(report.confidence_reasons).lower()
        assert "cloud cover" in reason_text
        assert "insufficient observations" in reason_text
        assert "saturation" in reason_text
        assert report.status == VerificationStatus.INCONCLUSIVE


class TestScoringEdgeCasesAndConfig:
    """Tests covering custom configurations, edge values, and optional fields."""

    def test_optional_canopy_change_unclaimed(
        self, base_claims: ProjectClaims, base_estimate: SatelliteEstimate
    ) -> None:
        """Test scoring when project did not report canopy change percentage."""
        claims = base_claims.model_copy(update={"claimed_canopy_change_pct": None})
        report = score(claims, base_estimate)

        assert report.canopy_discrepancy_pct is None
        assert report.area_discrepancy_pct == 0.0
        assert report.status == VerificationStatus.CONSISTENT

    def test_custom_thresholds_override(
        self, base_claims: ProjectClaims, base_estimate: SatelliteEstimate
    ) -> None:
        """Test scoring with custom tighter thresholds."""
        custom_config = {
            "scoring": {
                "thresholds": {
                    "minor_discrepancy_pct": 5.0,
                    "major_discrepancy_pct": 12.0,
                },
                "confidence": {
                    "max_cloud_cover_pct": 15.0,
                    "min_observation_count": 25,
                    "ndvi_saturation_threshold": 0.70,
                },
            }
        }
        # Area discrepancy = +7.0%
        # Under default thresholds (10%), 7% is CONSISTENT
        # Under custom thresholds (minor=5%), 7% is MINOR
        estimate = base_estimate.model_copy(update={"area_ha": 10700.0})
        report = score(base_claims, estimate, config=custom_config)

        assert report.status == VerificationStatus.MINOR
        assert report.area_discrepancy_pct == 7.0

    def test_load_scoring_thresholds_defaults(self) -> None:
        """Test default fallback thresholds."""
        thresholds = load_scoring_thresholds({})
        assert thresholds.minor_discrepancy_pct == 10.0
        assert thresholds.major_discrepancy_pct == 25.0
        assert thresholds.max_cloud_cover_pct == 20.0
        assert thresholds.min_observation_count == 10
        assert thresholds.ndvi_saturation_threshold == 0.80


class TestPlantedAreaOneSidedRule:
    """Unit tests for the one-sided planted area discrepancy verification rule."""

    @pytest.fixture
    def planted_claims(self, base_claims: ProjectClaims) -> ProjectClaims:
        """Project claims representing 1,300 ha plantation project."""
        return base_claims.model_copy(
            update={
                "project_id": "2469",
                "claimed_area_ha": 1300.0,
                "claimed_canopy_change_pct": None,
            }
        )

    @pytest.fixture
    def planted_estimate(self, base_estimate: SatelliteEstimate) -> SatelliteEstimate:
        """Satellite estimate with observation band for project 2469."""
        return base_estimate.model_copy(
            update={
                "area_ha": 2311.99,
                "planted_area_obs_low": 1015.20,
                "planted_area_obs_central": 1265.00,
                "planted_area_obs_high": 1505.62,
                "forest_allowance_ha": 541.0,
                "cohort_breakdown": {
                    "cohort_lower_bound_total_range_ha": [430.58, 732.66],
                    "cohort_2021_lower_bound_range_ha": [144.04, 222.63],
                    "label": "lower bound",
                    "scheduled_2019_2020_ha": 956.0,
                    "scheduled_2020_ha": 310.0,
                },
                "pre_existing_decline_ha": 43.11,
            }
        )

    def test_obs_high_ge_claim_is_consistent(
        self, planted_claims: ProjectClaims, planted_estimate: SatelliteEstimate
    ) -> None:
        """Test obs_high >= claim results in 0% discrepancy and CONSISTENT status."""
        # 1505.62 >= 1300.0 -> discrepancy = 0.0% -> CONSISTENT
        report = score(planted_claims, planted_estimate)

        assert report.status == VerificationStatus.CONSISTENT
        assert report.area_discrepancy_pct == 0.0
        assert report.planted_area_discrepancy_pct == 0.0
        assert report.canopy_discrepancy_pct is None

    def test_obs_high_15_pct_below_is_minor(
        self, planted_claims: ProjectClaims, planted_estimate: SatelliteEstimate
    ) -> None:
        """Test obs_high 15% below claimed area triggers MINOR discrepancy."""
        # Claimed: 1300.0 ha. 15% below -> obs_high = 1300 * 0.85 = 1105.0 ha
        estimate = planted_estimate.model_copy(update={"planted_area_obs_high": 1105.0})
        report = score(planted_claims, estimate)

        assert report.status == VerificationStatus.MINOR
        assert report.area_discrepancy_pct == 15.0
        assert report.planted_area_discrepancy_pct == 15.0

    def test_obs_high_30_pct_below_is_major(
        self, planted_claims: ProjectClaims, planted_estimate: SatelliteEstimate
    ) -> None:
        """Test obs_high 30% below claimed area triggers MAJOR discrepancy."""
        # Claimed: 1300.0 ha. 30% below -> obs_high = 1300 * 0.70 = 910.0 ha
        estimate = planted_estimate.model_copy(update={"planted_area_obs_high": 910.0})
        report = score(planted_claims, estimate)

        assert report.status == VerificationStatus.MAJOR
        assert report.area_discrepancy_pct == 30.0
        assert report.planted_area_discrepancy_pct == 30.0

    def test_shortfall_calculation(
        self, planted_claims: ProjectClaims, planted_estimate: SatelliteEstimate
    ) -> None:
        """Test shortfall calculation at central and low estimates."""
        # Claimed 1300 ha vs central 1265.0 ha -> 35.0 ha
        # Claimed 1300 ha vs low 1015.2 ha -> 284.8 ha
        report = score(planted_claims, planted_estimate)

        assert report.shortfall_central_ha == 35.0
        assert report.shortfall_low_ha == 284.8

    def test_confidence_reasons_populated(
        self, planted_claims: ProjectClaims, planted_estimate: SatelliteEstimate
    ) -> None:
        """Test all 5 specific confidence reasons, observations, and confidence rules."""
        report = score(planted_claims, planted_estimate)

        assert len(report.confidence_reasons) == 5
        text = " ".join(report.confidence_reasons)
        assert "490.42 ha" in text  # band span (1505.62 - 1015.20)
        assert "37.72%" in text     # span / claimed
        assert "284.80 ha" in text  # detection limit (1300.0 - 1015.20)
        assert "21.91%" in text     # detection limit / claimed
        assert "541.0 ha" in text   # forest allowance
        assert "44.12%" in text     # saturation share
        assert "raw ring p5 in 2019 vs 2022 is 0.3937 vs 0.2931" in text
        assert "qc_scenes.csv" in text

        # Test observations contains unscored pre-existing check
        assert len(report.observations) == 1
        assert "area with qm(2019) >= 0.7 and qm(2022) < 0.6 = 43.11 ha; land cover unknown; unscored" in report.observations[0]
        assert "forest loss" not in report.observations[0].lower()

        # Confidence rule: det_limit > 20% or span > 30% -> LOW
        assert report.confidence == ConfidenceLevel.LOW
        assert report.status == VerificationStatus.CONSISTENT

    def test_confidence_rule_detection_limit_greater_than_20_pct_gives_low(
        self, planted_claims: ProjectClaims, planted_estimate: SatelliteEstimate
    ) -> None:
        """Verify detection limit > 20% of claim gives confidence LOW."""
        # Claimed: 1300 ha.
        # Detection limit = (claimed - obs_low) / claimed
        # For obs_low = 1000 ha: det_limit = (1300 - 1000) / 1300 = 23.08% > 20%
        # Band span: obs_high - obs_low = 1200 - 1000 = 200 ha -> 15.38% <= 30%
        estimate = planted_estimate.model_copy(
            update={
                "planted_area_obs_low": 1000.0,
                "planted_area_obs_high": 1200.0,
                "planted_area_obs_central": 1100.0,
            }
        )
        report = score(planted_claims, estimate)
        assert report.confidence == ConfidenceLevel.LOW

    def test_confidence_rule_detection_limit_le_20_and_span_le_30_gives_medium(
        self, planted_claims: ProjectClaims, planted_estimate: SatelliteEstimate
    ) -> None:
        """Verify detection limit <= 20% and band span <= 30% gives confidence MEDIUM."""
        # Claimed: 1300 ha.
        # For obs_low = 1100 ha: det_limit = (1300 - 1100) / 1300 = 15.38% <= 20%
        # For obs_high = 1400 ha: span = 1400 - 1100 = 300 ha -> 23.08% <= 30%
        estimate = planted_estimate.model_copy(
            update={
                "planted_area_obs_low": 1100.0,
                "planted_area_obs_high": 1400.0,
                "planted_area_obs_central": 1250.0,
            }
        )
        report = score(planted_claims, estimate)
        assert report.confidence == ConfidenceLevel.MEDIUM

    def test_project_2469_canopy_discrepancy_stays_null_and_status_confidence_unchanged(
        self, planted_claims: ProjectClaims, planted_estimate: SatelliteEstimate
    ) -> None:
        """Verify that with canopy_biomass outputs present and no canopy claim, canopy_discrepancy_pct is null and status/confidence unchanged."""
        estimate = planted_estimate.model_copy(
            update={
                "canopy_change_pct": 94.35,
                "biomass_proxy_change_pct": 24.83,
                "reference_buffer_change_pct": 8.87,
            }
        )
        report = score(planted_claims, estimate)
        assert report.canopy_discrepancy_pct is None
        assert report.status == VerificationStatus.CONSISTENT
        assert report.confidence == ConfidenceLevel.LOW

