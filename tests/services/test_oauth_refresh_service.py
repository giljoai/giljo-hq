# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import hashlib
import re

from giljo_mcp.services.oauth_refresh_service import hash_refresh_token, new_family_id


def test_hash_refresh_token_is_deterministic() -> None:
    raw = "raw-refresh-token-value"
    assert hash_refresh_token(raw) == hash_refresh_token(raw)


def test_hash_refresh_token_ascii_digest_unchanged_by_utf8_encode() -> None:
    raw = "aGVsbG8td29ybGQtcmVmcmVzaC10b2tlbg"
    assert hash_refresh_token(raw) == hashlib.sha256(raw.encode("ascii")).hexdigest()


def test_hash_refresh_token_accepts_non_ascii_without_raising() -> None:
    raw = "réfresh-töken-ünïcode"
    digest = hash_refresh_token(raw)
    assert digest == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{64}", digest), digest


def test_hash_refresh_token_returns_64_hex_chars() -> None:
    digest = hash_refresh_token("any-non-empty-token")
    assert len(digest) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", digest), digest


def test_hash_refresh_token_distinguishes_distinct_inputs() -> None:
    assert hash_refresh_token("alpha") != hash_refresh_token("beta")


def test_new_family_id_is_uuid4_shape() -> None:
    fam = new_family_id()
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", fam), fam


def test_new_family_id_returns_distinct_values() -> None:
    assert new_family_id() != new_family_id()
