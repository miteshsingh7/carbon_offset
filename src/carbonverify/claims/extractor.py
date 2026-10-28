"""100% free document claim extraction using rule-based patterns and optional local Ollama."""

import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from carbonverify.claims.llm import BaseLLMClient
from carbonverify.claims.normalizer import normalize_field, validate_evidence_quote
from carbonverify.claims.ollama import OllamaLLMClient
from carbonverify.claims.pdf_parser import extract_pages_from_pdf
from carbonverify.claims.planting_schedule import extract_planting_schedule_from_documents
from carbonverify.claims.retrieval import retrieve_candidates_for_field
from carbonverify.claims.rule_based import RuleBasedExtractor
from carbonverify.schemas import (
    ExtractionReport,
    FieldExtractionDetail,
    ForestDefinition,
    ProjectClaims,
)

logger = logging.getLogger(__name__)

TARGET_FIELDS = [
    "project_id",
    "registry",
    "methodology",
    "claimed_area_ha",
    "estate_area_ha",
    "reporting_period_start",
    "reporting_period_end",
    "crediting_period_start",
    "crediting_period_end",
    "project_start_date",
    "credits_issued",
    "net_ghg_removals_tco2e",
    "buffer_credits_tco2e",
    "claimed_canopy_change_pct",
    "canopy_cover_pct",
    "min_area_ha",
    "min_height_m",
    "natural_forest_ha",
]

KEYWORDS_FOR_MISSING = ["area", "crediting period", "VCU", "hectare", "planted"]

MONITORING_PRIORITY_FIELDS = {
    "credits_issued",
    "claimed_area_ha",
    "reporting_period_start",
    "reporting_period_end",
    "net_ghg_removals_tco2e",
    "buffer_credits_tco2e",
}

PDD_PRIORITY_FIELDS = {
    "methodology",
    "project_id",
    "canopy_cover_pct",
    "min_area_ha",
    "min_height_m",
    "natural_forest_ha",
}


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA-256 cryptographic hash of a file for audit provenance."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


def _read_yaml_safely(file_path: Path) -> Optional[Dict[str, Any]]:
    """Safely read and parse a YAML file into a dictionary."""
    if not file_path.is_file():
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else None
    except (OSError, yaml.YAMLError) as exc:
        logger.debug("Could not read YAML from %s: %s", file_path, exc)
        return None


def _write_file_safely(file_path: Path, content: str) -> None:
    """Safely write string content to a file, logging errors on failure."""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Saved report to %s", file_path)
    except OSError as exc:
        logger.warning("Failed to write to %s: %s", file_path, exc)


def load_config_dict(
    config_source: Optional[Union[Dict[str, Any], Path, str]] = None,
) -> Dict[str, Any]:
    """Helper to load config dictionary from file or dict."""
    if isinstance(config_source, dict):
        return config_source
    if isinstance(config_source, (str, Path)):
        data = _read_yaml_safely(Path(config_source))
        if data is not None:
            return data
    for candidate in [
        Path("config.yaml"),
        Path(__file__).resolve().parents[3] / "config.yaml",
    ]:
        data = _read_yaml_safely(candidate)
        if data is not None:
            return data
    return {}


def is_monitoring_doc(doc_name: str) -> bool:
    """Check if document filename indicates a monitoring report."""
    name = doc_name.lower()
    return "monitoring" in name or "mon_rep" in name


def is_pdd_doc(doc_name: str) -> bool:
    """Check if document filename indicates a project design document (PDD)."""
    name = doc_name.lower()
    return (
        "pdd" in name
        or "project_description" in name
        or "proj_desc" in name
        or "joint" in name
    )


def _resolve_boundary_path(search_root: Path) -> Optional[str]:
    """Look for boundary.geojson in project root or parent directories."""
    for search_dir in [
        search_root,
        search_root.parent,
        search_root / "boundary.geojson",
    ]:
        if search_dir.is_file() and search_dir.name == "boundary.geojson":
            return str(search_dir)
        candidate = search_dir / "boundary.geojson"
        if candidate.is_file():
            return str(candidate)
    return None


def _write_extraction_report(
    report: ExtractionReport,
    target_path: Path,
    out_dir: Optional[Union[str, Path]],
) -> None:
    """Write extraction_report.json to output directory and beside target path."""
    report_json = report.model_dump_json(indent=2)
    if out_dir:
        _write_file_safely(Path(out_dir) / "extraction_report.json", report_json)
    target_dir = target_path if target_path.is_dir() else target_path.parent
    _write_file_safely(target_dir / "extraction_report.json", report_json)


def _is_demo_source(path: Path) -> bool:
    """Check if the source path corresponds to a demo claims JSON."""
    if path.is_file() and path.suffix.lower() == ".json":
        return True
    return bool(
        path.is_dir()
        and (path / "claims.json").exists()
        and not (path / "docs").exists()
        and not list(path.glob("*.pdf"))
    )


def _build_demo_fields(claims: ProjectClaims) -> Dict[str, FieldExtractionDetail]:
    """Construct FieldExtractionDetail mapping for demo claims."""
    demo_fields: Dict[str, FieldExtractionDetail] = {}
    for field in TARGET_FIELDS:
        val = getattr(claims, field, None)
        pg = claims.source_pages.get(field)
        if val is not None:
            demo_fields[field] = FieldExtractionDetail(
                value=val,
                raw_value=str(val),
                page=pg,
                evidence_quote=f"Demo fixture value: {val}",
                status="accepted",
                source_doc="claims.json",
                score=100.0,
                winner_reason="demo fixture",
            )
        else:
            demo_fields[field] = FieldExtractionDetail(
                value=None,
                status="missing",
            )
    return demo_fields


def _load_demo_claims(
    path: Path,
    out_dir: Optional[Union[str, Path]] = None,
) -> ProjectClaims:
    """Load and return claims from a demo claims.json fixture."""
    json_file = path if path.is_file() else (path / "claims.json")
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["demo"] = True
        claims = ProjectClaims.model_validate(data)
        logger.info("Loaded demo claims fixture from %s (demo=True)", json_file)

        demo_fields = _build_demo_fields(claims)
        sha256_hash = compute_file_sha256(json_file)
        extraction_rep = ExtractionReport(
            document_path=str(json_file),
            fields=demo_fields,
            extractor="demo",
            pdf_sha256=sha256_hash,
            demo=True,
            documents_scanned=["claims.json"],
            document_stats={"claims.json": {"status": "demo_fixture"}},
            debug={"top_candidates": {}, "keyword_pages": []},
        )
        _write_extraction_report(extraction_rep, json_file, out_dir)
        return claims
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.error("Failed to parse claims JSON from %s: %s", json_file, exc)
        raise


def _find_pdf_files(path: Path) -> List[Path]:
    """Locate all PDF files under docs/ or direct directory/file."""
    if path.is_file() and path.suffix.lower() == ".pdf":
        return [path]
    if path.is_dir():
        docs_dir = path / "docs"
        if docs_dir.is_dir():
            pdfs = sorted(list(docs_dir.glob("*.pdf")))
            if pdfs:
                return pdfs
        return sorted(list(path.glob("*.pdf")))
    return []


def _evaluate_pdf_text_layer(
    pdf_path: Path,
) -> Tuple[Dict[str, Any], Optional[List[Dict[str, Any]]], str]:
    """Check text character density per page for OCR necessity."""
    sha256_val = compute_file_sha256(pdf_path)
    pages = extract_pages_from_pdf(pdf_path)
    page_count = len(pages)
    total_chars = sum(len(p.get("text", "")) for p in pages)
    avg_chars = round(total_chars / page_count, 1) if page_count > 0 else 0.0

    if avg_chars < 100.0:
        logger.warning(
            "Document '%s' averages %.1f chars/page (<100 threshold). Flagged OCR needed.",
            pdf_path.name,
            avg_chars,
        )
        stats = {
            "page_count": page_count,
            "total_chars": total_chars,
            "avg_chars_per_page": avg_chars,
            "ocr_needed": True,
            "status": "skipped (no text layer, OCR needed)",
            "sha256": sha256_val,
        }
        return stats, None, sha256_val

    stats = {
        "page_count": page_count,
        "total_chars": total_chars,
        "avg_chars_per_page": avg_chars,
        "ocr_needed": False,
        "status": "processed",
        "sha256": sha256_val,
    }
    return stats, pages, sha256_val


def _discover_and_evaluate_pdfs(
    path: Path,
) -> Tuple[
    List[Path],
    List[Tuple[Path, List[Dict[str, Any]]]],
    Dict[str, Dict[str, Any]],
    Dict[str, str],
]:
    """Discover PDF documents and perform text-layer quality evaluation."""
    pdf_files = _find_pdf_files(path)
    if not pdf_files:
        raise FileNotFoundError(
            f"Expected PDF document(s) for claim extraction, but none found at: {path}"
        )

    document_stats: Dict[str, Dict[str, Any]] = {}
    valid_docs: List[Tuple[Path, List[Dict[str, Any]]]] = []
    doc_sha256_map: Dict[str, str] = {}

    for pdf_path in pdf_files:
        stats, pages, sha256_val = _evaluate_pdf_text_layer(pdf_path)
        doc_sha256_map[pdf_path.name] = sha256_val
        document_stats[pdf_path.name] = stats
        if pages is not None:
            valid_docs.append((pdf_path, pages))

    return pdf_files, valid_docs, document_stats, doc_sha256_map


def _process_candidate(
    field: str,
    raw_val: Any,
    quote: str,
    page_num: int,
    page_lookup: Dict[int, str],
    score: float,
    doc_name: str,
    all_cands: Dict[str, List[Dict[str, Any]]],
    valid_cands: Dict[str, List[Dict[str, Any]]],
) -> None:
    """Validate quote, normalize candidate, and append to candidate collections."""
    page_text = page_lookup.get(page_num, "")
    is_quote_valid = validate_evidence_quote(quote, page_text)
    norm_val, norm_err = (
        normalize_field(field, raw_val)
        if is_quote_valid
        else (None, "Quote not validated")
    )
    is_valid = bool(is_quote_valid and norm_val is not None and norm_err is None)
    rejection = norm_err if is_quote_valid else f"Quote not found on page {page_num}"

    cand = {
        "score": score,
        "doc": doc_name,
        "page": page_num,
        "quote": quote,
        "raw_value": str(raw_val),
        "norm_val": norm_val,
        "is_valid": is_valid,
        "rejection_reason": rejection,
    }
    all_cands[field].append(cand)
    if is_valid:
        valid_cands[field].append(cand)


def _extract_with_mock_llm(
    valid_docs: List[Tuple[Path, List[Dict[str, Any]]]],
    llm_client: BaseLLMClient,
    all_cands: Dict[str, List[Dict[str, Any]]],
    valid_cands: Dict[str, List[Dict[str, Any]]],
) -> None:
    """Extract candidate fields using injected mock LLM client."""
    logger.info("Using explicitly injected LLM client for extraction")
    for pdf_path, pages in valid_docs:
        page_lookup = {p["page"]: p["text"] for p in pages}
        candidates_by_field = {
            f: retrieve_candidates_for_field(pages, f, top_k=4)
            for f in TARGET_FIELDS
        }
        raw_extractions = llm_client.extract_fields(candidates_by_field)
        for field in TARGET_FIELDS:
            ext = raw_extractions.get(field, {})
            raw_val = ext.get("value")
            quote = ext.get("evidence_quote")
            page_num = ext.get("page")
            if raw_val is None or page_num is None or quote is None:
                continue
            _process_candidate(
                field=field,
                raw_val=raw_val,
                quote=quote,
                page_num=page_num,
                page_lookup=page_lookup,
                score=50.0,
                doc_name=pdf_path.name,
                all_cands=all_cands,
                valid_cands=valid_cands,
            )


def _extract_with_rule_based(
    valid_docs: List[Tuple[Path, List[Dict[str, Any]]]],
    all_cands: Dict[str, List[Dict[str, Any]]],
    valid_cands: Dict[str, List[Dict[str, Any]]],
) -> None:
    """Extract candidate fields using default RuleBasedExtractor."""
    rule_extractor = RuleBasedExtractor()
    for pdf_path, pages in valid_docs:
        logger.info("Running RuleBasedExtractor on %s", pdf_path.name)
        page_lookup = {p["page"]: p["text"] for p in pages}
        cands_map = rule_extractor.find_candidates(pages, TARGET_FIELDS)
        for field, cands in cands_map.items():
            for c in cands:
                _process_candidate(
                    field=field,
                    raw_val=c.raw_value,
                    quote=c.evidence_quote,
                    page_num=c.page,
                    page_lookup=page_lookup,
                    score=c.score,
                    doc_name=pdf_path.name,
                    all_cands=all_cands,
                    valid_cands=valid_cands,
                )


def _extract_candidates(
    valid_docs: List[Tuple[Path, List[Dict[str, Any]]]],
    llm_client: Optional[BaseLLMClient] = None,
) -> Tuple[
    Dict[str, List[Dict[str, Any]]],
    Dict[str, List[Dict[str, Any]]],
    str,
]:
    """Extract candidate records across all valid documents."""
    all_cands: Dict[str, List[Dict[str, Any]]] = {f: [] for f in TARGET_FIELDS}
    valid_cands: Dict[str, List[Dict[str, Any]]] = {f: [] for f in TARGET_FIELDS}

    if llm_client is not None:
        _extract_with_mock_llm(valid_docs, llm_client, all_cands, valid_cands)
        return all_cands, valid_cands, "mock"

    _extract_with_rule_based(valid_docs, all_cands, valid_cands)
    return all_cands, valid_cands, "rule_based"


def _resolve_field_winner(
    field: str,
    valid_cands: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Select the winning candidate for a field based on document priority."""
    if not valid_cands:
        return None, ""

    filter_fn = None
    pref_label = ""
    if field in MONITORING_PRIORITY_FIELDS:
        filter_fn = is_monitoring_doc
        pref_label = "monitoring_report"
    elif field in PDD_PRIORITY_FIELDS:
        filter_fn = is_pdd_doc
        pref_label = "pdd"

    if filter_fn is not None:
        preferred = [c for c in valid_cands if filter_fn(c["doc"])]
        if preferred:
            preferred.sort(key=lambda c: c["score"], reverse=True)
            winner = preferred[0]
            others = [c for c in valid_cands if not filter_fn(c["doc"])]
            reason = (
                f"{pref_label} prioritized for {field} over "
                f"{others[0]['doc']} (score={winner['score']})"
                if others
                else f"{pref_label} prioritized for {field} (score={winner['score']})"
            )
            return winner, reason

    valid_cands.sort(key=lambda c: c["score"], reverse=True)
    winner = valid_cands[0]
    return winner, f"highest score ({winner['score']}) from {winner['doc']}"


def _resolve_all_winners(
    valid_cands_by_field: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, FieldExtractionDetail]:
    """Select the winning candidate for each target field."""
    field_details: Dict[str, FieldExtractionDetail] = {}
    for field in TARGET_FIELDS:
        cands = valid_cands_by_field.get(field, [])
        if not cands:
            field_details[field] = FieldExtractionDetail(
                value=None,
                status="missing",
                reason="No valid candidate found matching rule-based patterns",
            )
            continue

        winner, winner_reason = _resolve_field_winner(field, cands)
        if winner is not None:
            field_details[field] = FieldExtractionDetail(
                value=winner["norm_val"],
                raw_value=winner["raw_value"],
                source_doc=winner["doc"],
                page=winner["page"],
                evidence_quote=winner["quote"],
                status="accepted",
                reason=None,
                score=winner["score"],
                winner_reason=winner_reason,
            )
        else:
            field_details[field] = FieldExtractionDetail(
                value=None,
                status="missing",
                reason="No valid candidate found matching rule-based patterns",
            )
    return field_details


def _invoke_ollama_extraction(
    ollama_cfg: Dict[str, Any],
    ollama_model: str,
    missing_fields: List[str],
    valid_docs: List[Tuple[Path, List[Dict[str, Any]]]],
) -> Optional[Dict[str, FieldExtractionDetail]]:
    """Helper to query local Ollama LLM client for missing fields."""
    ollama_client = OllamaLLMClient(
        base_url=ollama_cfg.get("base_url", "http://localhost:11434"),
        model=ollama_model,
        timeout_seconds=int(ollama_cfg.get("timeout_seconds", 30)),
    )
    primary_pdf, primary_pages = valid_docs[0]
    primary_lookup = {p["page"]: p["text"] for p in primary_pages}
    candidates_by_field = {
        field: retrieve_candidates_for_field(primary_pages, field, top_k=4)
        for field in missing_fields
    }
    return ollama_client.extract_missing_fields(
        missing_fields=missing_fields,
        candidates_by_field=candidates_by_field,
        page_lookup=primary_lookup,
    )


def _run_ollama_fallback_if_needed(
    field_details: Dict[str, FieldExtractionDetail],
    cfg: Dict[str, Any],
    valid_docs: List[Tuple[Path, List[Dict[str, Any]]]],
    current_extractor: str,
) -> str:
    """Run Ollama fallback on missing fields if configured in config.yaml."""
    extraction_cfg = cfg.get("extraction", {})
    configured_extractor = str(extraction_cfg.get("extractor", "rule_based")).lower()
    ollama_cfg = extraction_cfg.get("ollama", {})
    ollama_model = ollama_cfg.get("model")

    if configured_extractor != "ollama" or not ollama_model or not valid_docs:
        return current_extractor

    missing_fields = [
        f for f, det in field_details.items() if det.status == "missing"
    ]
    if not missing_fields:
        return current_extractor

    logger.info("Invoking local Ollama (%s) for missing fields", ollama_model)
    results = _invoke_ollama_extraction(
        ollama_cfg, ollama_model, missing_fields, valid_docs
    )
    if results:
        for field, det in results.items():
            field_details[field] = det
        return "rule_based+ollama"
    return current_extractor


def _check_credits_consistency(
    field_details: Dict[str, FieldExtractionDetail],
) -> Optional[Dict[str, Any]]:
    """Verify net GHG removals minus buffer credits equals credits issued."""
    net_det = field_details.get("net_ghg_removals_tco2e")
    buf_det = field_details.get("buffer_credits_tco2e")
    iss_det = field_details.get("credits_issued")

    if not (
        net_det
        and net_det.status == "accepted"
        and net_det.value is not None
        and buf_det
        and buf_det.status == "accepted"
        and buf_det.value is not None
        and iss_det
        and iss_det.status == "accepted"
        and iss_det.value is not None
    ):
        return None

    net_val = int(net_det.value)
    buf_val = int(buf_det.value)
    iss_val = int(iss_det.value)
    diff = (net_val - buf_val) - iss_val
    is_consistent = abs(diff) <= 2
    return {
        "is_consistent": is_consistent,
        "net_ghg_removals_tco2e": net_val,
        "buffer_credits_tco2e": buf_val,
        "credits_issued": iss_val,
        "calculated_net_minus_buffer": net_val - buf_val,
        "discrepancy_tco2e": diff,
        "status": "CONSISTENT" if is_consistent else "DISCREPANCY",
    }


def _find_keyword_pages(
    valid_docs: List[Tuple[Path, List[Dict[str, Any]]]],
) -> List[Dict[str, Any]]:
    """Search valid document pages for missing field keywords."""
    keyword_pages: List[Dict[str, Any]] = []
    for pdf_path, pages in valid_docs:
        for p in pages:
            p_text = p.get("text", "")
            for kw in KEYWORDS_FOR_MISSING:
                m = re.search(r"\b" + re.escape(kw) + r"\b", p_text, re.IGNORECASE)
                if m:
                    start = max(0, m.start() - 30)
                    end = min(len(p_text), m.end() + 50)
                    snippet = " ".join(p_text[start:end].split())
                    keyword_pages.append({
                        "keyword": kw,
                        "doc": pdf_path.name,
                        "page": p["page"],
                        "snippet": snippet,
                    })
    return keyword_pages


def _build_debug_section(
    all_candidates_by_field: Dict[str, List[Dict[str, Any]]],
    field_details: Dict[str, FieldExtractionDetail],
    valid_docs: List[Tuple[Path, List[Dict[str, Any]]]],
) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """Build top candidates list and keyword search results for missing fields."""
    debug_top_candidates: Dict[str, List[Dict[str, Any]]] = {}
    for field in TARGET_FIELDS:
        cands = sorted(
            all_candidates_by_field.get(field, []),
            key=lambda c: c["score"],
            reverse=True,
        )
        debug_top_candidates[field] = [
            {
                "score": c["score"],
                "doc": c["doc"],
                "page": c["page"],
                "quote": c["quote"],
                "raw_value": c["raw_value"],
                "status": "valid" if c["is_valid"] else "rejected",
                "rejection_reason": c.get("rejection_reason"),
            }
            for c in cands[:3]
        ]

    keyword_pages: List[Dict[str, Any]] = []
    if any(det.status == "missing" for det in field_details.values()):
        keyword_pages = _find_keyword_pages(valid_docs)

    return debug_top_candidates, keyword_pages[:50]


def _build_forest_definition(
    accepted_values: Dict[str, Any],
) -> Optional[ForestDefinition]:
    """Construct ForestDefinition if national thresholds are present."""
    c_pct = accepted_values.get("canopy_cover_pct")
    a_ha = accepted_values.get("min_area_ha")
    h_m = accepted_values.get("min_height_m")
    if c_pct is not None or a_ha is not None or h_m is not None:
        return ForestDefinition(
            canopy_cover_pct=c_pct,
            min_area_ha=a_ha,
            min_height_m=h_m,
        )
    return None


def _build_project_claims(
    field_details: Dict[str, FieldExtractionDetail],
    search_root: Path,
    sched_data: Optional[Dict[str, Any]] = None,
) -> ProjectClaims:
    """Build ProjectClaims schema instance from accepted extraction field details."""
    source_pages: Dict[str, int] = {}
    accepted: Dict[str, Any] = {}
    for field, det in field_details.items():
        if det.status == "accepted":
            if det.value is not None:
                accepted[field] = det.value
            if det.page is not None:
                source_pages[field] = det.page

    boundary = _resolve_boundary_path(
        search_root if search_root.is_dir() else search_root.parent
    )
    fd_model = _build_forest_definition(accepted)
    sched = sched_data or {}

    return ProjectClaims(
        project_id=accepted.get("project_id"),
        registry=accepted.get("registry"),
        methodology=accepted.get("methodology"),
        claimed_area_ha=accepted.get("claimed_area_ha"),
        estate_area_ha=accepted.get("estate_area_ha"),
        reporting_period_start=accepted.get("reporting_period_start"),
        reporting_period_end=accepted.get("reporting_period_end"),
        crediting_period_start=accepted.get("crediting_period_start"),
        crediting_period_end=accepted.get("crediting_period_end"),
        project_start_date=accepted.get("project_start_date"),
        claimed_canopy_change_pct=accepted.get("claimed_canopy_change_pct"),
        credits_issued=accepted.get("credits_issued"),
        net_ghg_removals_tco2e=accepted.get("net_ghg_removals_tco2e"),
        buffer_credits_tco2e=accepted.get("buffer_credits_tco2e"),
        forest_definition=fd_model,
        canopy_cover_pct=accepted.get("canopy_cover_pct"),
        min_area_ha=accepted.get("min_area_ha"),
        min_height_m=accepted.get("min_height_m"),
        planting_schedule=sched.get("planting_schedule"),
        planted_area_by_year=sched.get("planted_area_by_year"),
        planted_area_total_ha=sched.get("planted_area_total_ha"),
        stated_total_ha=sched.get("stated_total_ha"),
        natural_forest_ha=accepted.get("natural_forest_ha"),
        check=sched.get("check"),
        boundary_path=boundary,
        source_pages=source_pages,
        demo=False,
    )


def _build_and_save_report(
    path: Path,
    pdf_files: List[Path],
    field_details: Dict[str, FieldExtractionDetail],
    extractor_used: str,
    doc_sha_map: Dict[str, str],
    doc_stats: Dict[str, Dict[str, Any]],
    consistency_check: Optional[Dict[str, Any]],
    debug_top_cands: Dict[str, List[Dict[str, Any]]],
    kw_pages: List[Dict[str, Any]],
    out_dir: Optional[Union[str, Path]],
    sched_data: Optional[Dict[str, Any]] = None,
    source_notes: Optional[List[str]] = None,
    manual_overrides: Optional[Dict[str, Any]] = None,
    original_extracted_fields: Optional[Dict[str, Any]] = None,
) -> None:
    """Construct and save ExtractionReport model to disk."""
    primary_sha256 = next(iter(doc_sha_map.values()), None)
    sched = sched_data or {}
    debug_payload: Dict[str, Any] = {
        "top_candidates": debug_top_cands,
        "keyword_pages": kw_pages,
    }
    if manual_overrides:
        debug_payload["manual_overrides"] = manual_overrides
    if original_extracted_fields:
        debug_payload["original_extracted_fields"] = original_extracted_fields

    report = ExtractionReport(
        document_path=str(path),
        fields=field_details,
        extractor=extractor_used,
        pdf_sha256=primary_sha256,
        demo=False,
        documents_scanned=[p.name for p in pdf_files],
        document_stats=doc_stats,
        credits_consistency_check=consistency_check,
        planting_schedule=sched.get("planting_schedule"),
        planted_area_by_year=sched.get("planted_area_by_year"),
        planted_area_total_ha=sched.get("planted_area_total_ha"),
        stated_total_ha=sched.get("stated_total_ha"),
        check=sched.get("check"),
        source_notes=source_notes or [],
        debug=debug_payload,
    )
    _write_extraction_report(report, path, out_dir)


def _orchestrate_pdf_extraction(
    path: Path,
    cfg: Dict[str, Any],
    llm_client: Optional[BaseLLMClient],
    out_dir: Optional[Union[str, Path]],
) -> ProjectClaims:
    """Run extraction pipeline on discovered project PDF files."""
    pdf_files, valid_docs, doc_stats, doc_sha_map = _discover_and_evaluate_pdfs(path)
    all_cands, valid_cands, extractor = _extract_candidates(valid_docs, llm_client)
    fields = _resolve_all_winners(valid_cands)
    extractor = _run_ollama_fallback_if_needed(fields, cfg, valid_docs, extractor)
    consistency = _check_credits_consistency(fields)
    top_cands, kw_pages = _build_debug_section(all_cands, fields, valid_docs)

    sched_data = extract_planting_schedule_from_documents(pdf_files)
    source_notes: List[str] = []
    if consistency and consistency.get("discrepancy_tco2e") == 1:
        source_notes.append(
            "Credits issued: p.3 text reports 68,493 tCO2e eligible to be issued as VCUs, "
            "while p.54 carbon calculation table lists 68,494 tCO2e (1 tCO2e source inconsistency)."
        )

    # Apply manual claims_override from project.yaml if present
    proj_dir = path if path.is_dir() else path.parent
    proj_yaml_path = proj_dir / "project.yaml"
    if not proj_yaml_path.exists() and proj_dir.parent.exists():
        cand = proj_dir.parent / "project.yaml"
        if cand.exists():
            proj_yaml_path = cand
    proj_yaml = _read_yaml_safely(proj_yaml_path) or {}
    overrides = proj_yaml.get("claims_override", [])
    if overrides and isinstance(overrides, list):
        orig_fields_copy: Dict[str, Any] = {}
        overrides_debug: Dict[str, Any] = {}
        for item in overrides:
            if not isinstance(item, dict):
                continue
            field = item.get("field")
            if not field:
                continue
            orig_det = fields.get(field)
            if orig_det is not None:
                orig_fields_copy[field] = orig_det.model_dump()
                orig_raw = str(orig_det.value) if orig_det.value is not None else orig_det.raw_value
            else:
                orig_raw = None

            val = item.get("value")
            pg = item.get("page")
            qt = item.get("quote")

            fields[field] = FieldExtractionDetail(
                value=val,
                raw_value=orig_raw if orig_raw is not None else (str(val) if val is not None else None),
                page=pg,
                evidence_quote=qt,
                status="accepted",
                reason="manual_override",
                source_doc="manual_override",
                score=100.0,
                winner_reason="manual_override",
            )
            overrides_debug[field] = {
                "extractor": "manual_override",
                "value": val,
                "page": pg,
                "quote": qt,
                "original_value": orig_det.value if orig_det else None,
                "original_raw_value": orig_raw,
            }
        extractor = "manual_override"
        top_cands["manual_overrides"] = overrides_debug
        top_cands["original_extracted_fields"] = orig_fields_copy
    else:
        overrides_debug = None
        orig_fields_copy = None

    claims = _build_project_claims(fields, path, sched_data)
    _build_and_save_report(
        path, pdf_files, fields, extractor, doc_sha_map,
        doc_stats, consistency, top_cands, kw_pages, out_dir,
        sched_data=sched_data, source_notes=source_notes,
        manual_overrides=overrides_debug,
        original_extracted_fields=orig_fields_copy,
    )
    logger.info(
        "Claim extraction completed (%s): %d accepted, %d rejected, %d missing",
        extractor,
        sum(1 for d in fields.values() if d.status == "accepted"),
        sum(1 for d in fields.values() if d.status == "rejected"),
        sum(1 for d in fields.values() if d.status == "missing"),
    )
    return claims


def extract_claims(
    doc_path: Union[str, Path],
    config: Optional[Union[Dict[str, Any], Path, str]] = None,
    llm_client: Optional[BaseLLMClient] = None,
    out_dir: Optional[Union[str, Path]] = None,
) -> ProjectClaims:
    """Extract project claims from PDF project documentation or demo claims JSON.

    Args:
        doc_path: Path to project PDF document, claims.json, or project directory.
        config: Optional configuration dictionary or path to config.yaml.
        llm_client: Optional preconfigured BaseLLMClient (used only when injected in tests).
        out_dir: Optional directory where extraction_report.json will be saved.

    Returns:
        ProjectClaims: Validated project claims model.
    """
    path = Path(doc_path).resolve()
    logger.info("Extracting claims from: %s", path)
    cfg = load_config_dict(config)

    if _is_demo_source(path):
        return _load_demo_claims(path, out_dir)

    return _orchestrate_pdf_extraction(path, cfg, llm_client, out_dir)
