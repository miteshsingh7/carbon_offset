"""Tests for planted area schedule extraction by stratum."""

from pathlib import Path

import pytest

from carbonverify.claims.planting_schedule import (
    STRATUM_REGEX,
    extract_planting_schedule_from_pdf,
    parse_numeric,
    parse_planting_schedule_from_lines,
)


class TestStratumLabelRegex:
    r"""Validate label regex r'^(\d{4})_(\d+)$' for year_density stratum codes."""

    def test_valid_stratum_labels(self):
        valid_labels = ["2018_714", "2018_1000", "2019_500", "2020_476", "1999_250"]
        for label in valid_labels:
            m = STRATUM_REGEX.match(label)
            assert m is not None, f"Expected {label} to match"
            year, density = m.groups()
            assert len(year) == 4
            assert int(density) > 0

    def test_invalid_stratum_labels(self):
        invalid_labels = [
            "2018",
            "714",
            "stratum_2018",
            "2018-714",
            "2018/714",
            "2018_abc",
            "abc_714",
            "2018_714_extra",
        ]
        for label in invalid_labels:
            assert STRATUM_REGEX.match(label) is None, f"Expected {label} to be rejected"


class TestPlantingScheduleSumCheck:
    """Validate planting schedule sum checks (CONSISTENT vs MISMATCH)."""

    def test_sum_check_consistent_within_2ha(self):
        synthetic_lines = [
            "2018_714 159 161 -2",
            "2018_1000 186 185 2",
            "2019_500 41 41 0",
            "2019_714 252 252 0",
            "2019_1000 353 354 -1",
            "2020_476 104 104",
            "2020_500 10 10",
            "2020_800 108 108",
            "2020_1000 88 88",
            "Total 1,300 993 308",
        ]
        header = "Table 5. Distribution of areas in the project Stratum Total project area (ha)"
        result = parse_planting_schedule_from_lines(synthetic_lines, header=header)

        assert result is not None
        assert result["planted_area_by_year"] == {
            "2018": 345.0,
            "2019": 646.0,
            "2020": 310.0,
        }
        assert result["planted_area_total_ha"] == 1301.0
        assert result["stated_total_ha"] == 1300.0

        check = result["check"]
        assert check.status == "CONSISTENT"
        assert check.is_consistent is True
        assert check.discrepancy_ha == 1.0

    def test_sum_check_mismatch_exceeding_2ha(self):
        synthetic_lines = [
            "2018_714 200",
            "2019_500 500",
            "Total 600",
        ]
        header = "Distribution of areas Stratum"
        result = parse_planting_schedule_from_lines(synthetic_lines, header=header)

        assert result is not None
        assert result["planted_area_total_ha"] == 700.0
        assert result["stated_total_ha"] == 600.0

        check = result["check"]
        assert check.status == "MISMATCH"
        assert check.is_consistent is False
        assert check.discrepancy_ha == 100.0


class TestRowValidationAndHeaderFiltering:
    """Validate rejection of non-numeric rows and header criteria."""

    def test_rejection_of_non_numeric_rows(self):
        synthetic_lines = [
            "2018_714 159.0",
            "2019_500 - - -",        # Non-numeric area -> must be rejected
            "2019_714 N/A",          # Non-numeric area -> must be rejected
            "2020_1000 88.0",
            "Total 247.0",
        ]
        header = "Distribution of areas Stratum"
        result = parse_planting_schedule_from_lines(synthetic_lines, header=header)

        assert result is not None
        # Only 2018_714 and 2020_1000 should be accepted
        assert len(result["planting_schedule"]) == 2
        strata = [r.stratum for r in result["planting_schedule"]]
        assert strata == ["2018_714", "2020_1000"]
        assert result["planted_area_total_ha"] == 247.0
        assert result["check"].status == "CONSISTENT"

    def test_rejection_when_header_criteria_not_met(self):
        synthetic_lines = [
            "2018_714 159",
            "Total 159",
        ]
        # Header does not mention "Distribution of areas" or "Stratum"
        header = "Table 1. Project general parameters and coordinates"
        result = parse_planting_schedule_from_lines(synthetic_lines, header=header)
        assert result is None


class TestRealProject2469PlantingSchedule:
    """Integration test against actual project 2469 monitoring report."""

    def test_project_2469_planting_schedule(self):
        pdf_path = Path("data/projects/2469/docs/monitoring_report.pdf")
        if not pdf_path.exists():
            pytest.skip("Project 2469 monitoring report not available on disk")

        result = extract_planting_schedule_from_pdf(pdf_path)
        assert result is not None
        assert len(result["planting_schedule"]) == 9

        assert result["planted_area_by_year"] == {
            "2018": 345.0,
            "2019": 646.0,
            "2020": 310.0,
        }
        assert result["planted_area_total_ha"] == 1301.0
        assert result["stated_total_ha"] == 1300.0

        check = result["check"]
        assert check.status == "CONSISTENT"
        assert check.is_consistent is True
        assert check.discrepancy_ha == 1.0
        assert check.sum_area_ha == 1301.0
        assert check.stated_total_ha == 1300.0
