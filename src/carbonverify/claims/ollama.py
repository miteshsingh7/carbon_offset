"""Optional local LLM client using Ollama (http://localhost:11434)."""

import json
import logging
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

from carbonverify.claims.normalizer import normalize_field, validate_evidence_quote
from carbonverify.claims.retrieval import CandidateSnippet
from carbonverify.schemas import FieldExtractionDetail

logger = logging.getLogger(__name__)


class OllamaLLMClient:
    """Client for local Ollama server (e.g. qwen2.5:7b) for fallback claim extraction."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        timeout_seconds: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def extract_missing_fields(
        self,
        missing_fields: List[str],
        candidates_by_field: Dict[str, List[CandidateSnippet]],
        page_lookup: Dict[int, str],
    ) -> Dict[str, FieldExtractionDetail]:
        """Attempt to extract missing fields via local Ollama instance.

        Any extracted value is strictly validated against the cited page text
        and normalized. If invalid, unreachable, or missing, it remains None.

        Args:
            missing_fields: List of field names that were not found by rule-based extraction.
            candidates_by_field: Retrieved candidate snippets per field.
            page_lookup: Dict mapping page number to raw page text.

        Returns:
            Dict mapping field_name to FieldExtractionDetail.
        """
        results: Dict[str, FieldExtractionDetail] = {}

        if not missing_fields:
            return results

        # Build prompt for missing fields
        prompt_sections = [
            f"You are extracting verified claims for a carbon offset project using model {self.model}.\n",
            "Extract ONLY information explicitly stated in the candidate snippets. Never invent values.\n",
            "For each field, return a JSON object with 'value', 'evidence_quote' (exact verbatim quote), and 'page'.\n\n",
        ]

        for field in missing_fields:
            snippets = candidates_by_field.get(field, [])
            prompt_sections.append(f"Field: {field}")
            if not snippets:
                prompt_sections.append("No snippets available.\n")
                continue
            for i, snip in enumerate(snippets, 1):
                prompt_sections.append(f"[Page {snip.page}]: \"{snip.text}\"\n")

        prompt_sections.append(
            "\nRespond with a single JSON object mapping each requested field to:\n"
            "{\"value\": <value or null>, \"evidence_quote\": <verbatim string or null>, \"page\": <int or null>}"
        )
        full_prompt = "\n".join(prompt_sections)

        raw_extractions = self._call_ollama(full_prompt)
        if not raw_extractions:
            return results

        for field in missing_fields:
            ext = raw_extractions.get(field, {})
            raw_val = ext.get("value")
            evidence_quote = ext.get("evidence_quote")
            page_num = ext.get("page")

            if raw_val is None or page_num is None or evidence_quote is None:
                continue

            page_text = page_lookup.get(page_num, "")
            # Anti-hallucination check
            if not validate_evidence_quote(evidence_quote, page_text):
                logger.warning(
                    "Ollama extraction rejected: quote '%s' not on page %d",
                    evidence_quote,
                    page_num,
                )
                continue

            # Normalization check
            norm_val, norm_err = normalize_field(field, raw_val)
            if norm_err is not None or norm_val is None:
                continue

            # Accepted through Ollama
            logger.info("Ollama successfully extracted missing field '%s': %s", field, norm_val)
            results[field] = FieldExtractionDetail(
                value=norm_val,
                raw_value=str(raw_val),
                page=page_num,
                evidence_quote=evidence_quote,
                status="accepted",
                reason=None,
            )

        return results

    def _call_ollama(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Send generation request to Ollama /api/generate endpoint."""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0},
        }

        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                if resp.status == 200:
                    body = json.loads(resp.read().decode("utf-8"))
                    response_text = body.get("response", "{}")
                    return json.loads(response_text)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning(
                "Ollama server not reachable at %s (%s). Continuing with rule-based results.",
                self.base_url,
                exc,
            )
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse JSON response from Ollama: %s", exc)

        return None
