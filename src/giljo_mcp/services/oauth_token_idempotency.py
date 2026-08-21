# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""OAuth /token idempotency-window primitive (API-0021l, INF-5074).

Routes idempotency-window state through the `CacheBackend` registry
(`giljo_mcp.services.cache_backends`). CE installs see the default
`InProcessDictBackend` (single-worker correct). SaaS installs see the
Redis-backed adapter from `giljo_mcp.saas.services.redis_cache_backend`,
which keeps state coherent across uvicorn workers — that swap is the
INF-5074 fix.

Why this exists (observed in production):
ChatGPT's connector backend issues concurrent POST /token from different
Azure egress IPs, on mcp.example.com, using the same auth-code. Spec-strict
single-use enforcement returned 200 for the first and 400 "Authorization
code has already been used" for the second; the connector UI flashed
"Something went wrong" before reading the first response. Auth0/Okta/AWS
Cognito all implement a short idempotency window for confidential clients
to absorb honest retries — this is parity.
"""

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
    """One cached /token response keyed by (tenant_key, code)."""

    response_body: dict
    body_signature: str


def _serialize(entry: IdempotencyEntry) -> str:
    # SEC-9227f (M2a): the JSON contains the raw access+refresh token pair —
    # encrypt it so no readable token material reaches any cache backend
    # (SaaS Redis persistence/MONITOR would otherwise expose live pairs).
    return encrypt_payload(
        json.dumps(
            {
                "response_body": entry.response_body,
                "body_signature": entry.body_signature,
            }
        )
    )


def _deserialize(raw: str) -> dict[str, object] | None:
    # SEC-9227f: an undecryptable entry (tampered, rotated key, stale format)
    # is a cache MISS, never an exception — see _idem_crypto.decrypt_payload.
    plaintext = decrypt_payload(raw)
    if plaintext is None:
        return None
    return json.loads(plaintext)


async def cache_get(tenant_key: str, code: str) -> IdempotencyEntry | None:
    """Return the cached entry for `(tenant_key, code)` from the registered backend.

    The backend's TTL drives expiry; a miss is indistinguishable from a
    lapsed entry, which is the desired semantic.
    """
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
    """Insert `entry` under `(tenant_key, code)` with the configured TTL."""
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
    """SEC-9227e (M2b): durably COMMIT the token issuance, THEN cache it.

    The order is load-bearing — do not swap or split it. Pre-fix, the /token
    cache-put ran inside the still-open request transaction (the endpoint's
    ``get_db_session`` dependency commits only after the handler returns); a
    rollback after that point left the cache holding a phantom pair — an
    in-window retry received tokens the DB does not know, a hard logout at its
    next refresh. Committing first means a cache entry can never outlive a
    rolled-back transaction. Mirrors the /refresh reuse-detection branch's
    explicit commit-before-raise durability precedent (oauth_refresh_service);
    the dependency's own later commit becomes a no-op.

    Called as the LAST statement inside ``tenant_session_context`` so every
    write commits under the scoped ``session.info``/ContextVar; the context
    manager only mutates those markers (no transaction interaction), so
    committing here is safe.
    """
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
    """Canonical body-signature for the /token idempotency check.

    `proof` is the client's proof-of-possession token: code_verifier for
    public PKCE clients, the plaintext client_secret for confidential
    clients. The signature only needs to match across retries from the
    same caller — using whichever value the caller sends keeps the
    comparison deterministic without an extra resolver round-trip.

    The unit-separator byte (\\x1f) prevents ambiguous concatenation when
    adjacent fields would otherwise blend (e.g., ``"abcdef" + "1234"`` vs.
    ``"abc" + "def1234"``).
    """
    h = hashlib.sha256()
    h.update(client_id.encode("utf-8"))
    h.update(_TOKEN_IDEMPOTENCY_FIELD_SEP)
    h.update(proof.encode("utf-8"))
    h.update(_TOKEN_IDEMPOTENCY_FIELD_SEP)
    h.update(redirect_uri.encode("utf-8"))
    return h.hexdigest()
