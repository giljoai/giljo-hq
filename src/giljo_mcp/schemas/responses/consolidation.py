# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from pydantic import BaseModel, ConfigDict, Field


class SummaryLevel(BaseModel):
    """Single summary level (light or medium) within a consolidation result."""

    summary: str = ""
    tokens: int = 0

    model_config = ConfigDict(from_attributes=True)


class ConsolidationResult(BaseModel):
    """Vision document consolidation result.

    Fields match ConsolidatedVisionService.consolidate_vision_documents() output.
    """

    light: SummaryLevel = Field(default_factory=SummaryLevel)
    medium: SummaryLevel = Field(default_factory=SummaryLevel)
    hash: str = ""
    source_docs: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class SummarizeSingleResult(BaseModel):
    """Single-document summarization result.

    Transport shape for AI-tool summary responses; per-doc and aggregate
    summary text is produced by the agent via the ``update_product_context``
    MCP tool. Server-side extractive summarization is no longer performed.
    """

    summary: str = ""
    original_tokens: int = 0
    summary_tokens: int = 0
    compression_ratio: float = 0.0
    processing_time_ms: int = 0

    model_config = ConfigDict(from_attributes=True)


class MultiLevelSummaryLevel(BaseModel):
    """Single level within a multi-level summarization result."""

    summary: str = ""
    tokens: int = 0
    sentences: int = 0

    model_config = ConfigDict(from_attributes=True)


class SummarizeMultiLevelResult(BaseModel):
    """Multi-level summarization result.

    Transport shape for AI-tool light/medium summary responses; written by
    the agent via the ``update_product_context`` MCP tool. Server-side
    multi-level extractive summarization is no longer performed.
    """

    light: MultiLevelSummaryLevel = Field(default_factory=MultiLevelSummaryLevel)
    medium: MultiLevelSummaryLevel = Field(default_factory=MultiLevelSummaryLevel)
    original_tokens: int = 0
    processing_time_ms: int = 0

    model_config = ConfigDict(from_attributes=True)
