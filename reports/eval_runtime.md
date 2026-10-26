# Runtime Evaluation Report

Wall-clock runtime performance measured using `time.perf_counter` across 3 repetitions per execution phase.

## Machine Execution Times

### Document Claims Extraction (`carbonverify extract --project data/projects/2469`)

- Repetition 1: 3.6100 s
- Repetition 2: 2.5308 s
- Repetition 3: 2.6928 s
- **Median Runtime**: 2.6928 s

### Pipeline Run (`carbonverify run --project data/projects/2469 --out-dir /tmp/eval_run_out`)

- Repetition 1: 4.5413 s
- Repetition 2: 4.0272 s
- Repetition 3: 4.0893 s
- **Median Runtime**: 4.0893 s

## What was timed

Stages executed during `carbonverify run --project data/projects/2469` when `estimate.json` and composites already exist:

- Recomputed stages:
  - extract claims: recomputed (`src/carbonverify/pipeline.py:55`)
  - score: recomputed (`src/carbonverify/pipeline.py:116`)
  - render report: recomputed (`src/carbonverify/pipeline.py:159`)
- Stages read from stored files:
  - load imagery or timeseries: read from stored file (`src/carbonverify/imagery/fetch.py:712`)
  - build composites: read from stored file (`src/carbonverify/imagery/fetch.py:712`, `src/carbonverify/pipeline.py:128`)
  - plantation_area_estimate: read from stored file (`src/carbonverify/analysis/estimate.py:1143`)

The imagery download and the composite building were not timed here; the cold-run timing is taken on a project that is run from scratch.

The pipeline run includes claim extraction; the two timings are not added together.

## Stored Satellite Imagery Acquisition Baseline

Statistics recorded during the initial public Sentinel-2 L2A catalog query and scene ingestion:

- **Stored fetch runtime**: not recorded (imagery_report.json holds 0.0)
- **Total Scenes Ingested**: 185
- **Scene Distribution by Year**: {"2019": 40, "2020": 53, "2021": 46, "2022": 46}

## Manual baseline

Not measured. A manual baseline must come from an accepted benchmark; no figure is assumed here.

Manual baseline (hours per project): ____
