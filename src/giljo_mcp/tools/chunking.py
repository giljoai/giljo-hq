# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import re
from typing import Any


logger = logging.getLogger(__name__)

VISION_MAX_INGEST_TOKENS = 25000
VISION_DELIVERY_BUDGET = 24000
VISION_DEFAULT_CHUNK_SIZE = 24000
TOKEN_CHAR_RATIO = 4


class EnhancedChunker:

    TOKEN_CHAR_RATIO = TOKEN_CHAR_RATIO

    MAX_TOKENS = VISION_DELIVERY_BUDGET

    DEFAULT_MAX_TOKENS = VISION_DELIVERY_BUDGET

    DEFAULT_SEARCH_RANGE = 1000
    MINIMUM_SEARCH_RANGE = 500

    def __init__(self, max_tokens: int = DEFAULT_MAX_TOKENS):
        self.max_tokens = min(max_tokens, self.MAX_TOKENS)
        self.chars_per_chunk = self.max_tokens * self.TOKEN_CHAR_RATIO

    def estimate_tokens(self, content: str) -> int:
        return len(content) // self.TOKEN_CHAR_RATIO

    def find_natural_boundary(self, content: str, target_pos: int, search_range: int | None = None) -> tuple[int, str]:
        if search_range is None:
            search_range = min(self.DEFAULT_SEARCH_RANGE, int(self.chars_per_chunk * 0.1))

        content_len = len(content)
        if target_pos >= content_len:
            return content_len, "end"

        boundaries = [
            ("document", r"\n---+\n"),
            ("section", r"\n#{1,6}\s"),
            ("paragraph", r"\n\n"),
            ("line", r"\n"),
            ("sentence", r"[.!?]\s+"),
            ("word", r"\s"),
        ]

        search_start = max(0, target_pos - search_range)
        search_end = min(content_len, target_pos + search_range)

        for boundary_type, pattern in boundaries:
            if target_pos > search_start:
                backward_text = content[search_start:target_pos]
                matches = list(re.finditer(pattern, backward_text))
                if matches:
                    match = matches[-1]
                    boundary_pos = search_start + match.end()
                    return boundary_pos, boundary_type

            if target_pos < search_end:
                forward_text = content[target_pos:search_end]
                match = re.search(pattern, forward_text)
                if match:
                    boundary_pos = target_pos + match.end()
                    return boundary_pos, boundary_type

        return target_pos, "forced"

    def extract_keywords(self, content: str, max_keywords: int = 10) -> list[str]:
        keywords = []

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

        header_matches = re.findall(r"^#{1,6}\s+(.+)$", content, re.MULTILINE)
        for header in header_matches[: max_keywords - len(keywords)]:
            header_text = header.strip()
            if header_text and len(header_text) < 50:
                keywords.append(header_text)

        return keywords[:max_keywords]

    def extract_headers(self, content: str) -> list[str]:
        headers = []
        header_matches = re.findall(r"^(#{1,6})\s+(.+)$", content, re.MULTILINE)

        for level, text in header_matches:
            headers.append({"level": len(level), "text": text.strip()})

        return headers

    def chunk_content(self, content: str, document_name: str = "document") -> list[dict[str, Any]]:
        if not content:
            return []

        total_chars = len(content)
        estimated_tokens = self.estimate_tokens(content)

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

        num_chunks = (estimated_tokens + self.max_tokens - 1) // self.max_tokens

        chunks = []
        current_pos = 0

        for chunk_num in range(1, num_chunks + 1):
            if chunk_num == num_chunks:
                target_end = total_chars
            else:
                target_end = int((chunk_num * total_chars) / num_chunks)

            actual_end, boundary_type = self.find_natural_boundary(content, target_end, self.MINIMUM_SEARCH_RANGE)

            chunk_content = content[current_pos:actual_end]

            if not chunk_content.strip():
                continue

            chunk_tokens = self.estimate_tokens(chunk_content)

            chunk = {
                "chunk_number": len(chunks) + 1,
                "total_chunks": num_chunks,
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

        total_chunks = len(chunks)
        for chunk in chunks:
            chunk["total_chunks"] = total_chunks

        return chunks
