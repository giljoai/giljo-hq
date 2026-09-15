# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest

from giljo_mcp.api_key_utils import hash_api_key, verify_api_key
from giljo_mcp.utils.password_helper import async_hash_password


COST_PREFIX = "$2b$12$"
API_KEY_HASH_PREFIX = "sha256$"


@pytest.mark.asyncio
async def test_password_helper_pins_cost_12():
    hashed = await async_hash_password("S3cret-pass!")
    assert hashed.startswith(COST_PREFIX), f"expected {COST_PREFIX!r} prefix, got {hashed[:7]!r}"


def test_api_key_hash_uses_sha256_format():
    hashed = hash_api_key("gk_abc123def456")
    assert hashed.startswith(API_KEY_HASH_PREFIX), f"expected {API_KEY_HASH_PREFIX!r} prefix, got {hashed[:8]!r}"
    assert not hashed.startswith("$2b$"), "API keys must no longer be bcrypt-hashed (BE-6060b)"


def test_api_key_hash_round_trips_through_verify():
    hashed = hash_api_key("gk_roundtrip")
    assert hashed.startswith(API_KEY_HASH_PREFIX)
    assert verify_api_key("gk_roundtrip", hashed) is True
    assert verify_api_key("gk_wrong", hashed) is False
