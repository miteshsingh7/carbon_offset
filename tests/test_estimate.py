"""Tests for zone-level quality control gate and dry-season DiD estimation."""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from carbonverify.analysis.estimate import (
    dry_season_estimate,
    plantation_area_estimate,
    qc_scenes,
)



class TestSceneQCGate:
    """Unit tests for qc_scenes evaluation rules on synthetic DataFrames."""

    def test_offset_unresolved_rule(self) -> None:
        """Verify offset_unresolved flags ambiguous offset or offset=-0.1 with baseline < 04.00."""
        synthetic_rows = [
            {
                "scene_id": "s_ambiguous",
                "date": "2020-06-01",
                "baseline": "04.00",
                "detected_offset": None,
                "offset_flag": "ambiguous",
                "red_p1_dn": 150.0,
                "proj_valid_fraction": 0.8,
                "ring_valid_fraction": 0.8,
                "proj_ndvi_median": 0.75,
                "ring_ndvi_median": 0.65,
                "proj_ndvi_p90": 0.85,
                "ring_ndvi_p90": 0.75,
            },
            {
                "scene_id": "s_invalid_neg_offset",
                "date": "2020-06-05",
                "baseline": "02.13",
                "detected_offset": -0.1,
                "offset_flag": "present",
                "red_p1_dn": 1000.0,
                "proj_valid_fraction": 0.8,
                "ring_valid_fraction": 0.8,
                "proj_ndvi_median": 0.75,
                "ring_ndvi_median": 0.65,
                "proj_ndvi_p90": 0.85,
                "ring_ndvi_p90": 0.75,
            },
            {
                "scene_id": "s_valid_neg_offset",
                "date": "2020-06-10",
                "baseline": "04.00",
                "detected_offset": -0.1,
                "offset_flag": "present",
                "red_p1_dn": 1200.0,
                "proj_valid_fraction": 0.8,
                "ring_valid_fraction": 0.8,
                "proj_ndvi_median": 0.75,
                "ring_ndvi_median": 0.65,
                "proj_ndvi_p90": 0.85,
                "ring_ndvi_p90": 0.75,
            },
            {
                "scene_id": "s_valid_zero_offset",
                "date": "2020-06-15",
                "baseline": "02.13",
                "detected_offset": 0.0,
                "offset_flag": "absent",
                "red_p1_dn": 200.0,
                "proj_valid_fraction": 0.8,
                "ring_valid_fraction": 0.8,
                "proj_ndvi_median": 0.75,
                "ring_ndvi_median": 0.65,
                "proj_ndvi_p90": 0.85,
                "ring_ndvi_p90": 0.75,
            },
            {
                "scene_id": "s_unresolved_haze",
                "date": "2020-06-20",
                "baseline": "05.00",
                "detected_offset": -0.1,
                "offset_flag": "present",
                "red_p1_dn": 998.0,
                "proj_valid_fraction": 0.8,
                "ring_valid_fraction": 0.8,
                "proj_ndvi_median": 0.75,
                "ring_ndvi_median": 0.65,
                "proj_ndvi_p90": 0.85,
                "ring_ndvi_p90": 0.75,
            },
        ]
        df = pd.DataFrame(synthetic_rows)
        qc_df = qc_scenes(df)

        res_map = qc_df.set_index("scene_id")["qc_reasons"].to_dict()
        assert "offset_unresolved" in res_map["s_ambiguous"]
        assert "offset_unresolved" in res_map["s_invalid_neg_offset"]
        assert "offset_unresolved" in res_map["s_unresolved_haze"]
        assert "offset_unresolved" not in res_map["s_valid_neg_offset"]
        assert "offset_unresolved" not in res_map["s_valid_zero_offset"]

    def test_bad_red_and_low_valid_rules(self) -> None:
        """Verify bad_red (p1 < 50) and low_valid (vf < 0.5) exclusion rules."""
        synthetic_rows = [
            {
                "scene_id": "s_bad_red",
                "date": "2020-07-01",
                "baseline": "04.00",
                "detected_offset": 0.0,
                "offset_flag": "absent",
                "red_p1_dn": 25.0,  # Bad red (< 50)
                "proj_valid_fraction": 0.9,
                "ring_valid_fraction": 0.9,
                "proj_ndvi_median": 0.70,
                "ring_ndvi_median": 0.60,
                "proj_ndvi_p90": 0.80,
                "ring_ndvi_p90": 0.70,
            },
            {
                "scene_id": "s_low_valid_project",
                "date": "2020-07-05",
                "baseline": "04.00",
                "detected_offset": 0.0,
                "offset_flag": "absent",
                "red_p1_dn": 150.0,
                "proj_valid_fraction": 0.35,  # Low valid (< 0.5)
                "ring_valid_fraction": 0.9,
                "proj_ndvi_median": 0.70,
                "ring_ndvi_median": 0.60,
                "proj_ndvi_p90": 0.80,
                "ring_ndvi_p90": 0.70,
            },
            {
                "scene_id": "s_low_valid_ring",
                "date": "2020-07-10",
                "baseline": "04.00",
                "detected_offset": 0.0,
                "offset_flag": "absent",
                "red_p1_dn": 150.0,
                "proj_valid_fraction": 0.9,
                "ring_valid_fraction": 0.45,  # Low valid (< 0.5)
                "proj_ndvi_median": 0.70,
                "ring_ndvi_median": 0.60,
                "proj_ndvi_p90": 0.80,
                "ring_ndvi_p90": 0.70,
            },
            {
                "scene_id": "s_clean",
                "date": "2020-07-15",
                "baseline": "04.00",
                "detected_offset": 0.0,
                "offset_flag": "absent",
                "red_p1_dn": 150.0,
                "proj_valid_fraction": 0.9,
                "ring_valid_fraction": 0.9,
                "proj_ndvi_median": 0.70,
                "ring_ndvi_median": 0.60,
                "proj_ndvi_p90": 0.80,
                "ring_ndvi_p90": 0.70,
            },
        ]
        df = pd.DataFrame(synthetic_rows)
        qc_df = qc_scenes(df)

        res_map = qc_df.set_index("scene_id")["qc_reasons"].to_dict()
        assert "bad_red" in res_map["s_bad_red"]
        assert "low_valid" in res_map["s_low_valid_project"]
        assert "low_valid" in res_map["s_low_valid_ring"]
        assert res_map["s_clean"] == ""
        assert qc_df.set_index("scene_id")["qc_pass"].to_dict()["s_clean"] is True

    def test_common_mode_outlier_vs_single_zone(self) -> None:
        """Verify common-mode outliers (both zones differ > 0.25) vs single-zone outliers."""
        # 4 reference neighbor scenes (around 0.70 proj, 0.60 ring)
        scenes = [
            {
                "scene_id": f"s_ref_{i}",
                "date": f"2020-07-0{i}",
                "baseline": "04.00",
                "detected_offset": 0.0,
                "offset_flag": "absent",
                "red_p1_dn": 150.0,
                "proj_valid_fraction": 0.9,
                "ring_valid_fraction": 0.9,
                "proj_ndvi_median": 0.70,
                "ring_ndvi_median": 0.60,
                "proj_ndvi_p90": 0.80,
                "ring_ndvi_p90": 0.70,
            }
            for i in range(1, 5)
        ]

        # Common-mode outlier: both proj (0.20) and ring (0.15) drop by > 0.25
        scenes.append({
            "scene_id": "s_common_mode",
            "date": "2020-07-05",
            "baseline": "04.00",
            "detected_offset": 0.0,
            "offset_flag": "absent",
            "red_p1_dn": 150.0,
            "proj_valid_fraction": 0.9,
            "ring_valid_fraction": 0.9,
            "proj_ndvi_median": 0.20,
            "ring_ndvi_median": 0.15,
            "proj_ndvi_p90": 0.30,
            "ring_ndvi_p90": 0.25,
        })

        # Single-zone outlier: only project drops to 0.20, ring stays normal (0.60)
        scenes.append({
            "scene_id": "s_single_zone",
            "date": "2020-07-06",
            "baseline": "04.00",
            "detected_offset": 0.0,
            "offset_flag": "absent",
            "red_p1_dn": 150.0,
            "proj_valid_fraction": 0.9,
            "ring_valid_fraction": 0.9,
            "proj_ndvi_median": 0.20,
            "ring_ndvi_median": 0.60,
            "proj_ndvi_p90": 0.30,
            "ring_ndvi_p90": 0.70,
        })

        df = pd.DataFrame(scenes)
        qc_df = qc_scenes(df)
        res_by_id = qc_df.set_index("scene_id")

        # Common-mode outlier must fail QC and NOT be marked single_zone_outlier
        assert "common_mode_outlier" in res_by_id.loc["s_common_mode", "qc_reasons"]
        assert res_by_id.loc["s_common_mode", "qc_pass"] == False
        assert res_by_id.loc["s_common_mode", "single_zone_outlier"] == False

        # Single-zone outlier must pass QC and be flagged single_zone_outlier=True
        assert res_by_id.loc["s_single_zone", "qc_reasons"] == ""
        assert res_by_id.loc["s_single_zone", "qc_pass"] == True
        assert res_by_id.loc["s_single_zone", "single_zone_outlier"] == True


class TestDrySeasonEstimate:
    """Unit tests for dry_season_estimate and bootstrap reproducibility."""

    @pytest.fixture
    def synthetic_qc_scenes(self) -> pd.DataFrame:
        """Create synthetic Jun-Aug QC scenes across 2019-2022."""
        rows = []
        # 2019: delta ~ 0.02
        for i in range(1, 9):
            rows.append({
                "scene_id": f"s_2019_{i}",
                "date": f"2019-07-{i:02d}",
                "qc_pass": True,
                "single_zone_outlier": False,
                "proj_ndvi_median": 0.62 + i * 0.001,
                "ring_ndvi_median": 0.60,
                "proj_ndvi_p90": 0.72 + i * 0.001,
                "ring_ndvi_p90": 0.70,
            })
        # 2020: delta ~ 0.12 (including one single-zone outlier)
        for i in range(1, 9):
            is_szo = (i == 1)
            rows.append({
                "scene_id": f"s_2020_{i}",
                "date": f"2020-07-{i:02d}",
                "qc_pass": True,
                "single_zone_outlier": is_szo,
                "proj_ndvi_median": 0.72 + i * 0.001,
                "ring_ndvi_median": 0.60,
                "proj_ndvi_p90": 0.75 + i * 0.001,
                "ring_ndvi_p90": 0.70,
            })
        return pd.DataFrame(rows)

    def test_bootstrap_reproducibility(self, synthetic_qc_scenes: pd.DataFrame) -> None:
        """Verify bootstrap yields identical medians and CIs given the same seed."""
        res1 = dry_season_estimate(synthetic_qc_scenes, seed=123)
        res2 = dry_season_estimate(synthetic_qc_scenes, seed=123)
        res_diff_seed = dry_season_estimate(synthetic_qc_scenes, seed=999)

        # Identical seed must give exact identical CIs
        assert res1 == res2

        # Different seed will produce slight stochastic variations in CIs
        ci1 = res1["run_with_single_zone_outliers"]["ndvi_median"]["2020"]["ci"]
        ci_diff = res_diff_seed["run_with_single_zone_outliers"]["ndvi_median"]["2020"]["ci"]
        # Point estimates match, CIs may vary slightly
        med1 = res1["run_with_single_zone_outliers"]["ndvi_median"]["2020"]["median_delta"]
        med_diff = res_diff_seed["run_with_single_zone_outliers"]["ndvi_median"]["2020"]["median_delta"]
        assert med1 == med_diff

    def test_single_zone_outlier_exclusion(self, synthetic_qc_scenes: pd.DataFrame) -> None:
        """Verify single-zone outliers are included in Run 1 and excluded in Run 2."""
        res = dry_season_estimate(synthetic_qc_scenes, seed=42)

        n_inc_2020 = res["run_with_single_zone_outliers"]["ndvi_median"]["2020"]["n"]
        n_exc_2020 = res["run_without_single_zone_outliers"]["ndvi_median"]["2020"]["n"]

        # Run 1 includes all 8 scenes, Run 2 excludes the 1 single-zone outlier (n=7)
        assert n_inc_2020 == 8
        assert n_exc_2020 == 7


class TestPlantationAreaEstimate:
    """Unit tests for plantation_area_estimate function."""

    def test_plantation_area_estimate_project_2469(self, tmp_path: Path) -> None:
        """Verify plantation_area_estimate produces valid grid and cohort structures."""
        proj_dir = Path("data/projects/2469")
        if not (proj_dir / "imagery" / "composites" / "raw_composite_2019.tif").exists():
            pytest.skip("Project 2469 composite files not available in environment")

        res = plantation_area_estimate(proj_dir, output_json_path=tmp_path / "estimate.json")

        assert res["forest_allowance_ha"] == 541.0
        assert "grid_thresholds" in res
        assert "0.6" in res["grid_thresholds"]
        assert "0.75" in res["grid_thresholds"]
        assert np.isclose(res["grid_thresholds"]["0.6"]["obs_ha"], 1505.62, atol=1.0)
        assert np.isclose(res["grid_thresholds"]["0.75"]["obs_ha"], 1015.20, atol=1.0)

        # Check observation band
        band = res["band"]
        assert np.isclose(band["high"], 1505.62, atol=1.0)
        assert np.isclose(band["low"], 1015.20, atol=1.0)
        assert np.isclose(band["central"], 1265.00, atol=1.0)

        # Check hysteresis cohorts
        assert "(0.6, 0.7)" in res["hysteresis_cohorts"]
        assert np.isclose(res["pre_existing_decline_ha"], 43.11, atol=1.0)
        assert "cohort_total_range_ha" in res
        assert np.isclose(res["cohort_total_range_ha"][0], 430.58, atol=1.0)
        assert np.isclose(res["cohort_total_range_ha"][1], 732.66, atol=1.0)
        assert "cohort_2021_range_ha" in res
        assert np.isclose(res["cohort_2021_range_ha"][0], 144.04, atol=1.0)
        assert np.isclose(res["cohort_2021_range_ha"][1], 222.63, atol=1.0)

        # Check file hashes
        hashes = res["file_hashes"]
        assert "timeseries.csv" in hashes
        assert "raw_composite_2019.tif" in hashes
        assert "ndvi_qm_2019.tif" in hashes
        assert "qc_scenes.csv" in hashes
        assert "project_boundary.geojson" in hashes or "boundary.geojson" in hashes
        assert len(hashes["raw_composite_2019.tif"]) == 64

        # Check normalization_sensitivity inside satellite_estimate
        assert "normalization_sensitivity" in res["satellite_estimate"]
        norm_sens = res["satellite_estimate"]["normalization_sensitivity"]
        assert "areas_by_threshold" in norm_sens
        assert "ring_raw_median" in norm_sens
        assert "raw_obs_grid" in norm_sens
        assert "raw_band" in norm_sens
        for flat_k in ["low", "central", "high", "span_ha", "span_pct", "detection_limit_ha", "detection_limit_pct"]:
            assert flat_k not in norm_sens

        raw_band = norm_sens["raw_band"]
        assert round(raw_band["low"], 2) == 1122.50
        assert round(raw_band["central"], 2) == 1440.56
        assert round(raw_band["high"], 2) == 1620.79
        assert round(raw_band["span_ha"], 2) == 498.29
        assert round(raw_band["span_pct"], 2) == 38.33
        assert round(raw_band["detection_limit_ha"], 2) == 177.50
        assert round(raw_band["detection_limit_pct"], 2) == 13.65

        ring_med = norm_sens["ring_raw_median"]
        assert round(ring_med["2019"], 4) == 0.6165
        assert round(ring_med["2020"], 4) == 0.6353
        assert round(ring_med["2021"], 4) == 0.5535
        assert round(ring_med["2022"], 4) == 0.6712

        # Primary QM band remains unchanged
        assert round(band["low"], 2) == 1015.20
        assert round(band["central"], 2) == 1265.00
        assert round(band["high"], 2) == 1505.62

