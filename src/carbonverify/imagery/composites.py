"""Seasonal median NDVI composites and imagery verification reporting."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds

logger = logging.getLogger(__name__)

# Season definitions: wet (Oct-Mar), dry (Apr-Sep)
WET_MONTHS = {1, 2, 3, 10, 11, 12}
DRY_MONTHS = {4, 5, 6, 7, 8, 9}


def generate_seasonal_composites(
    scene_ndvis: List[Tuple[str, np.ndarray]],  # list of (date_str "YYYY-MM-DD", ndvi_array)
    project_window: Window,
    full_transform: rasterio.Affine,
    crs: rasterio.crs.CRS,
    output_dir: Path,
    years: Tuple[int, ...] = (2019, 2020, 2021, 2022),
) -> Dict[str, Path]:
    """Generate and save seasonal median NDVI composites cropped to project bbox.

    Args:
        scene_ndvis: List of tuples containing (date_str, 2D ndvi_array).
        project_window: Rasterio Window corresponding to project polygon bounds.
        full_transform: Affine transform of the full raster grid.
        crs: Coordinate reference system of the rasters.
        output_dir: Output directory (e.g. imagery/composites/).
        years: Tuple of calendar years to compute composites for.

    Returns:
        Dict mapping composite name (e.g. '2019_wet') to saved GeoTIFF path.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    col_off = int(project_window.col_off)
    row_off = int(project_window.row_off)
    width = int(project_window.width)
    height = int(project_window.height)

    # Window transform for the cropped project bbox
    cropped_transform = rasterio.windows.transform(project_window, full_transform)

    saved_files: Dict[str, Path] = {}

    for year in years:
        for season_name, season_months in [("wet", WET_MONTHS), ("dry", DRY_MONTHS)]:
            # Filter scenes matching year and season
            matching_arrays: List[np.ndarray] = []
            for date_str, ndvi in scene_ndvis:
                y = int(date_str[:4])
                m = int(date_str[5:7])
                if y == year and m in season_months:
                    # Crop ndvi to project window
                    cropped = ndvi[row_off : row_off + height, col_off : col_off + width]
                    matching_arrays.append(cropped)

            if not matching_arrays:
                logger.warning("No scenes found for year %d season %s", year, season_name)
                median_ndvi = np.full((height, width), np.nan, dtype=np.float32)
            else:
                stack = np.stack(matching_arrays, axis=0)
                # Suppress RuntimeWarnings when all slices are NaN
                with np.errstate(invalid="ignore"):
                    median_ndvi = np.nanmedian(stack, axis=0).astype(np.float32)

            out_filename = f"ndvi_composite_{year}_{season_name}.tif"
            out_path = output_dir / out_filename

            profile = {
                "driver": "GTiff",
                "dtype": "float32",
                "nodata": np.nan,
                "width": width,
                "height": height,
                "count": 1,
                "crs": crs,
                "transform": cropped_transform,
                "compress": "deflate",
            }

            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(median_ndvi, 1)

            saved_files[f"{year}_{season_name}"] = out_path
            logger.info("Saved seasonal composite: %s (from %d scenes)", out_path, len(matching_arrays))

    return saved_files


def generate_imagery_report(
    timeseries_rows: List[Dict[str, Any]],
    total_runtime_seconds: float,
    errors: Optional[List[str]] = None,
    years: Tuple[int, ...] = (2019, 2020, 2021, 2022),
    output_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Generate imagery summary report metrics.

    Args:
        timeseries_rows: Rows from timeseries.csv.
        total_runtime_seconds: Elapsed processing runtime.
        errors: List of error messages encountered, if any.
        years: Calendar years included in analysis.
        output_path: Optional path to write imagery_report.json.

    Returns:
        Dict representing imagery_report.json.
    """
    errors = errors or []

    # Filter to project zone rows for scene counts and valid fractions
    proj_rows = [r for r in timeseries_rows if r.get("zone") == "project"]
    if not proj_rows:
        proj_rows = timeseries_rows

    scene_counts_per_year: Dict[str, int] = {str(y): 0 for y in years}
    valid_fractions: List[float] = []
    months_with_scenes: set = set()

    for r in proj_rows:
        date_str = str(r.get("date", ""))
        if len(date_str) >= 7:
            y_str = date_str[:4]
            m_str = date_str[:7]
            if y_str in scene_counts_per_year:
                scene_counts_per_year[y_str] += 1
            # Check if this scene had valid pixels
            vf = float(r.get("valid_fraction", 0.0))
            valid_fractions.append(vf)
            if vf > 0.0:
                months_with_scenes.add(m_str)

    mean_valid_fraction = float(np.mean(valid_fractions)) if valid_fractions else 0.0

    # Determine all possible months for the 4 years
    all_months: List[str] = []
    for y in years:
        for m in range(1, 13):
            all_months.append(f"{y}-{m:02d}")

    months_with_no_valid_scene = [m for m in all_months if m not in months_with_scenes]

    report: Dict[str, Any] = {
        "scene_counts_per_year": scene_counts_per_year,
        "total_scenes_processed": len(proj_rows),
        "mean_valid_fraction": round(mean_valid_fraction, 4),
        "months_with_no_valid_scene": sorted(months_with_no_valid_scene),
        "total_runtime_seconds": round(total_runtime_seconds, 2),
        "errors": errors,
    }

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        logger.info("Saved imagery report to %s", output_path)

    return report
