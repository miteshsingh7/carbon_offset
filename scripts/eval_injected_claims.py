#!/usr/bin/env python3
"""Evaluate scoring behaviour on synthetically injected claim levels for project 2469.

Multiplies the extracted claim of VCS 2469 by fixed factors and scores the resulting
claims against the stored satellite observation band. Outputs CSV and Markdown reports.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from carbonverify.schemas import ProjectClaims, SatelliteEstimate, VerificationStatus
from carbonverify.scoring.discrepancy import load_scoring_thresholds, score


def run_eval_injected_claims(
    output_dir: Path = Path("reports"),
    report_json_path: Path = Path("output/2469/report.json"),
    factors: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Execute synthetic claim injection evaluation across factor grid."""
    if factors is None:
        factors = [0.90, 1.00, 1.10, 1.25, 1.30, 1.50, 2.00]

    output_dir.mkdir(parents=True, exist_ok=True)

    if not report_json_path.exists():
        raise FileNotFoundError(f"Project report JSON not found at: {report_json_path}")

    with open(report_json_path, "r", encoding="utf-8") as f:
        rep_data = json.load(f)

    claims = ProjectClaims(**rep_data["claims"])
    estimate = SatelliteEstimate(**rep_data["estimate"])

    base_claimed_ha = float(claims.claimed_area_ha or 0.0)
    if base_claimed_ha <= 0:
        raise ValueError("Stored claimed_area_ha must be greater than 0")

    obs_high = float(estimate.planted_area_obs_high or 0.0)
    obs_low = float(estimate.planted_area_obs_low or 0.0)
    obs_central = float(estimate.planted_area_obs_central or obs_high)

    thresholds = load_scoring_thresholds(None)
    minor_threshold_pct = float(thresholds.minor_discrepancy_pct)
    minor_threshold_frac = minor_threshold_pct / 100.0

    rows: List[Dict[str, Any]] = []
    tp = 0
    fp = 0
    tn = 0
    fn = 0
    unclassified: List[Dict[str, Any]] = []

    for factor in factors:
        claimed_ha = base_claimed_ha if factor == 1.00 else round(factor * base_claimed_ha, 4)
        c_injected = claims.model_copy(update={"claimed_area_ha": claimed_ha})

        result = score(claims=c_injected, estimate=estimate)

        span_pct: Optional[float] = None
        det_limit_pct: Optional[float] = None
        if result.confidence_reasons:
            first_reason = result.confidence_reasons[0]
            m_span = re.search(r"span / claimed = ([0-9.]+)%", first_reason)
            if m_span:
                span_pct = float(m_span.group(1))
            m_det = re.search(r"detection limit: \(claimed - obs_low\) / claimed = ([0-9.]+)%", first_reason)
            if m_det:
                det_limit_pct = float(m_det.group(1))

        if span_pct is None:
            span_pct = round(((obs_high - obs_low) / claimed_ha) * 100.0, 2)
        if det_limit_pct is None:
            det_limit_pct = round(((claimed_ha - obs_low) / claimed_ha) * 100.0, 2)

        st_str = result.status.value
        conf_str = result.confidence.value

        is_overclaim = factor > 1.00
        is_flag = st_str in ("MINOR", "MAJOR")
        is_consistent = st_str == "CONSISTENT"

        if is_overclaim:
            if is_flag:
                tp += 1
                classification = "TP"
            elif is_consistent:
                fn += 1
                classification = "FN"
            else:
                unclassified.append({"factor": factor, "status": st_str})
                classification = "NOT_FLAGGED_NOT_CONSISTENT"
        else:
            if is_flag:
                fp += 1
                classification = "FP"
            elif is_consistent:
                tn += 1
                classification = "TN"
            else:
                unclassified.append({"factor": factor, "status": st_str})
                classification = "NOT_FLAGGED_NOT_CONSISTENT"

        row = {
            "factor": factor,
            "claimed_ha": claimed_ha,
            "status": st_str,
            "confidence": conf_str,
            "area_discrepancy_pct": result.area_discrepancy_pct,
            "shortfall_central_ha": result.shortfall_central_ha,
            "shortfall_low_ha": result.shortfall_low_ha,
            "detection_limit_pct": det_limit_pct,
            "band_span_pct": span_pct,
            "classification": classification,
        }
        rows.append(row)

    # Precision & Recall
    precision_str = f"{(tp / (tp + fp)):.4f}" if (tp + fp) > 0 else "not defined"
    recall_str = f"{(tp / (tp + fn)):.4f}" if (tp + fn) > 0 else "not defined"

    # Smallest flagged factor
    flagged_factors = [r["factor"] for r in rows if r["status"] in ("MINOR", "MAJOR")]
    smallest_flagged_factor = min(flagged_factors) if flagged_factors else None

    # Analytical calculation
    claimed_min = obs_high / (1.0 - minor_threshold_frac)
    factor_analytic = claimed_min / base_claimed_ha
    pct_over_claim = ((claimed_min - base_claimed_ha) / base_claimed_ha) * 100.0
    pct_over_obs_high = ((claimed_min - obs_high) / obs_high) * 100.0
    confidence_values = ", ".join(sorted(set(r["confidence"] for r in rows)))

    disagree = False
    if smallest_flagged_factor is not None:
        # Check if the smallest flagged factor is the first grid point exceeding factor_analytic
        prev_factors = [f for f in factors if f < smallest_flagged_factor]
        if prev_factors:
            max_unflagged = max(prev_factors)
            if not (max_unflagged <= factor_analytic <= smallest_flagged_factor):
                disagree = True
        elif factor_analytic > smallest_flagged_factor:
            disagree = True

    # 1. Write CSV
    csv_path = output_dir / "eval_injected_claims.csv"
    csv_fieldnames = [
        "factor",
        "claimed_ha",
        "status",
        "confidence",
        "area_discrepancy_pct",
        "shortfall_central_ha",
        "shortfall_low_ha",
        "detection_limit_pct",
        "band_span_pct",
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r[k] for k in csv_fieldnames})

    # 2. Write Markdown
    md_path = output_dir / "eval_injected_claims.md"
    md_lines: List[str] = [
        "Synthetic test: the claim of VCS 2469 was multiplied by fixed factors and the stored satellite band was scored again. These are not documented over-crediting cases. Precision and recall here describe the scoring rule on injected claims only.",
        "",
        "### Injected Claims Evaluation Matrix",
        "",
        "| Factor | Claimed Area (ha) | Status | Confidence | Discrepancy (%) | Central Shortfall (ha) | Low Shortfall (ha) | Detection Limit (%) | Band Span (%) |",
        "| ---: | ---: | :--- | :--- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in rows:
        md_lines.append(
            f"| {r['factor']:.2f} | {r['claimed_ha']:.2f} | {r['status']} | {r['confidence']} | "
            f"{r['area_discrepancy_pct']:.2f}% | {r['shortfall_central_ha']:.2f} | {r['shortfall_low_ha']:.2f} | "
            f"{r['detection_limit_pct']:.2f}% | {r['band_span_pct']:.2f}% |"
        )

    md_lines.extend([
        "",
        "### Classification Counts & Metrics",
        "",
        f"- True Positives (TP, factor > 1.00 and flagged): {tp}",
        f"- False Positives (FP, factor <= 1.00 and flagged): {fp}",
        f"- True Negatives (TN, factor <= 1.00 and consistent): {tn}",
        f"- False Negatives (FN, factor > 1.00 and consistent): {fn}",
    ])
    if unclassified:
        md_lines.append(f"- Not flagged, not consistent: {len(unclassified)} ({unclassified})")
    else:
        md_lines.append("- Not flagged, not consistent: 0")

    md_lines.extend([
        f"- Precision: {precision_str}",
        f"- Recall: {recall_str}",
        "",
        "### How to read this",
        "",
        "1. The scoring rule is one-sided: it flags only a claim larger than obs_high / (1 - minor threshold). No claim at or below the stored claim can be flagged, so FP = 0 and precision = 1.0 follow from the rule, not from a tested behaviour.",
        f"2. The labels treat the stored claim of {base_claimed_ha:.2f} ha as the true area; that is not known.",
        f"3. Recall depends on the grid of factors used. The grid-independent result is the smallest claim that is flagged: {claimed_min:.2f} ha (factor {factor_analytic:.4f}), which is {pct_over_claim:.2f}% above the stored claim and {pct_over_obs_high:.2f}% above obs_high.",
        f"4. Every row has confidence {confidence_values}.",
        "",
        "### Flag Threshold Analysis",
        "",
        f"- Smallest observed factor producing a flag: {smallest_flagged_factor:.2f}" if smallest_flagged_factor else "- Smallest observed factor producing a flag: None",
        f"- Analytically derived minimum claim for MINOR status: {claimed_min:.2f} ha (factor {factor_analytic:.4f})",
        f"- Agreement status: {'Disagreement detected' if disagree else 'Observed smallest flagged factor matches analytical threshold position on the factor grid'}",
        "",
        "### Detection Limit Disclosure",
        "",
        f"The detection limit of the stored observation band is (claimed - obs_low) / claimed = {rows[1]['detection_limit_pct']:.2f}% ({rows[1]['shortfall_low_ha']:.2f} ha) at the stated claim of {base_claimed_ha:.2f} ha.",
    ])

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    return {
        "rows": rows,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "unclassified": unclassified,
        "precision": precision_str,
        "recall": recall_str,
        "smallest_flagged_factor": smallest_flagged_factor,
        "claimed_min": claimed_min,
        "factor_analytic": factor_analytic,
        "pct_over_claim": pct_over_claim,
        "pct_over_obs_high": pct_over_obs_high,
        "confidence_values": confidence_values,
        "base_claimed_ha": base_claimed_ha,
        "disagree": disagree,
        "csv_path": csv_path,
        "md_path": md_path,
    }


if __name__ == "__main__":
    result = run_eval_injected_claims()
    print("=== Injected Claims Evaluation Completed ===")
    print(f"Factors evaluated: {len(result['rows'])}")
    print(f"TP: {result['tp']}, FP: {result['fp']}, TN: {result['tn']}, FN: {result['fn']}")
    print(f"Precision: {result['precision']}")
    print(f"Recall: {result['recall']}")
    print(f"Observed smallest flagged factor: {result['smallest_flagged_factor']}")
    print(f"Analytic minimum flagged claim: {result['claimed_min']:.2f} ha (factor {result['factor_analytic']:.4f})")
    print(f"Thresholds agree: {not result['disagree']}")
    print(f"Reports written to: {result['csv_path']} and {result['md_path']}")
