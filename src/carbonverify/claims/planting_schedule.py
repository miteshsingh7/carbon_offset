import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Literal, Optional, Tuple

import fitz

from carbonverify.schemas import PlantingScheduleCheck, PlantingStratumClaim

logger = logging.getLogger(__name__)

STRATUM_REGEX = re.compile(r"^(\d{4})_(\d+)$")

WordTuple = Tuple[float, float, float, float, str, int, int, int]


def parse_numeric(val: str) -> Optional[float]:
    """Parse numeric string removing commas, returning None if invalid."""
    cleaned = val.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_strata_rows(
    lines: List[str],
    source_doc: str,
    page: int,
) -> Tuple[List[PlantingStratumClaim], Optional[float]]:
    """Parse stratum rows and total line from text lines."""
    strata_rows: List[PlantingStratumClaim] = []
    stated_total: Optional[float] = None

    for line in lines:
        tokens = line.strip().split()
        if not tokens:
            continue
        first_tok = tokens[0]
        m = STRATUM_REGEX.match(first_tok)
        if m:
            area_val = next(
                (parse_numeric(tok) for tok in tokens[1:] if parse_numeric(tok) is not None),
                None,
            )
            if area_val is None:
                continue

            strata_rows.append(
                PlantingStratumClaim(
                    stratum=first_tok,
                    planting_year=int(m.group(1)),
                    density=int(m.group(2)),
                    area_ha=area_val,
                    source_doc=source_doc,
                    page=page,
                    evidence_quote=line.strip(),
                )
            )
        elif first_tok.lower() == "total":
            stated_total = next(
                (parse_numeric(tok) for tok in tokens[1:] if parse_numeric(tok) is not None),
                None,
            )

    return strata_rows, stated_total


def _aggregate_schedule(
    strata_rows: List[PlantingStratumClaim],
    stated_total: Optional[float],
) -> Dict[str, Any]:
    """Aggregate stratum areas by year and compute consistency check."""
    yearly: Dict[str, float] = {}
    for r in strata_rows:
        y_str = str(r.planting_year)
        yearly[y_str] = round(yearly.get(y_str, 0.0) + r.area_ha, 2)

    total_sum = round(sum(r.area_ha for r in strata_rows), 2)
    stated = stated_total if stated_total is not None else total_sum
    discrepancy = round(abs(total_sum - stated), 2)
    is_consistent = discrepancy <= 2.0
    status: Literal["CONSISTENT", "MISMATCH"] = "CONSISTENT" if is_consistent else "MISMATCH"

    check = PlantingScheduleCheck(
        is_consistent=is_consistent,
        sum_area_ha=total_sum,
        stated_total_ha=stated,
        discrepancy_ha=discrepancy,
        status=status,
    )
    return {
        "planting_schedule": strata_rows,
        "planted_area_by_year": yearly,
        "planted_area_total_ha": total_sum,
        "stated_total_ha": stated,
        "check": check,
    }


def parse_planting_schedule_from_lines(
    lines: List[str],
    header: str = "",
    source_doc: str = "monitoring_report.pdf",
    page: int = 1,
) -> Optional[Dict[str, Any]]:
    """Parse planting schedule from table lines and header string."""
    has_dist = bool(re.search(r"Distribution\s+of\s+areas", header, re.IGNORECASE))
    has_stratum = bool(re.search(r"Stratum", header, re.IGNORECASE))
    if not (has_dist or has_stratum):
        return None

    strata_rows, stated_total = _parse_strata_rows(lines, source_doc, page)
    if not strata_rows:
        return None

    return _aggregate_schedule(strata_rows, stated_total)


def _reconstruct_page_lines(words: List[WordTuple]) -> List[List[WordTuple]]:
    """Cluster page words into visual horizontal lines sorted left-to-right."""
    words_sorted = sorted(words, key=lambda w: (w[1], w[0]))
    lines: List[List[WordTuple]] = []
    curr_line: List[WordTuple] = []
    curr_y: Optional[float] = None

    for w in words_sorted:
        y = w[1]
        if curr_y is None or abs(y - curr_y) > 3.0:
            if curr_line:
                curr_line.sort(key=lambda x: x[0])
                lines.append(curr_line)
            curr_line = [w]
            curr_y = y
        else:
            curr_line.append(w)

    if curr_line:
        curr_line.sort(key=lambda x: x[0])
        lines.append(curr_line)

    return lines


def _extract_table_blocks_from_page(
    page: fitz.Page, page_num: int
) -> List[Dict[str, Any]]:
    """Locate contiguous stratum row blocks and preceding headers on a page."""
    words: List[WordTuple] = page.get_text("words")
    if not words:
        return []

    lines = _reconstruct_page_lines(words)
    candidate_tables: List[Dict[str, Any]] = []

    i = 0
    while i < len(lines):
        first_tok = lines[i][0][4]
        if STRATUM_REGEX.match(first_tok):
            table_lines = [lines[i]]
            start_y = lines[i][0][1]
            j = i + 1
            while j < len(lines):
                next_tok = lines[j][0][4]
                if STRATUM_REGEX.match(next_tok):
                    table_lines.append(lines[j])
                    j += 1
                elif next_tok.lower() == "total":
                    table_lines.append(lines[j])
                    j += 1
                    break
                else:
                    break

            header_words = [
                w for w in words if start_y - 120 <= w[1] < start_y
            ]
            header_words.sort(key=lambda w: (w[1], w[0]))
            header_text = " ".join(w[4] for w in header_words)

            candidate_tables.append({
                "page": page_num,
                "header": header_text,
                "lines": [" ".join(w[4] for w in line) for line in table_lines],
            })
            i = j
        else:
            i += 1

    return candidate_tables


def extract_planting_schedule_from_pdf(
    pdf_path: Path,
) -> Optional[Dict[str, Any]]:
    """Extract and prioritize planting schedule tables from a single PDF.

    Prioritizes tables whose headers mention 'total project area' over tables
    that repeat strata for other metrics (e.g. Table 6 baseline emissions).
    """
    try:
        doc = fitz.open(pdf_path)
    except (OSError, fitz.FileDataError) as exc:
        logger.warning("Could not open %s for planting schedule: %s", pdf_path, exc)
        return None

    scored_candidates: List[Tuple[float, Dict[str, Any]]] = []

    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1
        blocks = _extract_table_blocks_from_page(page, page_num)
        for block in blocks:
            parsed = parse_planting_schedule_from_lines(
                lines=block["lines"],
                header=block["header"],
                source_doc=pdf_path.name,
                page=page_num,
            )
            if not parsed:
                continue

            header_lower = block["header"].lower()
            score = 10.0
            if all(k in header_lower for k in ["total", "project", "area"]):
                score += 100.0
            if "distribution of areas" in header_lower:
                score += 20.0

            scored_candidates.append((score, parsed))

    if not scored_candidates:
        return None

    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    return scored_candidates[0][1]


def extract_planting_schedule_from_documents(
    pdf_files: List[Path],
) -> Optional[Dict[str, Any]]:
    """Extract planting schedule across documents, prioritizing monitoring reports."""
    sorted_pdfs = sorted(
        pdf_files,
        key=lambda p: 0 if "monitoring" in p.name.lower() else 1,
    )
    for pdf_path in sorted_pdfs:
        result = extract_planting_schedule_from_pdf(pdf_path)
        if result is not None:
            return result
    return None
