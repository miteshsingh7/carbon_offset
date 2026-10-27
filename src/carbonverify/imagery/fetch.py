"""Satellite imagery acquisition, COG windowed fetching, and zonal statistics."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from dataclasses import dataclass, field
from datetime import date, datetime
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import geopandas as gpd
import numpy as np
from pystac_client import Client
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.windows import Window, from_bounds
from shapely.geometry import shape

from carbonverify.imagery.boundary import (
    BoundarySelectionError,
    prepare_project_and_reference_boundaries,
)
from carbonverify.imagery.composites import (
    generate_imagery_report,
    generate_seasonal_composites,
)
from carbonverify.imagery.radiometry import (
    compute_ndvi,
    create_scl_mask,
    detect_boa_offset,
    dn_to_reflectance,
    get_scale_and_offset,
)

logger = logging.getLogger(__name__)

EARTH_SEARCH_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION_SENTINEL_2 = "sentinel-2-l2a"


@dataclass(frozen=True)
class SatelliteTimeseries:
    """Satellite imagery timeseries container."""

    boundary_path: str
    start_date: str
    end_date: str
    sensor: str = "Sentinel-2 L2A"
    scene_count: Optional[int] = None
    mean_cloud_cover_pct: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def _extract_mgrs_tile(item: Any) -> Optional[str]:
    """Extract 5-character MGRS tile ID from STAC item properties or ID."""
    mgrs_tile = item.properties.get("s2:mgrs_tile")
    if mgrs_tile:
        return str(mgrs_tile)
    z = item.properties.get("mgrs:utm_zone")
    b = item.properties.get("mgrs:latitude_band")
    sq = item.properties.get("mgrs:grid_square")
    if z and b and sq:
        return f"{z}{b}{sq}"
    if "_" in item.id:
        parts = item.id.split("_")
        if len(parts) > 1 and len(parts[1]) == 5:
            return parts[1]
    return None


def _extract_item_proj_info(item: Any) -> Tuple[List[float], int]:
    """Extract red-band proj:transform and proj:epsg from a STAC item or dict representation."""
    red_asset = None
    if hasattr(item, "assets") and isinstance(item.assets, dict):
        red_asset = item.assets.get("red")
    elif isinstance(item, dict):
        red_asset = item.get("assets", {}).get("red")

    transform = None
    epsg = None

    if red_asset is not None:
        if hasattr(red_asset, "extra_fields") and isinstance(red_asset.extra_fields, dict):
            transform = red_asset.extra_fields.get("proj:transform")
            epsg = red_asset.extra_fields.get("proj:epsg")
        elif isinstance(red_asset, dict):
            transform = red_asset.get("proj:transform")
            epsg = red_asset.get("proj:epsg")

    if epsg is None:
        if hasattr(item, "properties") and isinstance(item.properties, dict):
            epsg = item.properties.get("proj:epsg")
        elif isinstance(item, dict):
            epsg = item.get("properties", {}).get("proj:epsg")

    if transform is None:
        if hasattr(item, "properties") and isinstance(item.properties, dict):
            transform = item.properties.get("proj:transform")
        elif isinstance(item, dict):
            transform = item.get("properties", {}).get("proj:transform")

    item_id = getattr(item, "id", None) or (item.get("id") if isinstance(item, dict) else str(item))
    if not transform or len(transform) != 6:
        raise ValueError(f"STAC item {item_id} missing valid red-band proj:transform: {transform}")
    if not epsg:
        raise ValueError(f"STAC item {item_id} missing valid proj:epsg: {epsg}")

    return [float(x) for x in transform], int(epsg)


def validate_single_tile_transform(items: List[Any]) -> rasterio.Affine:
    """Validate that all items share identical red-band proj:transform and proj:epsg.

    Args:
        items: List of STAC items or item dictionaries.

    Returns:
        rasterio.Affine transform for the single MGRS tile.

    Raises:
        ValueError: If items list is empty or items span multiple tiles (different transform or EPSG).
    """
    if not items:
        raise ValueError("Cannot derive tile transform: empty STAC items list.")

    first_transform, first_epsg = _extract_item_proj_info(items[0])

    for it in items[1:]:
        t, epsg = _extract_item_proj_info(it)
        if t != first_transform or epsg != first_epsg:
            item_id = getattr(it, "id", None) or (it.get("id") if isinstance(it, dict) else str(it))
            ref_id = getattr(items[0], "id", None) or (items[0].get("id") if isinstance(items[0], dict) else str(items[0]))
            raise ValueError(
                f"Single-tile guard failure: STAC items do not share the same tile transform or EPSG. "
                f"Reference item {ref_id} has transform={first_transform}, epsg={first_epsg}; "
                f"item {item_id} has transform={t}, epsg={epsg}."
            )

    return rasterio.Affine(*first_transform)


def search_stac_items(
    bbox: Tuple[float, float, float, float],
    start_date: str = "2019-01-01",
    end_date: str = "2022-12-31",
    max_cloud_cover: float = 60.0,
    stac_url: str = EARTH_SEARCH_URL,
) -> List[Any]:
    """Search Sentinel-2 L2A scenes matching bounding box and date range.

    Raises:
        RuntimeError: If STAC query fails or no items found.
    """
    logger.info("Connecting to STAC API at %s...", stac_url)
    try:
        client = Client.open(stac_url)
        search = client.search(
            collections=[COLLECTION_SENTINEL_2],
            bbox=list(bbox),
            datetime=f"{start_date}/{end_date}",
            query={"eo:cloud_cover": {"lt": max_cloud_cover}},
            limit=100,
        )
        items = list(search.items())
    except Exception as exc:
        raise RuntimeError(f"STAC search failed on {stac_url}: {exc}") from exc

    if not items:
        raise RuntimeError(
            f"No Sentinel-2 items found for bbox={bbox} between {start_date} and {end_date}."
        )

    logger.info("Found %d matching Sentinel-2 items from STAC.", len(items))
    return items


def save_stac_items_json(items: List[Any], output_file: Path) -> List[Dict[str, Any]]:
    """Serialize STAC item metadata to JSON file."""
    item_dicts: List[Dict[str, Any]] = []
    for it in items:
        dt_str = it.datetime.isoformat() if it.datetime else None
        item_dicts.append({
            "id": it.id,
            "datetime": dt_str,
            "cloud_cover": it.properties.get("eo:cloud_cover"),
            "tile": _extract_mgrs_tile(it),
            "processing_baseline": it.properties.get("s2:processing_baseline"),
            "relative_orbit": (
                it.properties.get("sat:relative_orbit")
                or it.properties.get("s2:relative_orbit")
                or it.properties.get("s2:sequence")
            ),
        })

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(item_dicts, f, indent=2)
    logger.info("Saved %d items to %s", len(item_dicts), output_file)
    return item_dicts


def _read_windowed_band(
    cog_url: str,
    window: Window,
    out_shape: Optional[Tuple[int, int]] = None,
    resampling: Resampling = Resampling.nearest,
) -> np.ndarray:
    """Read a windowed slice from a Cloud-Optimized GeoTIFF via HTTP range request."""
    with rasterio.Env(
        AWS_NO_SIGN_REQUEST="YES",
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF",
    ):
        with rasterio.open(cog_url) as src:
            if out_shape is not None:
                return src.read(1, window=window, out_shape=out_shape, resampling=resampling)
            return src.read(1, window=window)


def _check_valid_pixel_count_for_item(
    item: Any,
    window: Window,
    expected_shape: Tuple[int, int],
    cache_dir: Optional[Path] = None,
) -> int:
    """Get valid pixel count for an item from cache or by reading SCL band."""
    if cache_dir is not None:
        cache_path = cache_dir / f"{item.id}.npz"
        if cache_path.exists():
            try:
                with np.load(cache_path) as cached:
                    scl = cached["scl"]
                    return int(np.sum(create_scl_mask(scl)))
            except Exception:
                pass

    if "scl" not in item.assets:
        return 0

    try:
        scl_data = _read_windowed_band(
            item.assets["scl"].href,
            window=window,
            out_shape=expected_shape,
            resampling=Resampling.nearest,
        )
        return int(np.sum(create_scl_mask(scl_data)))
    except Exception as exc:
        logger.warning("Could not read SCL for item %s: %s", item.id, exc)
        return 0


def deduplicate_same_day_scenes(
    items: List[Any],
    window: Window,
    grid_shape: Tuple[int, int],
    cache_dir: Optional[Path] = None,
) -> List[Any]:
    """Deduplicate same-day items by keeping the best valid-pixel coverage."""
    items_by_date: Dict[str, List[Any]] = {}
    for it in items:
        d_str = it.datetime.strftime("%Y-%m-%d") if it.datetime else "unknown"
        items_by_date.setdefault(d_str, []).append(it)

    selected_items: List[Any] = []
    logger.info("Deduplicating %d STAC items across %d unique dates...", len(items), len(items_by_date))

    for d_str, date_items in items_by_date.items():
        if len(date_items) == 1:
            selected_items.append(date_items[0])
            continue

        # Multiple items for this date: evaluate valid pixel coverage
        best_item = date_items[0]
        best_valid_count = -1

        for it in date_items:
            valid_count = _check_valid_pixel_count_for_item(
                it, window, grid_shape, cache_dir=cache_dir
            )
            if valid_count > best_valid_count:
                best_valid_count = valid_count
                best_item = it

        selected_items.append(best_item)

    # Sort selected items chronologically
    selected_items.sort(key=lambda it: it.datetime or datetime.min)
    logger.info("Deduplication complete: retained %d scenes.", len(selected_items))
    return selected_items


def fetch_and_cache_scene(
    item: Any,
    window: Window,
    expected_shape: Tuple[int, int],
    cache_dir: Path,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Dict[str, Any]]:
    """Fetch windowed red, nir, scl bands or load from local cache.

    Returns:
        Tuple of (red_dn, nir_dn, scl, meta_dict).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{item.id}.npz"

    if cache_path.exists():
        try:
            with np.load(cache_path, allow_pickle=True) as data:
                red = data["red"]
                nir = data["nir"]
                scl = data["scl"]
                meta = data["meta"].item() if "meta" in data else {}
                return red, nir, scl, meta
        except Exception as exc:
            logger.warning("Cache load failed for %s (%s), re-fetching.", item.id, exc)

    if not ("red" in item.assets and "nir" in item.assets and "scl" in item.assets):
        raise ValueError(f"Item {item.id} is missing required red/nir/scl assets.")

    red = _read_windowed_band(item.assets["red"].href, window=window)
    nir = _read_windowed_band(item.assets["nir"].href, window=window)
    scl = _read_windowed_band(
        item.assets["scl"].href,
        window=window,
        out_shape=expected_shape,
        resampling=Resampling.nearest,
    )

    baseline = item.properties.get("s2:processing_baseline")
    red_scale, red_offset = get_scale_and_offset(item.assets["red"].extra_fields, baseline)
    nir_scale, nir_offset = get_scale_and_offset(item.assets["nir"].extra_fields, baseline)

    meta = {
        "id": item.id,
        "datetime": item.datetime.isoformat() if item.datetime else None,
        "processing_baseline": baseline,
        "red_scale": red_scale,
        "red_offset": red_offset,
        "nir_scale": nir_scale,
        "nir_offset": nir_offset,
    }

    try:
        np.savez_compressed(cache_path, red=red, nir=nir, scl=scl, meta=meta)
    except Exception as exc:
        logger.warning("Failed to save cache for %s: %s", item.id, exc)

    return red, nir, scl, meta


def compute_zone_statistics(
    ndvi: np.ndarray,
    valid_mask: np.ndarray,
    zone_mask: np.ndarray,
) -> Dict[str, Any]:
    """Compute zonal NDVI distribution metrics within a binary mask."""
    total_pixels = int(np.sum(zone_mask == 1))
    zone_valid = (zone_mask == 1) & valid_mask & np.isfinite(ndvi)
    valid_values = ndvi[zone_valid]
    n_valid = len(valid_values)

    valid_fraction = float(n_valid / total_pixels) if total_pixels > 0 else 0.0

    if n_valid > 0:
        return {
            "valid_fraction": round(valid_fraction, 4),
            "ndvi_mean": round(float(np.mean(valid_values)), 4),
            "ndvi_median": round(float(np.median(valid_values)), 4),
            "ndvi_p10": round(float(np.percentile(valid_values, 10)), 4),
            "ndvi_p90": round(float(np.percentile(valid_values, 90)), 4),
            "n_valid_pixels": n_valid,
        }

    return {
        "valid_fraction": 0.0,
        "ndvi_mean": None,
        "ndvi_median": None,
        "ndvi_p10": None,
        "ndvi_p90": None,
        "n_valid_pixels": 0,
    }


def write_timeseries_csv(rows: List[Dict[str, Any]], output_file: Path) -> None:
    """Write zonal timeseries records to CSV."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "scene_id",
        "date",
        "zone",
        "valid_fraction",
        "ndvi_mean",
        "ndvi_median",
        "ndvi_p10",
        "ndvi_p90",
        "n_valid_pixels",
        "stac_offset",
        "detected_offset",
        "red_p1_dn",
        "offset_flag",
    ]
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    logger.info("Saved %d timeseries records to %s", len(rows), output_file)


def _load_claimed_estate_area(project_dir: Path) -> float:
    """Read claimed estate_area_ha or claimed_area_ha from extraction_report.json."""
    report_file = project_dir / "extraction_report.json"
    if report_file.exists():
        try:
            with open(report_file, "r", encoding="utf-8") as f:
                d = json.load(f)
            if "estate_area_ha" in d and d["estate_area_ha"]:
                return float(d["estate_area_ha"])
            if "claimed_area_ha" in d and d["claimed_area_ha"]:
                return float(d["claimed_area_ha"])
        except Exception as exc:
            logger.warning("Could not parse area from %s: %s", report_file, exc)
    return 2309.0


def process_scene_pipeline(
    item: Any,
    window: Window,
    expected_shape: Tuple[int, int],
    mask_proj: np.ndarray,
    mask_ring: np.ndarray,
    cache_dir: Path,
) -> Tuple[List[Dict[str, Any]], str, Optional[np.ndarray]]:
    """Fetch a scene, calculate NDVI and zonal stats for project and ring."""
    red_dn, nir_dn, scl, meta = fetch_and_cache_scene(
        item, window=window, expected_shape=expected_shape, cache_dir=cache_dir
    )

    date_str = item.datetime.strftime("%Y-%m-%d") if item.datetime else "unknown"

    stac_offset = meta.get("red_offset", 0.0)
    detected_offset, red_p1, offset_flag = detect_boa_offset(red_dn, scl)

    # Exclude ambiguous scenes from time series
    if offset_flag == "ambiguous" or detected_offset is None:
        logger.warning(
            "Scene %s marked ambiguous (red p1=%.1f); excluding from timeseries",
            item.id,
            red_p1,
        )
        return [], date_str, None

    r_scale = meta.get("red_scale", 0.0001)
    n_scale = meta.get("nir_scale", 0.0001)

    red_refl = dn_to_reflectance(red_dn, scale=r_scale, offset=detected_offset)
    nir_refl = dn_to_reflectance(nir_dn, scale=n_scale, offset=detected_offset)

    scl_mask = create_scl_mask(scl)
    valid_mask = scl_mask & np.isfinite(red_refl) & np.isfinite(nir_refl)
    ndvi = compute_ndvi(red_refl, nir_refl, valid_mask=valid_mask)

    proj_stats = compute_zone_statistics(ndvi, valid_mask, mask_proj)
    ring_stats = compute_zone_statistics(ndvi, valid_mask, mask_ring)

    red_p1_val = round(red_p1, 1) if np.isfinite(red_p1) else None

    proj_row = {
        "scene_id": item.id,
        "date": date_str,
        "zone": "project",
        **proj_stats,
        "stac_offset": stac_offset,
        "detected_offset": detected_offset,
        "red_p1_dn": red_p1_val,
        "offset_flag": offset_flag,
    }
    ring_row = {
        "scene_id": item.id,
        "date": date_str,
        "zone": "ring",
        **ring_stats,
        "stac_offset": stac_offset,
        "detected_offset": detected_offset,
        "red_p1_dn": red_p1_val,
        "offset_flag": offset_flag,
    }

    return [proj_row, ring_row], date_str, ndvi


def execute_imagery_verification(
    project_dir: Path,
    max_workers: int = 8,
) -> Dict[str, Any]:
    """Execute complete real imagery acquisition and zonal NDVI processing."""
    t0 = time.time()
    imagery_dir = project_dir / "imagery"
    imagery_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = imagery_dir / "cache"

    target_area = _load_claimed_estate_area(project_dir)
    boundary_path = project_dir / "boundary.geojson"

    proj_gdf, ring_gdf, utm_epsg, combined_bbox = prepare_project_and_reference_boundaries(
        boundary_path=boundary_path,
        target_area_ha=target_area,
        output_dir=imagery_dir,
    )

    # Search STAC items
    items = search_stac_items(combined_bbox)
    stac_items_path = imagery_dir / "stac_items.json"
    save_stac_items_json(items, stac_items_path)

    # Compute grid window in UTM
    proj_utm = proj_gdf.to_crs(epsg=utm_epsg).geometry.iloc[0]
    ring_utm = ring_gdf.to_crs(epsg=utm_epsg).geometry.iloc[0]
    combined_geom = proj_utm.union(ring_utm)
    minx, miny, maxx, maxy = combined_geom.bounds

    # MGRS 10m grid origin and transform validated from STAC items (single-tile guard)
    cog_transform = validate_single_tile_transform(items)
    raw_win = from_bounds(minx, miny, maxx, maxy, cog_transform)
    col_off, row_off = int(raw_win.col_off), int(raw_win.row_off)
    width, height = int(raw_win.width) + 2, int(raw_win.height) + 2
    int_win = Window(col_off, row_off, width, height)
    win_transform = rasterio.windows.transform(int_win, cog_transform)
    expected_shape = (height, width)

    mask_proj = rasterize([proj_utm], out_shape=expected_shape, transform=win_transform, default_value=1, fill=0, dtype="uint8")
    mask_ring = rasterize([ring_utm], out_shape=expected_shape, transform=win_transform, default_value=1, fill=0, dtype="uint8")

    # Deduplicate same-day scenes
    selected_items = deduplicate_same_day_scenes(items, int_win, expected_shape, cache_dir=cache_dir)

    timeseries_rows: List[Dict[str, Any]] = []
    scene_ndvis: List[Tuple[str, np.ndarray]] = []
    errors: List[str] = []

    logger.info("Processing %d deduplicated scenes with max_workers=%d...", len(selected_items), max_workers)

    def _worker(idx_item: Tuple[int, Any]) -> Tuple[int, List[Dict[str, Any]], str, Optional[np.ndarray]]:
        idx, it = idx_item
        rows, d_str, ndvi = process_scene_pipeline(
            it, int_win, expected_shape, mask_proj, mask_ring, cache_dir
        )
        return idx, rows, d_str, ndvi

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_worker, (i, it)): it.id for i, it in enumerate(selected_items, 1)}
        completed_count = 0
        total_count = len(futures)
        for fut in as_completed(futures):
            item_id = futures[fut]
            try:
                idx, rows, d_str, ndvi = fut.result()
                if rows:
                    timeseries_rows.extend(rows)
                if ndvi is not None:
                    scene_ndvis.append((d_str, ndvi))
                completed_count += 1
                if completed_count % 20 == 0 or completed_count == total_count:
                    logger.info("[%d/%d] Processed scene %s (date=%s)", completed_count, total_count, item_id, d_str)
            except Exception as exc:
                err_msg = f"Failed processing {item_id}: {exc}"
                logger.error(err_msg)
                errors.append(err_msg)

    # Sort timeseries rows chronologically by date
    timeseries_rows.sort(key=lambda r: (r["date"], 0 if r["zone"] == "project" else 1))
    timeseries_path = imagery_dir / "timeseries.csv"
    write_timeseries_csv(timeseries_rows, timeseries_path)

    # Generate seasonal composites cropped to project bbox
    proj_minx, proj_miny, proj_maxx, proj_maxy = proj_utm.bounds
    proj_win_raw = from_bounds(proj_minx, proj_miny, proj_maxx, proj_maxy, win_transform)
    proj_crop_win = Window(
        int(proj_win_raw.col_off),
        int(proj_win_raw.row_off),
        int(proj_win_raw.width) + 1,
        int(proj_win_raw.height) + 1,
    )

    composites_dir = imagery_dir / "composites"
    generate_seasonal_composites(
        scene_ndvis=scene_ndvis,
        project_window=proj_crop_win,
        full_transform=win_transform,
        crs=rasterio.crs.CRS.from_epsg(utm_epsg),
        output_dir=composites_dir,
    )

    total_runtime = time.time() - t0
    report_path = imagery_dir / "imagery_report.json"
    report = generate_imagery_report(
        timeseries_rows=timeseries_rows,
        total_runtime_seconds=total_runtime,
        errors=errors,
        output_path=report_path,
    )

    logger.info("Imagery verification completed in %.2fs. Report saved to %s", total_runtime, report_path)
    return report


def recompute_timeseries_from_cache(
    project_dir: Path,
    items: Optional[List[Any]] = None,
) -> Path:
    """Recompute timeseries.csv and seasonal composites strictly from cached scenes.

    Uses data-driven BOA offset detector and excludes ambiguous scenes from timeseries.
    """
    imagery_dir = project_dir / "imagery"
    cache_dir = imagery_dir / "cache"

    old_timeseries = imagery_dir / "timeseries_old.csv"
    if old_timeseries.exists():
        with open(old_timeseries, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            cached_scene_ids = list(dict.fromkeys(r["scene_id"] for r in reader))
    else:
        cached_scene_ids = [p.stem for p in sorted(cache_dir.glob("*.npz"))]

    target_area = _load_claimed_estate_area(project_dir)
    boundary_path = project_dir / "boundary.geojson"
    proj_gdf, ring_gdf, utm_epsg, combined_bbox = prepare_project_and_reference_boundaries(
        boundary_path=boundary_path,
        target_area_ha=target_area,
        output_dir=imagery_dir,
    )

    proj_utm = proj_gdf.to_crs(epsg=utm_epsg).geometry.iloc[0]
    ring_utm = ring_gdf.to_crs(epsg=utm_epsg).geometry.iloc[0]
    combined_geom = proj_utm.union(ring_utm)
    minx, miny, maxx, maxy = combined_geom.bounds

    if items is None:
        items = search_stac_items(combined_bbox)
    cog_transform = validate_single_tile_transform(items)
    raw_win = from_bounds(minx, miny, maxx, maxy, cog_transform)
    col_off, row_off = int(raw_win.col_off), int(raw_win.row_off)
    width, height = int(raw_win.width) + 2, int(raw_win.height) + 2
    int_win = Window(col_off, row_off, width, height)
    win_transform = rasterio.windows.transform(int_win, cog_transform)
    expected_shape = (height, width)

    mask_proj = rasterize([proj_utm], out_shape=expected_shape, transform=win_transform, default_value=1, fill=0, dtype="uint8")
    mask_ring = rasterize([ring_utm], out_shape=expected_shape, transform=win_transform, default_value=1, fill=0, dtype="uint8")

    timeseries_rows: List[Dict[str, Any]] = []
    scene_ndvis: List[Tuple[str, np.ndarray]] = []

    for sid in cached_scene_ids:
        cf = cache_dir / f"{sid}.npz"
        if not cf.exists():
            continue
        with np.load(cf, allow_pickle=True) as data:
            red = data["red"]
            nir = data["nir"]
            scl = data["scl"]
            meta = data["meta"].item() if "meta" in data else {}

        d_str = meta.get("datetime", "")[:10]
        if not d_str:
            parts = sid.split("_")
            d_str = f"{parts[2][:4]}-{parts[2][4:6]}-{parts[2][6:8]}"

        stac_offset = meta.get("red_offset", 0.0)
        detected_offset, red_p1, offset_flag = detect_boa_offset(red, scl)

        if offset_flag == "ambiguous" or detected_offset is None:
            logger.warning(
                "Scene %s marked ambiguous (red p1=%.1f); excluding from timeseries",
                sid,
                red_p1,
            )
            continue

        r_scale = meta.get("red_scale", 0.0001)
        n_scale = meta.get("nir_scale", 0.0001)

        red_refl = dn_to_reflectance(red, scale=r_scale, offset=detected_offset)
        nir_refl = dn_to_reflectance(nir, scale=n_scale, offset=detected_offset)

        scl_mask = create_scl_mask(scl)
        valid_mask = scl_mask & np.isfinite(red_refl) & np.isfinite(nir_refl)
        ndvi = compute_ndvi(red_refl, nir_refl, valid_mask=valid_mask)

        proj_stats = compute_zone_statistics(ndvi, valid_mask, mask_proj)
        ring_stats = compute_zone_statistics(ndvi, valid_mask, mask_ring)

        red_p1_val = round(red_p1, 1) if np.isfinite(red_p1) else None

        proj_row = {
            "scene_id": sid,
            "date": d_str,
            "zone": "project",
            **proj_stats,
            "stac_offset": stac_offset,
            "detected_offset": detected_offset,
            "red_p1_dn": red_p1_val,
            "offset_flag": offset_flag,
        }
        ring_row = {
            "scene_id": sid,
            "date": d_str,
            "zone": "ring",
            **ring_stats,
            "stac_offset": stac_offset,
            "detected_offset": detected_offset,
            "red_p1_dn": red_p1_val,
            "offset_flag": offset_flag,
        }

        timeseries_rows.extend([proj_row, ring_row])
        scene_ndvis.append((d_str, ndvi))

    timeseries_rows.sort(key=lambda r: (r["date"], 0 if r["zone"] == "project" else 1))
    timeseries_path = imagery_dir / "timeseries.csv"
    write_timeseries_csv(timeseries_rows, timeseries_path)

    proj_minx, proj_miny, proj_maxx, proj_maxy = proj_utm.bounds
    proj_win_raw = from_bounds(proj_minx, proj_miny, proj_maxx, proj_maxy, win_transform)
    proj_crop_win = Window(
        int(proj_win_raw.col_off),
        int(proj_win_raw.row_off),
        int(proj_win_raw.width) + 1,
        int(proj_win_raw.height) + 1,
    )
    generate_seasonal_composites(
        scene_ndvis=scene_ndvis,
        project_window=proj_crop_win,
        full_transform=win_transform,
        crs=rasterio.crs.CRS.from_epsg(utm_epsg),
        output_dir=imagery_dir / "composites",
    )

    report_path = imagery_dir / "imagery_report.json"
    generate_imagery_report(
        timeseries_rows=timeseries_rows,
        total_runtime_seconds=0.0,
        errors=[],
        output_path=report_path,
    )

    return timeseries_path


def fetch_timeseries(
    boundary_path: Union[str, Path],
    start: Union[date, str],
    end: Union[date, str],
    is_demo: bool = False,
) -> SatelliteTimeseries:
    """Fetch satellite timeseries over boundary (demo stub or real acquisition)."""
    path_obj = Path(boundary_path)
    path_str = str(boundary_path)
    start_str = str(start)
    end_str = str(end)

    # If demo fixture, maintain lightweight deterministic stub
    if is_demo or "demo" in path_str.lower() or "demo" in path_obj.parts:
        logger.info("Fetching demo satellite timeseries stub for: %s", path_str)
        return SatelliteTimeseries(
            boundary_path=path_str,
            start_date=start_str,
            end_date=end_str,
            sensor="Sentinel-2 L2A",
            scene_count=24,
            mean_cloud_cover_pct=12.5,
            metadata={
                "resolution_m": 10,
                "bands": ["B02", "B03", "B04", "B08", "SCL"],
                "cloud_masking": "SCL_scene_classification",
                "demo": True,
            },
        )

    # Real project acquisition
    project_dir = path_obj.parent
    report_file = project_dir / "imagery" / "imagery_report.json"
    if report_file.exists():
        with open(report_file, "r", encoding="utf-8") as f:
            report = json.load(f)
    else:
        report = execute_imagery_verification(project_dir=project_dir)


    val_frac = report.get("mean_valid_fraction")
    mean_cloud = (
        round((1.0 - float(val_frac)) * 100.0, 1) if val_frac is not None else None
    )

    return SatelliteTimeseries(
        boundary_path=path_str,
        start_date=start_str,
        end_date=end_str,
        sensor="Sentinel-2 L2A",
        scene_count=report.get("total_scenes_processed"),
        mean_cloud_cover_pct=mean_cloud,
        metadata=report,
    )
