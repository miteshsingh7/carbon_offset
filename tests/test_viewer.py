"""Unit tests for viewer.py data loaders and normalization routines.

Verifies missing-key robustness, demo fixture handling, project 2469 outputs,
and ensures that viewer.py does NOT import Streamlit.
"""

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from carbonverify.viewer import (
    get_area_test_data,
    get_canopy_biomass_data,
    get_claims_table,
    get_verdict_summary,
    list_output_projects,
    load_extraction_report_json,
    load_imagery_qc_data,
    load_project_figures,
    load_project_geometries,
    load_report_html,
    load_report_json,
)


def test_viewer_does_not_import_streamlit() -> None:
    """Verify that carbonverify.viewer does not import streamlit."""
    # Ensure carbonverify.viewer is loaded
    import carbonverify.viewer as v_mod

    viewer_file = Path(v_mod.__file__).read_text(encoding="utf-8")
    assert "import streamlit" not in viewer_file
    assert "from streamlit" not in viewer_file


def test_list_output_projects(tmp_path: Path) -> None:
    """Test discovering projects in output folder that contain report.json."""
    # Real output folder check
    projects = list_output_projects("output")
    assert "demo" in projects
    assert "fake_proj" not in projects  # fake_proj has no report.json

    # Synthetic folder test
    synth_out = tmp_path / "test_out"
    synth_out.mkdir()
    (synth_out / "proj_a").mkdir()
    (synth_out / "proj_a" / "report.json").write_text("{}", encoding="utf-8")
    (synth_out / "proj_b").mkdir()  # no report.json

    found = list_output_projects(synth_out)
    assert found == ["proj_a"]

    # Nonexistent folder
    assert list_output_projects(tmp_path / "nonexistent") == []


def test_load_report_json_project_2469() -> None:
    """Verify loading real report.json for project 2469."""
    rep = load_report_json("output", "2469")
    assert rep.get("status") == "CONSISTENT"
    assert rep.get("confidence") == "LOW"

    verdict = get_verdict_summary(rep)
    assert verdict["status"] == "CONSISTENT"
    assert verdict["confidence"] == "LOW"
    assert verdict["claimed_area_ha"] == 1300.0
    assert verdict["obs_low"] == 1015.2
    assert verdict["obs_high"] == 1505.62
    assert verdict["is_demo"] is False
    assert len(verdict["confidence_reasons"]) > 0


def test_load_report_json_demo_project() -> None:
    """Verify loading demo project report with demo banner flag."""
    rep = load_report_json("output", "demo")
    assert rep.get("project_id") == "demo"
    assert rep.get("demo") is True

    verdict = get_verdict_summary(rep)
    assert verdict["project_id"] == "demo"
    assert verdict["is_demo"] is True
    assert verdict["claimed_area_ha"] == 12500.0


def test_load_report_missing_file() -> None:
    """Verify graceful handling when report.json does not exist."""
    rep = load_report_json("output", "nonexistent_project_9999")
    assert rep == {}

    verdict = get_verdict_summary(rep)
    assert verdict["status"] == "not available"
    assert verdict["confidence"] == "not available"
    assert verdict["claimed_area_ha"] == "not available"
    assert verdict["obs_low"] == "not available"
    assert verdict["is_demo"] is False


def test_missing_keys_robustness() -> None:
    """Verify all helper functions handle completely empty dictionaries gracefully."""
    empty_rep: Dict[str, Any] = {}

    # 1. Verdict summary
    v = get_verdict_summary(empty_rep)
    assert v["status"] == "not available"
    assert v["claimed_area_ha"] == "not available"

    # 2. Claims table
    claims_rows = get_claims_table(empty_rep)
    assert isinstance(claims_rows, list)
    assert len(claims_rows) > 0
    assert all(r["value"] == "not available" for r in claims_rows)

    # 3. Area test data
    area_data = get_area_test_data(empty_rep)
    assert area_data["claimed_area_ha"] is None
    assert area_data["grid_rows"] == []
    assert area_data["normalization_sensitivity"] is None

    # 4. Canopy and biomass data
    cb_data = get_canopy_biomass_data(empty_rep)
    assert cb_data["available"] is False
    assert cb_data["table_rows"] == []
    assert cb_data["p90_sentence"] == "not available"


def test_load_project_geometries() -> None:
    """Verify loading vector GeoJSON geometries without rasterization."""
    # Project 2469 has boundary and reference_ring
    geoms_2469 = load_project_geometries("output", "2469")
    assert geoms_2469["boundary"] is not None
    assert "features" in geoms_2469["boundary"]
    assert geoms_2469["reference_ring"] is not None

    # Demo project has boundary but no reference ring
    geoms_demo = load_project_geometries("output", "demo")
    assert geoms_demo["boundary"] is not None
    assert geoms_demo["reference_ring"] is None

    # Nonexistent project
    geoms_none = load_project_geometries("output", "nonexistent")
    assert geoms_none["boundary"] is None
    assert geoms_none["reference_ring"] is None


def test_load_imagery_qc_data() -> None:
    """Verify imagery quality control loader."""
    # Project 2469 has qc_scenes.csv
    qc_2469 = load_imagery_qc_data("output", "2469")
    assert qc_2469["available"] is True
    assert isinstance(qc_2469["total_scenes"], int)
    assert qc_2469["total_scenes"] > 0
    assert isinstance(qc_2469["pass_scenes"], int)
    assert isinstance(qc_2469["excluded_scenes"], int)
    assert isinstance(qc_2469["excluded_records"], list)

    # Demo project has no qc_scenes.csv
    qc_demo = load_imagery_qc_data("output", "demo")
    assert qc_demo["available"] is False
    assert qc_demo["total_scenes"] == "not available"
    assert qc_demo["excluded_records"] == []


def test_canopy_biomass_coincidence_sentence() -> None:
    """Verify coincidence of ranks sentence generation from 2469 report."""
    rep = load_report_json("output", "2469")
    cb_data = get_canopy_biomass_data(rep)
    assert cb_data["available"] is True
    assert "97.85" in cb_data["p90_sentence"]
    assert "coincidence of ranks, not a ceiling" in cb_data["p90_sentence"]


def test_load_report_html() -> None:
    """Verify loading HTML report content."""
    html_str = load_report_html("output", "2469")
    assert len(html_str) > 0
    assert "<html" in html_str.lower()

    # Nonexistent
    assert load_report_html("output", "nonexistent") == ""


def test_load_project_figures() -> None:
    """Verify loading figures for project 2469 and handling nonexistent projects."""
    figs_2469 = load_project_figures("output", "2469")
    assert "cohort_maps" in figs_2469
    assert "zone_timeseries" in figs_2469
    assert "decline_map" in figs_2469

    figs_none = load_project_figures("output", "nonexistent")
    assert figs_none["cohort_maps"] is None
    assert figs_none["zone_timeseries"] is None
    assert figs_none["decline_map"] is None
