# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Context Management for Giljo HQ.

Provides vision document chunking with tiktoken-based token counting
and semantic chunking. All operations enforce multi-tenant isolation
via tenant_key.
"""

from .chunker import VisionDocumentChunker


__all__ = [
    "VisionDocumentChunker",
]
