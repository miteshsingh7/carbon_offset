#!/usr/bin/env python3
"""Runtime benchmark evaluation script.

Times execution of claims extraction and pipeline execution over 3 repetitions.
Loads stored STAC catalog fetch runtime statistics from imagery_report.json.
Checks integrity of reference artifacts after execution.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

EXPECTED_HASHES = {
    "data/projects/2469/estimate.json": "79ca08edd9247ce25dc2cec76d06c6a765ac204d9720128a2c7fa02773510a47",
    "output/2469/report.json": "db803cbad924ba169d4ae43868bbf9ea1118f7feacb59ee98eccc75f63519f78",
    "output/2469/report.html": "6e6df1576167f8f2a4da93334606e3b52c624a6e874d98eeb9ebe407f1a0ab4e",
}


def compute_sha256(path: Path) -> str:
    """Compute hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_runtime_evaluation(
    output_dir: Path = Path("reports"),
    eval_out_dir: Path = Path("/tmp/eval_run_out"),
    repetitions: int = 3,
) -> Dict[str, Any]:
    """Execute runtime benchmarks and verify artifact integrity."""
    output_dir.mkdir(parents=True, exist_ok=True)
    eval_out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Benchmark: carbonverify extract --project data/projects/2469
    extract_cmd = ["carbonverify", "extract", "--project", "data/projects/2469"]
    extract_times: List[float] = []
    print(f"Running extract benchmark ({repetitions} repetitions)...")
    for i in range(1, repetitions + 1):
        t0 = time.perf_counter()
        subprocess.run(extract_cmd, check=True, capture_output=True, text=True)
        elapsed = time.perf_counter() - t0
        extract_times.append(elapsed)
        print(f"  Extract rep {i}: {elapsed:.4f} s")

    # 2. Benchmark: carbonverify run --project data/projects/2469 --out-dir /tmp/eval_run_out
    run_cmd = ["carbonverify", "run", "--project", "data/projects/2469", "--out-dir", str(eval_out_dir)]
    run_times: List[float] = []
    print(f"Running pipeline run benchmark ({repetitions} repetitions)...")
    for i in range(1, repetitions + 1):
        t0 = time.perf_counter()
        subprocess.run(run_cmd, check=True, capture_output=True, text=True)
        elapsed = time.perf_counter() - t0
        run_times.append(elapsed)
        print(f"  Pipeline run rep {i}: {elapsed:.4f} s")

    extract_median = statistics.median(extract_times)
    run_median = statistics.median(run_times)

    # 3. Read stored full-fetch runtime and scene counts from imagery_report.json
    img_report_path = Path("data/projects/2469/imagery/imagery_report.json")
    if not img_report_path.exists():
        raise FileNotFoundError(f"Missing imagery report: {img_report_path}")

    with open(img_report_path, "r", encoding="utf-8") as f:
        img_data = json.load(f)

    stored_runtime_sec = img_data.get("total_runtime_seconds")
    total_scenes = img_data.get("total_scenes_processed")
    scene_counts = img_data.get("scene_counts_per_year")

    # 4. Verify artifact hashes against Step 0c baselines
    mismatches: List[str] = []
    for file_str, expected_hash in EXPECTED_HASHES.items():
        f_path = Path(file_str)
        actual_hash = compute_sha256(f_path)
        if actual_hash != expected_hash:
            mismatches.append(f"{file_str}: expected {expected_hash}, got {actual_hash}")

    if mismatches:
        print(f"WARNING: Hash mismatches detected: {mismatches}")
        print("Restoring from /tmp/backup_2469_eval and /tmp/backup_out_2469_eval...")
        b_data = Path("/tmp/backup_2469_eval")
        b_out = Path("/tmp/backup_out_2469_eval")
        if b_data.exists():
            shutil.rmtree("data/projects/2469")
            shutil.copytree(b_data, "data/projects/2469")
        if b_out.exists():
            shutil.rmtree("output/2469")
            shutil.copytree(b_out, "output/2469")
        raise RuntimeError(f"Artifact integrity compromised: {mismatches}")
    else:
        print("All reference artifact SHA-256 digests match expected values.")

    # 5. Write Markdown report
    md_path = output_dir / "eval_runtime.md"
    md_lines: List[str] = [
        "# Runtime Evaluation Report",
        "",
        "Wall-clock runtime performance measured using `time.perf_counter` across 3 repetitions per execution phase.",
        "",
        "## Machine Execution Times",
        "",
        "### Document Claims Extraction (`carbonverify extract --project data/projects/2469`)",
        "",
    ]
    for idx, t in enumerate(extract_times, 1):
        md_lines.append(f"- Repetition {idx}: {t:.4f} s")
    md_lines.extend([
        f"- **Median Runtime**: {extract_median:.4f} s",
        "",
        "### Pipeline Run (`carbonverify run --project data/projects/2469 --out-dir /tmp/eval_run_out`)",
        "",
    ])
    for idx, t in enumerate(run_times, 1):
        md_lines.append(f"- Repetition {idx}: {t:.4f} s")
    md_lines.extend([
        f"- **Median Runtime**: {run_median:.4f} s",
        "",
        "## What was timed",
        "",
        "Stages executed during `carbonverify run --project data/projects/2469` when `estimate.json` and composites already exist:",
        "",
        "- Recomputed stages:",
        "  - extract claims: recomputed (`src/carbonverify/pipeline.py:55`)",
        "  - score: recomputed (`src/carbonverify/pipeline.py:116`)",
        "  - render report: recomputed (`src/carbonverify/pipeline.py:159`)",
        "- Stages read from stored files:",
        "  - load imagery or timeseries: read from stored file (`src/carbonverify/imagery/fetch.py:712`)",
        "  - build composites: read from stored file (`src/carbonverify/imagery/fetch.py:712`, `src/carbonverify/pipeline.py:128`)",
        "  - plantation_area_estimate: read from stored file (`src/carbonverify/analysis/estimate.py:1143`)",
        "",
        "The imagery download and the composite building were not timed here; the cold-run timing is taken on a project that is run from scratch.",
        "",
        "The pipeline run includes claim extraction; the two timings are not added together.",
        "",
        "## Stored Satellite Imagery Acquisition Baseline",
        "",
        "Statistics recorded during the initial public Sentinel-2 L2A catalog query and scene ingestion:",
        "",
        f"- **Stored fetch runtime**: not recorded (imagery_report.json holds {stored_runtime_sec})",
        f"- **Total Scenes Ingested**: {total_scenes}",
        f"- **Scene Distribution by Year**: {json.dumps(scene_counts)}",
        "",
        "## Manual baseline",
        "",
        "Not measured. A manual baseline must come from an accepted benchmark; no figure is assumed here.",
        "",
        "Manual baseline (hours per project): ____",
    ])

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    return {
        "extract_times": extract_times,
        "extract_median": extract_median,
        "run_times": run_times,
        "run_median": run_median,
        "stored_runtime_sec": stored_runtime_sec,
        "total_scenes": total_scenes,
        "scene_counts": scene_counts,
        "md_path": md_path,
    }


if __name__ == "__main__":
    res = run_runtime_evaluation()
    print("=== Runtime Evaluation Completed ===")
    print(f"Report written to: {res['md_path']}")
