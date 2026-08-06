# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Unit tests for VisionDocumentChunker.

Tests tiktoken-based accurate token counting, semantic chunking,
keyword extraction, and summarization.

TDD Approach: Tests written first, then implementation.
"""

import pytest

from giljo_mcp.context_management.chunker import VisionDocumentChunker


class TestVisionDocumentChunker:
    """Test suite for VisionDocumentChunker."""

    @pytest.fixture
    def chunker(self):
        """Create chunker with default settings."""
        return VisionDocumentChunker(target_chunk_size=5000)

    @pytest.fixture
    def small_chunker(self):
        """Create chunker with small chunk size for testing."""
        return VisionDocumentChunker(target_chunk_size=100)

    def test_initialization(self, chunker):
        """Test chunker initialization with correct encoding."""
        assert chunker.target_chunk_size == 5000
        assert chunker.encoding is not None
        assert chunker.encoding.name == "cl100k_base"

    def test_count_tokens_simple_text(self, chunker):
        """Test accurate token counting with tiktoken."""
        text = "Hello world! This is a test."
        tokens = chunker.count_tokens(text)

        # Verify tokens is an integer and reasonable
        assert isinstance(tokens, int)
        assert tokens > 0
        assert tokens < 20  # Should be around 7-8 tokens

    def test_count_tokens_empty_string(self, chunker):
        """Test token counting with empty string."""
        assert chunker.count_tokens("") == 0

    def test_count_tokens_multiline(self, chunker):
        """Test token counting with multiline text."""
        text = """# Header

This is a paragraph with multiple lines.
Another paragraph follows.

- List item 1
- List item 2
"""
        tokens = chunker.count_tokens(text)
        assert isinstance(tokens, int)
        assert tokens > 10  # Should have multiple tokens

    def test_extract_keywords_simple(self, chunker):
        """Test keyword extraction from simple text."""
        text = """
# Phase 1: Database Setup

This phase covers PostgreSQL database setup and configuration.
We'll use FastAPI for the API layer.
"""
        keywords = chunker.extract_keywords(text, max_keywords=5)

        assert isinstance(keywords, list)
        assert len(keywords) <= 5
        # Should extract technical terms
        keywords_lower = [k.lower() for k in keywords]
        assert any(
            "phase" in k or "database" in k or "postgresql" in k or "fastapi" in k or "api" in k for k in keywords_lower
        )

    def test_extract_keywords_empty_text(self, chunker):
        """Test keyword extraction from empty text."""
        keywords = chunker.extract_keywords("", max_keywords=10)
        assert keywords == []

    def test_extract_keywords_max_limit(self, chunker):
        """Test keyword extraction respects max limit."""
        text = "Database API PostgreSQL FastAPI Agent MCP Vision Context Testing Docker"
        keywords = chunker.extract_keywords(text, max_keywords=3)
        assert len(keywords) <= 3

    def test_generate_summary_simple(self, chunker):
        """Test summary generation from text."""
        text = "This is a test document with some content. " * 20
        summary = chunker.generate_summary(text, max_length=50)

        assert isinstance(summary, str)
        assert len(summary) <= 50
        assert len(summary) > 0

    def test_generate_summary_short_text(self, chunker):
        """Test summary generation from text shorter than max length."""
        text = "Short text"
        summary = chunker.generate_summary(text, max_length=200)
        assert summary == text

    def test_chunk_small_document(self, chunker):
        """Test chunking document that fits in one chunk."""
        text = "Small document content here."
        chunks = chunker.chunk_document(text, product_id="prod-123")

        assert len(chunks) == 1
        assert chunks[0]["content"] == text
        assert chunks[0]["chunk_number"] == 1
        assert chunks[0]["total_chunks"] == 1
        assert chunks[0]["product_id"] == "prod-123"
        assert chunks[0]["tokens"] > 0
        assert "keywords" in chunks[0]
        assert "summary" in chunks[0]

    def test_chunk_large_document(self, small_chunker):
        """Test chunking large document into multiple chunks."""
        # Create a document that requires multiple chunks
        text = "This is a paragraph. " * 200  # Should exceed 100 token limit
        chunks = small_chunker.chunk_document(text, product_id="prod-456")

        # Should create multiple chunks
        assert len(chunks) > 1

        # Verify chunk metadata
        for i, chunk in enumerate(chunks):
            assert chunk["chunk_number"] == i + 1
            assert chunk["total_chunks"] == len(chunks)
            assert chunk["product_id"] == "prod-456"
            assert chunk["tokens"] > 0
            assert "content" in chunk
            assert "keywords" in chunk
            assert "summary" in chunk

    def test_chunk_document_with_semantic_boundaries(self, small_chunker):
        """Test chunking respects semantic boundaries (paragraphs, headers)."""
        # Create a larger document that will definitely need chunking
        section_template = """
This is a paragraph with multiple sentences to add content.
We need enough text to exceed the 100 token limit.
Adding more sentences here to ensure we have sufficient content for chunking.
"""
        text = f"""# Section 1

{section_template}

## Subsection 1.1

{section_template}

# Section 2

{section_template}

## Subsection 2.1

{section_template}

# Section 3

{section_template}

## Subsection 3.1

{section_template}
"""
        chunks = small_chunker.chunk_document(text, product_id="prod-789")

        # Should create multiple chunks with 100 token limit
        assert len(chunks) > 1

        # Each chunk should have reasonable content
        for chunk in chunks:
            assert len(chunk["content"].strip()) > 0
            assert chunk["tokens"] > 0

    def test_chunk_document_keywords_extracted(self, chunker):
        """Test that keywords are extracted from each chunk."""
        text = """# Database Configuration

PostgreSQL setup for the Giljo HQ system.
We use FastAPI for the backend API.

# Agent Orchestration

The agent orchestrator manages multiple AI agents.
"""
        chunks = chunker.chunk_document(text, product_id="prod-abc")

        assert len(chunks) >= 1
        for chunk in chunks:
            assert isinstance(chunk["keywords"], list)
            # Should have extracted some keywords
            if len(chunk["content"]) > 50:
                assert len(chunk["keywords"]) > 0

    def test_chunk_document_summaries_generated(self, chunker):
        """Test that summaries are generated for each chunk."""
        text = "This is a test document. " * 100
        chunks = chunker.chunk_document(text, product_id="prod-def")

        assert len(chunks) >= 1
        for chunk in chunks:
            assert isinstance(chunk["summary"], str)
            assert len(chunk["summary"]) > 0
            # Summary should be shorter than content
            assert len(chunk["summary"]) <= len(chunk["content"])

    def test_chunk_document_token_counts_accurate(self, chunker):
        """Test that token counts are accurate using tiktoken."""
        text = "Hello world! This is a test document with some content."
        chunks = chunker.chunk_document(text, product_id="prod-ghi")

        assert len(chunks) == 1
        chunk = chunks[0]

        # Verify token count matches actual tiktoken count
        expected_tokens = chunker.count_tokens(text)
        assert chunk["tokens"] == expected_tokens

    def test_chunk_document_preserves_order(self, small_chunker):
        """Test that chunks maintain sequential order."""
        text = "Section 1. " * 50 + "Section 2. " * 50 + "Section 3. " * 50
        chunks = small_chunker.chunk_document(text, product_id="prod-jkl")

        # Verify sequential chunk numbers
        for i, chunk in enumerate(chunks):
            assert chunk["chunk_number"] == i + 1

    def test_chunk_empty_document(self, chunker):
        """Test chunking empty document."""
        chunks = chunker.chunk_document("", product_id="prod-mno")
        assert chunks == []

    def test_chunk_whitespace_only_document(self, chunker):
        """Test chunking document with only whitespace."""
        chunks = chunker.chunk_document("   \n\n   \t  ", product_id="prod-pqr")
        # Should return empty list for whitespace-only content
        assert chunks == []

    def test_chunk_document_boundary_detection(self, small_chunker):
        """Test that chunking uses EnhancedChunker for boundary detection."""
        # Create larger document to force chunking
        paragraph = "This is a paragraph with enough content to make chunking necessary. "
        text = f"""# Major Section

{paragraph * 10}

Second paragraph content here with more text to add tokens.

## Subsection

{paragraph * 10}

Third paragraph with additional content for proper chunking behavior.
"""
        chunks = small_chunker.chunk_document(text, product_id="prod-stu")

        # Should use semantic boundaries from EnhancedChunker
        assert len(chunks) > 1

        # Verify no chunks are excessively small or empty
        for chunk in chunks:
            assert len(chunk["content"].strip()) > 5

    def test_chunk_metadata_completeness(self, chunker):
        """Test that all required metadata is present in chunks."""
        text = "Test document with some content for metadata validation."
        chunks = chunker.chunk_document(text, product_id="prod-vwx")

        required_fields = ["chunk_number", "total_chunks", "content", "tokens", "keywords", "summary", "product_id"]

        for chunk in chunks:
            for field in required_fields:
                assert field in chunk, f"Missing field: {field}"

    def test_chunk_size_configuration(self):
        """Test chunker with different target chunk sizes."""
        small = VisionDocumentChunker(target_chunk_size=100)
        large = VisionDocumentChunker(target_chunk_size=10000)

        assert small.target_chunk_size == 100
        assert large.target_chunk_size == 10000

    def test_integration_with_enhanced_chunker(self, chunker):
        """Test that VisionDocumentChunker integrates with EnhancedChunker."""
        from giljo_mcp.tools.chunking import EnhancedChunker

        # Verify EnhancedChunker is available
        assert hasattr(chunker, "enhanced_chunker")
        assert isinstance(chunker.enhanced_chunker, EnhancedChunker)


class TestVisionDocumentChunkerEdgeCases:
    """Test edge cases for VisionDocumentChunker."""

    def test_very_long_line(self):
        """Test chunking document with very long single line."""
        chunker = VisionDocumentChunker(target_chunk_size=100)
        text = "word " * 500  # Very long line
        chunks = chunker.chunk_document(text, product_id="prod-edge1")

        # Should handle long lines gracefully
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk["tokens"] > 0

    def test_unicode_content(self):
        """Test chunking with unicode characters."""
        chunker = VisionDocumentChunker(target_chunk_size=5000)
        text = "Testing unicode: 你好世界 🚀 αβγδ"
        chunks = chunker.chunk_document(text, product_id="prod-edge2")

        assert len(chunks) == 1
        assert chunks[0]["content"] == text
        assert chunks[0]["tokens"] > 0

    def test_special_characters(self):
        """Test chunking with special characters."""
        chunker = VisionDocumentChunker(target_chunk_size=5000)
        text = "Special chars: @#$%^&*() <>?{}[]|\\~`"
        chunks = chunker.chunk_document(text, product_id="prod-edge3")

        assert len(chunks) == 1
        assert chunks[0]["tokens"] > 0

    def test_code_blocks(self):
        """Test chunking with code blocks."""
        chunker = VisionDocumentChunker(target_chunk_size=5000)
        text = """
# Code Example

```python
def hello_world():
    print("Hello, World!")
```

More text here.
"""
        chunks = chunker.chunk_document(text, product_id="prod-edge4")

        assert len(chunks) >= 1
        # Code blocks should be preserved
        assert "```python" in chunks[0]["content"]


# ---------------------------------------------------------------------------
# BE-5115 regression: chunk_vision_document is inline-only.
# ---------------------------------------------------------------------------


class TestBe5115ChunkerInlineOnly:
    """Regression guard for the Railway ephemeral-disk bug.

    Before BE-5115 ``chunk_vision_document`` read content from disk when
    ``storage_type`` was ``file`` or ``hybrid``. The migration in
    ``ce_0032_vision_docs_inline_only`` collapses everything to ``inline``
    and the chunker now reads ``doc.vision_document`` unconditionally.
    These tests fail loudly if anyone wires the file-read branch back in.
    """

    @pytest.mark.asyncio
    async def test_chunker_reads_inline_content_from_db_column(self):
        """Chunker yields the DB column content without touching the disk."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock, patch

        fake_doc = SimpleNamespace(
            id="doc-001",
            product_id="prod-001",
            document_name="vision.md",
            storage_type="inline",
            vision_path=None,
            vision_document="Hello world from DB column.",
        )

        fake_vision_repo = MagicMock()
        fake_vision_repo.get_by_id = AsyncMock(return_value=fake_doc)
        fake_vision_repo.mark_chunked = AsyncMock()

        fake_context_repo = MagicMock()
        fake_context_repo.delete_chunks_by_vision_document = AsyncMock(return_value=0)

        fake_session = MagicMock()
        fake_session.add = MagicMock()
        fake_session.flush = AsyncMock()

        with (
            patch(
                "giljo_mcp.repositories.vision_document_repository.VisionDocumentRepository",
                return_value=fake_vision_repo,
            ),
            patch(
                "giljo_mcp.repositories.context_repository.ContextRepository",
                return_value=fake_context_repo,
            ),
            patch("pathlib.Path.read_text") as read_text_spy,
        ):
            chunker = VisionDocumentChunker(target_chunk_size=5000)
            result = await chunker.chunk_vision_document(
                session=fake_session,
                tenant_key="tenant-001",
                vision_document_id=fake_doc.id,
            )

        assert result["success"] is True
        assert result["document_id"] == fake_doc.id
        assert result["chunks_created"] >= 1, "chunker should produce at least one chunk"
        read_text_spy.assert_not_called()

    @pytest.mark.asyncio
    async def test_chunker_raises_when_inline_content_missing(self):
        """Chunker raises ContextError when vision_document is empty/None."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock, patch

        from giljo_mcp.exceptions import ContextError

        fake_doc = SimpleNamespace(
            id="doc-empty",
            product_id="prod-empty",
            document_name="empty.md",
            storage_type="inline",
            vision_path=None,
            vision_document="",
        )

        fake_vision_repo = MagicMock()
        fake_vision_repo.get_by_id = AsyncMock(return_value=fake_doc)

        with (
            patch(
                "giljo_mcp.repositories.vision_document_repository.VisionDocumentRepository",
                return_value=fake_vision_repo,
            ),
            patch(
                "giljo_mcp.repositories.context_repository.ContextRepository",
                return_value=MagicMock(),
            ),
        ):
            chunker = VisionDocumentChunker(target_chunk_size=5000)
            with pytest.raises(ContextError, match="no content to chunk"):
                await chunker.chunk_vision_document(
                    session=MagicMock(),
                    tenant_key="tenant-empty",
                    vision_document_id=fake_doc.id,
                )

    def test_chunker_module_does_not_import_aiofiles_or_pathlib_path(self):
        """chunker.py must not import aiofiles or pathlib.Path after BE-5115."""
        import inspect

        from giljo_mcp.context_management import chunker as chunker_module

        source = inspect.getsource(chunker_module)
        assert "import aiofiles" not in source, "chunker.py must not import aiofiles after BE-5115"
        assert "from pathlib import Path" not in source, "chunker.py must not import Path after BE-5115"
