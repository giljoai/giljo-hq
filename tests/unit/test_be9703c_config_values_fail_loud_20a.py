# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest


def test_mistyped_log_level_is_refused(monkeypatch):
    from giljo_mcp import logging as giljo_logging

    monkeypatch.setattr(giljo_logging._LoggingState, "configured", False)
    monkeypatch.setenv("LOG_LEVEL", "DEBG")
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        giljo_logging.configure_logging()
