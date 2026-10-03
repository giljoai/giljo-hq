# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from tests.helpers.model_factories import (
    make_product,
    make_product_memory_entry,
    make_project,
)


def create_mock_db_session(project_mock, product_mock):
    mock_session = AsyncMock()
    mock_db_manager = MagicMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_session
    mock_cm.__aexit__.return_value = False
    mock_db_manager.get_session_async.return_value = mock_cm

    call_counter = {"count": 0}

    async def mock_execute_side_effect(*args, **kwargs):
        mock_result = MagicMock()
        if call_counter["count"] == 0:
            mock_result.scalar_one_or_none.return_value = project_mock
        else:
            mock_result.scalar_one_or_none.return_value = product_mock

        call_counter["count"] += 1
        return mock_result

    mock_session.execute.side_effect = mock_execute_side_effect
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.info = {}

    return mock_session, mock_db_manager


@pytest.fixture(autouse=True)
def _solo_chain_member():

    class _GitOff:
        def __init__(self, session, tenant_key):
            pass

        async def get_setting_value(self, category, key, default=None):
            return {"enabled": False}

    with (
        patch("giljo_mcp.tools._closeout_finalize.mark_chain_member_status", AsyncMock(return_value=False)),
        patch("giljo_mcp.services.settings_service.SettingsService", _GitOff),
    ):
        yield


@pytest.fixture
def sample_product_id():
    return uuid4()


@pytest.fixture
def sample_project_id():
    return uuid4()


@pytest.fixture
def tenant_key():
    return f"tk_{uuid4().hex}"


@pytest.fixture
def mock_product(sample_product_id, tenant_key):
    product = make_product(
        id=sample_product_id,
        tenant_key=tenant_key,
        name="Test Product",
        updated_at=datetime.now(UTC),
        product_memory={
            "git_integration": {
                "enabled": False,
            },
            "sequential_history": [],
            "context": {},
        },
    )
    return product


@pytest.fixture
def mock_project(sample_project_id, sample_product_id, tenant_key):
    return make_project(
        id=sample_project_id,
        product_id=sample_product_id,
        tenant_key=tenant_key,
        name="Test Project Alpha",
        mission="Test mission",
        status="completed",
        created_at=datetime(2025, 11, 1, 10, 0, 0, tzinfo=UTC),
        completed_at=datetime(2025, 11, 16, 10, 0, 0, tzinfo=UTC),
        updated_at=datetime(2025, 11, 16, 10, 0, 0, tzinfo=UTC),
        early_termination=False,
    )


@pytest.fixture
def mock_memory_entry():
    return make_product_memory_entry(
        id=uuid4(),
        sequence=1,
        entry_type="project_closeout",
        source="closeout_v1",
    )


class TestRepositoryIntegration:

    @pytest.mark.asyncio
    async def test_uses_repository_get_next_sequence(self, mock_product, mock_project, tenant_key, mock_memory_entry):
        from giljo_mcp.tools.project_closeout import close_project_and_update_memory

        mock_session, mock_db_manager = create_mock_db_session(mock_project, mock_product)

        with patch("giljo_mcp.tools.project_closeout.ProductMemoryService") as mock_svc_class:
            mock_repo = MagicMock()
            mock_svc_class.return_value = mock_repo
            mock_repo.get_next_sequence = AsyncMock(return_value=5)
            mock_repo.get_closeout_entry_for_project = AsyncMock(return_value=None)
            mock_repo.create_entry = AsyncMock(return_value=mock_memory_entry)

            result = await close_project_and_update_memory(
                project_id=str(mock_project.id),
                summary="Implemented user authentication with JWT",
                key_outcomes=["Secure token storage", "Refresh token rotation"],
                decisions_made=["Chose JWT over sessions"],
                tenant_key=tenant_key,
                db_manager=mock_db_manager,
            )

            mock_repo.get_next_sequence.assert_called_once_with(session=mock_session, product_id=mock_product.id)
            assert "entry_id" in result
            assert "message" in result
            assert result["sequence_number"] == 5

    @pytest.mark.asyncio
    async def test_uses_repository_create_entry(self, mock_product, mock_project, tenant_key, mock_memory_entry):
        from giljo_mcp.tools.project_closeout import close_project_and_update_memory

        mock_session, mock_db_manager = create_mock_db_session(mock_project, mock_product)

        with patch("giljo_mcp.tools.project_closeout.ProductMemoryService") as mock_svc_class:
            mock_repo = MagicMock()
            mock_svc_class.return_value = mock_repo
            mock_repo.get_next_sequence = AsyncMock(return_value=3)
            mock_repo.get_closeout_entry_for_project = AsyncMock(return_value=None)
            mock_repo.create_entry = AsyncMock(return_value=mock_memory_entry)

            await close_project_and_update_memory(
                project_id=str(mock_project.id),
                summary="Test summary",
                key_outcomes=["Outcome 1", "Outcome 2"],
                decisions_made=["Decision 1"],
                tenant_key=tenant_key,
                db_manager=mock_db_manager,
            )

            mock_repo.create_entry.assert_called_once()
            call_kwargs = mock_repo.create_entry.call_args[1]

            assert call_kwargs["session"] == mock_session
            params = call_kwargs["params"]
            assert params.tenant_key == tenant_key
            assert params.product_id == mock_product.id
            assert params.project_id == mock_project.id
            assert params.sequence == 3
            assert params.entry_type == "project_closeout"
            assert params.source == "closeout_v1"
            assert params.project_name == "Test Project Alpha"
            assert params.summary == "Test summary"
            assert params.key_outcomes == ["Outcome 1", "Outcome 2"]
            assert params.decisions_made == ["Decision 1"]
            assert params.timestamp is not None
            assert params.deliverables is None
            assert params.metrics is not None
            assert params.priority is not None
            assert params.significance_score is not None
            assert params.token_estimate is not None
            assert params.tags is not None

    @pytest.mark.asyncio
    async def test_does_not_mutate_jsonb_sequential_history(
        self, mock_product, mock_project, tenant_key, mock_memory_entry
    ):
        from giljo_mcp.tools.project_closeout import close_project_and_update_memory

        _mock_session, mock_db_manager = create_mock_db_session(mock_project, mock_product)

        initial_history = mock_product.product_memory["sequential_history"].copy()

        with patch("giljo_mcp.tools.project_closeout.ProductMemoryService") as mock_svc_class:
            mock_repo = MagicMock()
            mock_svc_class.return_value = mock_repo
            mock_repo.get_next_sequence = AsyncMock(return_value=1)
            mock_repo.get_closeout_entry_for_project = AsyncMock(return_value=None)
            mock_repo.create_entry = AsyncMock(return_value=mock_memory_entry)

            await close_project_and_update_memory(
                project_id=str(mock_project.id),
                summary="Test summary",
                key_outcomes=["Outcome 1"],
                decisions_made=["Decision 1"],
                tenant_key=tenant_key,
                db_manager=mock_db_manager,
            )

            assert mock_product.product_memory["sequential_history"] == initial_history
            assert len(mock_product.product_memory["sequential_history"]) == 0

    @pytest.mark.asyncio
    async def test_return_includes_entry_id(self, mock_product, mock_project, tenant_key):
        from giljo_mcp.tools.project_closeout import close_project_and_update_memory

        _mock_session, mock_db_manager = create_mock_db_session(mock_project, mock_product)

        entry_id = uuid4()
        mock_entry = make_product_memory_entry(id=entry_id, sequence=1)

        with patch("giljo_mcp.tools.project_closeout.ProductMemoryService") as mock_svc_class:
            mock_repo = MagicMock()
            mock_svc_class.return_value = mock_repo
            mock_repo.get_next_sequence = AsyncMock(return_value=1)
            mock_repo.get_closeout_entry_for_project = AsyncMock(return_value=None)
            mock_repo.create_entry = AsyncMock(return_value=mock_entry)

            result = await close_project_and_update_memory(
                project_id=str(mock_project.id),
                summary="Test summary",
                key_outcomes=["Outcome 1"],
                decisions_made=["Decision 1"],
                tenant_key=tenant_key,
                db_manager=mock_db_manager,
            )

            assert result["entry_id"] == str(entry_id)
            assert result["sequence_number"] == 1
            assert "message" in result

    @pytest.mark.asyncio
    async def test_all_field_mappings_preserved(self, mock_product, mock_project, tenant_key, mock_memory_entry):
        from giljo_mcp.tools.project_closeout import close_project_and_update_memory

        _mock_session, mock_db_manager = create_mock_db_session(mock_project, mock_product)

        mock_product.product_memory["git_integration"] = {
            "enabled": True,
            "repo_name": "test-repo",
            "repo_owner": "test-owner",
        }

        with patch("giljo_mcp.tools.project_closeout.ProductMemoryService") as mock_svc_class:
            mock_repo = MagicMock()
            mock_svc_class.return_value = mock_repo
            mock_repo.get_next_sequence = AsyncMock(return_value=1)
            mock_repo.get_closeout_entry_for_project = AsyncMock(return_value=None)
            mock_repo.create_entry = AsyncMock(return_value=mock_memory_entry)

            await close_project_and_update_memory(
                project_id=str(mock_project.id),
                summary="Comprehensive test summary with details",
                key_outcomes=["Outcome A", "Outcome B", "Outcome C"],
                decisions_made=["Decision X", "Decision Y"],
                tags=["refactor", "backend"],
                git_commits=[{"sha": "abc123", "message": "Test commit", "date": "2025-11-15T10:00:00Z"}],
                tenant_key=tenant_key,
                db_manager=mock_db_manager,
            )

            call_kwargs = mock_repo.create_entry.call_args[1]
            params = call_kwargs["params"]

            assert len(params.git_commits) == 1
            assert params.git_commits[0]["sha"] == "abc123"

            assert params.deliverables is None

            assert "commits" in params.metrics
            assert params.metrics["commits"] == 1
            assert params.metrics["test_coverage"] == 0.0

            assert params.priority == 2

            assert 0.0 <= params.significance_score <= 1.0

            assert params.token_estimate > 0

            assert params.tags == ["refactor", "backend"]

    @pytest.mark.asyncio
    async def test_git_commits_empty_when_disabled(self, mock_product, mock_project, tenant_key, mock_memory_entry):
        from giljo_mcp.tools.project_closeout import close_project_and_update_memory

        _mock_session, mock_db_manager = create_mock_db_session(mock_project, mock_product)

        with patch("giljo_mcp.tools.project_closeout.ProductMemoryService") as mock_svc_class:
            mock_repo = MagicMock()
            mock_svc_class.return_value = mock_repo
            mock_repo.get_next_sequence = AsyncMock(return_value=1)
            mock_repo.get_closeout_entry_for_project = AsyncMock(return_value=None)
            mock_repo.create_entry = AsyncMock(return_value=mock_memory_entry)

            await close_project_and_update_memory(
                project_id=str(mock_project.id),
                summary="Test summary",
                key_outcomes=["Outcome 1"],
                decisions_made=["Decision 1"],
                tenant_key=tenant_key,
                db_manager=mock_db_manager,
            )

            call_kwargs = mock_repo.create_entry.call_args[1]
            params = call_kwargs["params"]
            assert params.git_commits == []
