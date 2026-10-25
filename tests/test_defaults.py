"""Tests verifying absence of project-2469 hard-coded defaults and numeric defaults."""

from pathlib import Path
import re
import pytest

from carbonverify.analysis.decline import run_decline_analysis
from carbonverify.analysis.hansen import run_forest_allowance_check


def test_missing_claim_arguments_raise_type_error() -> None:
    """Calling decline and hansen functions without required claim arguments raises TypeError."""
    proj_dir = Path("data/projects/2469")
    if not (proj_dir / "imagery" / "composites" / "raw_composite_2019.tif").exists():
        pytest.skip("Project 2469 imagery not found")

    with pytest.raises(TypeError):
        # Missing required positional argument: forest_allowance_ha
        run_decline_analysis(proj_dir)  # type: ignore[call-arg]

    with pytest.raises(TypeError):
        # Missing required positional arguments: claimed_planted_ha and claimed_forest_allowance_ha
        run_forest_allowance_check(proj_dir)  # type: ignore[call-arg]


def test_fake_claims_produce_derived_results() -> None:
    """Calls with fake claim (planted 1000, allowance 200) produce derived values, none equal to 2469."""
    proj_dir = Path("data/projects/2469")
    if not (proj_dir / "imagery" / "composites" / "raw_composite_2019.tif").exists():
        pytest.skip("Project 2469 imagery not found")

    hansen_res = run_forest_allowance_check(
        proj_dir,
        claimed_planted_ha=1000.0,
        claimed_forest_allowance_ha=200.0,
    )
    # 2469 values were 746.62 and 205.62
    assert hansen_res["f_star_06_ha"] != 746.62
    assert hansen_res["margin_06_ha"] != 205.62
    # Derived from fake claims: A2022(0.60) = 2046.62; F*(0.60) = 2046.62 - 1000 = 1046.62; Margin = 1046.62 - 200 = 846.62
    assert hansen_res["f_star_06_ha"] == 1046.62
    assert hansen_res["margin_06_ha"] == 846.62

    decline_res = run_decline_analysis(
        proj_dir,
        forest_allowance_ha=200.0,
    )
    obs_excl = decline_res["sensitivity_t70_excl_g22"]["observed_area_excl_g22_ha"]
    # 2469 value was 1053.12
    assert obs_excl != 1053.12
    # Derived from fake allowance: A2022(0.70) = 1720.06; G22 = 125.94; obs = 1720.06 - 125.94 - 200 = 1394.12
    assert obs_excl == 1394.12


def test_no_hardcoded_defaults_or_forbidden_get_in_src() -> None:
    """Regex test over src/ ensuring no 2469 hard-coded numbers and no numeric defaults on forbidden keys."""
    num_pat = re.compile(r"\b(1300\.0|541\.0|956\.0|0\.891)\b")
    forbidden_keys = [
        "scene_count",
        "mean_cloud_cover_pct",
        "mean_valid_fraction",
        "scheduled_2019_2020",
        "scheduled_2020",
        "raw_ha",
        "loss_ha_total",
    ]
    get_pats = [
        (k, re.compile(r"\.get\([\"']" + k + r"[\"']\s*,\s*-?\d"))
        for k in forbidden_keys
    ]

    violations = []
    src_dir = Path("src")
    assert src_dir.exists(), "src directory not found"

    for py_file in src_dir.rglob("*.py"):
        lines = py_file.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines, 1):
            if num_pat.search(line):
                violations.append(f"{py_file}:{idx}: forbidden number: {line.strip()}")
            for k, pat in get_pats:
                if pat.search(line):
                    violations.append(f"{py_file}:{idx}: numeric default for key '{k}': {line.strip()}")

    assert not violations, "Found violations in src/:\n" + "\n".join(violations)


def test_project_with_missing_claims_leaves_dependents_none(tmp_path: Path) -> None:
    """A project with claims lacking natural_forest_ha and claimed_area_ha runs plantation_area_estimate without raising and leaves dependent fields None."""
    from carbonverify.analysis.estimate import plantation_area_estimate
    from carbonverify.schemas import ProjectClaims

    proj_dir = Path("data/projects/2469")
    comp_file = proj_dir / "imagery" / "composites" / "raw_composite_2019.tif"
    if not comp_file.exists():
        pytest.skip(f"Required local composite missing: {comp_file}")

    claims = ProjectClaims(
        project_id="missing_claims_test",
        claimed_area_ha=None,
        natural_forest_ha=None,
    )

    out_file = tmp_path / "estimate_missing.json"
    res = plantation_area_estimate(proj_dir, claims=claims, output_json_path=out_file)

    assert res["forest_allowance_ha"] is None
    sat_est = res["satellite_estimate"]
    assert sat_est.get("forest_allowance_check") is None
    assert sat_est.get("decline_analysis") is None

    raw_band = res.get("normalization_sensitivity", {}).get("raw_band", {})
    assert raw_band.get("span_pct") is None
    assert raw_band.get("detection_limit_ha") is None
    assert raw_band.get("detection_limit_pct") is None

