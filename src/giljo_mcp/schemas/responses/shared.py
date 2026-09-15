# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict


T = TypeVar("T")


class DeleteResult(BaseModel):
    """Standard delete operation result."""

    deleted: bool = True
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class OperationResult(BaseModel):
    """Generic operation success result with a message."""

    message: str

    model_config = ConfigDict(from_attributes=True)


class PaginatedResult(BaseModel, Generic[T]):  # noqa: UP046 -- Pydantic v2 + PEP 695 generics interaction is fragile, keep classic Generic[T]
    """Paginated list result."""

    items: list[T]
    total: int
    page: int = 1
    page_size: int = 50

    model_config = ConfigDict(from_attributes=True)
