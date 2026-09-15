# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import importlib




def _reload_app_state_module(monkeypatch, mode_value: str | None = None):
    if mode_value is None:
        monkeypatch.delenv("GILJO_MODE", raising=False)
    else:
        monkeypatch.setenv("GILJO_MODE", mode_value)

    import api.app_state as app_state_module

    importlib.reload(app_state_module)
    return app_state_module




class TestGiljoModeDetection:

    def test_default_mode_is_ce(self, monkeypatch):
        mod = _reload_app_state_module(monkeypatch, mode_value=None)
        assert mod.GILJO_MODE == "ce"

    def test_saas_mode_detected(self, monkeypatch):
        mod = _reload_app_state_module(monkeypatch, "saas")
        assert mod.GILJO_MODE == "saas"

    def test_case_insensitive_saas(self, monkeypatch):
        mod = _reload_app_state_module(monkeypatch, "SAAS")
        assert mod.GILJO_MODE == "saas"

    def test_legacy_demo_no_longer_special_cased(self, monkeypatch):
        mod = _reload_app_state_module(monkeypatch, "demo")
        assert mod.GILJO_MODE == "demo"
        assert mod.GILJO_MODE not in ("ce", "saas")

    def test_ce_mode_explicit(self, monkeypatch):
        mod = _reload_app_state_module(monkeypatch, "ce")
        assert mod.GILJO_MODE == "ce"
