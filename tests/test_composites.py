"""Unit tests for pixel composites calculation, >=3 observation threshold, and ring normalization."""

import numpy as np
import pandas as pd
import pytest

from carbonverify.analysis.composites import (
    calculate_transition_matrix,
    classify_hysteresis_cohorts,
    normalize_composite_to_ring,
    quantile_map,
)


class TestCompositeObservationThreshold:
    """Tests for the >= 3 valid observations per pixel rule."""

    def test_min_observations_rule_synthetic(self) -> None:
        """Verify pixels with < 3 valid observations become NaN, and >= 3 compute median."""
        # 5 scenes, 1x6 grid of pixels
        # pixel 0: 0 valid observations (all NaN)
        # pixel 1: 1 valid observation (0.7, others NaN)
        # pixel 2: 2 valid observations (0.6, 0.8, others NaN)
        # pixel 3: 3 valid observations (0.5, 0.6, 0.7, others NaN) -> median 0.6
        # pixel 4: 4 valid observations (0.4, 0.5, 0.6, 0.7, NaN) -> median 0.55
        # pixel 5: 5 valid observations (0.2, 0.4, 0.6, 0.8, 1.0) -> median 0.6

        stack = np.full((5, 1, 6), np.nan, dtype=np.float32)

        # pixel 1
        stack[0, 0, 1] = 0.7

        # pixel 2
        stack[0, 0, 2] = 0.6
        stack[1, 0, 2] = 0.8

        # pixel 3
        stack[0, 0, 3] = 0.5
        stack[1, 0, 3] = 0.6
        stack[2, 0, 3] = 0.7

        # pixel 4
        stack[0, 0, 4] = 0.4
        stack[1, 0, 4] = 0.5
        stack[2, 0, 4] = 0.6
        stack[3, 0, 4] = 0.7

        # pixel 5
        stack[0, 0, 5] = 0.2
        stack[1, 0, 5] = 0.4
        stack[2, 0, 5] = 0.6
        stack[3, 0, 5] = 0.8
        stack[4, 0, 5] = 1.0

        valid_counts = np.sum(~np.isnan(stack), axis=0)
        assert valid_counts[0, 0] == 0
        assert valid_counts[0, 1] == 1
        assert valid_counts[0, 2] == 2
        assert valid_counts[0, 3] == 3
        assert valid_counts[0, 4] == 4
        assert valid_counts[0, 5] == 5

        with np.errstate(all="ignore"):
            med = np.nanmedian(stack, axis=0)
        med[valid_counts < 3] = np.nan

        # Pixels with < 3 observations must be NaN
        assert np.isnan(med[0, 0])
        assert np.isnan(med[0, 1])
        assert np.isnan(med[0, 2])

        # Pixels with >= 3 observations must match median
        assert np.isclose(med[0, 3], 0.60, atol=1e-5)
        assert np.isclose(med[0, 4], 0.55, atol=1e-5)
        assert np.isclose(med[0, 5], 0.60, atol=1e-5)


class TestRingNormalization:
    """Tests for reference ring normalization: ndvi_norm(y) = ndvi(y) - (ring_median(y) - ring_median(2019))."""

    def test_ring_normalization_shift(self) -> None:
        """Verify normalization shifts composite so ring median matches reference year."""
        # 10x10 composite: columns 0-4 are project, columns 5-9 are ring
        ring_mask = np.zeros((10, 10), dtype=np.uint8)
        ring_mask[:, 5:] = 1

        ref_ring_median = 0.60

        # Current year raw composite with ring median = 0.65
        raw_comp = np.full((10, 10), 0.75, dtype=np.float32)
        raw_comp[:, 5:] = 0.65  # Ring values
        raw_comp[0, 0] = np.nan  # NaN project pixel
        raw_comp[0, 9] = np.nan  # NaN ring pixel

        norm_comp, cur_ring_med, shift = normalize_composite_to_ring(
            raw_composite=raw_comp,
            ring_mask=ring_mask,
            ref_ring_median=ref_ring_median,
        )

        assert np.isclose(cur_ring_med, 0.65, atol=1e-5)
        assert np.isclose(shift, 0.05, atol=1e-5)

        # After shift of +0.05, ring values should be 0.65 - 0.05 = 0.60
        finite_ring_norm = norm_comp[ring_mask == 1]
        finite_ring_norm = finite_ring_norm[~np.isnan(finite_ring_norm)]
        assert np.isclose(float(np.median(finite_ring_norm)), ref_ring_median, atol=1e-5)

        # Project values should be 0.75 - 0.05 = 0.70
        assert np.isclose(norm_comp[5, 2], 0.70, atol=1e-5)

        # NaN values must remain NaN
        assert np.isnan(norm_comp[0, 0])
        assert np.isnan(norm_comp[0, 9])

    def test_transition_matrix(self) -> None:
        """Verify class transition matrix calculation."""
        mask = np.ones((2, 2), dtype=np.uint8)
        arr1 = np.array([[0.4, 0.6], [0.8, np.nan]], dtype=np.float32)
        arr2 = np.array([[0.6, 0.6], [0.8, 0.4]], dtype=np.float32)

        df = calculate_transition_matrix(arr1, arr2, mask, pixel_area_ha=1.0)
        # arr1: [0,0] is low, arr2 is mid -> transition low -> mid = 1
        assert df.loc["low (<0.5)", "mid (0.5-0.7)"] == 1.0
        # arr1: [0,1] is mid, arr2 is mid -> transition mid -> mid = 1
        assert df.loc["mid (0.5-0.7)", "mid (0.5-0.7)"] == 1.0
        # arr1: [1,0] is high, arr2 is high -> transition high -> high = 1
        assert df.loc["high (>=0.7)", "high (>=0.7)"] == 1.0
        # arr1: [1,1] is NaN, arr2 is low -> transition NaN -> low = 1
        assert df.loc["NaN", "low (<0.5)"] == 1.0


class TestQuantileMapping:
    """Tests for monotone quantile mapping with constant-offset extrapolation."""

    def test_quantile_map_identity(self) -> None:
        """Verify identity mapping when source and target distributions are identical (e.g. 2019)."""
        q = np.linspace(0.1, 0.9, 201)
        x = np.array([-0.2, 0.1, 0.3, 0.5, 0.7, 0.9, 1.2, np.nan], dtype=np.float32)

        mapped = quantile_map(x, q_source=q, q_target=q)

        # Finite values must be identical to x
        valid = np.isfinite(x)
        assert np.allclose(mapped[valid], x[valid], atol=1e-6)
        # NaN must remain NaN
        assert np.isnan(mapped[-1])

    def test_quantile_map_monotonicity(self) -> None:
        """Verify monotonicity of quantile mapping across strictly increasing inputs."""
        q_source = np.array([0.2, 0.4, 0.6, 0.8], dtype=np.float32)
        q_target = np.array([0.3, 0.45, 0.7, 0.85], dtype=np.float32)

        # Inputs spanning below, within, and above the quantile range
        x = np.array([0.0, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95, 1.1], dtype=np.float32)
        mapped = quantile_map(x, q_source=q_source, q_target=q_target)

        # Mapped values must be strictly increasing
        diffs = np.diff(mapped)
        assert np.all(diffs > 0)

    def test_quantile_map_constant_extrapolation(self) -> None:
        """Verify constant-offset extrapolation outside the source range."""
        q_source = np.array([0.2, 0.5, 0.8], dtype=np.float32)
        q_target = np.array([0.3, 0.55, 0.9], dtype=np.float32)

        # Below lower boundary: offset = q_target[0] - q_source[0] = 0.3 - 0.2 = +0.10
        x_low = np.array([0.0, 0.1, 0.19], dtype=np.float32)
        mapped_low = quantile_map(x_low, q_source=q_source, q_target=q_target)
        assert np.allclose(mapped_low, x_low + 0.10, atol=1e-5)

        # Above upper boundary: offset = q_target[-1] - q_source[-1] = 0.9 - 0.8 = +0.10
        x_high = np.array([0.81, 0.95, 1.2], dtype=np.float32)
        mapped_high = quantile_map(x_high, q_source=q_source, q_target=q_target)
        assert np.allclose(mapped_high, x_high + 0.10, atol=1e-5)


class TestHysteresisCohorts:
    """Tests for the hysteresis cohort classification rule on a synthetic 4-year array."""

    def test_cohort_classification_synthetic_4year(self) -> None:
        """Verify cohort assignment, pre-existing, and unclassified logic across 4 years."""
        # 7 synthetic pixels across 4 years (2019, 2020, 2021, 2022)
        # Thresholds: T_low = 0.60, T_high = 0.70
        q19 = np.array([0.65, 0.35, 0.35, 0.35, 0.35, 0.35, 0.35], dtype=np.float32)
        q20 = np.array([0.75, 0.75, 0.75, 0.45, 0.62, 0.45, 0.45], dtype=np.float32)
        q21 = np.array([0.80, 0.65, 0.65, 0.72, 0.72, 0.55, 0.55], dtype=np.float32)
        q22 = np.array([0.85, 0.62, 0.55, 0.65, 0.65, 0.71, 0.58], dtype=np.float32)

        res = classify_hysteresis_cohorts(
            q19=q19,
            q20=q20,
            q21=q21,
            q22=q22,
            t_low=0.60,
            t_high=0.70,
        )

        pre = res["pre_existing"]
        c20 = res["cohort_2020"]
        c21 = res["cohort_2021"]
        c22 = res["cohort_2022"]
        unclass = res["unclassified"]

        # Pixel 0: q19 = 0.65 >= 0.60 -> pre-existing
        assert pre[0]
        assert not (c20[0] or c21[0] or c22[0] or unclass[0])

        # Pixel 1: crosses in 2020 (0.75 >= 0.70) and stays >= 0.60 (0.65, 0.62) -> cohort 2020
        assert c20[1]
        assert not (pre[1] or c21[1] or c22[1] or unclass[1])

        # Pixel 2: crosses in 2020 but drops in 2022 (0.55 < 0.60) -> unclassified
        assert unclass[2]
        assert not (pre[2] or c20[2] or c21[2] or c22[2])

        # Pixel 3: stays < 0.60 in 2019-2020, crosses in 2021 (0.72 >= 0.70), stays >= 0.60 in 2022 -> cohort 2021
        assert c21[3]
        assert not (pre[3] or c20[3] or c22[3] or unclass[3])

        # Pixel 4: in 2020 q20 = 0.62 >= 0.60 (not < T_low in earlier year) -> unclassified
        assert unclass[4]
        assert not (pre[4] or c20[4] or c21[4] or c22[4])

        # Pixel 5: stays < 0.60 in 2019-2021, crosses in 2022 (0.71 >= 0.70) -> cohort 2022
        assert c22[5]
        assert not (pre[5] or c20[5] or c21[5] or unclass[5])

        # Pixel 6: never reaches T_high -> unclassified
        assert unclass[6]
        assert not (pre[6] or c20[6] or c21[6] or c22[6])

        # Mutual exclusivity and complete coverage
        total_coverage = pre.astype(int) + c20.astype(int) + c21.astype(int) + c22.astype(int) + unclass.astype(int)
        assert np.all(total_coverage == 1)


