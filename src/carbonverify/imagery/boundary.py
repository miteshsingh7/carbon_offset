"""Project boundary selection and reference ring geometry generation."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import geopandas as gpd
from pyproj import CRS
import rasterio
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import transform, unary_union
from shapely.validation import make_valid
import yaml

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
    polygon_filter: Optional[Dict[str, Any]] = None,
) -> Tuple[gpd.GeoDataFrame, int]:
    """Select the feature whose area in UTM is closest to target_area_ha or match via polygon_filter.

    Args:
        boundary_gdf: GeoDataFrame containing boundary features.
        target_area_ha: Target estate/claimed area in hectares (used when polygon_filter is None).
        max_discrepancy_pct: Maximum allowed discrepancy percentage for area matching.
        polygon_filter: Optional dict specifying attribute name and list of matching values.

    Returns:
        Tuple of (single-row GeoDataFrame with selected feature, local UTM EPSG).

    Raises:
        BoundarySelectionError: If empty or closest polygon differs by > max_discrepancy_pct.
    """
    if boundary_gdf.empty:
        raise BoundarySelectionError("Boundary file contains no features.")

    if polygon_filter:
        attr_name = polygon_filter.get("attribute")
        raw_values = polygon_filter.get("values", [])
        if not attr_name:
            attr_name, raw_values = next(iter(polygon_filter.items()))
        if not isinstance(raw_values, (list, tuple, set)):
            raw_values = [raw_values]

        if attr_name not in boundary_gdf.columns:
            raise BoundarySelectionError(
                f"Polygon filter attribute '{attr_name}' not in boundary file columns: {list(boundary_gdf.columns)}"
            )

        val_strs = {str(v).removesuffix(".0") for v in raw_values}
        mask = boundary_gdf[attr_name].apply(
            lambda v: str(v).removesuffix(".0") in val_strs if v is not None else False
        )
        filtered_gdf = boundary_gdf[mask].copy()
        if filtered_gdf.empty:
            raise BoundarySelectionError(f"No features match polygon filter: {polygon_filter}")

        gdf_4326 = filtered_gdf.to_crs(epsg=4326)
        repaired_geoms = []
        for geom in gdf_4326.geometry:
            if geom is None or geom.is_empty:
                continue
            if not geom.is_valid:
                geom = make_valid(geom)
            repaired_geoms.append(geom)

        if not repaired_geoms:
            raise BoundarySelectionError("No valid geometries after filtering and repair.")

        dissolved = unary_union(repaired_geoms)
        if dissolved.geom_type == "GeometryCollection":
            polys = [g for g in dissolved.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
            dissolved = unary_union(polys)

        centroid = dissolved.centroid
        epsg = get_utm_epsg_from_centroid(centroid.x, centroid.y)
        selected_gdf = gpd.GeoDataFrame(
            [{"name": "project_boundary", "geometry": dissolved}],
            crs="EPSG:4326",
        )
        return selected_gdf, epsg

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
    exclusion_geometry: Optional[Any] = None,
) -> gpd.GeoDataFrame:
    """Generate reference ring buffer (1-5 km) outward in UTM, minus project polygon or exclusion geometry.

    Args:
        project_gdf: Single-row GeoDataFrame in EPSG:4326.
        utm_epsg: Projected UTM EPSG code.
        inner_buffer_m: Inner buffer distance in meters (e.g. 1000.0).
        outer_buffer_m: Outer buffer distance in meters (e.g. 5000.0).
        exclusion_geometry: Optional geometry (in EPSG:4326 or GeoDataFrame) representing all
            polygons to exclude from the ring (buffered by inner_buffer_m).

    Returns:
        GeoDataFrame containing reference ring in EPSG:4326.
    """
    proj_utm = project_gdf.to_crs(epsg=utm_epsg).geometry.iloc[0]

    # Buffer outer (5km) and inner (1km)
    outer_geom = proj_utm.buffer(outer_buffer_m)

    if exclusion_geometry is not None:
        if isinstance(exclusion_geometry, (gpd.GeoDataFrame, gpd.GeoSeries)):
            excl_utm = exclusion_geometry.to_crs(epsg=utm_epsg).geometry.iloc[0]
        else:
            excl_utm = gpd.GeoSeries([exclusion_geometry], crs="EPSG:4326").to_crs(epsg=utm_epsg).iloc[0]
        ring_utm = outer_geom.difference(excl_utm.buffer(inner_buffer_m))
    else:
        inner_geom = proj_utm.buffer(inner_buffer_m)
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
    polygon_filter: Optional[Dict[str, Any]] = None,
    exclusion: Optional[bool] = None,
    exclusion_geometry: Optional[Any] = None,
) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, int, Tuple[float, float, float, float]]:
    """Select project boundary and reference ring, and save GeoJSONs.

    Returns:
        Tuple of (project_gdf, ring_gdf, utm_epsg, combined_bbox_4326)
    """
    # Load project.yaml if present in boundary_path.parent or output_dir.parent
    if polygon_filter is None or exclusion is None:
        project_yaml_candidates = [
            boundary_path.parent / "project.yaml",
            output_dir.parent / "project.yaml",
        ]
        for py_path in project_yaml_candidates:
            if py_path.exists():
                try:
                    with open(py_path, "r", encoding="utf-8") as f:
                        pdata = yaml.safe_load(f) or {}
                    if polygon_filter is None:
                        polygon_filter = pdata.get("polygon_filter")
                    if exclusion is None:
                        exclusion = pdata.get("exclusion", False)
                    break
                except Exception as exc:
                    logger.warning("Could not read project.yaml at %s: %s", py_path, exc)

    boundary_gdf = gpd.read_file(boundary_path)
    project_gdf, utm_epsg = select_project_polygon(
        boundary_gdf, target_area_ha, polygon_filter=polygon_filter
    )

    if exclusion and exclusion_geometry is None:
        gdf_4326 = boundary_gdf.to_crs(epsg=4326)
        all_repaired = []
        for g in gdf_4326.geometry:
            if g is None or g.is_empty:
                continue
            if not g.is_valid:
                g = make_valid(g)
            all_repaired.append(g)
        if all_repaired:
            excl_union = unary_union(all_repaired)
            if excl_union.geom_type == "GeometryCollection":
                polys = [p for p in excl_union.geoms if p.geom_type in ("Polygon", "MultiPolygon")]
                excl_union = unary_union(polys)
            exclusion_geometry = excl_union

    ring_gdf = generate_reference_ring(
        project_gdf, utm_epsg, exclusion_geometry=exclusion_geometry
    )

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
