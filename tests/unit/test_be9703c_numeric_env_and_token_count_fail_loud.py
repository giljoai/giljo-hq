# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest


class TestNumericEnv:
    def test_bad_web_concurrency_raises_naming_the_variable(self, monkeypatch):
        from api.startup.database import _worker_count

        monkeypatch.setenv("WEB_CONCURRENCY", "garbage")
        with pytest.raises(ValueError, match="WEB_CONCURRENCY"):
            _worker_count()

    def test_bad_reserved_slots_raises_naming_the_variable(self, monkeypatch):
        from api.startup.database import _reserved_slots

        monkeypatch.setenv("GILJO_DB_RESERVED_SLOTS", "many")
        with pytest.raises(ValueError, match="GILJO_DB_RESERVED_SLOTS"):
            _reserved_slots()

    def test_non_numeric_pool_inputs_raise(self):
        from api.startup.database import check_connection_budget

        with pytest.raises(ValueError, match="pool_size"):
            check_connection_budget(pool_size=object(), max_overflow=10, workers=1, slot_budget=90)


class TestTokenCount:
    def test_special_token_text_is_counted_not_estimated(self):
        from giljo_mcp.context_management.chunker import VisionDocumentChunker

        chunker = VisionDocumentChunker()
        text = "before <|endoftext|> after"
        assert chunker.count_tokens(text) == len(chunker.encoding.encode(text, disallowed_special=()))
        assert chunker.count_tokens(text) != len(text) // 4
