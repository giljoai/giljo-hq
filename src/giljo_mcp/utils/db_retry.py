# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import logging
import random
from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import RetryExhaustedError


logger = logging.getLogger(__name__)

PG_DEADLOCK_CODE = "40P01"

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 0.1
DEFAULT_JITTER_MAX = 0.05


def _is_deadlock(err: OperationalError) -> bool:
    return getattr(getattr(err, "orig", None), "pgcode", None) == PG_DEADLOCK_CODE


async def _attempt_operation(
    session: AsyncSession,
    operation: Callable[[], Coroutine[Any, Any, Any]],
) -> tuple[bool, Any]:
    try:
        result = await operation()
    except OperationalError as db_err:
        if not _is_deadlock(db_err):
            raise
        await session.rollback()
        return False, db_err
    return True, result


async def with_deadlock_retry(
    session: AsyncSession,
    operation: Callable[[], Coroutine[Any, Any, Any]],
    *,
    operation_name: str = "db_operation",
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    jitter_max: float = DEFAULT_JITTER_MAX,
    context: dict[str, Any] | None = None,
) -> Any:
    if max_retries < 1:
        raise ValueError(f"max_retries must be >= 1, got {max_retries}")
    if base_delay < 0:
        raise ValueError(f"base_delay must be >= 0, got {base_delay}")

    last_error: OperationalError | None = None

    for attempt in range(max_retries):
        success, result = await _attempt_operation(session, operation)

        if success:
            return result

        last_error = result

        if attempt < max_retries - 1:
            backoff = (base_delay * (2**attempt)) + random.uniform(0, jitter_max)
            logger.warning(
                "[DEADLOCK] %s deadlock on attempt %d/%d, retrying in %.3fs",
                operation_name,
                attempt + 1,
                max_retries,
                backoff,
            )
            await asyncio.sleep(backoff)

    logger.error(
        "[DEADLOCK] %s failed after %d retries",
        operation_name,
        max_retries,
        exc_info=last_error,
    )
    raise RetryExhaustedError(
        message=f"Deadlock retry exhausted after {max_retries} attempts",
        context={"operation": operation_name, **(context or {})},
    ) from last_error
