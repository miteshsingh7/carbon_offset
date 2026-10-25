"""Claims extraction and validation package for carbonverify."""

from carbonverify.claims.extractor import extract_claims
from carbonverify.claims.llm import BaseLLMClient, MockLLMClient
from carbonverify.claims.normalizer import (
    normalize_area,
    normalize_canopy_change,
    normalize_credits,
    normalize_date,
    normalize_field,
    normalize_registry,
    validate_evidence_quote,
)
from carbonverify.claims.ollama import OllamaLLMClient
from carbonverify.claims.pdf_parser import extract_pages_from_pdf
from carbonverify.claims.retrieval import CandidateSnippet, retrieve_candidates_for_field
from carbonverify.claims.rule_based import RuleBasedExtractor

__all__ = [
    "BaseLLMClient",
    "CandidateSnippet",
    "MockLLMClient",
    "OllamaLLMClient",
    "RuleBasedExtractor",
    "extract_claims",
    "extract_pages_from_pdf",
    "normalize_area",
    "normalize_canopy_change",
    "normalize_credits",
    "normalize_date",
    "normalize_field",
    "normalize_registry",
    "retrieve_candidates_for_field",
    "validate_evidence_quote",
]
