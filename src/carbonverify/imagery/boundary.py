"""Project boundary selection and reference ring geometry generation."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import geopandas as gpd
from pyproj import CRS
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import transform

logger = logging.getLogger(__name__)


class BoundarySelectionError(ValueError):
    """Raised when boundary polygon selection fails or exceeds tolerance."""


def get_utm_epsg_from_centroid(lon: float, lat: float) -> int:
    """Calculate the EPSG code for the UTM zone at the given lon/lat centroid."""
    utm_zone = int((lon + 180) / 6) + 1
    if lat < 0:
        return 32700 + utm_zone
    return 32600 + utm_zone


def select_project_polygon(
    boundary_gdf: gpd.GeoDataFrame,
    target_area_ha: float,
    max_discrepancy_pct: float = 15.0,
) -> Tuple[gpd.GeoDataFrame, int]:
    """Select the feature whose area in UTM is closest to target_area_ha.

    Args:
        boundary_gdf: GeoDataFrame containing boundary features.
        target_area_ha: Target estate/claimed area in hectares.
        max_discrepancy_pct: Maximum allowed discrepancy percentage.

    Returns:
        Tuple of (single-row GeoDataFrame with selected feature, local UTM EPSG).

    Raises:
        BoundarySelectionError: If empty or closest polygon differs by > max_discrepancy_pct.
    """
    if boundary_gdf.empty:
        raise BoundarySelectionError("Boundary file contains no features.")

    # Ensure EPSG:4326 for centroid calculation
    gdf_4326 = boundary_gdf.to_crs(epsg=4326)

    best_idx: Optional[int] = None
    min_diff = float("inf")
    best_epsg = 32721
    best_area_ha = 0.0

    for idx, row in gdf_4326.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        centroid = geom.centroid
        epsg = get_utm_epsg_from_centroid(centroid.x, centroid.y)
        geom_utm = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs(epsg=epsg).iloc[0]
        area_ha = float(geom_utm.area) / 10000.0

        diff = abs(area_ha - target_area_ha)
        if diff < min_diff:
            min_diff = diff
            best_idx = idx
            best_epsg = epsg
            best_area_ha = area_ha

    if best_idx is None:
        raise BoundarySelectionError("No valid geometries found in boundary file.")

    pct_diff = (min_diff / target_area_ha) * 100.0 if target_area_ha > 0 else float("inf")
    logger.info(
        "Closest polygon index=%s: calculated area=%.2f ha, target=%.2f ha (diff=%.2f%%)",
        best_idx,
        best_area_ha,
        target_area_ha,
        pct_diff,
    )

    if pct_diff > max_discrepancy_pct:
        raise BoundarySelectionError(
            f"Closest polygon area ({best_area_ha:.2f} ha) differs from target ({target_area_ha:.2f} ha) "
            f"by {pct_diff:.1f}%, exceeding {max_discrepancy_pct:.1f}% tolerance."
        )

    selected_gdf = gdf_4326.iloc[[best_idx]].copy()
    return selected_gdf, best_epsg


def generate_reference_ring(
    project_gdf: gpd.GeoDataFrame,
    utm_epsg: int,
    inner_buffer_m: float = 1000.0,
    outer_buffer_m: float = 5000.0,
) -> gpd.GeoDataFrame:
    """Generate reference ring buffer (1-5 km) outward in UTM, minus project polygon.

    Args:
        project_gdf: Single-row GeoDataFrame in EPSG:4326.
        utm_epsg: Projected UTM EPSG code.
        inner_buffer_m: Inner buffer distance in meters (e.g. 1000.0).
        outer_buffer_m: Outer buffer distance in meters (e.g. 5000.0).

    Returns:
        GeoDataFrame containing reference ring in EPSG:4326.
    """
    proj_utm = project_gdf.to_crs(epsg=utm_epsg).geometry.iloc[0]

    # Buffer outer (5km) and inner (1km)
    outer_geom = proj_utm.buffer(outer_buffer_m)
    inner_geom = proj_utm.buffer(inner_buffer_m)

    # Ring = outer buffer minus inner buffer (and minus project geometry)
    ring_utm = outer_geom.difference(inner_geom).difference(proj_utm)

    # Convert back to EPSG:4326
    ring_gdf = gpd.GeoDataFrame(
        [{"name": "reference_ring_1km_5km", "geometry": ring_utm}],
        crs=f"EPSG:{utm_epsg}",
    ).to_crs(epsg=4326)

    return ring_gdf


def prepare_project_and_reference_boundaries(
    boundary_path: Path,
    target_area_ha: float,
    output_dir: Path,
) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, int, Tuple[float, float, float, float]]:
    """Select project boundary and reference ring, and save GeoJSONs.

    Returns:
        Tuple of (project_gdf, ring_gdf, utm_epsg, combined_bbox_4326)
    """
    boundary_gdf = gpd.read_file(boundary_path)
    project_gdf, utm_epsg = select_project_polygon(boundary_gdf, target_area_ha)
    ring_gdf = generate_reference_ring(project_gdf, utm_epsg)

    output_dir.mkdir(parents=True, exist_ok=True)
    project_out = output_dir / "project_boundary.geojson"
    ring_out = output_dir / "reference_ring.geojson"

    project_gdf.to_file(project_out, driver="GeoJSON")
    ring_gdf.to_file(ring_out, driver="GeoJSON")
    logger.info("Saved project boundary to %s and reference ring to %s", project_out, ring_out)

    # Compute combined bounding box in EPSG:4326
    combined_geom = project_gdf.geometry.iloc[0].union(ring_gdf.geometry.iloc[0])
    combined_bbox = combined_geom.bounds  # (minx, miny, maxx, maxy)

    return project_gdf, ring_gdf, utm_epsg, combined_bbox
