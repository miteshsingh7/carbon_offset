"""Candidate snippet retrieval for target claim fields using keywords and regex."""

from dataclasses import dataclass
import logging
import re
from typing import Any, Dict, List, Pattern

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CandidateSnippet:
    """A retrieved text snippet candidate with its source page and retrieval score."""
    page: int
    text: str
    score: float


# Field definition rules with keywords and regexes
FIELD_RULES: Dict[str, Dict[str, Any]] = {
    "project_id": {
        "keywords": ["project id", "project identifier", "project number", "vcs", "gold standard"],
        "regexes": [
            re.compile(r"project\s*(?:id|identifier|number|code)[\s:]*([A-Za-z0-9_\-]+)", re.IGNORECASE),
            re.compile(r"\b(?:VCS|GS)[\s\-_]?[0-9]+\b", re.IGNORECASE),
        ],
    },
    "registry": {
        "keywords": ["registry", "standard", "verified carbon standard", "verra", "gold standard"],
        "regexes": [
            re.compile(r"\b(?:verified\s*carbon\s*standard|verra|gold\s*standard)\b", re.IGNORECASE),
        ],
    },
    "methodology": {
        "keywords": ["methodology", "baseline and monitoring methodology", "vcs methodology"],
        "regexes": [
            re.compile(r"\b(?:VM\d{4}|AR-ACM\d{4}|ACM\d{4}|AMS-[A-Z]+-[A-Z\d]+)\b", re.IGNORECASE),
            re.compile(r"methodology\s*[:\-]?\s*([A-Za-z0-9\-_]+)", re.IGNORECASE),
        ],
    },
    "claimed_area_ha": {
        "keywords": [
            "project area", "total area", "accounting area", "hectares", "ha",
            "boundary area", "surface area", "km2", "acres", "size of the project"
        ],
        "regexes": [
            re.compile(r"[\d,\.]+\s*(?:ha|hectares?|km2|km²|acres?)\b", re.IGNORECASE),
            re.compile(r"(?:project|total|accounting)\s*area[\s:]*[\d,\.]+", re.IGNORECASE),
        ],
    },
    "reporting_period_start": {
        "keywords": [
            "monitoring period", "reporting period", "crediting period",
            "verification period", "start date", "start of period", "period start", "from"
        ],
        "regexes": [
            re.compile(r"(?:monitoring|reporting|crediting)\s*period[\s:]*.*?from\s*([0-9A-Za-z\s,\-]+)", re.IGNORECASE),
            re.compile(r"\b(?:20\d{2}[-/]\d{2}[-/]\d{2}|\d{1,2}\s+[A-Za-z]+\s+20\d{2})\b"),
        ],
    },
    "reporting_period_end": {
        "keywords": [
            "monitoring period", "reporting period", "crediting period",
            "verification period", "end date", "end of period", "period end", "to", "until"
        ],
        "regexes": [
            re.compile(r"(?:to|until|ending|end\s*date)[\s:]*([0-9A-Za-z\s,\-]+)", re.IGNORECASE),
            re.compile(r"\b(?:20\d{2}[-/]\d{2}[-/]\d{2}|\d{1,2}\s+[A-Za-z]+\s+20\d{2})\b"),
        ],
    },
    "credits_issued": {
        "keywords": [
            "credits issued", "vcus", "emission reductions", "total credits",
            "credits", "annual credits", "issuance", "verified carbon units"
        ],
        "regexes": [
            re.compile(r"[\d,\.]+\s*(?:vcus?|credits?|tco2e)\b", re.IGNORECASE),
            re.compile(r"(?:credits?\s*issued|emission\s*reductions?)[\s:]*[\d,\.]+", re.IGNORECASE),
        ],
    },
    "claimed_canopy_change_pct": {
        "keywords": [
            "canopy change", "canopy cover", "tree cover", "forest cover change",
            "deforestation rate", "afforestation", "canopy"
        ],
        "regexes": [
            re.compile(r"canopy\s*(?:cover)?\s*(?:change)?[\s:]*[\+\-]?\d+(?:\.\d+)?\s*%", re.IGNORECASE),
            re.compile(r"[\+\-]?\d+(?:\.\d+)?\s*%\s*(?:canopy|tree|forest)", re.IGNORECASE),
        ],
    },
}


def _split_into_blocks(text: str) -> List[str]:
    """Split page text into distinct semantic paragraphs or blocks."""
    # First attempt: split by double newline
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) >= 2:
        return paragraphs

    # Fallback: sliding window of lines
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return []
    blocks: List[str] = []
    window_size = 4
    for i in range(0, len(lines), 2):
        chunk = " ".join(lines[i : i + window_size])
        blocks.append(chunk)
    return blocks


def retrieve_candidates_for_field(
    pages: List[Dict[str, Any]],
    field_name: str,
    top_k: int = 4,
) -> List[CandidateSnippet]:
    """Retrieve top candidate snippets for a specific field across all pages.

    Args:
        pages: List of page dicts {"page": int, "text": str}.
        field_name: Target claim field name (e.g. 'claimed_area_ha').
        top_k: Number of highest-scoring snippets to return.

    Returns:
        List[CandidateSnippet]: Top ranked candidate snippets with page references.
    """
    rule = FIELD_RULES.get(field_name)
    if not rule:
        logger.warning("No retrieval rule defined for field '%s'", field_name)
        return []

    keywords = rule["keywords"]
    regexes: List[Pattern[str]] = rule["regexes"]

    scored_candidates: List[CandidateSnippet] = []

    for page_dict in pages:
        page_num = page_dict.get("page", 1)
        raw_text = page_dict.get("text", "")
        if not raw_text.strip():
            continue

        blocks = _split_into_blocks(raw_text)
        for block in blocks:
            block_lower = block.lower()
            score = 0.0

            # Score regex hits
            for r in regexes:
                matches = r.findall(block)
                if matches:
                    score += 5.0 * len(matches)

            # Score keyword hits
            for kw in keywords:
                if kw in block_lower:
                    score += 2.0

            if score > 0.0:
                scored_candidates.append(
                    CandidateSnippet(page=page_num, text=block, score=score)
                )

    # Sort descending by score
    scored_candidates.sort(key=lambda c: c.score, reverse=True)

    # Deduplicate similar texts on the same page
    unique_candidates: List[CandidateSnippet] = []
    seen_texts = set()
    for cand in scored_candidates:
        clean = " ".join(cand.text.split()[:20]).lower()
        key = (cand.page, clean)
        if key not in seen_texts:
            seen_texts.add(key)
            unique_candidates.append(cand)
            if len(unique_candidates) >= top_k:
                break

    logger.debug(
        "Retrieved %d candidates for field '%s' (top score: %.1f)",
        len(unique_candidates),
        field_name,
        unique_candidates[0].score if unique_candidates else 0.0,
    )
    return unique_candidates
