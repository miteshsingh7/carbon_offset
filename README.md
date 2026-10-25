# carbonverify

`carbonverify` cross-checks carbon-offset project claims against free public remote sensing data.
Boundaries are loaded from the project's KML/GeoJSON file; registry PDFs give the
claims (areas, periods, credits, forest allowance, planting schedule). No paid
APIs are used.
Using Sentinel-2 Level-2A imagery, it builds cloud-filtered annual dry-season NDVI composites normalized via reference rings.
It assesses observable planted canopy against claims using strict hysteresis cohort tracking and sensitivity grids.
Finally, it renders comprehensive discrepancy reports with observational confidence ratings and audit provenance.

## Installation and Execution

### Installation
```bash
pip install -e .
```

### Execution for Project 2469
Registry documents are not included: download the PDD and monitoring report for VCS 2469 from the Verra registry into data/projects/2469/docs/ and run `carbonverify extract`.

```bash
# Extract reported claims across project documentation (supported path scanning both pdd.pdf and monitoring_report.pdf)
carbonverify extract --project data/projects/2469

# Run full pipeline for Project 2469
carbonverify run --project data/projects/2469 --out-dir output/2469

# Run test suite
pytest
```

### Viewer
Install app dependencies:
```bash
pip install -e ".[app]"
```

Launch the interactive viewer:
```bash
streamlit run app/streamlit_app.py --server.address 127.0.0.1
```
> **Notes:**
> - The map's base tiles need an internet connection in the browser.
> - The viewer only reads `output/<project>/` files (zero recomputation).

### Web UI
`carbonverify serve` serves a read-only local app from output/<project>/ at 127.0.0.1:8765; Overview, Registry Claims and Planted Area Test are built, other planned pages are not built.

## Repository Layout
- `src/carbonverify/cli.py`: Command-line interface definitions and entry points (`extract`, `run`).
- `src/carbonverify/pipeline.py`: End-to-end orchestration linking extraction, analysis, scoring, and reporting.
- `src/carbonverify/schemas.py`: Pydantic domain models and enums for claims, satellite estimates, and reports.
- `src/carbonverify/claims/extractor.py`: Multi-strategy claims extraction coordinator with quote checking.
- `src/carbonverify/claims/rule_based.py`: Zero-cost regex and keyword pattern matcher for registry PDFs.
- `src/carbonverify/claims/pdf_parser.py`: PDF layout and text parser with per-page caching and SHA-256 checksums.
- `src/carbonverify/claims/planting_schedule.py`: Tabular planting record parsing from monitoring report tables.
- `src/carbonverify/claims/normalizer.py`: Area units, date ranges, credit volumes, and quote whitespace normalization.
- `src/carbonverify/claims/ollama.py`: Optional local LLM fallback client for unfilled claim fields.
- `src/carbonverify/claims/retrieval.py`: Context retrieval and keyword ranking across cached PDF pages.
- `src/carbonverify/claims/llm.py`: Abstract LLM extraction interfaces and prompt protocols.
- `src/carbonverify/imagery/fetch.py`: Free public STAC client for Sentinel-2 L2A tile catalog discovery.
- `src/carbonverify/imagery/composites.py`: Seasonal median composite aggregation and scene filtering.
- `src/carbonverify/imagery/radiometry.py`: SCL cloud masking, red band offset detection, and valid fraction checks.
- `src/carbonverify/imagery/boundary.py`: Vector boundary loading, UTM coordinate reprojecting, and geometry buffering.
- `src/carbonverify/analysis/composites.py`: Quantile mapping and additive ring normalisation algorithms.
- `src/carbonverify/analysis/estimate.py`: Multi-threshold canopy area evaluation, bootstrapping, and observation bands.
- `src/carbonverify/analysis/decline.py`: Connected components analysis for canopy decline and first-high cohorts.
- `src/carbonverify/analysis/hansen.py`: Global Forest Change (GFC) 30 m tree-cover and annual loss cross-checks.
- `src/carbonverify/analysis/figures.py`: Publication figure generation (`zone_timeseries`, `decline_map`, `cohort_maps`).
- `src/carbonverify/scoring/discrepancy.py`: Status evaluation, shortfall computation, and confidence scoring.
- `src/carbonverify/report/render.py`: Report HTML and JSON report generation with recorded SHA-256 hashes.
- `src/carbonverify/viewer.py`: Data loaders and geometry extraction routines for the interactive viewer.
- `app/streamlit_app.py`: Streamlit multi-tab verification viewer and Folium map interface.

## Results for Project 2469
- **Status:** CONSISTENT: no shortfall detected at the generous end of the band.
- **Confidence:** `LOW` (observation band span and detection limit exceed tolerance thresholds).
- **Observation Band (Quantile-Mapped):** [1,015.20, 1,505.62] ha; **Central (Median):** 1,265.00 ha.
- **Band Span:** 490.42 ha (37.72% of claim).
- **Detection Limit:** 21.91% of claim (284.80 ha shortfall at the lower bound).
- **Normalisation Sensitivity (Without Ring Normalisation / RAW):**
  - RAW Band: [1,122.50, 1,620.79] ha; Central: 1,440.56 ha.
  - RAW Span: 498.29 ha (38.33% of claim); RAW Detection Limit: 13.65% (177.50 ha).
- **Natural Forest Allowance Break-Even (F\*):**
  - Generous bound: F*(T = 0.60) = 746.62 ha (a 205.62 ha margin above the claimed 541.00 ha allowance).
  - Strict bound: F*(T = 0.75) = 256.20 ha (the 541.00 ha allowance exceeds the 256.20 ha break-even by 284.80 ha).

## File Guide
- `ndvi_qm_*.tif`: Primary satellite product generated via annual percentile quantile mapping onto the 2019 reference ring.
- `norm_composite_*.tif`: rejected additive normalisation output; not used by any step; kept for reference.
- **Data Sources & URLs:**
  - Sentinel-2 L2A STAC discovery endpoint constant (`EARTH_SEARCH_URL` in `src/carbonverify/imagery/fetch.py`): `https://earth-search.aws.element84.com/v1`.
  - Hansen Global Forest Change v1.10 tiles download URL (in `src/carbonverify/analysis/hansen.py`): `https://storage.googleapis.com/earthenginepartners-hansen/GFC-2022-v1.10/` (e.g. `Hansen_GFC-2022-v1.10_treecover2000_20S_060W.tif` and `Hansen_GFC-2022-v1.10_lossyear_20S_060W.tif`).
- **Git-Ignored Files & Regeneration:**
  - `data/projects/*/imagery/cache/`: Cached Sentinel-2 L2A scene NPZ arrays. Regenerated by running `carbonverify run`.
  - `data/projects/*/imagery/composites/*.tif`: Annual cloud-filtered dry-season GeoTIFF composites. Regenerated by `carbonverify run` from scene arrays.
  - `data/external/hansen/*.tif`: Hansen Global Forest Change v1.10 tiles (`20S_060W` treecover2000 and lossyear). Downloaded free from public Google/University of Maryland GFC storage.
  - `scratch/`: Scratch and throwaway analytical scripts.
  - `.DS_Store`: Operating system file metadata.

## Reproducibility
The local scene cache (`data/projects/*/imagery/cache/`) and Hansen tiles are git-ignored. A full re-fetch may query newer catalog versions or slightly alter scenes/items over time, which would modify raw composite SHA-256 hashes. Pinned hashes in `report.json` refer specifically to the cached data used for reported results. Regeneration from scratch involves downloading and processing approximately 190 Sentinel-2 scenes (~1.4 GB total).

## Scope and Deviations
Only project 2469 is built; imagery comes from AWS Earth Search, not Copernicus Data Space; NDVI thresholds were chosen, not calibrated; matches between planting-schedule cohorts and T = 0.70 areas are post hoc, not validation.

## Methodology Limitations
- See Section 6 of `output/2469/report.html` for complete methodological constraints.
- Crucially, satellites observe physical canopy presence and land-use change, not counterfactual baselines, meaning avoided-deforestation (REDD+) baseline over-crediting claims cannot be evaluated through remote sensing alone.
