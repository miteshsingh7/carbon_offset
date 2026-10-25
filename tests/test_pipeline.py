"""Integration and pipeline tests for carbonverify."""

import json
from pathlib import Path
import pytest

from carbonverify.cli import main as cli_main
from carbonverify.pipeline import run
from carbonverify.schemas import ConfidenceLevel, DiscrepancyReport, VerificationStatus


def test_pipeline_run_on_demo_project(tmp_path: Path) -> None:
    """Test full pipeline execution on demo project directory."""
    demo_dir = Path("data/projects/demo")
    out_dir = tmp_path / "output_test"

    report = run(project_dir=demo_dir, out_dir=out_dir)

    assert isinstance(report, DiscrepancyReport)
    assert report.project_id == "demo"
    assert report.status == VerificationStatus.CONSISTENT
    assert report.area_discrepancy_pct == -0.4
    assert report.canopy_discrepancy_pct is None

    # Verify generated output files
    json_path = out_dir / "report.json"
    html_path = out_dir / "report.html"

    assert json_path.exists()
    assert html_path.exists()

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["project_id"] == "demo"
    assert data["status"] == "CONSISTENT"

    html_content = html_path.read_text(encoding="utf-8")
    assert "Carbon Verification Report" in html_content
    assert "demo" in html_content
    assert "CONSISTENT" in html_content


def test_cli_execution_on_demo_project(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Test CLI invocation of carbonverify run command on demo project."""
    out_dir = tmp_path / "cli_output"
    exit_code = cli_main([
        "run",
        "--project",
        "data/projects/demo",
        "--out-dir",
        str(out_dir),
    ])

    assert exit_code == 0
    assert (out_dir / "report.json").exists()
    assert (out_dir / "report.html").exists()

    captured = capsys.readouterr()
    assert "Estate footprint (boundary):   12,450.0 ha (registry estate not available)" in captured.out
    assert "Planted-area band:             not available" in captured.out
    assert "Shortfall at generous end:     not available" in captured.out


def test_cli_summary_text_project_2469(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Test CLI summary text on project 2469."""
    doc_file = Path("data/projects/2469/docs/monitoring_report.pdf")
    if not doc_file.exists():
        pytest.skip(f"Required local PDF missing: {doc_file}")
    comp_file = Path("data/projects/2469/imagery/composites/raw_composite_2019.tif")
    if not comp_file.exists():
        pytest.skip(f"Required local composite missing: {comp_file}")
    out_dir = tmp_path / "cli_2469_output"
    exit_code = cli_main([
        "run",
        "--project",
        "data/projects/2469",
        "--out-dir",
        str(out_dir),
    ])

    assert exit_code == 0
    assert (out_dir / "report.json").exists()

    captured = capsys.readouterr()
    assert "Estate footprint (boundary):   2,312.0 ha (registry estate 2,309.0 ha)" in captured.out
    assert "Planted-area band:             [1,015.20, 1,505.62] ha, central 1,265.00 ha (claim 1,300.0 ha)" in captured.out
    assert "Shortfall at generous end:     0.00%" in captured.out


def test_pipeline_nonexistent_project_fails() -> None:
    """Test pipeline raises FileNotFoundError for nonexistent project directory."""
    with pytest.raises(FileNotFoundError):
        run(project_dir="data/projects/nonexistent_project_id")


def test_pipeline_missing_boundary_fails(tmp_path: Path) -> None:
    """Test pipeline raises FileNotFoundError when boundary file cannot be resolved."""
    fake_project = tmp_path / "fake_proj"
    fake_project.mkdir()
    claims_file = fake_project / "claims.json"
    claims_file.write_text(
        json.dumps({
            "project_id": "missing-boundary",
            "registry": "verra",
            "methodology": "VM0007",
            "claimed_area_ha": 5000.0,
            "reporting_period_start": "2020-01-01",
            "reporting_period_end": "2021-01-01",
            "boundary_path": "/nonexistent/boundary.geojson",
        }),
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError, match="Could not resolve boundary file"):
        run(project_dir=fake_project)


def test_pipeline_run_on_project_2469(tmp_path: Path) -> None:
    """Test full pipeline execution on project 2469."""
    proj_dir = Path("data/projects/2469")
    if not (proj_dir / "imagery" / "composites" / "raw_composite_2019.tif").exists():
        pytest.skip("Project 2469 imagery not found")

    out_dir = tmp_path / "output_2469"
    report = run(project_dir=proj_dir, out_dir=out_dir)

    assert report.project_id == "2469"
    assert report.status == VerificationStatus.CONSISTENT
    assert report.area_discrepancy_pct == 0.0
    assert report.canopy_discrepancy_pct is None
    assert report.shortfall_central_ha == 35.0
    assert report.shortfall_low_ha == 284.8
    assert len(report.confidence_reasons) == 6
    assert any("Without ring normalisation" in r for r in report.confidence_reasons)
    assert len(report.observations) == 1
    assert report.confidence == ConfidenceLevel.LOW
    assert (out_dir / "report.json").exists()
    assert (out_dir / "report.html").exists()

    html_content = (out_dir / "report.html").read_text(encoding="utf-8")
    assert "lower bound" in html_content.lower()
    assert "detection limit" in html_content.lower()
    assert "Without ring normalisation" in html_content
    assert html_content.lower().count("verified") == 1
    assert "not a verified biomass gain" in html_content.lower()


def test_render_project_2469_html_constraints(tmp_path: Path) -> None:
    """Verify render works for 2469, output contains 'lower bound', 'detection limit', REDD+ limitation, and does NOT contain 'verified', '\\(', or 'Pre-existing Forest'."""
    proj_dir = Path("data/projects/2469")
    if not (proj_dir / "imagery" / "composites" / "raw_composite_2019.tif").exists():
        pytest.skip("Project 2469 imagery not found")

    out_dir = tmp_path / "render_test"
    report = run(project_dir=proj_dir, out_dir=out_dir)

    html_path = out_dir / "report.html"
    assert html_path.exists()
    html_text = html_path.read_text(encoding="utf-8")

    assert "lower bound" in html_text
    assert "detection limit" in html_text
    assert "Without ring normalisation" in html_text
    assert html_text.lower().count("verified") == 1
    assert "not a verified biomass gain" in html_text.lower()

    assert r"\(" not in html_text
    assert "Pre-existing Forest" not in html_text
    assert (
        "Satellites verify observable claims (area, planting, canopy), not "
        "counterfactual baselines, so avoided-deforestation (REDD+) over-crediting "
        "claims are out of reach."
    ) in html_text


def test_render_demo_project_does_not_leak_2469_sha256(tmp_path: Path) -> None:
    """Verify rendering demo project (and non-2469 reports with missing metadata) does not leak 2469 sha256."""
    sha_2469 = "46d43884d90b48b66d7f5ccf363bc78e03e33ff9e0932883612cbd1c1a83bb54"

    demo_out = tmp_path / "demo_render"
    report = run(project_dir=Path("data/projects/demo"), out_dir=demo_out)
    demo_html = (demo_out / "report.html").read_text(encoding="utf-8")
    assert sha_2469 not in demo_html

    # Also verify full template rendering when project metadata files are absent renders 'not available'
    from carbonverify.report.render import render

    non_demo_report = report.model_copy(update={"project_id": "other-proj", "demo": False})
    other_out = tmp_path / "other_render"
    _, other_html_path = render(non_demo_report, other_out)
    other_html = other_html_path.read_text(encoding="utf-8")
    assert sha_2469 not in other_html
    assert "not available" in other_html


def test_normalization_sensitivity_structure_and_raw_band() -> None:
    """Verify normalization_sensitivity keys exist, flat duplicate keys are deleted, and raw band matches to 2 decimals."""
    proj_dir = Path("data/projects/2469")
    est_path = proj_dir / "estimate.json"
    if not est_path.exists():
        pytest.skip("Project 2469 estimate.json not found")

    with open(est_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # In estimate.json, normalization_sensitivity is kept in satellite_estimate (the copy read by scoring and report)
    assert "satellite_estimate" in data
    sat_est = data["satellite_estimate"]
    assert "normalization_sensitivity" in sat_est
    norm_sens = sat_est["normalization_sensitivity"]

    # Verify normalization_sensitivity keys exist
    assert "areas_by_threshold" in norm_sens
    assert "ring_raw_median" in norm_sens
    assert "raw_obs_grid" in norm_sens
    assert "raw_band" in norm_sens

    # Verify flat duplicate keys were deleted
    for flat_key in ["low", "central", "high", "span_ha", "span_pct", "detection_limit_ha", "detection_limit_pct"]:
        assert flat_key not in norm_sens

    # Verify raw band equals low 1122.50 / central 1440.56 / high 1620.79, span 38.33%, detection limit 13.65%
    raw_band = norm_sens["raw_band"]
    assert round(raw_band["low"], 2) == 1122.50
    assert round(raw_band["central"], 2) == 1440.56
    assert round(raw_band["high"], 2) == 1620.79
    assert round(raw_band["span_pct"], 2) == 38.33
    assert round(raw_band["detection_limit_pct"], 2) == 13.65


def test_normalization_sensitivity_pipeline_invariants_and_render(tmp_path: Path) -> None:
    """Verify quantile-mapped band, status and confidence unchanged, rendered html contains 'Without ring normalisation' and not 'verified'."""
    proj_dir = Path("data/projects/2469")
    if not (proj_dir / "imagery" / "composites" / "raw_composite_2019.tif").exists():
        pytest.skip("Project 2469 imagery not found")

    out_dir = tmp_path / "norm_sens_pipeline_test"
    report = run(project_dir=proj_dir, out_dir=out_dir)

    # Quantile-mapped band remains unchanged
    assert report.estimate.planted_area_obs_low == 1015.20
    assert report.estimate.planted_area_obs_central == 1265.00
    assert report.estimate.planted_area_obs_high == 1505.62

    # Status and confidence remain unchanged
    assert report.status == VerificationStatus.CONSISTENT
    assert report.confidence == ConfidenceLevel.LOW

    # Rendered html contains 'Without ring normalisation' and not 'verified'
    html_file = out_dir / "report.html"
    assert html_file.exists()
    html_content = html_file.read_text(encoding="utf-8")
    assert "Without ring normalisation" in html_content
    assert html_content.lower().count("verified") == 1
    assert "not a verified biomass gain" in html_content.lower()

