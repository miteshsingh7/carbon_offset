"""LLM client interface and mock client for tests."""

from abc import ABC, abstractmethod
import logging
import re
from typing import Any, Dict, List, Optional

from carbonverify.claims.retrieval import CandidateSnippet

logger = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    """Abstract interface for LLM claims extraction."""

    @abstractmethod
    def extract_fields(
        self,
        candidates_by_field: Dict[str, List[CandidateSnippet]],
    ) -> Dict[str, Dict[str, Any]]:
        """Extract field values with verbatim evidence quotes from candidate snippets.

        Args:
            candidates_by_field: Dict mapping field names to list of CandidateSnippet objects.

        Returns:
            Dict mapping field_name to dict:
            {"value": Optional[Any], "evidence_quote": Optional[str], "page": Optional[int]}
        """
        pass


class MockLLMClient(BaseLLMClient):
    """Mock LLM client used exclusively for test injection."""

    def __init__(
        self,
        predefined_responses: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self.predefined_responses = predefined_responses or {}

    def extract_fields(
        self,
        candidates_by_field: Dict[str, List[CandidateSnippet]],
    ) -> Dict[str, Dict[str, Any]]:
        """Extract fields using predefined responses or rule-based candidate parsing."""
        results: Dict[str, Dict[str, Any]] = {}

        for field_name, snippets in candidates_by_field.items():
            if field_name in self.predefined_responses:
                results[field_name] = self.predefined_responses[field_name]
                continue

            extracted = self._heuristic_extract(field_name, snippets)
            results[field_name] = extracted

        return results

    def _heuristic_extract(
        self,
        field_name: str,
        snippets: List[CandidateSnippet],
    ) -> Dict[str, Any]:
        """Extract value and exact verbatim evidence quote using pattern matching."""
        if not snippets:
            return {"value": None, "evidence_quote": None, "page": None}

        for snip in snippets:
            text = snip.text
            page = snip.page

            if field_name == "project_id":
                m = re.search(r"((?:VCS|GS)[\s\-_]?[0-9]+)", text, re.IGNORECASE)
                if m:
                    quote = self._find_sentence(text, m.group(0))
                    return {"value": m.group(1), "evidence_quote": quote, "page": page}

            elif field_name == "registry":
                m = re.search(r"(Verified\s*Carbon\s*Standard|Verra|Gold\s*Standard)", text, re.IGNORECASE)
                if m:
                    quote = self._find_sentence(text, m.group(0))
                    val = "verra" if "gold" not in m.group(1).lower() else "gold_standard"
                    return {"value": val, "evidence_quote": quote, "page": page}

            elif field_name == "methodology":
                m = re.search(r"\b(VM\d{4}|AR-ACM\d{4}|ACM\d{4})\b", text)
                if m:
                    quote = self._find_sentence(text, m.group(0))
                    return {"value": m.group(1), "evidence_quote": quote, "page": page}

            elif field_name == "claimed_area_ha":
                m = re.search(r"(\d+(?:,\d+)*(?:\.\d+)?)\s*(ha|hectares?|km2|km²|acres?)\b", text, re.IGNORECASE)
                if m:
                    quote = self._find_sentence(text, m.group(0))
                    return {"value": m.group(0), "evidence_quote": quote, "page": page}

            elif field_name == "reporting_period_start":
                m = re.search(r"(?:start(?:\s*date)?|from|period\s*start)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})", text, re.IGNORECASE)
                if m:
                    quote = self._find_sentence(text, m.group(1))
                    return {"value": m.group(1), "evidence_quote": quote, "page": page}
                m_date = re.search(r"\b(\d{4}[-/]\d{2}[-/]\d{2})\b", text)
                if m_date:
                    quote = self._find_sentence(text, m_date.group(1))
                    return {"value": m_date.group(1), "evidence_quote": quote, "page": page}

            elif field_name == "reporting_period_end":
                m = re.search(r"(?:end(?:\s*date)?|to|until|ending|period\s*end)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})", text, re.IGNORECASE)
                if m:
                    quote = self._find_sentence(text, m.group(1))
                    return {"value": m.group(1), "evidence_quote": quote, "page": page}

            elif field_name == "credits_issued":
                m = re.search(r"(\d+(?:,\d+)*)\s*(?:vcus?|credits?|tco2e)", text, re.IGNORECASE)
                if m:
                    quote = self._find_sentence(text, m.group(0))
                    return {"value": m.group(1), "evidence_quote": quote, "page": page}

            elif field_name == "claimed_canopy_change_pct":
                m = re.search(r"([\+\-]?\d+(?:\.\d+)?\s*%)", text)
                if m:
                    quote = self._find_sentence(text, m.group(1))
                    return {"value": m.group(1), "evidence_quote": quote, "page": page}

        return {"value": None, "evidence_quote": None, "page": None}

    def _find_sentence(self, text: str, target: str) -> str:
        """Find the exact sentence or line containing the target substring."""
        for line in text.split("\n"):
            if target in line:
                return line.strip()
        idx = text.find(target)
        if idx != -1:
            start = max(0, idx - 20)
            end = min(len(text), idx + len(target) + 20)
            return text[start:end].strip()
        return target
