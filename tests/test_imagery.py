"""Tests for satellite imagery acquisition, boundary selection, radiometry, and composites."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.windows import Window
from shapely.geometry import Polygon, box

from carbonverify.imagery.boundary import (
    BoundarySelectionError,
    generate_reference_ring,
    get_utm_epsg_from_centroid,
    select_project_polygon,
)
from carbonverify.imagery.composites import (
    generate_imagery_report,
    generate_seasonal_composites,
)
from carbonverify.imagery.fetch import deduplicate_same_day_scenes
from carbonverify.imagery.radiometry import (
    compute_ndvi,
    create_scl_mask,
    detect_boa_offset,
    dn_to_reflectance,
    get_scale_and_offset,
)


class TestBoundarySelectionAndRing:
    """Tests for boundary polygon selection and reference ring geometry."""

    def test_boundary_selection_rejects_regional_polygon(self) -> None:
        """Verify boundary selection picks estate polygon (~2324 ha) and rejects regional (2.09M ha)."""
        # Create a small polygon (~2320 ha) and a huge polygon (~2.09M ha) in UTM 21S (EPSG:32721)
        # 1 ha = 10,000 m2. 2320 ha = 23,200,000 m2 -> sqrt = ~4816.6 m
        small_poly_utm = box(540000, 7350000, 544817, 7354817)
        # Regional polygon: 2,000,000 ha = 20,000,000,000 m2 -> sqrt = ~141421 m
        huge_poly_utm = box(500000, 7300000, 641421, 7441421)

        gdf_utm = gpd.GeoDataFrame(
            [{"name": "project_estate", "geometry": small_poly_utm},
             {"name": "regional_admin", "geometry": huge_poly_utm}],
            crs="EPSG:32721",
        )
        gdf_4326 = gdf_utm.to_crs(epsg=4326)

        selected_gdf, epsg = select_project_polygon(gdf_4326, target_area_ha=2309.0, max_discrepancy_pct=15.0)
        assert len(selected_gdf) == 1
        assert selected_gdf.iloc[0]["name"] == "project_estate"
        assert epsg == 32721

    def test_boundary_selection_exceeding_tolerance_raises(self) -> None:
        """Verify error is raised if closest polygon differs by > 15%."""
        # Only regional polygon available
        huge_poly_utm = box(500000, 7300000, 641421, 7441421)
        gdf = gpd.GeoDataFrame([{"geometry": huge_poly_utm}], crs="EPSG:32721").to_crs(epsg=4326)

        with pytest.raises(BoundarySelectionError, match="exceeding 15.0% tolerance"):
            select_project_polygon(gdf, target_area_ha=2309.0, max_discrepancy_pct=15.0)

    def test_reference_ring_geometry_no_overlap(self) -> None:
        """Verify 1-5 km reference ring has ZERO spatial overlap with project polygon."""
        project_poly_utm = box(540000, 7350000, 545000, 7355000)
        project_gdf = gpd.GeoDataFrame(
            [{"geometry": project_poly_utm}],
            crs="EPSG:32721",
        ).to_crs(epsg=4326)

        ring_gdf = generate_reference_ring(project_gdf, utm_epsg=32721, inner_buffer_m=1000.0, outer_buffer_m=5000.0)

        # Check intersection in UTM
        proj_geom_utm = project_gdf.to_crs(epsg=32721).geometry.iloc[0]
        ring_geom_utm = ring_gdf.to_crs(epsg=32721).geometry.iloc[0]

        intersection_area = proj_geom_utm.intersection(ring_geom_utm).area
        assert intersection_area == 0.0, "Reference ring must not overlap with project polygon!"

        # Minimum distance between project boundary and ring inner edge must be >= 990.0 m (accounting for 4326 reprojection)
        min_dist = proj_geom_utm.distance(ring_geom_utm)
        assert min_dist >= 990.0


class TestRadiometryAndMasking:
    """Tests for SCL masking, BOA offset correction, and NDVI calculation."""

    def test_scl_masking(self) -> None:
        """Verify SCL masking keeps 4, 5, 6, 7 and drops all other classes."""
        scl = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], dtype=np.uint8)
        mask = create_scl_mask(scl)

        expected = np.array([
            False, False, False, False,  # 0, 1, 2, 3
            True,  True,  True,  True,   # 4, 5, 6, 7
            False, False, False, False   # 8, 9, 10, 11
        ], dtype=bool)

        np.testing.assert_array_equal(mask, expected)

    def test_baseline_offset_correction_preserves_ndvi(self) -> None:
        """Verify synthetic DN values yield identical NDVI for the same surface before and after baseline 04.00."""
        # True surface reflectance for vegetation:
        # Red: 0.05, NIR: 0.45 -> NDVI = (0.45 - 0.05) / (0.45 + 0.05) = 0.40 / 0.50 = 0.80

        # 1. Pre-baseline 04.00 (e.g. 02.11): scale=0.0001, offset=0.0
        # DN = reflectance / 0.0001
        red_dn_old = np.array([500], dtype=np.uint16)
        nir_dn_old = np.array([4500], dtype=np.uint16)

        scale_old, offset_old = get_scale_and_offset(
            asset_extra_fields={"raster:bands": [{"scale": 0.0001, "offset": 0.0}]},
            processing_baseline="02.11",
        )
        assert scale_old == 0.0001
        assert offset_old == 0.0

        red_refl_old = dn_to_reflectance(red_dn_old, scale=scale_old, offset=offset_old)
        nir_refl_old = dn_to_reflectance(nir_dn_old, scale=scale_old, offset=offset_old)
        ndvi_old = compute_ndvi(red_refl_old, nir_refl_old)

        # 2. Post-baseline 04.00 (e.g. 05.09): scale=0.0001, offset=-0.1 (BOA_ADD_OFFSET = -1000 DN)
        # DN = (reflectance + 0.1) / 0.0001
        # Red DN = (0.05 + 0.1) * 10000 = 1500
        # NIR DN = (0.45 + 0.1) * 10000 = 5500
        red_dn_new = np.array([1500], dtype=np.uint16)
        nir_dn_new = np.array([5500], dtype=np.uint16)

        scale_new, offset_new = get_scale_and_offset(
            asset_extra_fields={"raster:bands": [{"scale": 0.0001, "offset": -0.1}]},
            processing_baseline="05.09",
        )
        assert scale_new == 0.0001
        assert offset_new == -0.1

        red_refl_new = dn_to_reflectance(red_dn_new, scale=scale_new, offset=offset_new)
        nir_refl_new = dn_to_reflectance(nir_dn_new, scale=scale_new, offset=offset_new)
        ndvi_new = compute_ndvi(red_refl_new, nir_refl_new)

        # NDVI before and after baseline change must be mathematically identical (0.80)
        assert np.isclose(ndvi_old[0], 0.80, atol=1e-5)
        assert np.isclose(ndvi_new[0], 0.80, atol=1e-5)
        assert np.isclose(ndvi_old[0], ndvi_new[0], atol=1e-5)

    def test_fallback_offset_when_raster_bands_missing(self) -> None:
        """Verify baseline string fallback correctly sets offset=-0.1 for baseline >= 04.00."""
        scale, offset = get_scale_and_offset(asset_extra_fields=None, processing_baseline="04.00")
        assert scale == 0.0001
        assert offset == -0.1

        scale_old, offset_old = get_scale_and_offset(asset_extra_fields=None, processing_baseline="03.01")
        assert scale_old == 0.0001
        assert offset_old == 0.0

    def test_detect_boa_offset_synthetic(self) -> None:
        """Verify detect_boa_offset for offset present, absent, and ambiguous synthetic cases."""
        # 1. Offset present: red p1 >= 1100 -> offset -0.1, flag 'present'
        red_present = np.full((10, 10), 1200, dtype=np.uint16)
        scl_valid = np.full((10, 10), 4, dtype=np.uint8)  # Vegetation class
        offset, p1, flag = detect_boa_offset(red_present, scl_valid)
        assert offset == -0.1
        assert p1 >= 1100.0
        assert flag == "present"

        # 2. Offset absent: red p1 < 500 -> offset 0.0, flag 'absent'
        red_absent = np.full((10, 10), 250, dtype=np.uint16)
        offset, p1, flag = detect_boa_offset(red_absent, scl_valid)
        assert offset == 0.0
        assert p1 < 500.0
        assert flag == "absent"

        # 3. Ambiguous: 500 <= red p1 < 1100 -> offset None, flag 'ambiguous'
        for amb_val in (700, 1000):
            red_ambiguous = np.full((10, 10), amb_val, dtype=np.uint16)
            offset, p1, flag = detect_boa_offset(red_ambiguous, scl_valid)
            assert offset is None
            assert 500.0 <= p1 < 1100.0
            assert flag == "ambiguous"

        # Edge case: No valid pixels (all cloud / scl class 3) -> ambiguous
        scl_cloud = np.full((10, 10), 3, dtype=np.uint8)
        offset, p1, flag = detect_boa_offset(red_present, scl_cloud)
        assert offset is None
        assert np.isnan(p1)
        assert flag == "ambiguous"



class TestSTACDeduplicationAndComposites:
    """Tests for same-day scene deduplication and seasonal composite generation."""

    def test_deduplicate_same_day_scenes(self, tmp_path: Path) -> None:
        """Verify deduplication keeps the item with higher valid pixels for the same day."""
        dt = datetime(2021, 6, 15, 14, 0, 0)

        item1 = MagicMock()
        item1.id = "S2B_21KWP_20210615_0_L2A"
        item1.datetime = dt
        item1.properties = {"eo:cloud_cover": 10.0}

        item2 = MagicMock()
        item2.id = "S2B_21KWP_20210615_1_L2A"
        item2.datetime = dt
        item2.properties = {"eo:cloud_cover": 5.0}

        # Cache item1 with 50 valid pixels, item2 with 200 valid pixels
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        scl1 = np.full((10, 10), 3, dtype=np.uint8)  # cloud shadow (invalid)
        scl1[:5, :] = 4  # 50 valid pixels
        np.savez_compressed(cache_dir / f"{item1.id}.npz", scl=scl1)

        scl2 = np.full((10, 10), 4, dtype=np.uint8)  # 100 valid pixels
        np.savez_compressed(cache_dir / f"{item2.id}.npz", scl=scl2)

        window = Window(0, 0, 10, 10)
        selected = deduplicate_same_day_scenes(
            items=[item1, item2],
            window=window,
            grid_shape=(10, 10),
            cache_dir=cache_dir,
        )

        assert len(selected) == 1
        assert selected[0].id == item2.id

    def test_generate_seasonal_composites(self, tmp_path: Path) -> None:
        """Verify seasonal median GeoTIFFs are created for wet and dry seasons."""
        # 2 scenes in 2021: one in dry (July), one in wet (November)
        grid_shape = (20, 20)
        ndvi_dry = np.full(grid_shape, 0.65, dtype=np.float32)
        ndvi_wet = np.full(grid_shape, 0.85, dtype=np.float32)

        scene_ndvis = [
            ("2021-07-15", ndvi_dry),
            ("2021-11-20", ndvi_wet),
        ]

        proj_window = Window(0, 0, 10, 10)
        full_transform = rasterio.Affine(10.0, 0.0, 500000.0, 0.0, -10.0, 7000000.0)
        crs = rasterio.crs.CRS.from_epsg(32721)
        out_dir = tmp_path / "composites"

        composites = generate_seasonal_composites(
            scene_ndvis=scene_ndvis,
            project_window=proj_window,
            full_transform=full_transform,
            crs=crs,
            output_dir=out_dir,
            years=(2021,),
        )

        assert "2021_dry" in composites
        assert "2021_wet" in composites

        with rasterio.open(composites["2021_dry"]) as src:
            data = src.read(1)
            assert data.shape == (10, 10)
            assert np.isclose(data[0, 0], 0.65)

        with rasterio.open(composites["2021_wet"]) as src:
            data = src.read(1)
            assert data.shape == (10, 10)
            assert np.isclose(data[0, 0], 0.85)

    def test_generate_imagery_report(self) -> None:
        """Verify imagery report metrics structure."""
        timeseries_rows = [
            {"date": "2019-01-10", "zone": "project", "valid_fraction": 0.8, "n_valid_pixels": 80},
            {"date": "2019-01-10", "zone": "ring", "valid_fraction": 0.85, "n_valid_pixels": 85},
            {"date": "2020-05-12", "zone": "project", "valid_fraction": 0.9, "n_valid_pixels": 90},
            {"date": "2020-05-12", "zone": "ring", "valid_fraction": 0.92, "n_valid_pixels": 92},
        ]
        report = generate_imagery_report(
            timeseries_rows=timeseries_rows,
            total_runtime_seconds=12.5,
            years=(2019, 2020),
        )

        assert report["scene_counts_per_year"] == {"2019": 1, "2020": 1}
        assert report["total_scenes_processed"] == 2
        assert np.isclose(report["mean_valid_fraction"], 0.85)
        assert "2019-02" in report["months_with_no_valid_scene"]
        assert "2019-01" not in report["months_with_no_valid_scene"]
        assert report["total_runtime_seconds"] == 12.5
