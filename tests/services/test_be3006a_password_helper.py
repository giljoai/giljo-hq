# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio

import bcrypt
import pytest

from giljo_mcp.utils.password_helper import async_hash_password, async_verify_password


@pytest.mark.asyncio
async def test_hash_then_verify_roundtrip():
    hashed = await async_hash_password("S3cret-pass!")
    assert isinstance(hashed, str)
    assert hashed.startswith("$2")
    assert await async_verify_password("S3cret-pass!", hashed) is True
    assert await async_verify_password("wrong-pass", hashed) is False


@pytest.mark.asyncio
async def test_helper_offloads_bcrypt_via_to_thread(monkeypatch):
    seen: list[str] = []
    real_to_thread = asyncio.to_thread

    async def _spy(fn, *args, **kwargs):
        if fn is bcrypt.hashpw:
            seen.append("hash")
        elif fn is bcrypt.checkpw:
            seen.append("verify")
        return await real_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _spy)

    hashed = await async_hash_password("offload-me")
    assert await async_verify_password("offload-me", hashed) is True

    assert "hash" in seen, "async_hash_password did not offload bcrypt.hashpw via to_thread"
    assert "verify" in seen, "async_verify_password did not offload bcrypt.checkpw via to_thread"


@pytest.mark.asyncio
async def test_helper_interops_with_externally_hashed_value():
    legacy = bcrypt.hashpw(b"legacy-pw", bcrypt.gensalt()).decode("utf-8")
    assert await async_verify_password("legacy-pw", legacy) is True




@pytest.mark.asyncio
async def test_verify_overlong_password_fails_closed():
    hashed = await async_hash_password("S3cret-pass!")
    assert await async_verify_password("A" * 100, hashed) is False


@pytest.mark.asyncio
async def test_verify_overlong_multibyte_password_fails_closed():
    hashed = await async_hash_password("S3cret-pass!")
    assert await async_verify_password("é" * 40, hashed) is False


@pytest.mark.asyncio
async def test_verify_at_72_byte_boundary_still_works():
    password = "B" * 72
    hashed = await async_hash_password(password)
    assert await async_verify_password(password, hashed) is True
    assert await async_verify_password("B" * 71 + "x", hashed) is False


@pytest.mark.asyncio
async def test_verify_malformed_stored_hash_fails_closed():
    assert await async_verify_password("whatever", "not-a-bcrypt-hash") is False
