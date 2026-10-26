"""Tests for synthetic claim injection evaluation.

Checks reproducing the stored status and observation band at factor 1.00,
verifies CSV output format per factor, and ensures confusion counts sum
to the evaluated factors.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

from carbonverify.schemas import ProjectClaims, SatelliteEstimate
from carbonverify.scoring.discrepancy import score
from scripts.eval_injected_claims import run_eval_injected_claims


REPORT_PATH = Path("output/2469/report.json")
ESTIMATE_PATH = Path("data/projects/2469/estimate.json")
INJECTED_MD_PATH = Path("reports/eval_injected_claims.md")
RUNTIME_MD_PATH = Path("reports/eval_runtime.md")
INJECTED_CSV_PATH = Path("reports/eval_injected_claims.csv")


@pytest.fixture(autouse=True)
def check_prerequisites():
    """Skip test module if required stored artifacts are missing."""
    if not REPORT_PATH.exists():
        pytest.skip(f"Missing required artifact path: {REPORT_PATH}")
    if not ESTIMATE_PATH.exists():
        pytest.skip(f"Missing required artifact path: {ESTIMATE_PATH}")


def test_factor_one_reproduces_stored_results() -> None:
    """(a) Factor 1.00 reproduces status CONSISTENT, confidence LOW and observation band."""
    with open(REPORT_PATH, "r", encoding="utf-8") as f:
        rep_data = json.load(f)

    claims = ProjectClaims(**rep_data["claims"])
    estimate = SatelliteEstimate(**rep_data["estimate"])

    result = score(claims=claims, estimate=estimate)

    assert result.status.value == "CONSISTENT"
    assert result.confidence.value == "LOW"

    obs_low = float(estimate.planted_area_obs_low)
    obs_high = float(estimate.planted_area_obs_high)
    assert [obs_low, obs_high] == [1015.20, 1505.62]


def test_csv_has_one_row_per_factor(tmp_path: Path) -> None:
    """(b) Generated CSV has exactly one row per evaluated factor."""
    factors = [0.90, 1.00, 1.10, 1.25, 1.30, 1.50, 2.00]
    out_dir = tmp_path / "reports"
    res = run_eval_injected_claims(output_dir=out_dir, report_json_path=REPORT_PATH, factors=factors)

    csv_path = res["csv_path"]
    assert csv_path.exists()

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    assert len(reader) == len(factors)
    recorded_factors = [float(row["factor"]) for row in reader]
    assert recorded_factors == factors


def test_confusion_counts_sum_to_factors(tmp_path: Path) -> None:
    """(c) Confusion counts (TP + FP + TN + FN + unclassified) sum to factor count."""
    factors = [0.90, 1.00, 1.10, 1.25, 1.30, 1.50, 2.00]
    out_dir = tmp_path / "reports"
    res = run_eval_injected_claims(output_dir=out_dir, report_json_path=REPORT_PATH, factors=factors)

    total_confusion = res["tp"] + res["fp"] + res["tn"] + res["fn"] + len(res["unclassified"])
    assert total_confusion == len(factors)
    assert res["tp"] == 3
    assert res["fp"] == 0
    assert res["tn"] == 2
    assert res["fn"] == 2


def test_md_contains_required_strings() -> None:
    """Step 3a: the md contains strings 'follow from the rule' and 'not recorded'."""
    assert INJECTED_MD_PATH.exists(), f"Missing {INJECTED_MD_PATH}"
    assert RUNTIME_MD_PATH.exists(), f"Missing {RUNTIME_MD_PATH}"

    injected_text = INJECTED_MD_PATH.read_text(encoding="utf-8")
    runtime_text = RUNTIME_MD_PATH.read_text(encoding="utf-8")

    assert "follow from the rule" in injected_text
    assert "not recorded" in runtime_text


def test_how_to_read_this_numbers_equal_csv_values() -> None:
    """Step 3b: the numbers in 'How to read this' equal the values in the CSV."""
    assert INJECTED_MD_PATH.exists(), f"Missing {INJECTED_MD_PATH}"
    assert INJECTED_CSV_PATH.exists(), f"Missing {INJECTED_CSV_PATH}"

    injected_text = INJECTED_MD_PATH.read_text(encoding="utf-8")
    with open(INJECTED_CSV_PATH, "r", encoding="utf-8") as f:
        csv_rows = list(csv.DictReader(f))

    # 1. Stored claim in point 2 equals CSV row for factor 1.00
    m_claim = re.search(r"stored claim of ([0-9.]+) ha", injected_text)
    assert m_claim is not None, "Could not find stored claim in 'How to read this'"
    md_claim = float(m_claim.group(1))

    row_factor_1 = next(r for r in csv_rows if float(r["factor"]) == 1.00)
    csv_claim = float(row_factor_1["claimed_ha"])
    assert md_claim == csv_claim

    # 2. Confidence in point 4 equals confidence values across all rows in CSV
    m_conf = re.search(r"Every row has confidence ([A-Z]+)\.", injected_text)
    assert m_conf is not None, "Could not find confidence in 'How to read this'"
    md_conf = m_conf.group(1)

    csv_confs = set(r["confidence"] for r in csv_rows)
    assert csv_confs == {md_conf}

    # 3. Smallest flagged claim in point 3 correctly separates CSV rows by status
    m_min = re.search(r"smallest claim that is flagged: ([0-9.]+) ha \(factor ([0-9.]+)\)", injected_text)
    assert m_min is not None, "Could not find smallest flagged claim in 'How to read this'"
    claimed_min = float(m_min.group(1))
    factor_min = float(m_min.group(2))

    for r in csv_rows:
        c_ha = float(r["claimed_ha"])
        fac = float(r["factor"])
        if fac < factor_min:
            assert r["status"] == "CONSISTENT"
            assert c_ha < claimed_min
        else:
            assert r["status"] in ("MINOR", "MAJOR")
            assert c_ha > claimed_min

