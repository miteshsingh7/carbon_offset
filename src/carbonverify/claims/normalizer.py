"""Validation and unit normalization for extracted project claims."""

from datetime import datetime
import logging
import re
from typing import Any, Optional, Tuple

from dateutil import parser as date_parser

from carbonverify.schemas import Registry

logger = logging.getLogger(__name__)

# Conversion factors to hectares
KM2_TO_HA = 100.0
ACRES_TO_HA = 0.40468564224


def normalize_whitespace(text: str) -> str:
    """Normalize consecutive whitespace and newlines into a single space."""
    return " ".join(text.split()).strip()


def validate_evidence_quote(
    evidence_quote: Optional[str],
    page_text: Optional[str],
) -> bool:
    """Anti-hallucination validation: verify evidence quote verbatim in cited page text.

    Args:
        evidence_quote: The quote returned by the extractor as grounding evidence.
        page_text: The full text of the page where the quote was cited.

    Returns:
        bool: True if normalized quote is a substring of the normalized page text,
              not a URL line, and not a dotted-leader table of contents line.
    """
    if not evidence_quote or not page_text:
        return False

    norm_quote = normalize_whitespace(evidence_quote).lower()
    norm_page = normalize_whitespace(page_text).lower()

    if not norm_quote:
        return False

    # Never accept dotted-leader table-of-contents lines as evidence
    if ".." in norm_quote or re.search(r"\.{2,}", norm_quote):
        return False

    # Never accept a bare URL line as evidence
    if re.search(r"^\d*\s*https?://", norm_quote) or (
        norm_quote.startswith("http://") or norm_quote.startswith("https://")
    ):
        return False

    return norm_quote in norm_page


def normalize_area(raw_value: Any) -> Optional[float]:
    """Normalize area string or number to float hectares.

    Supports hectares (ha), square kilometers (km2), and acres.

    Examples:
        - "14,500 ha" -> 14500.0
        - "120 km2"   -> 12000.0
        - "24710.5 acres" -> 10000.0
    """
    if raw_value is None:
        return None

    if isinstance(raw_value, (int, float)):
        return round(float(raw_value), 2) if raw_value > 0 else None

    text = str(raw_value).strip().lower()

    # Match numeric portion and optional unit
    match = re.search(r"(\d+(?:,\d+)*(?:\.\d+)?)\s*(ha|hectares?|km2|km²|sq\s*km|square\s*kilometers?|acres?)?", text)
    if not match:
        return None

    num_str = match.group(1).replace(",", "")
    unit_str = match.group(2) or "ha"

    try:
        val = float(num_str)
    except ValueError:
        return None

    if unit_str in ("km2", "km²", "sq km", "square kilometer", "square kilometers"):
        ha_val = val * KM2_TO_HA
    elif unit_str in ("acre", "acres"):
        ha_val = val * ACRES_TO_HA
    else:
        ha_val = val

    return round(ha_val, 2)


def normalize_date(raw_value: Any) -> Optional[str]:
    """Normalize date representation to ISO format YYYY-MM-DD (DAY-FIRST for ambiguous dates)."""
    if raw_value is None:
        return None

    if isinstance(raw_value, datetime):
        return raw_value.date().isoformat()

    text = str(raw_value).strip()

    # Direct YYYY-MM-DD match
    direct_match = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", text)
    if direct_match:
        y, m, d = direct_match.groups()
        try:
            return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
        except ValueError:
            pass

    # Day-first format: dd-mm-yyyy or dd.mm.yyyy or dd/mm/yyyy
    day_first_match = re.search(r"\b(\d{1,2})[-/\.](\d{1,2})[-/\.](\d{4})\b", text)
    if day_first_match:
        d, m, y = day_first_match.groups()
        try:
            return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
        except ValueError:
            pass

    try:
        parsed = date_parser.parse(text, dayfirst=True, fuzzy=True)
        return parsed.date().isoformat()
    except (ValueError, OverflowError):
        return None


def normalize_canopy_change(raw_value: Any) -> Optional[float]:
    """Normalize canopy cover change percentage to float."""
    if raw_value is None:
        return None

    if isinstance(raw_value, (int, float)):
        return round(float(raw_value), 2)

    text = str(raw_value).strip()
    match = re.search(r"([\+\-]?\d+(?:\.\d+)?)\s*%", text)
    if match:
        try:
            return round(float(match.group(1)), 2)
        except ValueError:
            pass

    # Bare number
    match_num = re.search(r"([\+\-]?\d+(?:\.\d+)?)", text)
    if match_num:
        try:
            return round(float(match_num.group(1)), 2)
        except ValueError:
            pass

    return None


def normalize_credits(raw_value: Any) -> Optional[int]:
    """Normalize credits issued to integer."""
    if raw_value is None:
        return None

    if isinstance(raw_value, int):
        return raw_value if raw_value >= 0 else None
    if isinstance(raw_value, float):
        return int(raw_value) if raw_value >= 0 else None

    text = str(raw_value).strip()
    match = re.search(r"([\d,]+)", text)
    if match:
        try:
            clean = match.group(1).replace(",", "")
            return int(clean)
        except ValueError:
            pass

    return None


def normalize_registry(raw_value: Any) -> Optional[Registry]:
    """Normalize registry to Registry enum (verra | gold_standard)."""
    if raw_value is None:
        return None

    text = str(raw_value).strip().lower()
    if "verra" in text or "vcs" in text or "verified carbon standard" in text:
        return Registry.VERRA
    if "gold standard" in text or "gs" in text:
        return Registry.GOLD_STANDARD

    return None


def normalize_field(
    field_name: str,
    raw_value: Any,
) -> Tuple[Optional[Any], Optional[str]]:
    """Normalize a raw extracted field value.

    Returns:
        Tuple[Optional[Any], Optional[str]]: (normalized_value, error_reason)
    """
    if raw_value is None:
        return None, "Raw value is None"

    if field_name in ("claimed_area_ha", "estate_area_ha", "natural_forest_ha"):
        val = normalize_area(raw_value)
        if val is None:
            return None, f"Could not normalize area from '{raw_value}'"
        return val, None

    elif field_name in (
        "reporting_period_start",
        "reporting_period_end",
        "crediting_period_start",
        "crediting_period_end",
        "project_start_date",
    ):
        val = normalize_date(raw_value)
        if val is None:
            return None, f"Could not parse valid date from '{raw_value}'"
        return val, None

    elif field_name == "claimed_canopy_change_pct":
        val = normalize_canopy_change(raw_value)
        if val is None:
            return None, f"Could not parse canopy change percentage from '{raw_value}'"
        return val, None

    elif field_name in ("credits_issued", "net_ghg_removals_tco2e", "buffer_credits_tco2e"):
        val = normalize_credits(raw_value)
        if val is None:
            return None, f"Could not parse integer credits from '{raw_value}'"
        return val, None

    elif field_name in ("canopy_cover_pct", "min_area_ha", "min_height_m"):
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(raw_value))
        if match:
            try:
                return round(float(match.group(1)), 2), None
            except ValueError:
                pass
        return None, f"Could not parse float value from '{raw_value}'"

    elif field_name == "registry":
        val = normalize_registry(raw_value)
        if val is None:
            return None, f"Unrecognized registry '{raw_value}' (must be verra or gold_standard)"
        return val, None

    elif field_name == "project_id":
        clean = str(raw_value).strip()
        # Remove trailing periods or quotes
        clean = re.sub(r"^[\"']|[\"'.]$", "", clean)
        return clean, None

    elif field_name == "methodology":
        clean = str(raw_value).strip()
        # Find standard methodology pattern
        match = re.search(r"\b(VM\d{4}|AR-ACM\d{4}|ACM\d{4}|AMS-[A-Z]+-[A-Z\d]+)\b", clean, re.IGNORECASE)
        if match:
            return match.group(1).upper(), None
        return clean, None

    return str(raw_value).strip(), None
