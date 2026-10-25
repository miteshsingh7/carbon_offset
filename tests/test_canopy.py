"""Unit tests for independent canopy-cover and biomass-proxy change analysis."""

import json
from pathlib import Path
from bs4 import BeautifulSoup
import pytest

from carbonverify.analysis.canopy import compute_canopy_biomass_change
from carbonverify.pipeline import run


class TestCanopyBiomassAnalysis:
    """Test suite for analysis/canopy.py and rendered HTML section."""

    def test_compute_canopy_biomass_change_project_2469(self) -> None:
        """Verify calculations match expected checks: +94.4% canopy at T=0.70, mean qm ~0.61->0.76, ring +8.87%."""
        proj_dir = Path("data/projects/2469")
        comp_file = proj_dir / "imagery" / "composites" / "raw_composite_2019.tif"
        if not comp_file.exists():
            pytest.skip(f"Required local composite missing: {comp_file}")
        res = compute_canopy_biomass_change(proj_dir)

        assert "table" in res
        assert "biomass_proxy_by_year" in res
        assert "reference_buffer_raw_medians" in res

        # Expected checks:
        # 1. Primary canopy change at T=0.70: 885.01 ha in 2019 to 1720.06 ha in 2022 -> +94.35% (+94.4%)
        assert res["table"]["0.70"]["2019"]["area_ha"] == 885.01
        assert res["table"]["0.70"]["2022"]["area_ha"] == 1720.06
        assert pytest.approx(res["canopy_change_pct"], abs=0.1) == 94.4
        assert res["canopy_change_pct"] == 94.35

        # 2. Min-max over T grid
        assert res["canopy_change_min_pct"] == 54.94  # T=0.60
        assert res["canopy_change_max_pct"] == 135.81  # T=0.75

        # 3. Biomass proxy: mean qm NDVI about 0.61 -> 0.76 (~+24.6% to +24.8%)
        assert pytest.approx(res["biomass_proxy_by_year"]["2019"]["mean"], abs=0.01) == 0.61
        assert pytest.approx(res["biomass_proxy_by_year"]["2022"]["mean"], abs=0.01) == 0.76
        assert pytest.approx(res["biomass_proxy_change_pct"], abs=0.5) == 24.8

        # 4. Ring median: 0.6165 -> 0.6712 (+8.87%)
        assert res["reference_buffer_raw_medians"]["2019"] == 0.6165
        assert res["reference_buffer_raw_medians"]["2022"] == 0.6712
        assert res["reference_buffer_change_pct"] == 8.87

    def test_canopy_biomass_rendered_report_section(self, tmp_path: Path) -> None:
        """Verify report section title, plain text, sentence negation, and no other 'verified'."""
        proj_dir = Path("data/projects/2469")
        doc_file = proj_dir / "docs" / "monitoring_report.pdf"
        if not doc_file.exists():
            pytest.skip(f"Required local PDF missing: {doc_file}")
        comp_file = proj_dir / "imagery" / "composites" / "raw_composite_2019.tif"
        if not comp_file.exists():
            pytest.skip(f"Required local composite missing: {comp_file}")
        out_dir = tmp_path / "canopy_report_out"
        report = run(project_dir=proj_dir, out_dir=out_dir)

        html_path = out_dir / "report.html"
        assert html_path.exists()
        html_text = html_path.read_text(encoding="utf-8")

        soup = BeautifulSoup(html_text, "html.parser")
        target_card = None
        for card in soup.find_all("div", class_="card"):
            h2 = card.find("h2")
            if h2 and "Independent canopy-cover and biomass-proxy change" in h2.text:
                target_card = card
                break

        assert target_card is not None
        card_text = target_card.get_text("\n", strip=True)

        # Title check
        assert "Independent canopy-cover and biomass-proxy change (no canopy claim exists, so unscored)" in card_text

        # Required sentence check
        req_sentence = "NDVI is a proxy that saturates in dense vegetation, and part of the change reflects planting dynamics, not a verified biomass gain."
        assert req_sentence in card_text

        # Prompt 21 required three sentences check
        sent1 = "The 2019 baseline composite postdates the 2018 plantings (project start 2018-06), so change since project start is understated."
        sent2 = "The biomass proxy is computed on ring-normalised NDVI; the ring change shown is the raw median and is context only, not a quantity to subtract."
        sent3 = "The 2020 and 2021 p90 values coincide (0.8504) because the project p90 sits at nearly the same rank of the reference ring in both years (about the 97.85th percentile, computed from the data); this is a coincidence of ranks, not a ceiling."
        assert sent1 in card_text
        assert sent2 in card_text
        assert sent3 in card_text

        # Check that 'verified' only occurs in that negation in this card
        verified_count = card_text.lower().count("verified")
        assert verified_count == 1

        # Check table contents
        assert "1,320.88 ha (57.13%)" in card_text
        assert "1,720.06 ha (74.40%)" in card_text
        assert "0.6060" in card_text
        assert "0.7565" in card_text
        assert "0.6165" in card_text
        assert "0.6712" in card_text

        # Invariants: status, band, confidence unchanged
        assert report.status.value == "CONSISTENT"
        assert report.confidence.value == "LOW"
        assert report.estimate.planted_area_obs_low == 1015.20
        assert report.estimate.planted_area_obs_central == 1265.00
        assert report.estimate.planted_area_obs_high == 1505.62
