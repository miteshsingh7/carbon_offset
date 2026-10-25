"""Tests for Hansen Global Forest Change (GFC) cross-check analysis."""

import json
from pathlib import Path
import pytest

from carbonverify.pipeline import run
from carbonverify.schemas import ConfidenceLevel, VerificationStatus


def test_hansen_crosscheck_block_exists_and_shares_valid() -> None:
    """Verify hansen_crosscheck block exists, tile/version recorded, and all shares are between 0 and 1."""
    est_path = Path("data/projects/2469/estimate.json")
    if not est_path.exists():
        pytest.skip("Project 2469 estimate.json not found")

    with open(est_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "satellite_estimate" in data
    sat_est = data["satellite_estimate"]
    assert "hansen_crosscheck" in sat_est
    hc = sat_est["hansen_crosscheck"]

    assert hc["gfc_version"] == "GFC-2022-v1.10"
    assert "20S_060W" in hc["tiles"]
    assert hc["primary_tile"] == "20S_060W"

    hashes = hc["file_hashes"]
    assert len(hashes) == 2
    for hname, hval in hashes.items():
        assert len(hval) == 64

    # Verify decline pixels shares
    dec = hc["decline_43ha"]
    assert 0.0 <= dec["treecover2000_ge_25_share"] <= 1.0
    assert 0.0 <= dec["treecover2000_ge_50_share"] <= 1.0
    assert 0.0 <= dec["loss_share_2019"] <= 1.0
    assert 0.0 <= dec["loss_share_2020"] <= 1.0
    assert 0.0 <= dec["loss_share_2021"] <= 1.0
    assert 0.0 <= dec["loss_share_2022"] <= 1.0
    assert 0.0 <= dec["loss_share_2019_2022_total"] <= 1.0

    # Verify controls shares
    controls = hc["controls"]
    assert "high_all4" in controls
    assert "project_boundary" in controls
    assert "reference_ring" in controls

    for cname, cstats in controls.items():
        assert 0.0 <= cstats["treecover2000_ge_25_share"] <= 1.0
        assert 0.0 <= cstats["treecover2000_ge_50_share"] <= 1.0
        assert 0.0 <= cstats["loss_share_2019_2022_total"] <= 1.0
        for yr in ["2019", "2020", "2021", "2022"]:
            assert 0.0 <= cstats[f"loss_share_{yr}"] <= 1.0

    # Verify boundary loss in ha per year
    b_loss = hc["boundary_loss_ha_by_year"]
    for yr in ["2019", "2020", "2021", "2022"]:
        assert yr in b_loss
        assert b_loss[yr] >= 0.0


def test_hansen_pipeline_run_invariants_and_render(tmp_path: Path) -> None:
    """Verify pipeline run for 2469 preserves status/band/confidence and renders required Hansen wording."""
    proj_dir = Path("data/projects/2469")
    if not (proj_dir / "imagery" / "composites" / "raw_composite_2019.tif").exists():
        pytest.skip("Project 2469 imagery not found")

    out_dir = tmp_path / "hansen_pipeline_test"
    report = run(project_dir=proj_dir, out_dir=out_dir)

    # Invariants: status, band, confidence unchanged
    assert report.status == VerificationStatus.CONSISTENT
    assert report.confidence == ConfidenceLevel.LOW
    assert report.estimate.planted_area_obs_low == 1015.20
    assert report.estimate.planted_area_obs_central == 1265.00
    assert report.estimate.planted_area_obs_high == 1505.62

    # Check rendered report.html
    html_file = out_dir / "report.html"
    assert html_file.exists()
    html_text = html_file.read_text(encoding="utf-8")

    expected_wording = (
        "Hansen tree-cover loss includes plantation harvest and is 30 m; "
        "this is an indicator of land cover, not proof; unscored."
    )
    assert expected_wording in html_text
    assert "Without ring normalisation" in html_text
    assert html_text.lower().count("verified") == 1
    assert "not a verified biomass gain" in html_text.lower()
    assert "forest loss" not in html_text.lower()


def test_forest_allowance_check_block_exists_and_values() -> None:
    """Verify forest_allowance_check block exists and F*(0.6) == A2022(0.6) - 1300."""
    est_path = Path("data/projects/2469/estimate.json")
    if not est_path.exists():
        pytest.skip("Project 2469 estimate.json not found")

    with open(est_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "satellite_estimate" in data
    sat_est = data["satellite_estimate"]
    assert "forest_allowance_check" in sat_est
    fa = sat_est["forest_allowance_check"]

    assert fa["gfc_version"] == "GFC-2022-v1.10"
    assert "20S_060W" in fa["tiles"]
    assert len(fa["file_hashes"]) == 2

    # Break-even check: F*(0.6) == A2022(0.6) - 1300
    be = fa["break_even_allowance"]
    a_06 = be["by_threshold"]["0.6"]["a_2022_ha"]
    f_star_06 = be["by_threshold"]["0.6"]["f_star_ha"]
    assert f_star_06 == pytest.approx(a_06 - 1300.0, abs=0.01)
    assert f_star_06 == 746.62
    assert fa["f_star_06_ha"] == 746.62
    assert fa["margin_06_ha"] == pytest.approx(746.62 - 541.0, abs=0.01)

    # Check persistence entries
    pers = fa["persistence"]
    for t in ["25", "50", "75"]:
        assert t in pers
        row = pers[t]
        assert row["treecover2000_ha"] >= row["persistent_2018_ha"]
        assert row["persistent_2018_ha"] >= row["persistent_qm19_ge_06_ha"]
        assert row["persistent_qm19_ge_06_ha"] >= row["persistent_qm19_ge_07_ha"]


def test_forest_allowance_pipeline_invariants_and_render(tmp_path: Path) -> None:
    """Verify pipeline invariants, status/band/confidence, and Section 3 rendering."""
    proj_dir = Path("data/projects/2469")
    if not (proj_dir / "imagery" / "composites" / "raw_composite_2019.tif").exists():
        pytest.skip("Project 2469 imagery not found")

    out_dir = tmp_path / "fa_pipeline_test"
    report = run(project_dir=proj_dir, out_dir=out_dir)

    # Status, band, confidence unchanged
    assert report.status == VerificationStatus.CONSISTENT
    assert report.confidence == ConfidenceLevel.LOW
    assert report.estimate.planted_area_obs_low == 1015.20
    assert report.estimate.planted_area_obs_central == 1265.00
    assert report.estimate.planted_area_obs_high == 1505.62

    # Rendered HTML assertions
    html_file = out_dir / "report.html"
    assert html_file.exists()
    html_text = html_file.read_text(encoding="utf-8")

    assert "At the generous end (T = 0.60) the status stays CONSISTENT for any forest allowance up to 746.62 ha" in html_text
    assert "Hansen cannot separate natural forest from older plantations or scattered trees, so it is an indicator only" in html_text
    assert html_text.lower().count("verified") == 1
    assert "not a verified biomass gain" in html_text.lower()


def test_decline_analysis_block_and_reproducible_section5(tmp_path: Path) -> None:
    """Verify decline_analysis block, exact values, invariants, and no static literals in render.py."""
    proj_dir = Path("data/projects/2469")
    if not (proj_dir / "estimate.json").exists():
        pytest.skip(f"Required local estimate missing: {proj_dir / 'estimate.json'}")
    doc_file = proj_dir / "docs" / "monitoring_report.pdf"
    if not doc_file.exists():
        pytest.skip(f"Required local PDF missing: {doc_file}")
    comp_file = proj_dir / "imagery" / "composites" / "raw_composite_2019.tif"
    if not comp_file.exists():
        pytest.skip(f"Required local composite missing: {comp_file}")

    with open(proj_dir / "estimate.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "satellite_estimate" in data
    sat_est = data["satellite_estimate"]
    assert "decline_analysis" in sat_est
    da = sat_est["decline_analysis"]

    # Step 5 key number checks
    d = da["decline_set_d"]
    assert d["area_ha"] == 74.70
    assert d["first_high_split"]["2019"] == 43.11
    assert d["first_high_split"]["2020"] == 26.94
    assert d["first_high_split"]["2021"] == 4.65
    assert d["moderate_decline_60_70_ha"] == 179.02
    assert d["components"]["count"] == 848
    assert d["components"]["share_lt_1ha_pct"] == 59.64
    assert d["components"]["share_1_to_5ha_pct"] == 26.87
    assert d["components"]["share_gt_5ha_pct"] == 13.49
    assert d["components"]["largest_component_ha"] == 10.08
    assert round(d["components"]["largest_component_raw_means"]["2020"], 2) == 0.74
    assert round(d["components"]["largest_component_raw_means"]["2021"], 2) == 0.37
    assert round(d["components"]["largest_component_raw_means"]["2022"], 2) == 0.57

    g22 = da["g22_cohort"]
    assert g22["area_ha"] == 125.94
    assert g22["components"]["components_gt_5ha"] == [29.33, 14.63, 9.10, 5.33]
    assert g22["components"]["share_gt_5ha_pct"] == 46.36
    assert g22["components"]["share_lt_1ha_pct"] == 39.77
    assert round(g22["components"]["largest_component_raw_means"]["2019"], 2) == 0.51
    assert round(g22["components"]["largest_component_raw_means"]["2020"], 2) == 0.61
    assert round(g22["components"]["largest_component_raw_means"]["2022"], 2) == 0.81

    sens = da["sensitivity_t70_excl_g22"]
    assert sens["observed_area_excl_g22_ha"] == 1053.12

    c22 = da["strict_2022_cohort"]
    assert c22["area_ha"] == 22.46
    assert c22["share_lt_1ha_round_pct"] == 63

    assert da["latest_planting_year"] == 2020

    # Test pipeline run invariants
    out_dir = tmp_path / "decline_pipeline_test"
    report = run(project_dir=proj_dir, out_dir=out_dir)

    assert report.status == VerificationStatus.CONSISTENT
    assert report.confidence == ConfidenceLevel.LOW
    assert report.estimate.planted_area_obs_low == 1015.20
    assert report.estimate.planted_area_obs_central == 1265.00
    assert report.estimate.planted_area_obs_high == 1505.62

    # Verify rendered HTML contains Section 5 text
    html_text = (out_dir / "report.html").read_text(encoding="utf-8")
    assert "Pixels with qm &gt;= 0.70 in some year and &lt; 0.60 in 2022: 74.70 ha" in html_text
    assert "Decline set D (qm &gt;= 0.70 in some year and qm2022 &lt; 0.60; 74.70 ha): 848 components" in html_text
    assert "2022 first-high set G22 (first year qm &gt;= 0.70 is 2022, T = 0.70; 125.94 ha)" in html_text
    assert "Strict (0.6, 0.7) 2022 cohort (22.46 ha): 63% of the area is in components &lt; 1 ha" in html_text

    # Verify none of the literals remain in render.py
    literals = [
        "74.70", "43.11", "26.94", "4.65", "848", "59.64", "26.87", "13.49",
        "10.08", "0.74", "0.37", "0.57", "125.94", "29.33", "14.63", "9.10",
        "5.33", "46.36", "39.77", "0.51-0.61", "0.81", "1,053.12", "1053.12",
        "22.46", "63%", "179.02"
    ]
    render_code = Path("src/carbonverify/report/render.py").read_text(encoding="utf-8")
    for lit in literals:
        assert lit not in render_code, f"Literal {lit} found in render.py"

