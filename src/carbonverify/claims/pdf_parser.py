"""PDF document text extraction and page caching using PyMuPDF."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Union

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


def extract_pages_from_pdf(
    pdf_path: Union[str, Path],
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    """Extract text per page from a PDF document with local JSON caching.

    Caches the extracted pages as JSON next to the PDF file (e.g. `<doc>.pages.json`)
    so repeated pipeline passes do not re-parse the PDF.

    Args:
        pdf_path: Path to the target PDF file.
        force_refresh: If True, re-parse the PDF even if a cache file exists.

    Returns:
        List[Dict[str, Any]]: List of dicts with {"page": int (1-indexed), "text": str}.
    """
    path = Path(pdf_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"PDF document does not exist: {path}")

    cache_file = path.parent / f"{path.stem}.pages.json"

    # Check cache
    if not force_refresh and cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
            if isinstance(cached_data, list) and len(cached_data) > 0:
                logger.info(
                    "Loaded %d parsed pages from cache: %s",
                    len(cached_data),
                    cache_file,
                )
                return cached_data
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read page cache %s: %s. Re-extracting.", cache_file, exc)

    logger.info("Extracting text from PDF via PyMuPDF: %s", path)
    pages: List[Dict[str, Any]] = []

    try:
        with fitz.open(path) as doc:
            for page_index in range(len(doc)):
                page = doc[page_index]
                page_text = page.get_text()
                pages.append({
                    "page": page_index + 1,
                    "text": page_text,
                    "char_count": len(page_text),
                })
    except Exception as exc:
        logger.error("Failed to parse PDF document %s: %s", path, exc)
        raise

    # Write cache
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(pages, f, indent=2, ensure_ascii=False)
        logger.info("Cached %d parsed pages to %s", len(pages), cache_file)
    except OSError as exc:
        logger.warning("Could not write cache file %s: %s", cache_file, exc)

    return pages
