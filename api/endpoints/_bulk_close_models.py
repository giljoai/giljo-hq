# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import UUID

from pydantic import BaseModel, Field

from giljo_mcp.services.bulk_close import BULK_CLOSE_MAX, BulkCloseAction


class BulkCloseRequest(BaseModel):
    """What to do and to which items: archive, unarchive or delete, at most 500 ids."""

    action: BulkCloseAction
    ids: list[UUID] = Field(..., min_length=1, max_length=BULK_CLOSE_MAX)


class BulkCloseItem(BaseModel):
    """An item the batch did not change, and why."""

    id: str
    reason: str


class BulkCloseResponse(BaseModel):
    """What the batch did: the ids changed, the ones left alone with a reason, and any that failed."""

    done: list[str]
    skipped: list[BulkCloseItem]
    failed: list[BulkCloseItem]
