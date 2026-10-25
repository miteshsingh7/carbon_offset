"""Rule-based claims extractor tailored for VCS and Gold Standard PDD documents."""

from dataclasses import dataclass
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from carbonverify.claims.normalizer import (
    normalize_date,
    normalize_field,
    validate_evidence_quote,
)
from carbonverify.schemas import FieldExtractionDetail

logger = logging.getLogger(__name__)

DATE_REGEX = r"(?:\d{1,2}[-/\.]\d{1,2}[-/\.]\d{4}|\d{1,2}[-/\.\s]+[A-Za-z]+[-/\.\s]+\d{4}|\d{4}[-/]\d{2}[-/]\d{2})"


@dataclass(frozen=True)
class ScoredCandidate:
    """A field extraction candidate extracted via regex/keyword rules."""
    field_name: str
    raw_value: str
    page: int
    evidence_quote: str
    score: float


def is_toc_quote(quote: str) -> bool:
    """Check if quote comes from a table-of-contents with dotted leader lines."""
    return ".." in quote or bool(re.search(r"\.{2,}", quote))


def is_url_quote(quote: str) -> bool:
    """Check if quote is a bare URL line or reference without descriptive standard name."""
    clean = quote.strip()
    return bool(
        re.search(r"^\d*\s*https?://", clean)
        or (
            re.search(r"https?://", clean)
            and not any(k in clean.lower() for k in ["verified carbon standard", "vcs (afolu)", "vcs version"])
        )
    )


# General VCS / Gold Standard extraction patterns
EXTRACTION_PATTERNS: Dict[str, List[Tuple[re.Pattern, float]]] = {
    "project_id": [
        (re.compile(r"project\s*(?:id|identifier|number|code)[\s:]*([A-Za-z0-9_\-]+)", re.IGNORECASE), 25.0),
        (re.compile(r"\b(VCS[\s\-_]?[0-9]+)\b", re.IGNORECASE), 20.0),
        (re.compile(r"\b(GS[\s\-_]?[0-9]+)\b", re.IGNORECASE), 20.0),
        (re.compile(r"\b(VCS\s*Project\s*[0-9]+)\b", re.IGNORECASE), 15.0),
    ],
    "registry": [
        (re.compile(r"(Monitoring\s*Report:\s*VCS\s*Version[^\n]*)", re.IGNORECASE), 35.0),
        (re.compile(r"(VCS\s*\(AFOLU\))", re.IGNORECASE), 32.0),
        (re.compile(r"(Verified\s*Carbon\s*Standard(?:\s*\(Verra\))?)", re.IGNORECASE), 30.0),
        (re.compile(r"(Gold\s*Standard(?:\s*Foundation)?)", re.IGNORECASE), 30.0),
        (re.compile(r"\b(Verra)\b", re.IGNORECASE), 15.0),
    ],
    "methodology": [
        (re.compile(r"\b(VM\d{4}|AR-ACM\d{4}|ACM\d{4}|AMS-[A-Z]+-[A-Z\d]+)\b", re.IGNORECASE), 26.0),
        (re.compile(r"(?:applied\s*)?methodology[\s:]*([A-Za-z0-9\-_]+)", re.IGNORECASE), 15.0),
    ],
    "claimed_area_ha": [
        (
            re.compile(
                r"(?:current\s*project\s*area|management\s*of|project\s*accounting\s*area|total\s*(?:project\s*)?area|project\s*boundary\s*area)[\s:]*(?:is|encompasses|comprises|of)?\s*(?:a\s*(?:verified\s*)?total\s*area\s*of\s*)?(\d+(?:,\d+)*(?:\.\d+)?)\s*(ha|hectares?|km2|km²|sq\s*km|square\s*kilometers?|acres?)\b",
                re.IGNORECASE,
            ),
            30.0,
        ),
        (
            re.compile(
                r"(?:project\s*area|total\s*area)[\s:]*.*?(\d+(?:,\d+)*(?:\.\d+)?)\s*(ha|hectares?|km2|km²|acres?)\b",
                re.IGNORECASE,
            ),
            20.0,
        ),
    ],
    "estate_area_ha": [
        (
            re.compile(
                r"(?:with\s*an\s*area\s*of|total\s*(?:estate|property|landholding)\s*area[\s:]*)\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(ha|hectares?|km2|km²|acres?)\b",
                re.IGNORECASE,
            ),
            30.0,
        ),
        (
            re.compile(
                r"(?:estancia|finca|property|estate|concession|landholding)\s*.*?with\s*(?:an\s*)?area\s*of\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(ha|hectares?)\b",
                re.IGNORECASE,
            ),
            28.0,
        ),
    ],
    "natural_forest_ha": [
        (
            re.compile(
                r"(?:remaining\s+natural\s+forests?\s+with\s+a\s+total\s+area\s+of|total\s+area\s+of\s+natural\s+forests?[\s:]*)\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(ha|hectares?)\b",
                re.IGNORECASE,
            ),
            30.0,
        ),
        (
            re.compile(
                r"(?:natural\s+forests?)\s*.*?with\s*(?:a\s*)?total\s*area\s*of\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(ha|hectares?)\b",
                re.IGNORECASE,
            ),
            25.0,
        ),
    ],
    "project_start_date": [
        (
            re.compile(
                rf"(?:starting\s*date\s*of\s*(?:the\s*)?(?:proposed\s*)?(?:[A-Z/]+\s*)?project\s*activity|project\s*start\s*date)[\s:]*({DATE_REGEX})",
                re.IGNORECASE,
            ),
            30.0,
        ),
    ],
    "credits_issued": [
        (
            re.compile(
                r"eligible\s*to\s*be\s*issued\s*as\s*vcus\b[\s\S]{0,150}?(?:is|are)\s*([0-9,]+)\s*(?:tco2e|vcus?|credits?)",
                re.IGNORECASE,
            ),
            35.0,
        ),
        (
            re.compile(
                r"(?:total\s*)?credits?\s*issued[\s:]*.*?([0-9,]+)\s*(?:vcus?|credits?|tco2e)?",
                re.IGNORECASE,
            ),
            25.0,
        ),
        (re.compile(r"([0-9,]+)\s*(?:vcus?|verified\s*carbon\s*units)\b", re.IGNORECASE), 20.0),
    ],
    "net_ghg_removals_tco2e": [
        (
            re.compile(
                r"(?:ghg\s*emission\s*reductions?\s*(?:generated|and\s*removals?)?|net\s*ghg\s*emission\s*reductions?|estimated\s*net\s*ghg\s*emission\s*reductions?|net\s*emission\s*reductions?)[\s\S]{0,150}?(?:are|is)\s*([0-9,]+)\s*tco2e",
                re.IGNORECASE,
            ),
            30.0,
        ),
    ],
    "buffer_credits_tco2e": [
        (
            re.compile(
                r"buffer\s*credits\s*(?:that\s*need\s*to\s*be\s*deposited)[\s\S]{0,150}?(?:is|are)\s*([0-9,]+)\s*tco2e",
                re.IGNORECASE,
            ),
            30.0,
        ),
    ],
    "claimed_canopy_change_pct": [
        (
            re.compile(
                r"(?:(?:canopy|tree|forest)\s*(?:cover(?:age)?\s*)?change|(?:increase|growth|gain|reduction|decrease)\s*(?:in\s*)?(?:canopy|tree|forest)\s*(?:cover(?:age)?|density)?)[\s\S]{0,80}?([+\-]?\d+(?:\.\d+)?\s*%)",
                re.IGNORECASE,
            ),
            25.0,
        ),
        (
            re.compile(
                r"([+\-]?\d+(?:\.\d+)?\s*%)\s*(?:canopy|tree|forest\s*cover)\s*(?:increase|growth|gain|reduction|change)\b",
                re.IGNORECASE,
            ),
            22.0,
        ),
    ],
}


def _find_exact_line_quote(page_text: str, match_text: str) -> str:
    """Extract the exact single line or clean snippet containing the matched text."""
    for line in page_text.splitlines():
        if match_text in line:
            return line.strip()

    idx = page_text.find(match_text)
    if idx != -1:
        start = max(0, idx - 40)
        end = min(len(page_text), idx + len(match_text) + 40)
        return " ".join(page_text[start:end].split())

    return " ".join(match_text.split())


class RuleBasedExtractor:
    """100% free rule-based claim extractor using regex and keyword pattern ranking."""

    def _extract_period_candidates(
        self,
        pages: List[Dict[str, Any]],
        anchor_pattern: str,
        start_field: str,
        end_field: str,
    ) -> Dict[str, List[ScoredCandidate]]:
        """Extract paired start/end period dates anchored to specific section labels."""
        results: Dict[str, List[ScoredCandidate]] = {start_field: [], end_field: []}

        for page_dict in pages:
            page_num = page_dict.get("page", 1)
            text = page_dict.get("text", "")
            if not text.strip():
                continue

            for m in re.finditer(anchor_pattern, text, re.IGNORECASE):
                idx = m.start()
                window = text[idx : min(len(text), idx + 400)]

                # Check 1: Inline range using -, –, or "to"
                range_match = re.search(
                    rf"({DATE_REGEX})\s*(?:–|-|to)\s*({DATE_REGEX})",
                    window,
                    re.IGNORECASE,
                )
                if range_match:
                    s_raw, e_raw = range_match.groups()
                    s_norm = normalize_date(s_raw)
                    e_norm = normalize_date(e_raw)
                    if s_norm and e_norm and s_norm < e_norm:
                        quote = " ".join(window[: range_match.end()].split())
                        if not is_toc_quote(quote):
                            results[start_field].append(
                                ScoredCandidate(start_field, s_raw, page_num, quote, 35.0)
                            )
                            results[end_field].append(
                                ScoredCandidate(end_field, e_raw, page_num, quote, 35.0)
                            )
                            continue

                # Check 2: Tabular / multiple dates following anchor header
                all_dates = list(re.finditer(DATE_REGEX, window))
                if len(all_dates) >= 2:
                    s_raw = all_dates[0].group(0)
                    e_raw = all_dates[1].group(0)
                    s_norm = normalize_date(s_raw)
                    e_norm = normalize_date(e_raw)
                    if s_norm and e_norm and s_norm < e_norm:
                        end_pos = all_dates[1].end()
                        quote = " ".join(window[:end_pos].split())
                        if not is_toc_quote(quote):
                            results[start_field].append(
                                ScoredCandidate(start_field, s_raw, page_num, quote, 30.0)
                            )
                            results[end_field].append(
                                ScoredCandidate(end_field, e_raw, page_num, quote, 30.0)
                            )

        return results

    def _extract_forest_def_candidates(
        self,
        pages: List[Dict[str, Any]],
    ) -> Dict[str, List[ScoredCandidate]]:
        """Extract forest definition thresholds: canopy cover %, min area (ha), min height (m)."""
        results: Dict[str, List[ScoredCandidate]] = {
            "canopy_cover_pct": [],
            "min_area_ha": [],
            "min_height_m": [],
        }

        pattern = re.compile(
            r"forest\s*definition[^\n]*?defined\s*as\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*(?:tree|canopy)\s*cover(?:age)?[\s,]+([0-9]+(?:\.[0-9]+)?)\s*ha[\s,]+(?:and\s*)?([0-9]+(?:\.[0-9]+)?)\s*m\s*(?:of\s*)?(?:minimum\s*)?tree\s*height",
            re.IGNORECASE,
        )

        for page_dict in pages:
            page_num = page_dict.get("page", 1)
            text = page_dict.get("text", "")
            if not text.strip():
                continue

            for m in pattern.finditer(text):
                c_val = m.group(1)
                a_val = m.group(2)
                h_val = m.group(3)
                quote = " ".join(m.group(0).split())
                if not is_toc_quote(quote):
                    results["canopy_cover_pct"].append(
                        ScoredCandidate("canopy_cover_pct", f"{c_val}%", page_num, quote, 30.0)
                    )
                    results["min_area_ha"].append(
                        ScoredCandidate("min_area_ha", f"{a_val} ha", page_num, quote, 30.0)
                    )
                    results["min_height_m"].append(
                        ScoredCandidate("min_height_m", f"{h_val} m", page_num, quote, 30.0)
                    )

        return results

    def find_candidates(
        self,
        pages: List[Dict[str, Any]],
        target_fields: Optional[List[str]] = None,
    ) -> Dict[str, List[ScoredCandidate]]:
        """Find and score all candidate matches across all document pages."""
        all_possible_fields = list(EXTRACTION_PATTERNS.keys()) + [
            "reporting_period_start",
            "reporting_period_end",
            "crediting_period_start",
            "crediting_period_end",
            "canopy_cover_pct",
            "min_area_ha",
            "min_height_m",
        ]
        fields_to_extract = target_fields or all_possible_fields
        candidates_by_field: Dict[str, List[ScoredCandidate]] = {f: [] for f in fields_to_extract}

        # 1. Regex pattern matching
        for field_name in fields_to_extract:
            patterns = EXTRACTION_PATTERNS.get(field_name, [])
            for page_dict in pages:
                page_num = page_dict.get("page", 1)
                text = page_dict.get("text", "")
                if not text.strip():
                    continue

                for pattern, base_score in patterns:
                    for match in pattern.finditer(text):
                        raw_val = match.group(1) if match.groups() else match.group(0)
                        if field_name in ("claimed_area_ha", "estate_area_ha", "natural_forest_ha") and len(match.groups()) >= 2 and match.group(2):
                            full_raw = f"{raw_val} {match.group(2)}"
                        else:
                            full_raw = raw_val

                        quote = _find_exact_line_quote(text, match.group(0))

                        # Filter out table of contents dotted leader lines
                        if is_toc_quote(quote):
                            continue

                        # Filter out URL quotes for registry
                        if field_name == "registry" and is_url_quote(quote):
                            continue

                        # Canopy change percentage must strictly come from change statements
                        if field_name == "claimed_canopy_change_pct":
                            q_lower = quote.lower()
                            if "forest definition" in q_lower or not any(
                                w in q_lower for w in ["increase", "growth", "gain", "reduction", "decrease", "change"]
                            ):
                                continue

                        score = base_score
                        text_lower = text.lower()
                        if "pdd" in text_lower or "project description" in text_lower:
                            score += 1.0

                        candidates_by_field[field_name].append(
                            ScoredCandidate(
                                field_name=field_name,
                                raw_value=full_raw.strip(),
                                page=page_num,
                                evidence_quote=quote,
                                score=score,
                            )
                        )

        # 2. Monitoring Period anchor extraction
        if "reporting_period_start" in fields_to_extract or "reporting_period_end" in fields_to_extract:
            period_matches = self._extract_period_candidates(
                pages,
                anchor_pattern=r"(?:monitoring|reporting|verification)\s*period",
                start_field="reporting_period_start",
                end_field="reporting_period_end",
            )
            for f in ("reporting_period_start", "reporting_period_end"):
                if f in fields_to_extract:
                    candidates_by_field[f].extend(period_matches.get(f, []))

        # 3. Crediting Period anchor extraction
        if "crediting_period_start" in fields_to_extract or "crediting_period_end" in fields_to_extract:
            cred_matches = self._extract_period_candidates(
                pages,
                anchor_pattern=r"(?:project\s*)?crediting\s*period",
                start_field="crediting_period_start",
                end_field="crediting_period_end",
            )
            for f in ("crediting_period_start", "crediting_period_end"):
                if f in fields_to_extract:
                    candidates_by_field[f].extend(cred_matches.get(f, []))

        # 4. Forest Definition thresholds
        forest_fields = [f for f in ("canopy_cover_pct", "min_area_ha", "min_height_m") if f in fields_to_extract]
        if forest_fields:
            forest_matches = self._extract_forest_def_candidates(pages)
            for f in forest_fields:
                candidates_by_field[f].extend(forest_matches.get(f, []))

        # Sort candidate matches by score descending
        for field_name in candidates_by_field:
            candidates_by_field[field_name].sort(key=lambda c: c.score, reverse=True)

        return candidates_by_field

    def extract(
        self,
        pages: List[Dict[str, Any]],
        target_fields: Optional[List[str]] = None,
    ) -> Dict[str, FieldExtractionDetail]:
        """Extract target claims across all document pages using pattern scoring.

        Args:
            pages: List of page dicts {"page": int, "text": str}.
            target_fields: List of fields to extract (defaults to all supported fields).

        Returns:
            Dict mapping field name to FieldExtractionDetail.
        """
        candidates_by_field = self.find_candidates(pages, target_fields)
        results: Dict[str, FieldExtractionDetail] = {}

        for field_name, candidates in candidates_by_field.items():
            accepted_detail: Optional[FieldExtractionDetail] = None

            for cand in candidates:
                page_text = next((p["text"] for p in pages if p["page"] == cand.page), "")

                # 1. Anti-hallucination check
                if not validate_evidence_quote(cand.evidence_quote, page_text):
                    continue

                # 2. Normalization check
                norm_val, norm_err = normalize_field(field_name, cand.raw_value)
                if norm_err is not None or norm_val is None:
                    continue

                accepted_detail = FieldExtractionDetail(
                    value=norm_val,
                    raw_value=cand.raw_value,
                    page=cand.page,
                    evidence_quote=cand.evidence_quote,
                    status="accepted",
                    reason=None,
                    score=cand.score,
                )
                break

            if accepted_detail is not None:
                results[field_name] = accepted_detail
            else:
                results[field_name] = FieldExtractionDetail(
                    value=None,
                    status="missing",
                    reason="No valid candidate found matching rule-based patterns",
                    score=None,
                )

        return results
