"""Pydantic data models and schemas for carbonverify."""

from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Registry(str, Enum):
    """Supported carbon registries."""
    VERRA = "verra"
    GOLD_STANDARD = "gold_standard"


class VerificationStatus(str, Enum):
    """Verification discrepancy status categories."""
    CONSISTENT = "CONSISTENT"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    INCONCLUSIVE = "INCONCLUSIVE"


class ConfidenceLevel(str, Enum):
    """Confidence levels for satellite observation quality."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ForestDefinition(BaseModel):
    """National or standard forest definition parameters."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    canopy_cover_pct: Optional[float] = Field(
        default=None, description="Minimum canopy cover percentage threshold"
    )
    min_area_ha: Optional[float] = Field(
        default=None, description="Minimum area threshold in hectares"
    )
    min_height_m: Optional[float] = Field(
        default=None, description="Minimum tree height threshold in meters"
    )


class PlantingStratumClaim(BaseModel):
    """Claimed planted area for an individual stratum row."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    stratum: str = Field(..., description="Stratum code matching year_density, e.g. 2019_714")
    planting_year: int = Field(..., description="Planting year")
    density: int = Field(..., description="Stems per hectare density")
    area_ha: float = Field(..., ge=0.0, description="Total project area in hectares")
    source_doc: str = Field(..., description="Source document filename")
    page: int = Field(..., description="1-indexed page number")
    evidence_quote: str = Field(..., description="Evidence quote from table row")


class PlantingScheduleCheck(BaseModel):
    """Consistency audit between sum of stratum areas and stated total."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    is_consistent: bool = Field(..., description="Whether discrepancy <= 2.0 ha")
    sum_area_ha: float = Field(..., description="Sum of stratum areas in hectares")
    stated_total_ha: float = Field(..., description="Stated total project area in hectares")
    discrepancy_ha: float = Field(..., description="Absolute difference between sum and stated total")
    status: Literal["CONSISTENT", "MISMATCH"] = Field(..., description="Consistency check status")


class ProjectClaims(BaseModel):
    """Claims extracted from carbon-offset project documentation."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: Optional[str] = Field(default=None, description="Unique project identifier (e.g. VCS-1234)")
    registry: Optional[Union[Registry, Literal["verra", "gold_standard"]]] = Field(
        default=None, description="Standard registry issuing credits"
    )
    methodology: Optional[str] = Field(default=None, description="Methodology code, e.g. VM0007, AR-ACM0003")
    claimed_area_ha: Optional[float] = Field(
        default=None, gt=0.0, description="Project area claimed in hectares"
    )
    estate_area_ha: Optional[float] = Field(
        default=None, gt=0.0, description="Total property or estate area in hectares"
    )
    reporting_period_start: Optional[Union[date, str]] = Field(
        default=None, description="Start of verification reporting period (YYYY-MM-DD)"
    )
    reporting_period_end: Optional[Union[date, str]] = Field(
        default=None, description="End of verification reporting period (YYYY-MM-DD)"
    )
    crediting_period_start: Optional[Union[date, str]] = Field(
        default=None, description="Start of crediting period (YYYY-MM-DD)"
    )
    crediting_period_end: Optional[Union[date, str]] = Field(
        default=None, description="End of crediting period (YYYY-MM-DD)"
    )
    project_start_date: Optional[Union[date, str]] = Field(
        default=None, description="Project start date (YYYY-MM-DD)"
    )
    claimed_canopy_change_pct: Optional[float] = Field(
        default=None, description="Reported canopy cover change percentage over period"
    )
    credits_issued: Optional[int] = Field(
        default=None, ge=0, description="Total carbon credits (VCUs) issued for period"
    )
    net_ghg_removals_tco2e: Optional[int] = Field(
        default=None, ge=0, description="Net GHG emission reductions or removals (tCO2e)"
    )
    buffer_credits_tco2e: Optional[int] = Field(
        default=None, ge=0, description="AFOLU buffer credits deposited (tCO2e)"
    )
    forest_definition: Optional[ForestDefinition] = Field(
        default=None, description="National forest definition parameters"
    )
    canopy_cover_pct: Optional[float] = Field(
        default=None, description="National forest definition canopy cover threshold (%)"
    )
    min_area_ha: Optional[float] = Field(
        default=None, description="National forest definition minimum area (ha)"
    )
    min_height_m: Optional[float] = Field(
        default=None, description="National forest definition minimum tree height (m)"
    )
    planting_schedule: Optional[List[PlantingStratumClaim]] = Field(
        default=None, description="Extracted planting schedule by stratum"
    )
    planted_area_by_year: Optional[Dict[str, float]] = Field(
        default=None, description="Aggregated planted area in hectares by year"
    )
    planted_area_total_ha: Optional[float] = Field(
        default=None, description="Calculated sum of planted stratum areas in hectares"
    )
    stated_total_ha: Optional[float] = Field(
        default=None, description="Stated total planted area from table in hectares"
    )
    natural_forest_ha: Optional[float] = Field(
        default=None, description="Reported or claimed natural forest area in hectares"
    )
    check: Optional[PlantingScheduleCheck] = Field(
        default=None, description="Consistency audit for planting schedule"
    )
    boundary_path: Optional[str] = Field(
        default=None, description="Path to spatial boundary file (GeoJSON/Shapefile)"
    )
    source_pages: Dict[str, int] = Field(
        default_factory=dict,
        description="Mapping of accepted claim field name to source document page number",
    )
    demo: bool = Field(
        default=False,
        description="Flag indicating if claims originate from demo fixture",
    )

    @field_validator("boundary_path")
    @classmethod
    def convert_boundary_path_to_str(cls, v: Optional[Union[str, Path]]) -> Optional[str]:
        return str(v) if v is not None else None


class FieldExtractionDetail(BaseModel):
    """Extraction audit record for an individual project claims field."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: Any = None
    raw_value: Optional[str] = None
    page: Optional[int] = None
    evidence_quote: Optional[str] = None
    status: Literal["accepted", "rejected", "missing"]
    reason: Optional[str] = None
    source_doc: Optional[str] = None
    score: Optional[float] = None
    winner_reason: Optional[str] = None


class ExtractionReport(BaseModel):
    """Detailed audit report of document claim extraction and anti-hallucination validation."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_path: str
    fields: Dict[str, FieldExtractionDetail]
    extractor: str = Field(default="rule_based", description="Extraction strategy that generated report")
    pdf_sha256: Optional[str] = Field(default=None, description="SHA-256 hash of the input document")
    demo: bool = False
    documents_scanned: List[str] = Field(default_factory=list, description="All documents scanned during extraction")
    document_stats: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="Per-document text density and OCR flags")
    credits_consistency_check: Optional[Dict[str, Any]] = Field(
        default=None, description="Consistency audit: net_ghg_removals - buffer_credits == credits_issued"
    )
    planting_schedule: Optional[List[PlantingStratumClaim]] = Field(
        default=None, description="Extracted planting schedule by stratum"
    )
    planted_area_by_year: Optional[Dict[str, float]] = Field(
        default=None, description="Aggregated planted area in hectares by year"
    )
    planted_area_total_ha: Optional[float] = Field(
        default=None, description="Calculated sum of planted stratum areas in hectares"
    )
    stated_total_ha: Optional[float] = Field(
        default=None, description="Stated total planted area from table in hectares"
    )
    check: Optional[PlantingScheduleCheck] = Field(
        default=None, description="Consistency audit for planting schedule"
    )
    source_notes: List[str] = Field(
        default_factory=list, description="Observations or source notes regarding discrepancies"
    )
    debug: Dict[str, Any] = Field(default_factory=dict, description="Top candidates per field and keyword pages for missing fields")


class SatelliteEstimate(BaseModel):
    """Satellite-derived observations and change estimates."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    area_ha: float = Field(..., gt=0.0, description="Satellite-derived boundary area in hectares")
    ndvi_mean_start: float = Field(
        ..., ge=-1.0, le=1.0, description="Mean NDVI at start of reporting period"
    )
    ndvi_mean_end: float = Field(
        ..., ge=-1.0, le=1.0, description="Mean NDVI at end of reporting period"
    )
    canopy_change_pct: Optional[float] = Field(
        default=None, description="Satellite-observed canopy cover change percentage"
    )
    biomass_proxy_change_pct: Optional[float] = Field(
        default=None, description="Estimated biomass proxy change percentage"
    )
    reference_buffer_change_pct: Optional[float] = Field(
        default=None, description="Canopy change observed in external reference control buffer"
    )
    valid_observation_count: Optional[int] = Field(
        default=None, ge=0, description="Number of valid, non-cloud-occluded satellite scenes"
    )
    mean_cloud_cover_pct: Optional[float] = Field(
        default=None, ge=0.0, le=100.0, description="Average scene cloud cover percentage"
    )
    planted_area_obs_low: Optional[float] = Field(
        default=None, description="Lower bound of observed planted area in hectares"
    )
    planted_area_obs_central: Optional[float] = Field(
        default=None, description="Central (median) observed planted area in hectares"
    )
    planted_area_obs_high: Optional[float] = Field(
        default=None, description="Upper bound of observed planted area in hectares"
    )
    forest_allowance_ha: Optional[float] = Field(
        default=None, description="Deducted natural forest allowance in hectares"
    )
    grid_estimates: Optional[Dict[str, Dict[str, Optional[float]]]] = Field(
        default=None, description="Detailed A2022 and obs estimates across NDVI threshold grid"
    )
    cohort_breakdown: Optional[Dict[str, Any]] = Field(
        default=None, description="Hysteresis cohort breakdown and lower bounds"
    )
    pre_existing_decline_ha: Optional[float] = Field(
        default=None, description="Area of pre-existing forest decline in hectares"
    )
    saturation_share_pct: Optional[float] = Field(
        default=None, description="Percentage of qm>=0.75 project pixels in 2022 with raw NDVI >= 0.85"
    )
    saturation_pixel_count: Optional[int] = Field(
        default=None, description="Pixel count with qm>=0.75 and raw NDVI >= 0.85"
    )
    saturation_total_count: Optional[int] = Field(
        default=None, description="Total pixel count with qm>=0.75"
    )
    ring_p5_2019: Optional[float] = Field(
        default=None, description="Reference ring NDVI 5th percentile in 2019"
    )
    ring_p5_2022_raw: Optional[float] = Field(
        default=None, description="Reference ring raw NDVI 5th percentile in 2022"
    )
    ring_p5_2022_qm: Optional[float] = Field(
        default=None, description="Reference ring quantile-mapped NDVI 5th percentile in 2022"
    )
    dry_season_qc_scenes: Optional[Dict[str, int]] = Field(
        default=None, description="Number of dry-season QC-pass scenes per year"
    )
    file_hashes: Optional[Dict[str, str]] = Field(
        default=None, description="SHA-256 hashes of input timeseries and composites"
    )
    normalization_sensitivity: Optional[Dict[str, Any]] = Field(
        default=None, description="Sensitivity analysis of RAW composite vs Quantile-Mapped band"
    )
    hansen_crosscheck: Optional[Dict[str, Any]] = Field(
        default=None, description="Hansen Global Forest Change cross-check metrics and file hashes"
    )
    forest_allowance_check: Optional[Dict[str, Any]] = Field(
        default=None, description="Forest allowance break-even analysis and Hansen persistence check"
    )
    decline_analysis: Optional[Dict[str, Any]] = Field(
        default=None, description="Detailed connected components and decline set spatial analysis"
    )
    canopy_biomass: Optional[Dict[str, Any]] = Field(
        default=None, description="Detailed canopy cover and biomass proxy change analysis"
    )
    first_high_year_areas: Optional[Dict[str, float]] = Field(
        default=None, description="Observed hectares where qm NDVI >= 0.70 first per year (2019, 2020, 2021, 2022, never)"
    )


class DiscrepancyReport(BaseModel):
    """Cross-check comparison between claims and satellite estimates."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str = Field(..., description="Project identifier")
    claims: ProjectClaims = Field(..., description="Project claimed metrics")
    estimate: SatelliteEstimate = Field(..., description="Satellite-derived metrics")
    area_discrepancy_pct: Optional[float] = Field(
        default=None,
        description="Relative area difference percentage ((satellite - claimed) / claimed) * 100",
    )
    canopy_discrepancy_pct: Optional[float] = Field(
        default=None,
        description="Difference between satellite and claimed canopy change percentages",
    )
    planted_area_discrepancy_pct: Optional[float] = Field(
        default=None,
        description="One-sided planted area discrepancy percentage max(0, (claimed - obs_high)/claimed) * 100",
    )
    shortfall_central_ha: Optional[float] = Field(
        default=None,
        description="Planted area shortfall at central estimate (claimed - obs_central) in hectares",
    )
    shortfall_low_ha: Optional[float] = Field(
        default=None,
        description="Planted area shortfall at low estimate (claimed - obs_low) in hectares",
    )
    status: Union[VerificationStatus, Literal["CONSISTENT", "MINOR", "MAJOR", "INCONCLUSIVE"]] = Field(
        ..., description="Verification classification based on discrepancy thresholds"
    )
    confidence: Union[ConfidenceLevel, Literal["HIGH", "MEDIUM", "LOW"]] = Field(
        ..., description="Assessment confidence based on data quality"
    )
    confidence_reasons: List[str] = Field(
        default_factory=list,
        description="Explanatory reasons for reduced confidence if applicable",
    )
    observations: List[str] = Field(
        default_factory=list,
        description="Auditor observations and findings separate from confidence reasons",
    )
    notes: str = Field(default="", description="Auditor and pipeline notes")
    demo: bool = Field(default=False, description="Flag indicating if report is from demo fixture")

