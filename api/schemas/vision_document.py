# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VisionDocumentCreate(BaseModel):
    """
    Schema for creating a vision document.

    Users can choose between:
    - File upload (vision_file) → storage_type="file"
    - Inline content (content) → storage_type="inline"
    - Both (hybrid) → storage_type="hybrid"
    """

    product_id: str = Field(..., description="Product ID this document belongs to")
    document_name: str = Field(..., min_length=1, max_length=255, description="User-friendly document name")
    document_type: str = Field(
        "vision",
        description="Document category: vision, architecture, features, setup, api, testing, deployment, custom",
    )
    content: str | None = Field(default=None, description="Inline document content (for inline or hybrid storage)")
    storage_type: str = Field(default="inline", description="Storage mode: file, inline, hybrid")
    auto_chunk: bool = Field(default=True, description="Automatically chunk document after creation")
    display_order: int = Field(default=0, description="Display order in UI (lower numbers first)")
    version: str = Field(default="1.0.0", description="Semantic version")

    model_config = ConfigDict(from_attributes=True)


class VisionDocumentUpdate(BaseModel):
    """
    Schema for updating vision document content.

    Updating content automatically:
    - Recalculates content hash
    - Resets chunked flag to False
    - Triggers re-chunking if auto_rechunk=True
    """

    content: str = Field(..., description="New document content")
    auto_rechunk: bool = Field(default=True, description="Automatically re-chunk after update")

    model_config = ConfigDict(from_attributes=True)


class VisionDocumentResponse(BaseModel):
    """
    Full vision document response with all fields.

    Returned from:
    - GET /vision-documents/product/{product_id}
    - POST /vision-documents/
    - PUT /vision-documents/{document_id}
    """

    id: str = Field(..., description="Vision document ID")
    tenant_key: str = Field(..., description="Tenant key (multi-tenant isolation)")
    product_id: str = Field(..., description="Product ID")
    document_name: str = Field(..., description="Document name")
    document_type: str = Field(..., description="Document category")
    storage_type: str = Field(..., description="Storage mode: file, inline, hybrid")
    vision_path: str | None = Field(None, description="File path (if file-based storage)")
    vision_document: str | None = Field(None, description="Inline content (if inline storage)")
    chunked: bool = Field(..., description="Has document been chunked")
    chunk_count: int = Field(..., description="Number of chunks created")
    total_tokens: int | None = Field(None, description="Estimated total tokens")
    file_size: int | None = Field(None, description="Original file size in bytes")
    content_hash: str | None = Field(None, description="SHA-256 content hash")
    version: str = Field(..., description="Document version")
    is_active: bool = Field(..., description="Active status")
    display_order: int = Field(..., description="Display order")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime | None = Field(None, description="Last update timestamp")
    chunked_at: datetime | None = Field(None, description="Last chunking timestamp")
    deleted_at: datetime | None = Field(None, description="Soft-delete timestamp (NULL for live docs)")
    meta_data: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    is_summarized: bool = Field(default=False, description="Whether summaries have been generated")
    summary_light: str | None = Field(default=None, description="Light summary (33% of original)")
    summary_medium: str | None = Field(default=None, description="Medium summary (66% of original)")
    summary_light_tokens: int | None = Field(default=None, description="Token count for light summary")
    summary_medium_tokens: int | None = Field(default=None, description="Token count for medium summary")
    original_token_count: int | None = Field(default=None, description="Original document token count")
    has_summaries: bool = Field(default=False, description="Whether summaries have been generated (computed)")

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def compute_has_summaries(self) -> "VisionDocumentResponse":
        self.has_summaries = bool(self.summary_light or self.summary_medium)
        return self


class RechunkRequest(BaseModel):
    """
    Schema for triggering re-chunking (POST /vision-documents/{document_id}/rechunk).

    Re-chunking:
    - Deletes existing chunks for this document
    - Chunks content using EnhancedChunker
    - Updates vision document metadata (chunked=True, chunk_count, total_tokens)
    """



class RechunkResponse(BaseModel):
    """
    Response from re-chunking operation.
    """

    success: bool = Field(..., description="Whether re-chunking succeeded")
    document_id: str = Field(..., description="Document ID that was re-chunked")
    document_name: str = Field(..., description="Document name")
    chunks_created: int = Field(..., description="Number of chunks created")
    total_tokens: int = Field(..., description="Total estimated tokens")
    old_chunks_deleted: int = Field(..., description="Number of old chunks deleted")

    model_config = ConfigDict(from_attributes=True)


class DeleteResponse(BaseModel):
    """
    Response from vision document deletion.

    Deletion cascades:
    - Deletes vision document
    - Cascades to delete all chunks (via MCPContextIndex.vision_document_id)
    """

    success: bool = Field(..., description="Whether deletion succeeded")
    document_id: str = Field(..., description="Deleted document ID")
    document_name: str = Field(..., description="Deleted document name")
    chunks_deleted: int = Field(..., description="Number of chunks deleted (CASCADE)")

    model_config = ConfigDict(from_attributes=True)
