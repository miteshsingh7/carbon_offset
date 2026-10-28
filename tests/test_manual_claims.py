"""Tests for manual claims override from project.yaml."""

import json
from pathlib import Path
import fitz
import pytest
import yaml

from carbonverify.claims.extractor import extract_claims
from carbonverify.schemas import ProjectClaims


def _create_synthetic_project(
    base_dir: Path,
    include_override: bool = True,
    override_area: float = 1850.5,
    override_quote: str = "The verified monitoring area is 1,850.5 ha for this period.",
) -> Path:
    """Create a temporary project with synthetic PDF documentation and optional project.yaml."""
    proj_dir = base_dir / ("proj_with_override" if include_override else "proj_no_override")
    docs_dir = proj_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    # Create synthetic monitoring report PDF
    pdf_path = docs_dir / "monitoring_report.pdf"
    doc = fitz.open()

    # Page 1: Project Details
    p1 = doc.new_page()
    p1.insert_text(
        (50, 72),
        "Monitoring Report: VCS Version 4.2\nProject ID 9999\nProject Name: Synthetic Forest Project\n"
        "Reporting period: 2021-01-01 to 2022-12-31\n",
    )

    # Page 2: Location
    p2 = doc.new_page()
    p2.insert_text(
        (50, 72),
        "The project estate encompasses a total property area of 3,500 ha on degraded pasture land.\n",
    )

    # Page 3: Area Claims
    p3 = doc.new_page()
    p3.insert_text(
        (50, 72),
        "The current project area is 1,200 ha of planted forest.\n"
        f"{override_quote}\n"
        "Natural forest stands: not applicable in production compartments.\n",
    )

    doc.save(pdf_path)
    doc.close()

    if include_override:
        project_yaml_content = {
            "claims_override": [
                {
                    "field": "claimed_area_ha",
                    "value": override_area,
                    "page": 3,
                    "quote": override_quote,
                },
                {
                    "field": "natural_forest_ha",
                    "value": 0.0,
                    "page": None,
                    "quote": None,
                },
            ]
        }
        with open(proj_dir / "project.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(project_yaml_content, f)

    return proj_dir


class TestManualClaimsOverride:
    """Test suite for manual claims override functionality."""

    def test_override_applied_with_metadata_and_original_value_kept(self, tmp_path: Path) -> None:
        """Verify override sets extractor, winner_reason, page, quote, and preserves original value."""
        override_area = 1850.5
        override_quote = "The verified monitoring area is 1,850.5 ha for this period."

        proj_dir = _create_synthetic_project(
            tmp_path,
            include_override=True,
            override_area=override_area,
            override_quote=override_quote,
        )
        out_dir = tmp_path / "output_override"

        claims = extract_claims(proj_dir, out_dir=out_dir)

        # 1. Verify claims object values
        assert isinstance(claims, ProjectClaims)
        assert claims.claimed_area_ha == override_area
        assert claims.natural_forest_ha == 0.0
        assert claims.source_pages["claimed_area_ha"] == 3
        # natural_forest_ha had page=None, should not be in source_pages
        assert "natural_forest_ha" not in claims.source_pages

        # 2. Verify extraction_report.json details
        rep_path = out_dir / "extraction_report.json"
        assert rep_path.exists()
        with open(rep_path, "r", encoding="utf-8") as f:
            rep_data = json.load(f)

        # Overridden report has extractor "manual_override"
        assert rep_data["extractor"] == "manual_override"

        # Overridden field details
        field_det = rep_data["fields"]["claimed_area_ha"]
        assert field_det["value"] == override_area
        assert field_det["page"] == 3
        assert field_det["evidence_quote"] == override_quote
        assert field_det["status"] == "accepted"
        assert field_det["reason"] == "manual_override"
        assert field_det["winner_reason"] == "manual_override"

        # Original value kept in raw_value and debug
        assert field_det["raw_value"] is not None
        assert "1,200" in str(field_det["raw_value"]) or "1200" in str(field_det["raw_value"])

        # Debug section captures manual_overrides and original_extracted_fields
        assert "manual_overrides" in rep_data["debug"]
        ov_debug = rep_data["debug"]["manual_overrides"]["claimed_area_ha"]
        assert ov_debug["extractor"] == "manual_override"
        assert ov_debug["value"] == override_area
        assert ov_debug["page"] == 3
        assert ov_debug["quote"] == override_quote
        assert ov_debug["original_value"] == 1200.0

        assert "original_extracted_fields" in rep_data["debug"]
        orig_fields = rep_data["debug"]["original_extracted_fields"]
        assert "claimed_area_ha" in orig_fields
        assert orig_fields["claimed_area_ha"]["value"] == 1200.0

    def test_project_without_override_behaves_identically(self, tmp_path: Path) -> None:
        """Verify project without claims_override key behaves identically to default rule-based extraction."""
        proj_dir = _create_synthetic_project(tmp_path, include_override=False)
        out_dir = tmp_path / "output_no_override"

        claims = extract_claims(proj_dir, out_dir=out_dir)

        # Claims object values derived purely by rule-based extraction
        assert isinstance(claims, ProjectClaims)
        assert claims.claimed_area_ha == 1200.0
        assert claims.natural_forest_ha is None

        rep_path = out_dir / "extraction_report.json"
        assert rep_path.exists()
        with open(rep_path, "r", encoding="utf-8") as f:
            rep_data = json.load(f)

        # Extractor is default rule_based
        assert rep_data["extractor"] == "rule_based"
        field_det = rep_data["fields"]["claimed_area_ha"]
        assert field_det["value"] == 1200.0
        assert field_det["winner_reason"] != "manual_override"
        assert field_det["reason"] != "manual_override"

        # No manual overrides recorded in debug
        assert "manual_overrides" not in rep_data.get("debug", {})
