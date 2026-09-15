# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from uuid import UUID, uuid4

from giljo_mcp.services.dto import MemoryEntryCreateParams


class TestMemoryEntryCreateParams:

    def _make_required_kwargs(self):
        return {
            "tenant_key": "tk_testTenantValue1234567890123",
            "product_id": uuid4(),
            "sequence": 1,
            "entry_type": "session_progress",
            "source": "orchestrator",
            "timestamp": datetime.now(tz=UTC),
        }

    def test_create_with_required_fields_only(self):
        params = MemoryEntryCreateParams(**self._make_required_kwargs())

        assert params.tenant_key.startswith("tk_")
        assert isinstance(params.product_id, UUID)
        assert params.sequence == 1
        assert params.entry_type == "session_progress"
        assert params.source == "orchestrator"
        assert isinstance(params.timestamp, datetime)

    def test_optional_fields_default_to_none(self):
        params = MemoryEntryCreateParams(**self._make_required_kwargs())

        assert params.project_id is None
        assert params.project_name is None
        assert params.summary is None
        assert params.key_outcomes is None
        assert params.decisions_made is None
        assert params.git_commits is None
        assert params.deliverables is None
        assert params.metrics is None
        assert params.token_estimate is None
        assert params.tags is None
        assert params.author_job_id is None
        assert params.author_name is None
        assert params.author_type is None

    def test_numeric_defaults(self):
        params = MemoryEntryCreateParams(**self._make_required_kwargs())

        assert params.priority == 3
        assert params.significance_score == 0.5

    def test_all_fields_populated(self):
        project_uuid = uuid4()
        author_uuid = uuid4()
        now = datetime.now(tz=UTC)

        params = MemoryEntryCreateParams(
            tenant_key="tk_fullPopulatedTest12345678901",
            product_id=uuid4(),
            sequence=42,
            entry_type="handover_closeout",
            source="agent",
            timestamp=now,
            project_id=project_uuid,
            project_name="Test Project",
            summary="Completed all tasks",
            key_outcomes=["outcome1", "outcome2"],
            decisions_made=["decision1"],
            git_commits=[{"sha": "abc123", "message": "fix", "author": "bot"}],
            deliverables=["file.py"],
            metrics={"lines_changed": 50},
            priority=1,
            significance_score=0.9,
            token_estimate=500,
            tags=["sprint-002e", "backend"],
            author_job_id=author_uuid,
            author_name="implementer",
            author_type="agent",
        )

        assert params.project_id == project_uuid
        assert params.project_name == "Test Project"
        assert params.summary == "Completed all tasks"
        assert len(params.key_outcomes) == 2
        assert params.decisions_made == ["decision1"]
        assert params.git_commits[0]["sha"] == "abc123"
        assert params.deliverables == ["file.py"]
        assert params.metrics["lines_changed"] == 50
        assert params.priority == 1
        assert params.significance_score == 0.9
        assert params.token_estimate == 500
        assert params.tags == ["sprint-002e", "backend"]
        assert params.author_job_id == author_uuid
        assert params.author_name == "implementer"
        assert params.author_type == "agent"

    def test_missing_required_field_raises_type_error(self):
        import pytest

        with pytest.raises(TypeError):
            MemoryEntryCreateParams(
                tenant_key="tk_testValue12345678901234567",
                product_id=uuid4(),
                sequence=1,
                entry_type="session_progress",
                source="orchestrator",
            )

    def test_field_count_regression_guard(self):
        import dataclasses

        fields = dataclasses.fields(MemoryEntryCreateParams)
        assert len(fields) == 21, (
            f"Expected 21 fields on MemoryEntryCreateParams, got {len(fields)}. "
            "If a field was added or removed, update this test."
        )

    def test_product_id_accepts_uuid_object(self):
        pid = uuid4()
        params = MemoryEntryCreateParams(
            tenant_key="tk_uuidTypeTest12345678901234567",
            product_id=pid,
            sequence=1,
            entry_type="session_progress",
            source="test",
            timestamp=datetime.now(tz=UTC),
        )
        assert params.product_id == pid
        assert isinstance(params.product_id, UUID)
