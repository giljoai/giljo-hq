# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Enhanced chunking utilities for Giljo HQ.
Supports documents up to 100K+ tokens with natural boundary preservation.
Based on proven chunking implementation with enhancements.
"""

import logging
import re
from typing import Any


logger = logging.getLogger(__name__)

# Canonical vision document token constants (Handover 0493)
VISION_MAX_INGEST_TOKENS = 25000  # Max accepted document size on upload
VISION_DELIVERY_BUDGET = 24000  # Max tokens per delivery call (safety buffer below 25K)
VISION_DEFAULT_CHUNK_SIZE = 24000  # Default chunk target (= delivery budget)
TOKEN_CHAR_RATIO = 4  # Approximate chars-per-token ratio


class EnhancedChunker:
    """
    Enhanced document chunker with multi-level boundary detection.
    Supports documents up to 100K+ tokens with natural breaks.
    """

    # Token to character ratio (from analysis)
    TOKEN_CHAR_RATIO = TOKEN_CHAR_RATIO

    # Maximum tokens per chunk (hard limit from MCP)
    MAX_TOKENS = VISION_DELIVERY_BUDGET

    # Default chunk size
    DEFAULT_MAX_TOKENS = VISION_DELIVERY_BUDGET

    # Boundary search ranges
    DEFAULT_SEARCH_RANGE = 1000
    MINIMUM_SEARCH_RANGE = 500

    def __init__(self, max_tokens: int = DEFAULT_MAX_TOKENS):
        """
        Initialize the chunker.

        Args:
            max_tokens: Maximum tokens per chunk (capped at 24000)
        """
        self.max_tokens = min(max_tokens, self.MAX_TOKENS)
        self.chars_per_chunk = self.max_tokens * self.TOKEN_CHAR_RATIO

    def estimate_tokens(self, content: str) -> int:
        """
        Estimate token count from character count.
        Uses 1:4 token-to-character ratio.

        Args:
            content: Text content

        Returns:
            Estimated token count
        """
        return len(content) // self.TOKEN_CHAR_RATIO

    def find_natural_boundary(self, content: str, target_pos: int, search_range: int | None = None) -> tuple[int, str]:
        """
        Find the nearest natural boundary to the target position.
        Implements multi-level boundary hierarchy.

        Args:
            content: Full content to search
            target_pos: Target character position
            search_range: How far to search for boundaries

        Returns:
            Tuple of (boundary_position, boundary_type)
        """
        if search_range is None:
            search_range = min(self.DEFAULT_SEARCH_RANGE, int(self.chars_per_chunk * 0.1))

        # Ensure we don't go out of bounds
        content_len = len(content)
        if target_pos >= content_len:
            return content_len, "end"

        # Define boundary types in order of preference
        boundaries = [
            ("document", r"\n---+\n"),  # Document separator
            ("section", r"\n#{1,6}\s"),  # Markdown headers
            ("paragraph", r"\n\n"),  # Paragraph break
            ("line", r"\n"),  # Line break
            ("sentence", r"[.!?]\s+"),  # Sentence end
            ("word", r"\s"),  # Word boundary
        ]

        # Calculate search window
        search_start = max(0, target_pos - search_range)
        search_end = min(content_len, target_pos + search_range)

        # Try each boundary type
        for boundary_type, pattern in boundaries:
            # Look backwards first (preferred)
            if target_pos > search_start:
                backward_text = content[search_start:target_pos]
                matches = list(re.finditer(pattern, backward_text))
                if matches:
                    # Use the last match (closest to target)
                    match = matches[-1]
                    boundary_pos = search_start + match.end()
                    return boundary_pos, boundary_type

            # Look forwards if no backward match
            if target_pos < search_end:
                forward_text = content[target_pos:search_end]
                match = re.search(pattern, forward_text)
                if match:
                    boundary_pos = target_pos + match.end()
                    return boundary_pos, boundary_type

        # No boundary found, use target position
        return target_pos, "forced"

    def extract_keywords(self, content: str, max_keywords: int = 10) -> list[str]:
        """
        Extract keywords from content chunk.

        Args:
            content: Text content
            max_keywords: Maximum keywords to extract

        Returns:
            List of keywords
        """
        keywords = []

        # Common technical terms to look for
        tech_terms = [
            "Phase",
            "Project",
            "Agent",
            "Database",
            "API",
            "UI",
            "Deploy",
            "Orchestrator",
            "Message",
            "Context",
            "Vision",
            "MCP",
            "PostgreSQL",
            "FastAPI",
            "WebSocket",
            "Docker",
            "Testing",
        ]

        content_lower = content.lower()
        for term in tech_terms:
            if term.lower() in content_lower:
                keywords.append(term)
                if len(keywords) >= max_keywords:
                    break

        # Extract headers as keywords
        header_matches = re.findall(r"^#{1,6}\s+(.+)$", content, re.MULTILINE)
        for header in header_matches[: max_keywords - len(keywords)]:
            # Clean and add header text
            header_text = header.strip()
            if header_text and len(header_text) < 50:
                keywords.append(header_text)

        return keywords[:max_keywords]

    def extract_headers(self, content: str) -> list[str]:
        """
        Extract markdown headers from content.

        Args:
            content: Text content

        Returns:
            List of header texts
        """
        headers = []
        header_matches = re.findall(r"^(#{1,6})\s+(.+)$", content, re.MULTILINE)

        for level, text in header_matches:
            headers.append({"level": len(level), "text": text.strip()})

        return headers

    def chunk_content(self, content: str, document_name: str = "document") -> list[dict[str, Any]]:
        """
        Chunk content into parts with natural boundaries.
        Based on proven algorithm with enhancements.

        Args:
            content: Full content to chunk
            document_name: Name of the document being chunked

        Returns:
            List of chunk dictionaries with metadata
        """
        if not content:
            return []

        total_chars = len(content)
        estimated_tokens = self.estimate_tokens(content)

        # If content fits in one chunk, return as-is
        if estimated_tokens <= self.max_tokens:
            return [
                {
                    "chunk_number": 1,
                    "total_chunks": 1,
                    "content": content,
                    "tokens": estimated_tokens,
                    "char_start": 0,
                    "char_end": total_chars,
                    "boundary_type": "complete",
                    "keywords": self.extract_keywords(content),
                    "headers": self.extract_headers(content),
                    "document_name": document_name,
                }
            ]

        # Calculate number of chunks needed
        num_chunks = (estimated_tokens + self.max_tokens - 1) // self.max_tokens

        chunks = []
        current_pos = 0

        for chunk_num in range(1, num_chunks + 1):
            # Calculate target end position
            if chunk_num == num_chunks:
                # Last chunk takes remaining content
                target_end = total_chars
            else:
                # Calculate proportional position
                target_end = int((chunk_num * total_chars) / num_chunks)

            # Find natural boundary near target
            actual_end, boundary_type = self.find_natural_boundary(content, target_end, self.MINIMUM_SEARCH_RANGE)

            # Extract chunk content
            chunk_content = content[current_pos:actual_end]

            # Skip empty chunks
            if not chunk_content.strip():
                continue

            # Calculate chunk metadata
            chunk_tokens = self.estimate_tokens(chunk_content)

            # Create chunk entry
            chunk = {
                "chunk_number": len(chunks) + 1,
                "total_chunks": num_chunks,  # Will update after filtering empties
                "content": chunk_content,
                "tokens": chunk_tokens,
                "char_start": current_pos,
                "char_end": actual_end,
                "boundary_type": boundary_type,
                "keywords": self.extract_keywords(chunk_content),
                "headers": self.extract_headers(chunk_content),
                "document_name": document_name,
            }

            chunks.append(chunk)
            current_pos = actual_end

        # Update total_chunks after filtering
        total_chunks = len(chunks)
        for chunk in chunks:
            chunk["total_chunks"] = total_chunks

        return chunks
