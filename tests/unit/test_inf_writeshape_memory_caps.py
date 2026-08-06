# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-WriteShape: 360-memory write caps + headlines-only fetch + 30K safety net.

TDD-first: these tests are written BEFORE the implementation. They cover the
single shared validator (used by both write_360_memory and
close_project_and_update_memory), the headlines-only default for fetch_context,
and the 30K-char graceful field-drop.

Acceptance criteria (12 tests):
1. summary > 500 chars -> structured rejection
2. > 5 key_outcomes -> rejection
3. key_outcome item > 250 chars -> rejection
4. > 5 decisions_made + item > 250 chars -> rejection
5. unknown tag (not in vocab) -> rejection
6. > 8 tags -> rejection
7. close_project_and_update_memory shares the same oversize rejection (single
   validator)
8. fetch_context(memory_360) default returns headlines-only shape
9. fetch_context(memory_360, depth_config={"memory_360": "full"}) returns full
10. > 30K-char synthetic payload triggers graceful field-drop
11. tenant isolation regression: oversize-write rejection still scoped by
    tenant_key (no info leak across tenants).
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from pydantic import ValidationError as PydanticValidationError

from giljo_mcp.models import Project
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.services.product_memory_service import (
    MemoryEntryWriteSchema,
    MemoryEntryWriteValidationError,
)
from giljo_mcp.tools.context_tools.fetch_context import fetch_context
from giljo_mcp.tools.project_closeout import close_project_and_update_memory
from giljo_mcp.tools.write_memory_entry import write_360_memory


# ---- Fixtures ---------------------------------------------------------------


@pytest_asyncio.fixture
async def linked_project(db_session, test_tenant_key, test_product):
    """A project linked to test_product (write tools require product link)."""
    project = Project(
        id=str(uuid.uuid4()),
        name="INF-WriteShape Project",
        description="Project for write-cap tests",
        mission="Test mission",
        status="active",
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    return project


def _valid_payload(**overrides):
    base = {
        "summary": "A short, valid headline summary.",
        "key_outcomes": ["Outcome A", "Outcome B"],
        "decisions_made": ["Decision A"],
        "deliverables": ["Deliverable A"],
        "tags": ["bug-fix"],
    }
    base.update(overrides)
    return base


# ---- Validator-level tests (pure pydantic, no DB) --------------------------


class TestMemoryEntryWriteSchema:
    """Pydantic-level cap enforcement -- single source of truth."""

    def test_summary_too_long_rejected(self):
        """Test 1: summary > 1500 chars -> structured ValidationError."""
        long_summary = "x" * 1501
        with pytest.raises(PydanticValidationError) as exc_info:
            MemoryEntryWriteSchema(**_valid_payload(summary=long_summary))
        errors = exc_info.value.errors()
        assert any(err["loc"] == ("summary",) for err in errors)

    def test_too_many_key_outcomes_rejected(self):
        """Test 2: > 5 key_outcomes items -> rejection."""
        with pytest.raises(PydanticValidationError) as exc_info:
            MemoryEntryWriteSchema(**_valid_payload(key_outcomes=["a", "b", "c", "d", "e", "f"]))
        assert any(err["loc"][0] == "key_outcomes" for err in exc_info.value.errors())

    def test_oversize_key_outcome_item_rejected(self):
        """Test 3: a single key_outcome > 250 chars -> rejection."""
        with pytest.raises(PydanticValidationError) as exc_info:
            MemoryEntryWriteSchema(**_valid_payload(key_outcomes=["x" * 251]))
        assert any("key_outcomes" in str(err["loc"]) for err in exc_info.value.errors())

    def test_too_many_decisions_or_oversize_item_rejected(self):
        """Test 4: > 5 decisions_made OR item > 250 chars -> rejection."""
        with pytest.raises(PydanticValidationError):
            MemoryEntryWriteSchema(**_valid_payload(decisions_made=["a"] * 6))
        with pytest.raises(PydanticValidationError):
            MemoryEntryWriteSchema(**_valid_payload(decisions_made=["x" * 251]))

    def test_unknown_tag_rejected(self):
        """Test 5: tag failing the controlled vocabulary -> rejection.

        Step A scaffold uses a regex-based vocab (lowercase + digits + hyphen);
        an obviously bad tag like 'BAD TAG!!' must be rejected. After analyzer
        relays the real vocab the regex becomes a Literal[...] enum and this
        test still holds.
        """
        with pytest.raises(PydanticValidationError):
            MemoryEntryWriteSchema(**_valid_payload(tags=["BAD TAG!!"]))

    def test_too_many_tags_rejected(self):
        """Test 6: > 8 tags -> rejection."""
        with pytest.raises(PydanticValidationError):
            MemoryEntryWriteSchema(**_valid_payload(tags=[f"tag-{i}" for i in range(9)]))

    def test_valid_payload_passes(self):
        schema = MemoryEntryWriteSchema(**_valid_payload())
        assert schema.summary == "A short, valid headline summary."
        assert len(schema.tags) == 1


# ---- write_360_memory: structured rejection on oversize summary ------------


@pytest.mark.asyncio
async def test_write_360_memory_oversize_summary_structured_rejection(
    db_session, test_tenant_key, test_product, linked_project
):
    """Test 1 (tool-level): structured error includes field, actual_size, max_size, guidance."""
    mock_db_manager = MagicMock()
    long_summary = "x" * 1843
    # Now > 1500 cap (was > 500); kept at 1843 for readable error sample.

    with (
        patch(
            "giljo_mcp.tools.write_memory_entry._check_and_emit_tuning_staleness",
            new_callable=AsyncMock,
        ),
        pytest.raises(MemoryEntryWriteValidationError) as exc_info,
    ):
        await write_360_memory(
            project_id=str(linked_project.id),
            tenant_key=test_tenant_key,
            summary=long_summary,
            key_outcomes=["A"],
            decisions_made=["B"],
            entry_type="session_handover",
            db_manager=mock_db_manager,
            session=db_session,
        )

    err = exc_info.value
    assert err.error == "validation_failed"
    assert err.field == "summary"
    assert err.actual_size == 1843
    assert err.max_size == 1500
    assert "trim" in err.guidance.lower() or "headline" in err.guidance.lower()


# ---- close_project_and_update_memory: shared validator ---------------------


@pytest.mark.asyncio
async def test_close_project_and_update_memory_shares_validator(
    db_session, test_tenant_key, test_product, linked_project
):
    """Test 7: close_project_and_update_memory rejects the same oversize summary.

    Confirms a SINGLE validated write path (no parallel branch).
    """
    mock_db_manager = MagicMock()
    long_summary = "y" * 1600

    with pytest.raises(MemoryEntryWriteValidationError) as exc_info:
        await close_project_and_update_memory(
            project_id=str(linked_project.id),
            summary=long_summary,
            key_outcomes=["A"],
            decisions_made=["B"],
            tenant_key=test_tenant_key,
            db_manager=mock_db_manager,
            session=db_session,
            force=True,  # bypass agent-readiness gate
        )

    assert exc_info.value.field == "summary"
    assert exc_info.value.max_size == 1500


# ---- fetch_context: headlines-only default + opt-in full -------------------


@pytest.mark.asyncio
async def test_fetch_context_memory_360_default_is_headlines(db_session, test_tenant_key, test_product, linked_project):
    """Test 8: default fetch_context(memory_360) returns headlines-only shape."""
    # Seed one rich entry
    long_summary = "L" * 500  # full write-cap length, must come back uncut
    entry = ProductMemoryEntry(
        id=str(uuid.uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        project_id=linked_project.id,
        sequence=1,
        entry_type="project_closeout",
        source="test",
        timestamp=datetime.now(UTC),
        project_name=linked_project.name,
        summary=long_summary,
        key_outcomes=["k1", "k2"],
        decisions_made=["d1"],
        git_commits=[],
        deliverables=["d-A"],
        metrics={},
        priority=2,
        significance_score=0.5,
        token_estimate=100,
        tags=["bug-fix"],
    )
    db_session.add(entry)
    await db_session.commit()

    mock_db_manager = MagicMock()
    mock_db_manager.get_session_async = MagicMock()
    mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=db_session)
    mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await fetch_context(
        product_id=str(test_product.id),
        tenant_key=test_tenant_key,
        categories=["memory_360"],
        db_manager=mock_db_manager,
    )

    memory_data = result["data"]["memory_360"]
    assert len(memory_data) >= 1
    item = memory_data[0]
    # Headlines shape: identity fields + full summary + tags + has_full_body flag
    assert "id" in item
    assert "sequence" in item
    assert "project_name" in item
    assert "type" in item
    assert "timestamp" in item
    assert "tags" in item
    # Headlines no longer truncate -- full summary is emitted verbatim and the
    # has_full_body flag signals that a shape="full" follow-up returns more fields.
    assert item["has_full_body"] is True
    assert item["summary"] == long_summary
    # Body fields excluded in headlines mode
    assert "key_outcomes" not in item
    assert "decisions_made" not in item
    assert "git_commits" not in item


@pytest.mark.asyncio
async def test_fetch_context_memory_360_full_opt_in(db_session, test_tenant_key, test_product, linked_project):
    """Test 9: depth_config={"memory_360": "full"} returns full bodies."""
    long_summary = "Z" * 500
    entry = ProductMemoryEntry(
        id=str(uuid.uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        project_id=linked_project.id,
        sequence=1,
        entry_type="project_closeout",
        source="test",
        timestamp=datetime.now(UTC),
        project_name=linked_project.name,
        summary=long_summary,
        key_outcomes=["k1"],
        decisions_made=["d1"],
        git_commits=[],
        deliverables=["dlv"],
        metrics={},
        priority=2,
        significance_score=0.5,
        token_estimate=100,
        tags=["bug-fix"],
    )
    db_session.add(entry)
    await db_session.commit()

    mock_db_manager = MagicMock()
    mock_db_manager.get_session_async = MagicMock()
    mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=db_session)
    mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await fetch_context(
        product_id=str(test_product.id),
        tenant_key=test_tenant_key,
        categories=["memory_360"],
        depth_config={"memory_360": "full"},
        db_manager=mock_db_manager,
    )

    memory_data = result["data"]["memory_360"]
    item = memory_data[0]
    assert item["has_full_body"] is False
    assert item["summary"] == long_summary  # full body, complete
    assert "key_outcomes" in item
    assert "decisions_made" in item


# ---- 30K char ceiling: graceful field-drop ---------------------------------


@pytest.mark.asyncio
async def test_fetch_context_30k_char_ceiling_graceful_drop(db_session, test_tenant_key, test_product, linked_project):
    """Test 10: > 30K-char synthetic full payload triggers graceful field-drop.

    Result must be <= 30K chars, dropped entries marked truncated:true, and
    metadata.truncation_applied:true is set.
    """
    # 5 huge entries (each ~10K chars in summary alone) -> well over 30K total
    big_summary = "S" * 10000
    big_outcome = ["O" * 200] * 5
    big_decisions = ["D" * 250] * 5

    for i in range(5):
        entry = ProductMemoryEntry(
            id=str(uuid.uuid4()),
            tenant_key=test_tenant_key,
            product_id=test_product.id,
            project_id=linked_project.id,
            sequence=i + 1,
            entry_type="project_closeout",
            source="test",
            timestamp=datetime.now(UTC),
            project_name=f"{linked_project.name}-{i}",
            summary=big_summary,
            key_outcomes=big_outcome,
            decisions_made=big_decisions,
            git_commits=[],
            deliverables=["d"],
            metrics={},
            priority=2,
            significance_score=0.5,
            token_estimate=2500,
            tags=["bug-fix"],
        )
        db_session.add(entry)
    await db_session.commit()

    mock_db_manager = MagicMock()
    mock_db_manager.get_session_async = MagicMock()
    mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=db_session)
    mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await fetch_context(
        product_id=str(test_product.id),
        tenant_key=test_tenant_key,
        categories=["memory_360"],
        depth_config={"memory_360": "full"},
        db_manager=mock_db_manager,
    )

    import json

    serialized = json.dumps(result)
    assert len(serialized) <= 30000, f"Response exceeded 30K cap: {len(serialized)} chars"
    assert result["metadata"].get("truncation_applied") is True
    assert "30K" in str(result["metadata"].get("truncation_reason", "")) or "ceiling" in str(
        result["metadata"].get("truncation_reason", "")
    )
    # At least one entry must be marked truncated
    assert any(item.get("truncated") is True for item in result["data"]["memory_360"])


# ---- Tenant isolation regression -------------------------------------------


@pytest.mark.asyncio
async def test_oversize_write_rejection_does_not_leak_other_tenants(
    db_session, test_tenant_key, test_product, linked_project
):
    """Test 12: oversize-write rejection still filters by tenant_key (no leak).

    The rejected error must contain ONLY the calling tenant's identifier (or
    no tenant info at all), never another tenant's project_id or product_id.
    """
    mock_db_manager = MagicMock()
    long_summary = "x" * 1600
    other_tenant = "tk_OTHER_TENANT_NEVER_TOUCH"

    with pytest.raises(MemoryEntryWriteValidationError) as exc_info:
        await write_360_memory(
            project_id=str(linked_project.id),
            tenant_key=test_tenant_key,
            summary=long_summary,
            key_outcomes=["A"],
            decisions_made=["B"],
            entry_type="session_handover",
            db_manager=mock_db_manager,
            session=db_session,
        )

    msg = str(exc_info.value.guidance) + str(exc_info.value.field)
    assert other_tenant not in msg


# ---- Step C: controlled tag vocabulary (16 tags, two-axis + 1) -------------


class TestControlledTagVocabulary:
    """Step C: write-side vocabulary enforcement (analyzer-ratified 2026-04-25)."""

    def test_excluded_edition_tag_saas_rejected(self):
        """saas is deliberately NOT in vocab -- writes must be rejected."""
        with pytest.raises(PydanticValidationError):
            MemoryEntryWriteSchema(**_valid_payload(tags=["saas"]))

    def test_vocab_tag_feature_accepted(self):
        schema = MemoryEntryWriteSchema(**_valid_payload(tags=["feature"]))
        assert schema.tags == ["feature"]

    def test_vocab_tag_backend_accepted(self):
        schema = MemoryEntryWriteSchema(**_valid_payload(tags=["backend"]))
        assert schema.tags == ["backend"]

    def test_vocab_tag_bug_fix_accepted(self):
        schema = MemoryEntryWriteSchema(**_valid_payload(tags=["bug-fix"]))
        assert schema.tags == ["bug-fix"]

    def test_vocab_tag_migration_accepted(self):
        schema = MemoryEntryWriteSchema(**_valid_payload(tags=["migration"]))
        assert schema.tags == ["migration"]

    def test_unknown_tag_surfaces_invalid_tag_and_allowed(self):
        """Validator reports the offending tag + the full allowed set.

        Validates the structured rejection contract end-to-end so agents get
        the vocabulary back without a second round-trip.
        """
        from giljo_mcp.services.product_memory_service import validate_memory_entry_write

        with pytest.raises(MemoryEntryWriteValidationError) as exc_info:
            validate_memory_entry_write(_valid_payload(tags=["saas"]))
        err = exc_info.value
        assert err.field == "tags"
        assert err.invalid_tag == "saas"
        assert err.allowed is not None
        # 16-tag vocabulary
        assert len(err.allowed) == 16
        assert "feature" in err.allowed
        assert "migration" in err.allowed
        assert "saas" not in err.allowed


# ---- Step C: deliverables drop-cap (3x100) ---------------------------------


class TestDeliverablesDropCap:
    """Step C: deliverables narrowed from placeholder 10x150 to ratified 3x100."""

    def test_four_deliverables_rejected(self):
        with pytest.raises(PydanticValidationError):
            MemoryEntryWriteSchema(**_valid_payload(deliverables=["a", "b", "c", "d"]))

    def test_oversize_deliverable_item_rejected(self):
        with pytest.raises(PydanticValidationError):
            MemoryEntryWriteSchema(**_valid_payload(deliverables=["x" * 150]))

    def test_three_deliverables_max_size_accepted(self):
        schema = MemoryEntryWriteSchema(**_valid_payload(deliverables=["x" * 100, "y" * 100, "z" * 100]))
        assert len(schema.deliverables) == 3
        assert all(len(d) == 100 for d in schema.deliverables)


# ---- Step C: read-time legacy tag mapping ----------------------------------


class TestLegacyTagMapping:
    """Step C: read-time normalization of legacy tags (analyzer-ratified)."""

    def test_legacy_tags_mapped_filtered_and_deduped(self):
        """service->backend, added->feature, saas->null, from->null; deduped."""
        from giljo_mcp.tools.context_tools.get_360_memory import _apply_legacy_tag_mapping

        result = _apply_legacy_tag_mapping(["service", "added", "saas", "from"])
        assert result == ["backend", "feature"]

    def test_unmapped_legacy_tag_passes_through_unchanged(self):
        """Unknown legacy tags stay readable -- they pre-date the vocabulary."""
        from giljo_mcp.tools.context_tools.get_360_memory import _apply_legacy_tag_mapping

        result = _apply_legacy_tag_mapping(["some-old-tag"])
        assert result == ["some-old-tag"]


# ---- BE-5031: headlines emit the full summary, no mid-sentence truncation --


class TestSerializeHeadlineNoTruncation:
    """BE-5031: _serialize_headline must emit the summary verbatim with the
    has_full_body flag, replacing the legacy truncated/ellipsis behavior."""

    def _entry(self, summary: str):
        from types import SimpleNamespace

        return SimpleNamespace(
            id="11111111-1111-1111-1111-111111111111",
            sequence=1,
            project_name="Proj",
            entry_type="project_closeout",
            timestamp=datetime.now(UTC),
            summary=summary,
            tags=["bug-fix"],
        )

    def test_500_char_summary_returned_uncut(self):
        """A 500-char summary (the schema write cap) round-trips verbatim."""
        from giljo_mcp.tools.context_tools.get_360_memory import _serialize_headline

        long_summary = "L" * 500
        result = _serialize_headline(self._entry(long_summary))
        assert result["summary"] == long_summary
        assert not result["summary"].endswith("...")
        assert result["has_full_body"] is True

    def test_headline_has_full_body_true(self):
        from giljo_mcp.tools.context_tools.get_360_memory import _serialize_headline

        result = _serialize_headline(self._entry("short"))
        assert result["has_full_body"] is True
        assert "truncated" not in result

    def test_full_has_full_body_false(self):
        """_serialize_full emits has_full_body:false (full shape, nothing more)."""
        from giljo_mcp.tools.context_tools.get_360_memory import _serialize_full

        class StubEntry:
            def to_dict(self):
                return {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "summary": "anything",
                    "tags": ["bug-fix"],
                }

        result = _serialize_full(StubEntry())
        assert result["has_full_body"] is False
        assert "truncated" not in result

    # ---- BE-5031 edge cases (verification scope) ---------------------------

    def test_empty_summary_returned_as_empty_string(self):
        """Empty string summary -> headlines returns summary:'' without crash."""
        from giljo_mcp.tools.context_tools.get_360_memory import _serialize_headline

        result = _serialize_headline(self._entry(""))
        assert result["summary"] == ""
        assert result["has_full_body"] is True

    def test_none_summary_coerced_to_empty_string(self):
        """None summary -> headlines coerces to '' (no crash, no None leak)."""
        from giljo_mcp.tools.context_tools.get_360_memory import _serialize_headline

        result = _serialize_headline(self._entry(None))
        assert result["summary"] == ""
        assert result["has_full_body"] is True

    def test_499_char_summary_boundary_returned_uncut(self):
        """One under the write cap: still returned verbatim with no slicing."""
        from giljo_mcp.tools.context_tools.get_360_memory import _serialize_headline

        boundary = "B" * 499
        result = _serialize_headline(self._entry(boundary))
        assert result["summary"] == boundary
        assert len(result["summary"]) == 499

    def test_tags_preserved_through_headline_serializer(self):
        """Canonical tags pass through unchanged in headlines shape."""
        from types import SimpleNamespace

        from giljo_mcp.tools.context_tools.get_360_memory import _serialize_headline

        entry = SimpleNamespace(
            id="33333333-3333-3333-3333-333333333333",
            sequence=2,
            project_name="Proj",
            entry_type="project_closeout",
            timestamp=datetime.now(UTC),
            summary="ok",
            tags=["bug-fix", "backend", "feature"],
        )
        result = _serialize_headline(entry)
        # All three canonical tags survive (no drop, no reorder)
        assert result["tags"] == ["bug-fix", "backend", "feature"]

    def test_tags_preserved_through_full_serializer(self):
        """Canonical tags pass through unchanged in full shape."""
        from giljo_mcp.tools.context_tools.get_360_memory import _serialize_full

        class StubEntry:
            def to_dict(self):
                return {
                    "id": "44444444-4444-4444-4444-444444444444",
                    "summary": "ok",
                    "tags": ["bug-fix", "backend", "feature"],
                }

        result = _serialize_full(StubEntry())
        assert result["tags"] == ["bug-fix", "backend", "feature"]


# ---- BE-5031 regression: ceiling 'truncated' flag and 'has_full_body' coexist


class TestResponseCeilingPreservesHasFullBody:
    """BE-5031 regression: the 30K-char field-drop path in
    _apply_response_ceiling sets entry['truncated']=True for a separate
    concern (field drop) and must not be confused with the renamed
    has_full_body flag from the headlines/full serializers. Both flags must
    be able to coexist on the same entry without one clobbering the other.
    """

    def _build_oversize_response(self) -> dict[str, Any]:
        """Build a memory_360 payload that comfortably exceeds the 30K cap."""
        big_blob = "X" * 8000
        return {
            "data": {
                "memory_360": [
                    {
                        "id": f"00000000-0000-0000-0000-{i:012d}",
                        "sequence": i,
                        "project_name": f"Proj-{i}",
                        "type": "project_closeout",
                        "timestamp": "2026-04-25T00:00:00+00:00",
                        "summary": "S" * 400,
                        "key_outcomes": [big_blob],
                        "decisions_made": [big_blob],
                        "tags": ["bug-fix"],
                        # Mirrors the headline serializer flag -- must survive
                        # the ceiling pass even when other fields are dropped.
                        "has_full_body": True,
                    }
                    for i in range(5)
                ]
            },
            "metadata": {},
        }

    def test_ceiling_sets_truncated_flag_after_field_drop(self):
        """_apply_response_ceiling must set entry['truncated']=True when it
        drops fields, AND must not strip the unrelated has_full_body flag."""
        from giljo_mcp.tools.context_tools._response_ceiling import (
            RESPONSE_CHAR_CEILING,
            _apply_response_ceiling,
        )

        response = self._build_oversize_response()
        out = _apply_response_ceiling(response)

        import json

        assert len(json.dumps(out)) <= RESPONSE_CHAR_CEILING
        assert out["metadata"]["truncation_applied"] is True

        entries = out["data"]["memory_360"]
        # At least one entry got fields dropped -> ceiling-truncated:true set
        assert any(e.get("truncated") is True for e in entries)
        # has_full_body is a separate flag and must still be present
        # on every entry that retained any optional field.
        # (PROTECTED_ENTRY_FIELDS doesn't include has_full_body, but the
        # ceiling only drops the LARGEST droppable field per pass; the
        # tiny boolean must outlive the giant blobs.)
        assert any(e.get("has_full_body") is True for e in entries)

    def test_ceiling_does_not_rename_truncated_to_has_full_body(self):
        """Defensive: prove the rename in get_360_memory.py did NOT bleed
        into the ceiling path. It must still emit the literal
        key 'truncated', not 'has_full_body', when it drops fields."""
        from giljo_mcp.tools.context_tools._response_ceiling import (
            _apply_response_ceiling,
        )

        response = self._build_oversize_response()
        out = _apply_response_ceiling(response)

        entries = out["data"]["memory_360"]
        truncated_entries = [e for e in entries if e.get("truncated") is True]
        # Field-drop must mark with the ORIGINAL 'truncated' key
        assert truncated_entries, "expected at least one entry marked truncated"
        # And the rename must NOT have replaced 'truncated' with 'has_full_body'
        # on the ceiling path (those are unrelated concerns).
        for e in truncated_entries:
            assert "truncated" in e
