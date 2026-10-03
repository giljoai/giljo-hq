# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.http.url_resolver import GILJO_PUBLIC_URL_DEFAULT, get_public_url


def test_saas_without_public_url_uses_the_pinned_origin(monkeypatch):
    monkeypatch.setenv("GILJO_MODE", "saas")
    monkeypatch.delenv("GILJO_PUBLIC_URL", raising=False)
    monkeypatch.setenv("GILJO_PUBLIC_BASE_URL", "https://app.example.test/")
    assert get_public_url() == "https://app.example.test"


def test_saas_with_no_origin_at_all_refuses_localhost(monkeypatch):
    monkeypatch.setenv("GILJO_MODE", "saas")
    monkeypatch.delenv("GILJO_PUBLIC_URL", raising=False)
    monkeypatch.delenv("GILJO_PUBLIC_BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="GILJO_PUBLIC"):
        get_public_url()


def test_ce_without_public_url_keeps_the_localhost_default(monkeypatch):
    monkeypatch.setenv("GILJO_MODE", "ce")
    monkeypatch.delenv("GILJO_PUBLIC_URL", raising=False)
    assert get_public_url() == GILJO_PUBLIC_URL_DEFAULT
