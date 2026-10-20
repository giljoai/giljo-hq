# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import AuthenticationError


TermsVersionLookup = Callable[..., Awaitable[str]]
TermsVersionIsCurrent = Callable[[str], bool]

TERMS_REACCEPTANCE_REQUIRED = "TERMS_REACCEPTANCE_REQUIRED"
SESSION_REFRESH_REQUIRED = "SESSION_REFRESH_REQUIRED"


@dataclass(frozen=True)
class _TermsGate:
    lookup: TermsVersionLookup
    is_current: TermsVersionIsCurrent


_gate: _TermsGate | None = None


def register_terms_gate(lookup: TermsVersionLookup, is_current: TermsVersionIsCurrent) -> None:
    global _gate  # noqa: PLW0603
    _gate = _TermsGate(lookup=lookup, is_current=is_current)


def terms_gate_installed() -> bool:
    return _gate is not None


async def session_terms_version(db: AsyncSession, tenant_key: str) -> str | None:
    if _gate is None:
        return None
    return await _gate.lookup(db, tenant_key=tenant_key)


def terms_claim_violation(terms_version: str | None) -> AuthenticationError | None:
    if _gate is None:
        return None
    if terms_version is None:
        return AuthenticationError(
            message="Your session must be renewed before continuing.",
            error_code=SESSION_REFRESH_REQUIRED,
        )
    if not _gate.is_current(terms_version):
        return AuthenticationError(
            message="Updated Terms of Service must be accepted before continuing.",
            error_code=TERMS_REACCEPTANCE_REQUIRED,
        )
    return None
