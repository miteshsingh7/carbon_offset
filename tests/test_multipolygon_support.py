"""Tests for MultiPolygon support, attribute filtering, geometry repair, and single-tile guard."""

from pathlib import Path
from typing import Any, Dict
import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
import yaml

from carbonverify.imagery.boundary import (
    BoundarySelectionError,
    generate_reference_ring,
    prepare_project_and_reference_boundaries,
    select_project_polygon,
)
from carbonverify.imagery.fetch import (
    _extract_item_proj_info,
    validate_single_tile_transform,
)


class TestMultiPolygonAndExclusionSupport:
    """Tests for polygon subset filtering, make_valid repair, and ring exclusion."""

    def test_filter_and_dissolve_multipolygon(self) -> None:
        """Synthetic project: select matching rows, dissolve into MultiPolygon, skip area matching."""
        # Synthetic polygons in UTM zone 22S (EPSG:32722)
        # Stand 1: 50 ha = 500,000 m2 (707.1 x 707.1 m)
        poly1 = box(310000, 8100000, 311000, 8100500)
        # Stand 2: 50 ha separated by 1 km
        poly2 = box(312000, 8100000, 313000, 8100500)
        # Stand 3: 150 ha outside the monitored cohort
        poly3 = box(315000, 8100000, 316500, 8101000)

        gdf_utm = gpd.GeoDataFrame(
            [
                {"lot_id": "L1", "planting_year": "2016", "geometry": poly1},
                {"lot_id": "L2", "planting_year": "2017", "geometry": poly2},
                {"lot_id": "L3", "planting_year": "2018", "geometry": poly3},
            ],
            crs="EPSG:32722",
        )
        gdf_4326 = gdf_utm.to_crs(epsg=4326)

        filter_spec = {"attribute": "planting_year", "values": ["2016", "2017"]}
        # target_area_ha is set to 9999.0 to ensure area matching is bypassed
        selected_gdf, epsg = select_project_polygon(
            gdf_4326, target_area_ha=9999.0, polygon_filter=filter_spec
        )

        assert len(selected_gdf) == 1
        geom = selected_gdf.geometry.iloc[0]
        assert geom.geom_type in ("MultiPolygon", "Polygon")
        assert geom.is_valid

        # Dissolved area in UTM should be approximately 100 ha (poly1 + poly2)
        dissolved_utm = selected_gdf.to_crs(epsg=epsg).geometry.iloc[0]
        area_ha = dissolved_utm.area / 10000.0
        assert pytest.approx(area_ha, abs=1.0) == 100.0

    def test_invalid_geometry_repair_with_make_valid(self) -> None:
        """Synthetic bowtie polygon is repaired via shapely make_valid without raising error."""
        # Self-intersecting bowtie polygon in WGS84
        invalid_poly = Polygon([(10.0, 10.0), (10.0, 12.0), (12.0, 10.0), (12.0, 12.0), (10.0, 10.0)])
        assert not invalid_poly.is_valid

        gdf = gpd.GeoDataFrame(
            [{"parcel": "P1", "status": "active", "geometry": invalid_poly}],
            crs="EPSG:4326",
        )

        filter_spec = {"attribute": "status", "values": ["active"]}
        selected_gdf, epsg = select_project_polygon(
            gdf, target_area_ha=50.0, polygon_filter=filter_spec
        )

        repaired_geom = selected_gdf.geometry.iloc[0]
        assert repaired_geom.is_valid
        assert not repaired_geom.is_empty

    def test_exclusion_ring_does_not_overlap_any_file_polygon(self) -> None:
        """Reference ring with exclusion geometry does not overlap any polygon in the file."""
        # Synthetic project in UTM (EPSG:32722)
        # Poly 1: Project stand (500m x 500m = 25 ha)
        p1 = box(300000, 8000000, 300500, 8000500)
        # Poly 2: Non-project stand 800m north (inside the standard 1km-5km ring)
        p2 = box(300000, 8001300, 300500, 8001800)
        # Poly 3: Non-project stand 2km east
        p3 = box(302000, 8000000, 302500, 8000500)

        proj_gdf = gpd.GeoDataFrame([{"name": "proj", "geometry": p1}], crs="EPSG:32722").to_crs(epsg=4326)
        all_gdf = gpd.GeoDataFrame(
            [{"name": "p1", "geometry": p1}, {"name": "p2", "geometry": p2}, {"name": "p3", "geometry": p3}],
            crs="EPSG:32722",
        ).to_crs(epsg=4326)

        # Build exclusion geometry as dissolved union of all polygons
        exclusion_geom = unary_union(list(all_gdf.geometry))

        # Inner buffer = 400m, Outer buffer = 3000m
        ring_gdf = generate_reference_ring(
            proj_gdf,
            utm_epsg=32722,
            inner_buffer_m=400.0,
            outer_buffer_m=3000.0,
            exclusion_geometry=exclusion_geom,
        )

        ring_geom = ring_gdf.to_crs(epsg=32722).geometry.iloc[0]

        # Verify ring does not intersect any polygon in the file
        assert not ring_geom.intersects(p1)
        assert not ring_geom.intersects(p2)
        assert not ring_geom.intersects(p3)

        # Distance from ring to every polygon must be at least inner_buffer_m
        for p in [p1, p2, p3]:
            dist = ring_geom.distance(p)
            assert dist >= 399.0

    def test_filter_none_path_unchanged(self) -> None:
        """When polygon_filter is None, select_project_polygon uses target area matching."""
        poly_small = box(300000, 8000000, 301000, 8001000)  # 100 ha
        poly_large = box(300000, 8000000, 303162, 8003162)  # ~1000 ha

        gdf_utm = gpd.GeoDataFrame(
            [{"stand": "small", "geometry": poly_small}, {"stand": "large", "geometry": poly_large}],
            crs="EPSG:32722",
        )
        gdf_4326 = gdf_utm.to_crs(epsg=4326)

        # Request target area 100.0 ha -> should select poly_small
        selected_gdf, epsg = select_project_polygon(gdf_4326, target_area_ha=100.0, polygon_filter=None)
        assert selected_gdf.iloc[0]["stand"] == "small"

        # Request target area 1000.0 ha -> should select poly_large
        selected_gdf, epsg = select_project_polygon(gdf_4326, target_area_ha=1000.0, polygon_filter=None)
        assert selected_gdf.iloc[0]["stand"] == "large"

        # Discrepancy exceeding tolerance raises error
        with pytest.raises(BoundarySelectionError):
            select_project_polygon(gdf_4326, target_area_ha=500.0, max_discrepancy_pct=10.0, polygon_filter=None)

    def test_project_yaml_settings_loading(self, tmp_path: Path) -> None:
        """Project settings (polygon_filter and exclusion) are read from project.yaml."""
        b_file = tmp_path / "boundary.geojson"
        out_dir = tmp_path / "imagery"
        yaml_file = tmp_path / "project.yaml"

        p1 = box(300000, 8000000, 301000, 8001000)  # 100 ha
        p2 = box(302000, 8000000, 303000, 8001000)  # 100 ha
        p3 = box(304000, 8000000, 305000, 8001000)  # 100 ha

        gdf = gpd.GeoDataFrame(
            [
                {"zone": "alpha", "geometry": p1},
                {"zone": "alpha", "geometry": p2},
                {"zone": "beta", "geometry": p3},
            ],
            crs="EPSG:32722",
        ).to_crs(epsg=4326)
        gdf.to_file(b_file, driver="GeoJSON")

        yaml_content = {
            "polygon_filter": {"attribute": "zone", "values": ["alpha"]},
            "exclusion": True,
        }
        yaml_file.write_text(yaml.safe_dump(yaml_content), encoding="utf-8")

        p_gdf, r_gdf, epsg, bbox = prepare_project_and_reference_boundaries(
            boundary_path=b_file,
            target_area_ha=9999.0,
            output_dir=out_dir,
        )

        assert (out_dir / "project_boundary.geojson").exists()
        assert (out_dir / "reference_ring.geojson").exists()

        # Project boundary is dissolved p1 + p2 (~200 ha)
        p_utm = p_gdf.to_crs(epsg=epsg).geometry.iloc[0]
        assert pytest.approx(p_utm.area / 10000.0, abs=1.0) == 200.0

        # Ring excludes all polygons including zone beta (p3)
        p3_utm = gpd.GeoSeries([p3], crs="EPSG:32722").iloc[0]
        r_utm = r_gdf.to_crs(epsg=epsg).geometry.iloc[0]
        assert not r_utm.intersects(p3_utm)


class TestSingleTileGuardAndTransform:
    """Tests for STAC item transform extraction and single-tile guard."""

    def test_transform_taken_from_mocked_item(self) -> None:
        """Transform is derived from red-band proj:transform of STAC item."""
        mock_item = {
            "id": "S2_MOCK_SCENE_1",
            "properties": {"proj:epsg": 32722},
            "assets": {
                "red": {
                    "proj:transform": [10.0, 0.0, 300000.0, 0.0, -10.0, 8500000.0],
                    "proj:epsg": 32722,
                }
            },
        }

        transform, epsg = _extract_item_proj_info(mock_item)
        assert transform == [10.0, 0.0, 300000.0, 0.0, -10.0, 8500000.0]
        assert epsg == 32722

        aff = validate_single_tile_transform([mock_item])
        assert aff == rasterio.Affine(10.0, 0.0, 300000.0, 0.0, -10.0, 8500000.0)

    def test_mixed_tile_error_raised(self) -> None:
        """Single-tile guard raises error when items span different transforms or EPSGs."""
        item_a = {
            "id": "ITEM_TILE_A",
            "properties": {"proj:epsg": 32722},
            "assets": {"red": {"proj:transform": [10.0, 0.0, 300000.0, 0.0, -10.0, 8500000.0]}},
        }
        # Different origin (tile B)
        item_b = {
            "id": "ITEM_TILE_B",
            "properties": {"proj:epsg": 32722},
            "assets": {"red": {"proj:transform": [10.0, 0.0, 400000.0, 0.0, -10.0, 8500000.0]}},
        }
        # Different EPSG
        item_c = {
            "id": "ITEM_TILE_C",
            "properties": {"proj:epsg": 32723},
            "assets": {"red": {"proj:transform": [10.0, 0.0, 300000.0, 0.0, -10.0, 8500000.0]}},
        }

        with pytest.raises(ValueError, match="Single-tile guard failure"):
            validate_single_tile_transform([item_a, item_b])

        with pytest.raises(ValueError, match="Single-tile guard failure"):
            validate_single_tile_transform([item_a, item_c])

    def test_empty_items_error_raised(self) -> None:
        """Deriving transform from empty items list raises error."""
        with pytest.raises(ValueError, match="empty STAC items list"):
            validate_single_tile_transform([])
