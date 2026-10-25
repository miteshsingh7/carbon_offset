"""Tests for publication figure generation routines in carbonverify.analysis.figures."""

from pathlib import Path

import pytest

from carbonverify.analysis.figures import (
    generate_cohort_maps_figure,
    generate_decline_map_figure,
    generate_zone_timeseries_figure,
)


def test_generate_zone_timeseries_figure(tmp_path: Path) -> None:
    """Verify zone_timeseries.png generation with below-axes legend and outlier annotation."""
    qc_csv = Path("data/projects/2469/imagery/qc_scenes.csv")
    out_png = tmp_path / "zone_timeseries.png"

    meta = generate_zone_timeseries_figure(
        qc_csv_path=qc_csv,
        output_png_path=out_png,
        reporting_period_start="2021-01-01",
        reporting_period_end="2022-09-30",
        project_id="2469",
    )

    assert out_png.exists()
    assert out_png.stat().st_size > 50_000
    assert meta["file_size"] > 50_000
    assert meta["pass_count"] == 162
    assert meta["fail_count"] > 0
    assert "2021-01-01" in meta["reporting_period_label"]
    assert "2022-09-30" in meta["reporting_period_label"]
    assert "bad_red;low_valid" in meta["annotated_reason"]


def test_generate_decline_map_figure(tmp_path: Path) -> None:
    """Verify decline_map.png generation with first-high cohorts and Hansen classification."""
    proj_dir = Path("data/projects/2469")
    comp_file = proj_dir / "imagery" / "composites" / "raw_composite_2019.tif"
    if not comp_file.exists():
        pytest.skip(f"Required local composite missing: {comp_file}")
    out_png = tmp_path / "decline_map.png"

    meta = generate_decline_map_figure(
        project_dir=proj_dir,
        output_png_path=out_png,
        hansen_dir="data/external/hansen",
    )

    assert out_png.exists()
    assert out_png.stat().st_size > 50_000
    assert meta["file_size"] > 50_000

    # Area metrics
    assert meta["area_D_ha"] == 74.70
    assert meta["ha_19"] == 43.11
    assert meta["ha_20"] == 26.94
    assert meta["ha_21"] == 4.65
    assert meta["largest_ha"] == 10.08

    # Legend text contents
    labels_a = meta["legend_labels_a"]
    assert any("43.11" in lbl for lbl in labels_a)
    assert any("26.94" in lbl for lbl in labels_a)
    assert any("4.65" in lbl for lbl in labels_a)
    assert any("10.08" in lbl for lbl in labels_a)

    labels_b = meta["legend_labels_b"]
    assert any("treecover2000 < 25" in lbl for lbl in labels_b)
    assert any("no loss 2019-2022" in lbl for lbl in labels_b)
    assert any("loss in 2019-2022" in lbl for lbl in labels_b)


def test_generate_cohort_maps_figure(tmp_path: Path) -> None:
    """Verify cohort_maps.png generation."""
    proj_dir = Path("data/projects/2469")
    comp_file = proj_dir / "imagery" / "composites" / "raw_composite_2019.tif"
    if not comp_file.exists():
        pytest.skip(f"Required local composite missing: {comp_file}")
    out_png = tmp_path / "cohort_maps.png"

    meta = generate_cohort_maps_figure(
        project_dir=proj_dir,
        output_png_path=out_png,
    )

    assert out_png.exists()
    assert out_png.stat().st_size > 50_000
    assert meta["file_size"] > 50_000
    assert meta["gain_ha"] > 600.0
