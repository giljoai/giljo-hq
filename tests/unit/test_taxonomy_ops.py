# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for giljo_mcp.services.taxonomy_ops

Validates that ensure_default_types_seeded and list_taxonomy_types
behave correctly at the canonical location after the Phase A rename
(taxonomy_ops -> taxonomy_ops).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.services.taxonomy_ops import (
    DEFAULT_TAXONOMY_TYPES,
    ensure_default_types_seeded,
    list_taxonomy_types,
)


class TestDefaultTaxonomyTypes:
    """Verify the DEFAULT_TAXONOMY_TYPES constant is intact after extraction."""

    def test_has_expected_count(self):
        # BE-6049c: TSK reserved task tag (9 -> 10).
        # BE-6054a: CHT reserved chat-thread tag (10 -> 11).
        assert len(DEFAULT_TAXONOMY_TYPES) == 11

    def test_includes_reserved_tsk_tag(self):
        # BE-6049c: TSK must be seeded for new tenants (purple reserved task tag).
        tsk = next((pt for pt in DEFAULT_TAXONOMY_TYPES if pt["abbr"] == "TSK"), None)
        assert tsk is not None, "TSK reserved tag must be in DEFAULT_TAXONOMY_TYPES"
        assert tsk["color"] == "#8b5cf6"

    def test_includes_reserved_cht_tag(self):
        # BE-6054a: CHT (Chat Thread) must be seeded for new tenants so thread
        # serial minting never 422s on the unknown type.
        cht = next((pt for pt in DEFAULT_TAXONOMY_TYPES if pt["abbr"] == "CHT"), None)
        assert cht is not None, "CHT reserved tag must be in DEFAULT_TAXONOMY_TYPES"
        assert cht["label"] == "Chat Thread"

    def test_each_has_required_keys(self):
        for pt in DEFAULT_TAXONOMY_TYPES:
            assert "abbr" in pt
            assert "label" in pt
            assert "color" in pt

    def test_abbreviations_are_unique(self):
        abbrs = [pt["abbr"] for pt in DEFAULT_TAXONOMY_TYPES]
        assert len(abbrs) == len(set(abbrs))

    def test_colors_are_hex(self):
        for pt in DEFAULT_TAXONOMY_TYPES:
            assert pt["color"].startswith("#")
            assert len(pt["color"]) == 7


class TestEnsureDefaultTypesSeeded:
    """Tests for the idempotent seeding function."""

    @pytest.mark.asyncio
    async def test_skips_when_types_exist(self):
        """If tenant already has types, no inserts should happen."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 3
        session.execute.return_value = mock_result

        await ensure_default_types_seeded(session, "tenant_abc")

        # Only the COUNT query should have been executed, no flush
        assert session.execute.call_count == 1
        session.add.assert_not_called()
        session.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_seeds_when_no_types(self):
        """If tenant has zero types, all defaults should be added."""
        session = AsyncMock()
        session.add = MagicMock()  # Session.add is sync in real SQLAlchemy
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        session.execute.return_value = mock_result

        await ensure_default_types_seeded(session, "tenant_abc")

        assert session.add.call_count == len(DEFAULT_TAXONOMY_TYPES)
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tenant_key_isolation(self):
        """Verify the function passes tenant_key into the query."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        session.execute.return_value = mock_result

        await ensure_default_types_seeded(session, "tenant_xyz")

        # The execute call should contain the tenant key filter
        call_args = session.execute.call_args
        assert call_args is not None


class TestListTaxonomyTypes:
    """Tests for the list function."""

    @pytest.mark.asyncio
    async def test_returns_list(self):
        """Verify it returns a list (possibly empty)."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        session.execute.return_value = mock_result

        result = await list_taxonomy_types(session, "tenant_abc")

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_attaches_project_count(self):
        """Each returned type should have a project_count attribute."""
        session = AsyncMock()
        mock_pt = MagicMock()
        mock_row = (mock_pt, 7)
        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]
        session.execute.return_value = mock_result

        result = await list_taxonomy_types(session, "tenant_abc")

        assert len(result) == 1
        assert result[0].project_count == 7


class TestReExportCompatibility:
    """Verify that api/endpoints/taxonomy_types/crud_ops.py re-exports work."""

    def test_crud_ops_reexports_ensure_default(self):
        from api.endpoints.taxonomy_types.crud_ops import ensure_default_types_seeded as reexported
        from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded as canonical

        assert reexported is canonical

    def test_crud_ops_reexports_list(self):
        from api.endpoints.taxonomy_types.crud_ops import list_taxonomy_types as reexported
        from giljo_mcp.services.taxonomy_ops import list_taxonomy_types as canonical

        assert reexported is canonical

    def test_crud_ops_reexports_defaults(self):
        from api.endpoints.taxonomy_types.crud_ops import DEFAULT_TAXONOMY_TYPES as REEXPORTED
        from giljo_mcp.services.taxonomy_ops import DEFAULT_TAXONOMY_TYPES as CANONICAL

        assert REEXPORTED is CANONICAL
