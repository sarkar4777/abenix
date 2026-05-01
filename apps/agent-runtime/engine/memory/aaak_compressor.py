"""AAAK Compressor — Lossless shorthand compression for AI memory."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

AAAK_SYSTEM_PROMPT = """You are an AAAK encoder. AAAK is a lossless shorthand for AI memory.

Rules:
- Remove all filler words, articles, prepositions where meaning is preserved
- Use entity codes: P=person, C=company, T=technology, E=event, M=metric, L=location
- Use emotion markers: +pos -neg ~neutral !important ?uncertain
- Use relationship notation: X>Y (X causes Y), X<>Y (bidirectional), X~Y (related)
- Dates as YYMMDD, currencies as $XXk/$XXm/$XXb
- Preserve ALL facts, numbers, names, and relationships
- Output should be ~30x shorter than input
- Must be readable by any LLM without a decoder

Example:
Input: "Sarah Chen founded Abenix in 2024. The company raised $25 million in Series A funding led by Sequoia Capital. They use Neo4j for their knowledge graph technology."
AAAK: "P:SarahChen>founded>C:Abenix[240101] C:Abenix>raised>M:$25m[SeriesA,C:Sequoia] C:Abenix>uses>T:Neo4j[knowledge_graph]"

Compress the following text into AAAK notation. Output ONLY the AAAK text, nothing else."""


async def compress_to_aaak(text: str, llm_router: Any = None) -> str:
    """Compress text to AAAK notation using an LLM call."""
    if not text or len(text) < 50:
        return text  # Too short to compress

    if llm_router is None:
        from engine.llm_router import LLMRouter
        llm_router = LLMRouter()

    try:
        response = await llm_router.complete(
            messages=[
                {"role": "system", "content": AAAK_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            model="claude-haiku-3-5-20241022",  # Use cheap model for compression
            temperature=0.0,
        )
        compressed = response.content if hasattr(response, "content") else str(response)
        if compressed:
            ratio = len(text) / max(len(compressed), 1)
            logger.debug("AAAK compression: %d chars -> %d chars (%.1fx)", len(text), len(compressed), ratio)
            return compressed
        return text
    except Exception as e:
        logger.warning("AAAK compression failed, storing uncompressed: %s", e)
        return text


async def decompress_aaak(aaak_text: str, llm_router: Any = None) -> str:
    """Expand AAAK notation back to natural language (for display)."""
    if not aaak_text or not any(c in aaak_text for c in [">", "P:", "C:", "T:", "M:"]):
        return aaak_text  # Not AAAK formatted

    if llm_router is None:
        from engine.llm_router import LLMRouter
        llm_router = LLMRouter()

    try:
        response = await llm_router.complete(
            messages=[
                {"role": "system", "content": "Expand this AAAK shorthand into clear natural language. Preserve all facts."},
                {"role": "user", "content": aaak_text},
            ],
            model="claude-haiku-3-5-20241022",
            temperature=0.0,
        )
        expanded = response.content if hasattr(response, "content") else str(response)
        return expanded or aaak_text
    except Exception:
        return aaak_text
