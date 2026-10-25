"""Unit and integration tests for claims extraction, validation, and normalization."""

import json
from pathlib import Path
import shutil
from unittest.mock import patch
import pytest

from carbonverify.claims.extractor import compute_file_sha256, extract_claims
from carbonverify.claims.llm import MockLLMClient
from carbonverify.claims.normalizer import (
    normalize_area,
    normalize_canopy_change,
    normalize_credits,
    normalize_date,
    normalize_registry,
    validate_evidence_quote,
)
from carbonverify.claims.ollama import OllamaLLMClient
from carbonverify.claims.pdf_parser import extract_pages_from_pdf
from carbonverify.claims.retrieval import retrieve_candidates_for_field
from carbonverify.claims.rule_based import RuleBasedExtractor
from carbonverify.schemas import Registry, SatelliteEstimate, VerificationStatus
from carbonverify.scoring.discrepancy import score

SYNTHETIC_PDD = Path("tests/fixtures/synthetic_pdd.pdf")


class TestUnitNormalization:
    """Test suite for unit and format normalizers."""

    def test_normalize_area_hectares(self) -> None:
        """Verify parsing and normalization of hectare units."""
        assert normalize_area("14,500 ha") == 14500.0
        assert normalize_area("14500 hectares") == 14500.0
        assert normalize_area("12500.5 ha") == 12500.5
        assert normalize_area(10000) == 10000.0

    def test_normalize_area_km2(self) -> None:
        """Verify conversion of square kilometers to hectares (1 km2 = 100 ha)."""
        assert normalize_area("120 km2") == 12000.0
        assert normalize_area("185 km²") == 18500.0
        assert normalize_area("10 sq km") == 1000.0

    def test_normalize_area_acres(self) -> None:
        """Verify conversion of acres to hectares (1 acre ~ 0.404686 ha)."""
        res = normalize_area("24,710.5 acres")
        assert res is not None
        assert abs(res - 10000.0) < 1.0

    def test_normalize_area_invalid(self) -> None:
        """Verify invalid or unparseable area values return None."""
        assert normalize_area("no area mentioned") is None
        assert normalize_area(None) is None
        assert normalize_area(-50) is None

    def test_normalize_date_formats(self) -> None:
        """Verify parsing of various date representations into ISO YYYY-MM-DD."""
        assert normalize_date("2021-01-01") == "2021-01-01"
        assert normalize_date("2023/12/31") == "2023-12-31"
        assert normalize_date("January 1, 2021") == "2021-01-01"
        assert normalize_date("31 December 2023") == "2023-12-31"
        assert normalize_date("invalid date") is None
        assert normalize_date(None) is None

    def test_normalize_canopy_change(self) -> None:
        """Verify parsing of percentage canopy cover changes."""
        assert normalize_canopy_change("+3.2%") == 3.2
        assert normalize_canopy_change("-1.85%") == -1.85
        assert normalize_canopy_change("2.5") == 2.5
        assert normalize_canopy_change(None) is None

    def test_normalize_credits(self) -> None:
        """Verify parsing of integer carbon credits."""
        assert normalize_credits("340,000 VCUs") == 340000
        assert normalize_credits("150000") == 150000
        assert normalize_credits(50000) == 50000
        assert normalize_credits("none") is None

    def test_normalize_registry(self) -> None:
        """Verify registry enum parsing."""
        assert normalize_registry("Verified Carbon Standard (Verra)") == Registry.VERRA
        assert normalize_registry("verra") == Registry.VERRA
        assert normalize_registry("Gold Standard Foundation") == Registry.GOLD_STANDARD
        assert normalize_registry("Random Registry") is None


class TestEvidenceQuoteValidation:
    """Test suite for anti-hallucination evidence quote validation."""

    def test_accepts_verbatim_quote_on_cited_page(self) -> None:
        """Verify exact verbatim quote is accepted."""
        page_text = (
            "The project accounting boundary encompasses a verified total area "
            "of 18,500 hectares of primary tropical moist forest."
        )
        quote = "encompasses a verified total area of 18,500 hectares"
        assert validate_evidence_quote(quote, page_text) is True

    def test_accepts_quote_with_normalized_whitespace(self) -> None:
        """Verify quote matching succeeds despite line breaks or excess spaces."""
        page_text = "Project ID:\n   VCS-1396\n   Status: Active"
        quote = "Project ID: VCS-1396"
        assert validate_evidence_quote(quote, page_text) is True

    def test_rejects_fabricated_quote(self) -> None:
        """Verify fabricated quote not present in page text is rejected."""
        page_text = "Project covers 18,500 hectares of forest."
        fake_quote = "The project strictly covers 99,999 hectares of degraded grassland."
        assert validate_evidence_quote(fake_quote, page_text) is False

    def test_rejects_empty_or_none_quotes(self) -> None:
        """Verify empty or None quotes return False."""
        assert validate_evidence_quote(None, "sample text") is False
        assert validate_evidence_quote("", "sample text") is False
        assert validate_evidence_quote("quote", "") is False


class TestRuleBasedExtraction:
    """Test suite for default 100% free RuleBasedExtractor."""

    def test_pdf_parsing_and_sha256(self) -> None:
        """Verify PyMuPDF extracts pages and SHA-256 hash is computed."""
        assert SYNTHETIC_PDD.exists()
        pages = extract_pages_from_pdf(SYNTHETIC_PDD)

        assert len(pages) == 5
        assert pages[0]["page"] == 1
        assert "VCS-1396" in pages[0]["text"]

        sha256_val = compute_file_sha256(SYNTHETIC_PDD)
        assert len(sha256_val) == 64
        assert int(sha256_val, 16) > 0

    def test_rule_based_extractor_direct(self) -> None:
        """Verify RuleBasedExtractor extracts all VCS fields with pattern scoring."""
        pages = extract_pages_from_pdf(SYNTHETIC_PDD)
        extractor = RuleBasedExtractor()
        details = extractor.extract(pages)

        assert details["project_id"].status == "accepted"
        assert details["project_id"].value == "VCS-1396"

        assert details["registry"].status == "accepted"
        assert details["registry"].value == Registry.VERRA

        assert details["methodology"].status == "accepted"
        assert details["methodology"].value == "VM0007"

        assert details["claimed_area_ha"].status == "accepted"
        assert details["claimed_area_ha"].value == 18500.0

        assert details["reporting_period_start"].status == "accepted"
        assert details["reporting_period_start"].value == "2021-01-01"

        assert details["reporting_period_end"].status == "accepted"
        assert details["reporting_period_end"].value == "2023-12-31"

        assert details["credits_issued"].status == "accepted"
        assert details["credits_issued"].value == 340000

        assert details["claimed_canopy_change_pct"].status == "accepted"
        assert details["claimed_canopy_change_pct"].value == 3.2

    def test_default_pipeline_extraction_uses_rule_based(self, tmp_path: Path) -> None:
        """Verify extract_claims defaults to RuleBasedExtractor without any API keys."""
        out_dir = tmp_path / "out_rule_based"

        # Call with no client injected -> should run RuleBasedExtractor by default
        claims = extract_claims(
            doc_path=SYNTHETIC_PDD,
            out_dir=out_dir,
        )

        assert claims.project_id == "VCS-1396"
        assert claims.registry == Registry.VERRA
        assert claims.methodology == "VM0007"
        assert claims.claimed_area_ha == 18500.0
        assert str(claims.reporting_period_start) == "2021-01-01"
        assert str(claims.reporting_period_end) == "2023-12-31"
        assert claims.credits_issued == 340000
        assert claims.claimed_canopy_change_pct == 3.2
        assert claims.demo is False

        # Verify extraction_report.json provenance attributes
        report_file = out_dir / "extraction_report.json"
        assert report_file.exists()
        with open(report_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["extractor"] == "rule_based"
        assert data["pdf_sha256"] is not None
        assert len(data["pdf_sha256"]) == 64
        assert data["fields"]["claimed_area_ha"]["status"] == "accepted"


class TestOllamaClientAndFallbacks:
    """Test suite for optional Ollama fallback client."""

    def test_ollama_fallback_mocked(self, tmp_path: Path) -> None:
        """Verify Ollama client is called for missing fields when configured."""
        config_override = {
            "extraction": {
                "extractor": "ollama",
                "ollama": {
                    "base_url": "http://localhost:11434",
                    "model": "qwen2.5:7b",
                },
            }
        }

        # Mock Ollama HTTP response providing a missing canopy change field
        mock_response = {
            "claimed_canopy_change_pct": {
                "value": "+3.2%",
                "evidence_quote": "claimed canopy change of +3.2% across the project accounting area",
                "page": 5,
            }
        }

        with patch.object(OllamaLLMClient, "_call_ollama", return_value=mock_response):
            claims = extract_claims(
                doc_path=SYNTHETIC_PDD,
                config=config_override,
                out_dir=tmp_path / "out_ollama",
            )
            assert claims.claimed_canopy_change_pct == 3.2

    def test_ollama_unreachable_falls_back_gracefully(self, tmp_path: Path) -> None:
        """Verify pipeline succeeds with rule-based results even if Ollama is unreachable."""
        config_override = {
            "extraction": {
                "extractor": "ollama",
                "ollama": {
                    "base_url": "http://localhost:9999",  # Non-existent port
                    "model": "qwen2.5:7b",
                    "timeout_seconds": 1,
                },
            }
        }

        claims = extract_claims(
            doc_path=SYNTHETIC_PDD,
            config=config_override,
            out_dir=tmp_path / "out_offline_ollama",
        )
        assert claims.project_id == "VCS-1396"
        assert claims.claimed_area_ha == 18500.0


class TestMockClientInjectionAndAntiHallucination:
    """Test suite for explicit mock client injection and missing-field safety."""

    def test_explicit_mock_client_injection(self, tmp_path: Path) -> None:
        """Verify MockLLMClient can be injected explicitly in tests."""
        mock_client = MockLLMClient()
        claims = extract_claims(
            doc_path=SYNTHETIC_PDD,
            llm_client=mock_client,
            out_dir=tmp_path / "out_injected_mock",
        )
        assert claims.project_id == "VCS-1396"

        report_file = tmp_path / "out_injected_mock" / "extraction_report.json"
        with open(report_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["extractor"] == "mock"

    def test_hallucination_rejection(self, tmp_path: Path) -> None:
        """Verify that fabricated quotes injected via mock are rejected and set field to None."""
        tampered_responses = {
            "project_id": {"value": "VCS-1396", "evidence_quote": "Project ID: VCS-1396", "page": 1},
            "registry": {"value": "verra", "evidence_quote": "Verified Carbon Standard (Verra)", "page": 1},
            "claimed_area_ha": {"value": "18,500 hectares", "evidence_quote": "total area of 18,500 hectares", "page": 3},
            "credits_issued": {
                "value": "9,999,999 VCUs",
                "evidence_quote": "Fabricated quote that does not appear anywhere on page 1",
                "page": 1,
            },
        }

        mock_client = MockLLMClient(predefined_responses=tampered_responses)
        claims = extract_claims(
            doc_path=SYNTHETIC_PDD,
            llm_client=mock_client,
            out_dir=tmp_path / "out_hallucination",
        )

        assert claims.credits_issued is None
        assert "credits_issued" not in claims.source_pages

    def test_missing_fields_produce_inconclusive_pipeline(self, tmp_path: Path) -> None:
        """Verify missing critical claims produce INCONCLUSIVE status without crashing."""
        missing_responses = {
            "project_id": {"value": "VCS-INCOMPLETE", "evidence_quote": "Project ID: VCS-1396", "page": 1},
            "registry": {"value": "verra", "evidence_quote": "Verified Carbon Standard (Verra)", "page": 1},
            "claimed_area_ha": {"value": None, "evidence_quote": None, "page": None},
            "reporting_period_start": {"value": None, "evidence_quote": None, "page": None},
            "reporting_period_end": {"value": None, "evidence_quote": None, "page": None},
        }

        claims = extract_claims(
            doc_path=SYNTHETIC_PDD,
            llm_client=MockLLMClient(predefined_responses=missing_responses),
            out_dir=tmp_path,
        )

        assert claims.claimed_area_ha is None
        assert claims.reporting_period_start is None

        placeholder = SatelliteEstimate(
            area_ha=100.0,
            ndvi_mean_start=0.5,
            ndvi_mean_end=0.5,
            canopy_change_pct=0.0,
            biomass_proxy_change_pct=0.0,
            reference_buffer_change_pct=0.0,
            valid_observation_count=10,
            mean_cloud_cover_pct=5.0,
        )
        report = score(claims=claims, estimate=placeholder)

        assert report.status == VerificationStatus.INCONCLUSIVE
        assert "critical claims" in report.notes.lower()
        assert report.area_discrepancy_pct is None

    def test_demo_claims_flagged_with_demo_true(self) -> None:
        """Verify demo claims.json is loaded with demo=True flag."""
        demo_json = Path("data/projects/demo/claims.json")
        claims = extract_claims(demo_json)

        assert claims.demo is True
        assert claims.project_id == "demo"
        assert claims.claimed_area_ha == 12500.0


class TestMultiDocumentSelectionAndOCR:
    """Test suite for multi-document priority resolution and scanned PDF OCR check."""

    def test_multi_document_selection_priority(self, tmp_path: Path) -> None:
        """Verify monitoring_report wins for credits/area, and pdd wins for methodology/id."""
        import fitz

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True)

        # Create pdd.pdf
        pdd_path = docs_dir / "pdd.pdf"
        pdd_doc = fitz.open()
        pdd_page = pdd_doc.new_page()
        pdd_page.insert_text(
            (50, 72),
            "Verified Carbon Standard Project Description (PDD)\n"
            "Project ID: VCS-8888\n"
            "Applied Methodology: VM0047\n"
            "Project area: 5,000 ha\n"
            "Estimated GHG emission reductions: 10,000 VCUs\n"
            + ("Detailed methodology and baseline information text. " * 10),
        )
        pdd_doc.save(pdd_path)
        pdd_doc.close()

        # Create monitoring_report.pdf
        mr_path = docs_dir / "monitoring_report.pdf"
        mr_doc = fitz.open()
        mr_page = mr_doc.new_page()
        mr_page.insert_text(
            (50, 72),
            "Verified Carbon Standard Monitoring Report\n"
            "Project ID: VCS-9999\n"
            "Methodology: VM0007\n"
            "Project area: 7,500 ha\n"
            "Credits issued: 45,000 VCUs\n"
            + ("Detailed monitoring observations and verification metrics text. " * 10),
        )
        mr_doc.save(mr_path)
        mr_doc.close()

        out_dir = tmp_path / "output"
        claims = extract_claims(tmp_path, out_dir=out_dir)

        # Verification of priority rules:
        # PDD wins for project_id and methodology
        assert claims.project_id == "VCS-8888"
        assert claims.methodology == "VM0047"
        # Monitoring Report wins for claimed_area_ha and credits_issued
        assert claims.claimed_area_ha == 7500.0
        assert claims.credits_issued == 45000

        # Check extraction_report.json details
        rep_file = out_dir / "extraction_report.json"
        assert rep_file.exists()
        with open(rep_file, "r", encoding="utf-8") as f:
            report_data = json.load(f)

        fields = report_data["fields"]
        assert fields["project_id"]["source_doc"] == "pdd.pdf"
        assert "pdd prioritized" in fields["project_id"]["winner_reason"].lower()

        assert fields["methodology"]["source_doc"] == "pdd.pdf"
        assert "pdd prioritized" in fields["methodology"]["winner_reason"].lower()

        assert fields["claimed_area_ha"]["source_doc"] == "monitoring_report.pdf"
        assert "monitoring_report prioritized" in fields["claimed_area_ha"]["winner_reason"].lower()

        assert fields["credits_issued"]["source_doc"] == "monitoring_report.pdf"
        assert "monitoring_report prioritized" in fields["credits_issued"]["winner_reason"].lower()

        # Verify debug section top_candidates
        assert "top_candidates" in report_data["debug"]
        assert len(report_data["debug"]["top_candidates"]["credits_issued"]) >= 2

    def test_scanned_pdf_ocr_needed_flag(self, tmp_path: Path) -> None:
        """Verify document averaging under 100 chars/page is flagged as OCR needed and skipped."""
        import fitz

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True)

        scanned_path = docs_dir / "scanned_doc.pdf"
        doc = fitz.open()
        p = doc.new_page()
        # Insert minimal text (< 50 chars)
        p.insert_text((50, 72), "Scan image only.")
        doc.save(scanned_path)
        doc.close()

        out_dir = tmp_path / "output"
        claims = extract_claims(tmp_path, out_dir=out_dir)

        assert claims.project_id is None
        assert claims.claimed_area_ha is None

        rep_file = out_dir / "extraction_report.json"
        assert rep_file.exists()
        with open(rep_file, "r", encoding="utf-8") as f:
            report_data = json.load(f)

        stats = report_data["document_stats"]["scanned_doc.pdf"]
        assert stats["ocr_needed"] is True
        assert "OCR needed" in stats["status"]
        assert stats["avg_chars_per_page"] < 100.0


class TestVCSAuditRegressions:
    """Regression tests based on short plain-text snippets from VCS Project 2469 audit."""

    def test_monitoring_and_crediting_period_extraction(self) -> None:
        """Verify label-anchored period date extraction with day-first parsing and en-dash."""
        extractor = RuleBasedExtractor()

        # Monitoring Period snippet
        mr_text = (
            "FORESTAL AZUL CARBON PROJECT\n"
            "Project ID 2469\n"
            "Monitoring Period 01-January-2021 – 30-September-2022\n"
            "Document Prepared by UNIQUE\n"
        )
        pages_mr = [{"page": 1, "text": mr_text}]
        details_mr = extractor.extract(pages_mr)
        assert details_mr["reporting_period_start"].status == "accepted"
        assert details_mr["reporting_period_start"].value == "2021-01-01"
        assert details_mr["reporting_period_end"].status == "accepted"
        assert details_mr["reporting_period_end"].value == "2022-09-30"

        # Tabular Crediting Period snippet
        cred_text = (
            "1.5 Project Start Date\n"
            "Starting date of the ARR project activity: 01-06-2018.\n"
            "1.6 Project Crediting Period\n"
            "Project start date:\n"
            "Project end date:\n"
            "01-06-2018\n"
            "31-05-2038\n"
            "Total number of crediting years: 20\n"
        )
        pages_cred = [{"page": 5, "text": cred_text}]
        details_cred = extractor.extract(pages_cred)
        assert details_cred["project_start_date"].status == "accepted"
        assert details_cred["project_start_date"].value == "2018-06-01"
        assert details_cred["crediting_period_start"].status == "accepted"
        assert details_cred["crediting_period_start"].value == "2018-06-01"
        assert details_cred["crediting_period_end"].status == "accepted"
        assert details_cred["crediting_period_end"].value == "2038-05-31"

    def test_credits_and_buffer_extraction_with_toc_filtering(self) -> None:
        """Verify credits, net removals, buffer pool, and rejection of table-of-contents dots."""
        extractor = RuleBasedExtractor()

        # TOC dotted leader lines from PDD p. 2/3 should be ignored
        toc_text = (
            "TABLE OF CONTENTS\n"
            "1.10 Project Scale and Estimated GHG Emission Reductions or Removals..................... 13\n"
            "4 ESTIMATED GHG EMISSION REDUCTIONS AND REMOVALS ............................... 67\n"
            "4.4 Estimated Net GHG Emission Reductions and Removals ......................................... 82\n"
        )
        details_toc = extractor.extract([{"page": 2, "text": toc_text}])
        assert details_toc["credits_issued"].status == "missing"

        # Real credits paragraph spanning lines
        credits_text = (
            "The GHG emission reduction generated from the plantations until 30-09-2022 for this monitoring\n"
            "report are 77,834 tCO2e. The non-permanence risk rating is 12% (as determined in the AFOLU\n"
            "non-permanence risk report attached as a separate document). Therefore, the total number of\n"
            "buffer credits that need to be deposited into the AFOLU pooled buffer account is 9,340 tCO2e.\n"
            "The number of GHG credits eligible to be issued as VCUs for the first project instances of this\n"
            "monitoring period is 68,493 tCO2e.\n"
        )
        details_real = extractor.extract([{"page": 3, "text": credits_text}])
        assert details_real["credits_issued"].status == "accepted"
        assert details_real["credits_issued"].value == 68493
        assert details_real["net_ghg_removals_tco2e"].status == "accepted"
        assert details_real["net_ghg_removals_tco2e"].value == 77834
        assert details_real["buffer_credits_tco2e"].status == "accepted"
        assert details_real["buffer_credits_tco2e"].value == 9340

        # Consistency check: 77,834 - 9,340 = 68,494 (diff = 1 <= 2)
        diff = abs((77834 - 9340) - 68493)
        assert diff <= 2

    def test_forest_definition_distinguished_from_canopy_change(self) -> None:
        """Verify forest definition is not treated as a canopy change claim."""
        extractor = RuleBasedExtractor()

        # Forest definition snippet from PDD p. 69
        forest_def_text = (
            "Therefore, the canopy cover assessment has the following implications on the assessment:\n"
            "Baseline shrub carbon stock\n"
            "The baseline carbon stock is estimated using the forest definition of Paraguay, whi ch is defined\n"
            "as 25% tree coverage, 0.5 ha and 5m of minimum tree height. According to AR-Tool 14, chapter\n"
            "11 the shrub carbon stock is accounted as 0 t C/ha, since shrub coverage is <5%.\n"
        )
        details = extractor.extract([{"page": 69, "text": forest_def_text}])

        # A forest definition is NOT a change claim
        assert details["claimed_canopy_change_pct"].status == "missing"
        # Forest definition thresholds extracted accurately
        assert details["canopy_cover_pct"].status == "accepted"
        assert details["canopy_cover_pct"].value == 25.0
        assert details["min_area_ha"].status == "accepted"
        assert details["min_area_ha"].value == 0.5
        assert details["min_height_m"].status == "accepted"
        assert details["min_height_m"].value == 5.0

    def test_registry_url_line_rejection(self) -> None:
        """Verify bare URL lines are never accepted as registry evidence."""
        extractor = RuleBasedExtractor()

        # URL citation from PDD p. 7
        url_text = (
            "1 https://verra.org/wp-content/uploads/2020/03/VCS-Standard-v4.0_Updated.pdf\n"
            "Document version 4.0\n"
        )
        details_url = extractor.extract([{"page": 7, "text": url_text}])
        assert details_url["registry"].status == "missing"

        # Standard header from MR p. 3
        vcs_header_text = (
            "Monitoring Report: VCS Version 4.2\n"
            "1 PROJECT DETAILS\n"
            "1.1 Summary Description of the Implementation Status\n"
        )
        details_header = extractor.extract([{"page": 3, "text": vcs_header_text}])
        assert details_header["registry"].status == "accepted"
        assert details_header["registry"].value == Registry.VERRA

    def test_estate_area_and_claimed_area_distinction(self) -> None:
        """Verify estate area (property title) vs claimed management area."""
        extractor = RuleBasedExtractor()

        # MR p. 5 snippet for estate area
        estate_text = (
            "1.7 Project Location\n"
            "The project is located on a single estate (known as Estancia or Finca) with an area of 2,309 ha\n"
            "(Estancia Rodeo Guazu). It is located in the eastern region of Paraguay.\n"
        )
        details_estate = extractor.extract([{"page": 5, "text": estate_text}])
        assert details_estate["estate_area_ha"].status == "accepted"
        assert details_estate["estate_area_ha"].value == 2309.0

        # MR p. 3 snippet for claimed management area
        claimed_text = (
            "The current project area is 1,300 ha. 7 ha were lost due map adjustment.\n"
        )
        details_claimed = extractor.extract([{"page": 3, "text": claimed_text}])
        assert details_claimed["claimed_area_ha"].status == "accepted"
        assert details_claimed["claimed_area_ha"].value == 1300.0

    def test_natural_forest_extraction(self) -> None:
        """Verify extraction of natural forest allowance area."""
        extractor = RuleBasedExtractor()
        text = "The remaining natural forests with a total area of 541 ha consist of three forest types."
        details = extractor.extract([{"page": 19, "text": text}])
        assert details["natural_forest_ha"].status == "accepted"
        assert details["natural_forest_ha"].value == 541.0
        assert details["natural_forest_ha"].page == 19

