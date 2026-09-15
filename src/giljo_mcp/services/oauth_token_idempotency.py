# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from giljo_mcp.services._idem_crypto import decrypt_payload, encrypt_payload
from giljo_mcp.services.cache_backends import OAUTH_IDEMPOTENCY_BACKEND_NAME, get_cache_backend


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)

OAUTH_TOKEN_IDEMPOTENCY_WINDOW_SECONDS = int(os.environ.get("OAUTH_TOKEN_IDEMPOTENCY_WINDOW_SECONDS", "5"))
_TOKEN_IDEMPOTENCY_FIELD_SEP = b"\x1f"


@dataclass(frozen=True)
class IdempotencyEntry:

    response_body: dict
    body_signature: str


def _serialize(entry: IdempotencyEntry) -> str:
    return encrypt_payload(
        json.dumps(
            {
                "response_body": entry.response_body,
                "body_signature": entry.body_signature,
            }
        )
    )


def _deserialize(raw: str) -> dict[str, object] | None:
    plaintext = decrypt_payload(raw)
    if plaintext is None:
        return None
    return json.loads(plaintext)


async def cache_get(tenant_key: str, code: str) -> IdempotencyEntry | None:
    backend = get_cache_backend(OAUTH_IDEMPOTENCY_BACKEND_NAME)
    raw = await backend.get(tenant_key, code)
    if raw is None:
        return None
    payload = _deserialize(raw)
    if payload is None:
        return None
    return IdempotencyEntry(
        response_body=dict(payload["response_body"]),  # type: ignore[arg-type]
        body_signature=str(payload["body_signature"]),
    )


async def cache_put(tenant_key: str, code: str, entry: IdempotencyEntry) -> None:
    backend = get_cache_backend(OAUTH_IDEMPOTENCY_BACKEND_NAME)
    await backend.set(
        tenant_key,
        code,
        _serialize(entry),
        ttl_seconds=OAUTH_TOKEN_IDEMPOTENCY_WINDOW_SECONDS,
    )


async def commit_then_cache_pair(
    session: AsyncSession,
    *,
    tenant_key: str,
    code: str,
    response_body: dict,
    body_signature: str,
) -> None:
    await session.commit()
    await cache_put(
        tenant_key,
        code,
        IdempotencyEntry(
            response_body=dict(response_body),
            body_signature=body_signature,
        ),
    )


def compute_body_signature(
    *,
    client_id: str,
    proof: str,
    redirect_uri: str,
) -> str:
    h = hashlib.sha256()
    h.update(client_id.encode("utf-8"))
    h.update(_TOKEN_IDEMPOTENCY_FIELD_SEP)
    h.update(proof.encode("utf-8"))
    h.update(_TOKEN_IDEMPOTENCY_FIELD_SEP)
    h.update(redirect_uri.encode("utf-8"))
    return h.hexdigest()
