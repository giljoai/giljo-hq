# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError




TENANT_KEY = "test-tenant-key"
PRODUCT_ID = "prod-001"
USER_ID = "user-001"


@pytest.fixture
def mock_db_manager():
    db_manager = Mock()
    session = AsyncMock()
    session.info = {}

    async_cm = AsyncMock()
    async_cm.__aenter__ = AsyncMock(return_value=session)
    async_cm.__aexit__ = AsyncMock(return_value=False)

    db_manager.get_session_async = Mock(return_value=async_cm)

    return db_manager, session


@pytest.fixture
def mock_websocket_manager():
    ws_manager = AsyncMock()
    ws_manager.broadcast_to_tenant = AsyncMock()
    return ws_manager


@pytest.fixture
def sample_product():
    product = Mock()
    product.id = PRODUCT_ID
    product.tenant_key = TENANT_KEY
    product.name = "Giljo HQ"
    product.description = "An AI agent orchestration platform"
    product.quality_standards = "80% test coverage, all endpoints tested"
    product.target_platforms = ["windows", "linux"]
    product.core_features = "Agent orchestration, project management, 360 memory"
    product.deleted_at = None

    tech_stack = Mock()
    tech_stack.programming_languages = "Python 3.12"
    tech_stack.frontend_frameworks = "Vue 3"
    tech_stack.backend_frameworks = "FastAPI"
    tech_stack.databases_storage = "PostgreSQL"
    tech_stack.infrastructure = ""
    tech_stack.dev_tools = ""
    product.tech_stack = tech_stack

    architecture = Mock()
    architecture.primary_pattern = "Monolithic backend with REST API"
    architecture.design_patterns = "Repository, Service"
    architecture.api_style = "REST"
    architecture.architecture_notes = ""
    product.architecture = architecture

    test_config = Mock()
    test_config.quality_standards = "80% test coverage, all endpoints tested"
    test_config.test_strategy = "TDD"
    test_config.coverage_target = 80
    test_config.testing_frameworks = "pytest"
    product.test_config = test_config

    product.product_memory = {
        "github": {},
        "context": {},
        "git_integration": {
            "enabled": True,
            "commit_limit": 25,
            "default_branch": "master",
        },
    }
    product.tuning_state = None
    return product


@pytest.fixture
def sample_memory_entries():
    entries = []
    for i in range(3):
        entry = {
            "sequence": i + 1,
            "summary": f"Project {i + 1} summary: implemented feature {chr(65 + i)}",
            "key_outcomes": [f"Outcome {i + 1}.1", f"Outcome {i + 1}.2"],
            "decisions_made": [f"Decision {i + 1}: chose approach {chr(65 + i)}"],
            "deliverables": [f"deliverable_{i + 1}.py"],
            "git_commits": [{"sha": f"abc{i}", "message": f"feat: feature {chr(65 + i)}", "date": f"2026-03-{15 + i}"}],
            "tags": ["closeout"],
            "project_name": f"Project {i + 1}",
            "timestamp": datetime(2026, 3, 15 + i, tzinfo=UTC).isoformat(),
        }
        entries.append(entry)
    return entries


@pytest.fixture
def sample_user_settings():
    toggle_config = {
        "version": "4.0",
        "priorities": {
            "product_core": {"toggle": True},
            "project_description": {"toggle": True},
            "memory_360": {"toggle": True},
            "tech_stack": {"toggle": True},
            "testing": {"toggle": True},
            "vision_documents": {"toggle": True},
            "architecture": {"toggle": True},
            "agent_templates": {"toggle": True},
            "git_history": {"toggle": False},
        },
    }
    depth_config = {
        "vision_documents": "medium",
        "memory_last_n_projects": 3,
        "git_commits": 25,
        "agent_templates": "basic",
        "tech_stack_sections": "all",
        "architecture_depth": "overview",
    }
    return toggle_config, depth_config




class TestAssembleTuningPromptSections:

    @pytest.mark.asyncio
    async def test_includes_only_selected_sections_in_prompt(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_user_settings
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with patch.object(service, "_get_user_configs", new_callable=AsyncMock, return_value=sample_user_settings):
            result = await service.assemble_tuning_prompt(
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                sections=["tech_stack", "description"],
            )

        assert "prompt" in result
        assert "sections_included" in result
        assert set(result["sections_included"]) == {"tech_stack", "description"}

    @pytest.mark.asyncio
    async def test_excludes_unselected_sections_from_prompt(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_user_settings
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with patch.object(service, "_get_user_configs", new_callable=AsyncMock, return_value=sample_user_settings):
            result = await service.assemble_tuning_prompt(
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                sections=["description"],
            )

        assert "architecture" not in result["sections_included"]
        assert "tech_stack" not in result["sections_included"]

    @pytest.mark.asyncio
    async def test_prompt_contains_product_id(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_user_settings
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with patch.object(service, "_get_user_configs", new_callable=AsyncMock, return_value=sample_user_settings):
            result = await service.assemble_tuning_prompt(
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                sections=["tech_stack"],
            )

        assert PRODUCT_ID in result["prompt"]

    @pytest.mark.asyncio
    async def test_prompt_contains_product_name(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_user_settings
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with patch.object(service, "_get_user_configs", new_callable=AsyncMock, return_value=sample_user_settings):
            result = await service.assemble_tuning_prompt(
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                sections=["description"],
            )

        assert sample_product.name in result["prompt"]

    @pytest.mark.asyncio
    async def test_prompt_contains_four_phases(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_user_settings
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with patch.object(service, "_get_user_configs", new_callable=AsyncMock, return_value=sample_user_settings):
            result = await service.assemble_tuning_prompt(
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                sections=["description"],
            )

        prompt = result["prompt"]
        assert "Phase 1: RESEARCH" in prompt
        assert "Phase 2: QUICK SCAN" in prompt
        assert "Phase 3: INTERACTIVE REVIEW" in prompt
        assert "Phase 4: SUBMIT" in prompt

    @pytest.mark.asyncio
    async def test_prompt_reframe_carries_hard_rule_and_verdict_vocabulary(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_user_settings
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with patch.object(service, "_get_user_configs", new_callable=AsyncMock, return_value=sample_user_settings):
            result = await service.assemble_tuning_prompt(
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                sections=["description"],
            )

        prompt = result["prompt"]
        assert "STATE + INTENT" in prompt
        assert "BUILT, ADDED, or CHANGED" in prompt
        assert "reviewing a product's stored context for accuracy" not in prompt
        assert "Code-authoritative" in prompt
        assert "Intent-bearing" in prompt
        assert "NEVER propose removing an item merely because it is not in the code yet" in prompt
        assert "planned — not yet built" in prompt
        assert "**Verdict:**" in prompt
        assert "ADDED" in prompt
        assert "CONTRADICTION" in prompt
        assert "INTENT" in prompt
        assert "**Drift detected:** Yes / No" not in prompt

    @pytest.mark.asyncio
    async def test_prompt_test_discovery_step_is_multi_ecosystem(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_user_settings
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with patch.object(service, "_get_user_configs", new_callable=AsyncMock, return_value=sample_user_settings):
            result = await service.assemble_tuning_prompt(
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                sections=["description"],
            )

        prompt = result["prompt"]
        assert "pytest" not in prompt
        assert "4. Tests:" in prompt
        assert "test-discovery/listing command" in prompt
        assert "go test -list ." in prompt
        assert "requirements.txt (or package.json, go.mod, etc.)" in prompt




class TestAssembleTuningPromptToggles:

    @pytest.mark.asyncio
    async def test_filters_out_sections_with_toggled_off_parent(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_memory_entries
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        settings_arch_off = (
            {
                "version": "4.0",
                "priorities": {
                    "product_core": {"toggle": True},
                    "tech_stack": {"toggle": True},
                    "architecture": {"toggle": False},
                    "testing": {"toggle": True},
                    "memory_360": {"toggle": True},
                    "vision_documents": {"toggle": True},
                    "git_history": {"toggle": False},
                    "agent_templates": {"toggle": True},
                    "project_description": {"toggle": True},
                },
            },
            {"memory_last_n_projects": 3, "git_commits": 25},
        )

        with patch.object(service, "_get_user_configs", new_callable=AsyncMock, return_value=settings_arch_off):
            result = await service.assemble_tuning_prompt(
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                sections=["architecture", "core_features", "tech_stack"],
            )

        assert "architecture" not in result["sections_included"]
        assert "core_features" not in result["sections_included"]
        assert "tech_stack" in result["sections_included"]

    @pytest.mark.asyncio
    async def test_all_toggles_off_returns_empty_sections(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_memory_entries
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        all_off = (
            {
                "version": "4.0",
                "priorities": {
                    "product_core": {"toggle": False},
                    "tech_stack": {"toggle": False},
                    "architecture": {"toggle": False},
                    "testing": {"toggle": False},
                    "memory_360": {"toggle": False},
                    "vision_documents": {"toggle": False},
                    "git_history": {"toggle": False},
                    "agent_templates": {"toggle": False},
                    "project_description": {"toggle": False},
                },
            },
            {"memory_last_n_projects": 3},
        )

        with (
            patch.object(service, "_get_user_configs", new_callable=AsyncMock, return_value=all_off),
            pytest.raises(ValidationError),
        ):
            await service.assemble_tuning_prompt(
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                sections=["description", "tech_stack", "architecture"],
            )




class TestAssembleTuningPromptV2Features:

    @pytest.mark.asyncio
    async def test_prompt_instructs_agent_to_fetch_context_via_mcp(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_user_settings
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with patch.object(service, "_get_user_configs", new_callable=AsyncMock, return_value=sample_user_settings):
            result = await service.assemble_tuning_prompt(
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                sections=["description"],
            )

        assert "get_context" in result["prompt"]
        assert "memory_360" in result["prompt"]

    @pytest.mark.asyncio
    async def test_includes_vision_note_when_vision_documents_selected(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_user_settings
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        toggle_config, depth_config = sample_user_settings
        with (
            patch.object(
                service, "_get_user_configs", new_callable=AsyncMock, return_value=(toggle_config, depth_config)
            ),
            patch.object(service, "_get_eligible_sections", return_value=["description", "vision_documents"]),
        ):
            result = await service.assemble_tuning_prompt(
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                sections=["description", "vision_documents"],
            )

        assert "Vision Documents are historical records" in result["prompt"]

    @pytest.mark.asyncio
    async def test_omits_vision_note_when_vision_documents_not_selected(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_user_settings
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with patch.object(service, "_get_user_configs", new_callable=AsyncMock, return_value=sample_user_settings):
            result = await service.assemble_tuning_prompt(
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                sections=["description"],
            )

        assert "Vision Documents are historical records" not in result["prompt"]

    @pytest.mark.asyncio
    async def test_returns_correct_structure(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_user_settings
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with patch.object(service, "_get_user_configs", new_callable=AsyncMock, return_value=sample_user_settings):
            result = await service.assemble_tuning_prompt(
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                sections=["description", "tech_stack"],
            )

        assert isinstance(result["prompt"], str)
        assert isinstance(result["sections_included"], list)
        assert result["lookback_depth"] is None
        assert result["git_enabled"] is False

    @pytest.mark.asyncio
    async def test_prompt_includes_interactive_wait_instruction(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_user_settings
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with patch.object(service, "_get_user_configs", new_callable=AsyncMock, return_value=sample_user_settings):
            result = await service.assemble_tuning_prompt(
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                sections=["description"],
            )

        assert "Wait for user approval" in result["prompt"]




class TestAssembleTuningPromptErrors:

    @pytest.mark.asyncio
    async def test_raises_not_found_when_product_missing(self, mock_db_manager, mock_websocket_manager):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))

        with pytest.raises(ResourceNotFoundError):
            await service.assemble_tuning_prompt(
                product_id="nonexistent-id",
                user_id=USER_ID,
                sections=["description"],
            )

    @pytest.mark.asyncio
    async def test_raises_validation_error_for_empty_sections_list(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_user_settings
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with patch.object(service, "_get_user_configs", new_callable=AsyncMock, return_value=sample_user_settings):
            with pytest.raises(ValidationError):
                await service.assemble_tuning_prompt(
                    product_id=PRODUCT_ID,
                    user_id=USER_ID,
                    sections=[],
                )

    @pytest.mark.asyncio
    async def test_prompt_includes_apply_context_tuning_instruction(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_user_settings
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with patch.object(service, "_get_user_configs", new_callable=AsyncMock, return_value=sample_user_settings):
            result = await service.assemble_tuning_prompt(
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                sections=["description"],
            )

        assert "apply_context_tuning" in result["prompt"]
        assert "propose_product_context_update" not in result["prompt"]




DRIFT_PROPOSALS = [
    {
        "section": "description",
        "drift_detected": True,
        "current_summary": "An AI agent orchestration platform",
        "evidence": "Redis caching added",
        "proposed_value": "Updated AI orchestration platform with Redis caching",
        "confidence": "medium",
        "reasoning": "Description should reflect caching addition",
    },
    {
        "section": "architecture",
        "drift_detected": False,
        "current_summary": "Monolithic backend with REST API",
        "evidence": "No architectural changes observed",
        "proposed_value": "Monolithic backend with REST API",
        "confidence": "high",
        "reasoning": "Architecture description remains accurate",
    },
    {
        "section": "core_features",
        "drift_detected": True,
        "current_summary": "Agent orchestration, project management, 360 memory",
        "evidence": "Caching layer added",
        "proposed_value": "Agent orchestration, project management, 360 memory, caching",
        "confidence": "medium",
        "reasoning": "Core features expanded",
    },
    {
        "section": "quality_standards",
        "drift_detected": True,
        "current_summary": "80% test coverage, all endpoints tested",
        "evidence": "Coverage target increased",
        "proposed_value": "90% test coverage, all endpoints tested, performance benchmarks",
        "confidence": "high",
        "reasoning": "Quality bar raised",
    },
    {
        "section": "target_platforms",
        "drift_detected": True,
        "current_summary": "windows, linux",
        "evidence": "macOS support added",
        "proposed_value": "windows, linux, macos",
        "confidence": "high",
        "reasoning": "macOS now supported",
    },
]


class TestBuildUpdateKwargs:

    def test_maps_direct_fields(self):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        service = ProductTuningService.__new__(ProductTuningService)
        kwargs, sections = service._build_update_kwargs(DRIFT_PROPOSALS)

        assert kwargs["description"] == "Updated AI orchestration platform with Redis caching"
        assert kwargs["core_features"] == "Agent orchestration, project management, 360 memory, caching"
        assert "description" in sections
        assert "core_features" in sections

    def test_maps_relation_field_to_nested_dict(self):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        service = ProductTuningService.__new__(ProductTuningService)
        kwargs, sections = service._build_update_kwargs(DRIFT_PROPOSALS)

        assert "test_config" in kwargs
        assert (
            kwargs["test_config"]["quality_standards"]
            == "90% test coverage, all endpoints tested, performance benchmarks"
        )
        assert "quality_standards" in sections

    def test_skips_no_drift_proposals(self):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        service = ProductTuningService.__new__(ProductTuningService)
        kwargs, sections = service._build_update_kwargs(DRIFT_PROPOSALS)

        assert "architecture" not in kwargs
        assert "architecture" not in sections

    def test_skips_unknown_sections(self):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        service = ProductTuningService.__new__(ProductTuningService)
        proposals = [{"section": "nonexistent_field", "drift_detected": True, "proposed_value": "x"}]
        kwargs, sections = service._build_update_kwargs(proposals)

        assert kwargs == {}
        assert sections == []

    def test_returns_correct_section_count(self):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        service = ProductTuningService.__new__(ProductTuningService)
        _kwargs, sections = service._build_update_kwargs(DRIFT_PROPOSALS)

        assert len(sections) == 4
        assert set(sections) == {"description", "core_features", "quality_standards", "target_platforms"}


class TestApplyTuningUpdates:

    @pytest.mark.asyncio
    async def test_calls_product_service_update(self, mock_db_manager, mock_websocket_manager, sample_product):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))
        session.commit = AsyncMock()

        with (
            patch("giljo_mcp.services.product_service.ProductService") as mock_ps_cls,
            patch(
                "giljo_mcp.repositories.product_memory_repository.ProductMemoryRepository.get_next_sequence",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            mock_ps_instance = AsyncMock()
            mock_ps_cls.return_value = mock_ps_instance

            result = await service.apply_tuning_updates(
                product_id=PRODUCT_ID,
                proposals=DRIFT_PROPOSALS,
            )

        mock_ps_instance.update_product.assert_called_once()
        call_kwargs = mock_ps_instance.update_product.call_args
        assert call_kwargs.args[0] == PRODUCT_ID
        assert "description" in call_kwargs.kwargs
        assert "core_features" in call_kwargs.kwargs
        assert result["success"] is True
        assert result["applied_count"] == 4

    @pytest.mark.asyncio
    async def test_skips_product_service_when_no_drift(self, mock_db_manager, mock_websocket_manager, sample_product):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))
        session.commit = AsyncMock()

        no_drift = [{"section": "description", "drift_detected": False, "proposed_value": "x"}]

        with (
            patch("giljo_mcp.services.product_service.ProductService") as mock_ps_cls,
            patch(
                "giljo_mcp.repositories.product_memory_repository.ProductMemoryRepository.get_next_sequence",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            result = await service.apply_tuning_updates(
                product_id=PRODUCT_ID,
                proposals=no_drift,
            )

        mock_ps_cls.return_value.update_product.assert_not_called()
        assert result["applied_count"] == 0

    @pytest.mark.asyncio
    async def test_sets_last_tuned_at(self, mock_db_manager, mock_websocket_manager, sample_product):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        sample_product.tuning_state = None
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))
        session.commit = AsyncMock()

        with (
            patch("giljo_mcp.services.product_service.ProductService") as mock_ps_cls,
            patch(
                "giljo_mcp.repositories.product_memory_repository.ProductMemoryRepository.get_next_sequence",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            mock_ps_cls.return_value = AsyncMock()
            await service.apply_tuning_updates(
                product_id=PRODUCT_ID,
                proposals=DRIFT_PROPOSALS,
            )

        assert sample_product.tuning_state is not None
        assert sample_product.tuning_state.get("last_tuned_at") is not None

    @pytest.mark.asyncio
    async def test_emits_context_updated_websocket_event(self, mock_db_manager, mock_websocket_manager, sample_product):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))
        session.commit = AsyncMock()

        with (
            patch("giljo_mcp.services.product_service.ProductService") as mock_ps_cls,
            patch(
                "giljo_mcp.repositories.product_memory_repository.ProductMemoryRepository.get_next_sequence",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            mock_ps_cls.return_value = AsyncMock()
            await service.apply_tuning_updates(
                product_id=PRODUCT_ID,
                proposals=DRIFT_PROPOSALS,
            )

        mock_websocket_manager.broadcast_to_tenant.assert_called_once()
        call_kwargs = mock_websocket_manager.broadcast_to_tenant.call_args.kwargs
        assert call_kwargs["tenant_key"] == TENANT_KEY
        assert call_kwargs["event_type"] == "product:context_updated"

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_product(self, mock_db_manager, mock_websocket_manager):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, _session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        with patch("giljo_mcp.services.product_service.ProductService") as mock_ps_cls:
            mock_ps_instance = AsyncMock()
            mock_ps_instance.update_product.side_effect = ResourceNotFoundError(
                message="Product not found", context={"product_id": "nonexistent-id"}
            )
            mock_ps_cls.return_value = mock_ps_instance

            with pytest.raises(ResourceNotFoundError):
                await service.apply_tuning_updates(
                    product_id="nonexistent-id",
                    proposals=DRIFT_PROPOSALS,
                )

    @pytest.mark.asyncio
    async def test_no_drift_submission_stamps_tuning_state(
        self, mock_db_manager, mock_websocket_manager, sample_product
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        sample_product.tuning_state = None
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))
        session.commit = AsyncMock()

        no_drift_proposal = [
            {
                "section": "description",
                "drift_detected": False,
                "current_summary": "An AI agent orchestration platform",
                "proposed_value": None,
                "confidence": "high",
                "reasoning": "no drift",
                "evidence": "Reviewed; current value still matches the codebase",
            }
        ]

        with (
            patch("giljo_mcp.services.product_service.ProductService") as mock_ps_cls,
            patch(
                "giljo_mcp.repositories.product_memory_repository.ProductMemoryRepository.get_next_sequence",
                new_callable=AsyncMock,
                return_value=7,
            ),
        ):
            mock_ps_cls.return_value = AsyncMock()
            result = await service.apply_tuning_updates(
                product_id=PRODUCT_ID,
                proposals=no_drift_proposal,
            )

        mock_ps_cls.return_value.update_product.assert_not_called()
        assert result["applied_count"] == 0
        assert result["sections_applied"] == []

        assert sample_product.tuning_state is not None
        assert sample_product.tuning_state.get("last_tuned_at") is not None
        assert sample_product.tuning_state.get("last_tuned_at_sequence") == 6

    @pytest.mark.asyncio
    async def test_all_drift_sections_unresolved_declines_instead_of_success(
        self, mock_db_manager, mock_websocket_manager
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        unresolved = [
            {"section": "not_a_real_section", "drift_detected": True, "proposed_value": "x"},
        ]

        with patch("giljo_mcp.services.product_service.ProductService") as mock_ps_cls:
            result = await service.apply_tuning_updates(product_id=PRODUCT_ID, proposals=unresolved)

        mock_ps_cls.return_value.update_product.assert_not_called()
        assert result["success"] is False
        assert result["error"] == "NO_SECTIONS_APPLIED"
        assert result["sections_skipped"] == ["not_a_real_section"]
        session.commit.assert_not_called()




class TestCheckTuningStaleness:

    @pytest.mark.asyncio
    async def test_disabled_preference_returns_not_stale(self, mock_db_manager, mock_websocket_manager, sample_product):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        user = Mock()
        user.id = USER_ID
        user.tenant_key = TENANT_KEY
        user.notification_preferences = {
            "context_tuning_reminder": False,
            "tuning_reminder_threshold": 3,
        }

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with (
            patch.object(service._user_repo, "get_user_by_id", new_callable=AsyncMock, return_value=user),
            patch(
                "giljo_mcp.repositories.product_memory_repository.ProductMemoryRepository.get_next_sequence",
                new_callable=AsyncMock,
                return_value=100,
            ),
        ):
            result = await service.check_tuning_staleness(product_id=PRODUCT_ID, user_id=USER_ID)

        assert result["enabled"] is False
        assert result["is_stale"] is False

    @pytest.mark.asyncio
    async def test_high_threshold_below_count_returns_not_stale(
        self, mock_db_manager, mock_websocket_manager, sample_product
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        sample_product.tuning_state = {"last_tuned_at_sequence": 95}
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        user = Mock()
        user.id = USER_ID
        user.tenant_key = TENANT_KEY
        user.notification_preferences = {
            "context_tuning_reminder": True,
            "tuning_reminder_threshold": 100,
        }

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with (
            patch.object(service._user_repo, "get_user_by_id", new_callable=AsyncMock, return_value=user),
            patch(
                "giljo_mcp.repositories.product_memory_repository.ProductMemoryRepository.get_next_sequence",
                new_callable=AsyncMock,
                return_value=101,
            ),
        ):
            result = await service.check_tuning_staleness(product_id=PRODUCT_ID, user_id=USER_ID)

        assert result["enabled"] is True
        assert result["projects_since_tune"] == 5
        assert result["threshold"] == 100
        assert result["is_stale"] is False




class TestBE9218BannerCadence:

    @pytest.mark.asyncio
    async def test_manual_refresh_resets_the_reminder_countdown(
        self, mock_db_manager, mock_websocket_manager, sample_product
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        sample_product.tuning_state = {"last_tuned_at_sequence": 0}
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        user = Mock()
        user.id = USER_ID
        user.tenant_key = TENANT_KEY
        user.notification_preferences = {"context_tuning_reminder": True, "tuning_reminder_threshold": 3}

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))
        session.commit = AsyncMock()

        with (
            patch.object(service._user_repo, "get_user_by_id", new_callable=AsyncMock, return_value=user),
            patch(
                "giljo_mcp.repositories.product_memory_repository.ProductMemoryRepository.get_next_sequence",
                new_callable=AsyncMock,
                return_value=6,
            ),
        ):
            before = await service.check_tuning_staleness(product_id=PRODUCT_ID, user_id=USER_ID)
            assert before["is_stale"] is True
            assert before["projects_since_tune"] == 5

            await service.apply_tuning_updates(
                product_id=PRODUCT_ID,
                proposals=[{"section": "description", "drift_detected": False, "proposed_value": None}],
            )
            assert sample_product.tuning_state.get("last_tuned_at_sequence") == 5

            after = await service.check_tuning_staleness(product_id=PRODUCT_ID, user_id=USER_ID)
            assert after["is_stale"] is False
            assert after["projects_since_tune"] == 0

    @pytest.mark.asyncio
    async def test_legacy_anchor_without_sequence_is_tolerated(
        self, mock_db_manager, mock_websocket_manager, sample_product
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        sample_product.tuning_state = {"last_tuned_at": "2026-01-01T00:00:00+00:00"}
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        user = Mock()
        user.id = USER_ID
        user.tenant_key = TENANT_KEY
        user.notification_preferences = {"context_tuning_reminder": True, "tuning_reminder_threshold": 3}

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with (
            patch.object(service._user_repo, "get_user_by_id", new_callable=AsyncMock, return_value=user),
            patch(
                "giljo_mcp.repositories.product_memory_repository.ProductMemoryRepository.get_next_sequence",
                new_callable=AsyncMock,
                return_value=6,
            ),
        ):
            result = await service.check_tuning_staleness(product_id=PRODUCT_ID, user_id=USER_ID)

        assert result["projects_since_tune"] == 5
        assert result["is_stale"] is True




class TestTenantIsolation:

    @pytest.mark.asyncio
    async def test_assemble_prompt_filters_by_tenant(
        self, mock_db_manager, mock_websocket_manager, sample_product, sample_user_settings
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))

        with patch.object(service, "_get_user_configs", new_callable=AsyncMock, return_value=sample_user_settings):
            await service.assemble_tuning_prompt(
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                sections=["description"],
            )

        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_apply_tuning_updates_passes_tenant_to_product_service(
        self, mock_db_manager, mock_websocket_manager, sample_product
    ):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, session = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        session.execute = AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=sample_product)))
        session.commit = AsyncMock()

        with (
            patch("giljo_mcp.services.product_service.ProductService") as mock_ps_cls,
            patch(
                "giljo_mcp.repositories.product_memory_repository.ProductMemoryRepository.get_next_sequence",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            mock_ps_instance = AsyncMock()
            mock_ps_cls.return_value = mock_ps_instance

            await service.apply_tuning_updates(
                product_id=PRODUCT_ID,
                proposals=DRIFT_PROPOSALS,
            )

        mock_ps_cls.assert_called_once_with(db_manager, TENANT_KEY)




class TestBuildUpdateKwargsTargetPlatforms:

    def test_target_platforms_string_converts_to_list(self):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        service = ProductTuningService.__new__(ProductTuningService)
        proposals = [
            {
                "section": "target_platforms",
                "drift_detected": True,
                "proposed_value": "windows, linux, macos",
            }
        ]
        kwargs, sections = service._build_update_kwargs(proposals)

        assert kwargs["target_platforms"] == ["windows", "linux", "macos"]
        assert "target_platforms" in sections


class TestProductServiceAllowlist:

    def test_allowlist_excludes_tenant_key(self):
        from giljo_mcp.services.product_service import _ALLOWED_PRODUCT_FIELDS

        assert "tenant_key" not in _ALLOWED_PRODUCT_FIELDS

    def test_allowlist_excludes_deleted_at(self):
        from giljo_mcp.services.product_service import _ALLOWED_PRODUCT_FIELDS

        assert "deleted_at" not in _ALLOWED_PRODUCT_FIELDS

    def test_allowlist_contains_all_expected_fields(self):
        from giljo_mcp.services.product_service import _ALLOWED_PRODUCT_FIELDS

        expected = {
            "name",
            "description",
            "project_path",
            "core_features",
            "brand_guidelines",
            "extraction_custom_instructions",
            "target_platforms",
            "consolidated_vision_light",
            "consolidated_vision_light_tokens",
            "consolidated_vision_medium",
            "consolidated_vision_medium_tokens",
            "vision_analysis_complete",
        }
        assert expected == _ALLOWED_PRODUCT_FIELDS


class TestValidateProposals:

    def test_rejects_integer_proposed_value(self):
        from giljo_mcp.tools.submit_tuning_review import _validate_proposals

        proposals = [
            {
                "section": "description",
                "drift_detected": True,
                "proposed_value": 42,
            }
        ]
        errors = _validate_proposals(proposals)

        assert any("proposed_value" in e for e in errors)
        assert any("int" in e for e in errors)

    def test_rejects_proposed_value_over_10000_chars(self):
        from giljo_mcp.tools.submit_tuning_review import _validate_proposals

        proposals = [
            {
                "section": "description",
                "drift_detected": True,
                "proposed_value": "x" * 10001,
            }
        ]
        errors = _validate_proposals(proposals)

        assert any("proposed_value" in e for e in errors)
        assert any("10000" in e for e in errors)

    def test_accepts_proposed_value_at_10000_chars(self):
        from giljo_mcp.tools.submit_tuning_review import _validate_proposals

        proposals = [
            {
                "section": "description",
                "drift_detected": True,
                "proposed_value": "x" * 10000,
            }
        ]
        errors = _validate_proposals(proposals)

        assert not any("proposed_value" in e for e in errors)

    def test_accepts_none_proposed_value(self):
        from giljo_mcp.tools.submit_tuning_review import _validate_proposals

        proposals = [
            {
                "section": "description",
                "drift_detected": True,
                "proposed_value": None,
            }
        ]
        errors = _validate_proposals(proposals)

        assert not any("proposed_value" in e for e in errors)

    def test_accepts_dict_proposed_value(self):
        from giljo_mcp.tools.submit_tuning_review import _validate_proposals

        proposals = [
            {
                "section": "tech_stack",
                "drift_detected": True,
                "proposed_value": {"programming_languages": "Python"},
            }
        ]
        errors = _validate_proposals(proposals)

        assert not any("proposed_value" in e for e in errors)

    def test_accepts_list_proposed_value_for_target_platforms(self):
        from giljo_mcp.tools.submit_tuning_review import _validate_proposals

        proposals = [
            {
                "section": "target_platforms",
                "drift_detected": True,
                "proposed_value": ["windows", "linux", "macos"],
            }
        ]
        errors = _validate_proposals(proposals)

        assert not any("proposed_value" in e for e in errors)

    def test_rejects_list_with_non_string_items_for_target_platforms(self):
        from giljo_mcp.tools.submit_tuning_review import _validate_proposals

        proposals = [
            {
                "section": "target_platforms",
                "drift_detected": True,
                "proposed_value": ["windows", 123],
            }
        ]
        errors = _validate_proposals(proposals)

        assert any("proposed_value" in e for e in errors)


class TestRelationSectionStringRejection:

    def test_relation_section_with_string_value_is_skipped(self):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        service = ProductTuningService.__new__(ProductTuningService)
        service._logger = Mock()

        proposals = [
            {
                "section": "tech_stack",
                "drift_detected": True,
                "proposed_value": "Python, FastAPI, PostgreSQL",
            }
        ]
        kwargs, sections = service._build_update_kwargs(proposals)

        assert "tech_stack" not in kwargs
        assert "tech_stack" not in sections

    def test_relation_section_with_string_value_logs_warning(self):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        service = ProductTuningService.__new__(ProductTuningService)
        service._logger = Mock()

        proposals = [
            {
                "section": "architecture",
                "drift_detected": True,
                "proposed_value": "monolith",
            }
        ]
        service._build_update_kwargs(proposals)

        service._logger.warning.assert_called_once()
        warning_args = service._logger.warning.call_args[0]
        assert "architecture" in warning_args[1]

    def test_relation_section_with_dict_value_is_applied(self):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        service = ProductTuningService.__new__(ProductTuningService)
        service._logger = Mock()

        proposals = [
            {
                "section": "tech_stack",
                "drift_detected": True,
                "proposed_value": {"programming_languages": "Python 3.12"},
            }
        ]
        kwargs, sections = service._build_update_kwargs(proposals)

        assert "tech_stack" in kwargs
        assert kwargs["tech_stack"] == {"programming_languages": "Python 3.12"}
        assert "tech_stack" in sections




class TestBuildUpdateKwargsDottedKeys:

    def test_submit_tech_stack_backend_frameworks_only(self, mock_db_manager, mock_websocket_manager):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, _ = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        proposals = [
            {
                "section": "tech_stack.backend_frameworks",
                "drift_detected": True,
                "proposed_value": "FastAPI, Starlette",
            }
        ]
        kwargs, sections = service._build_update_kwargs(proposals)

        assert kwargs == {"tech_stack": {"backend_frameworks": "FastAPI, Starlette"}}
        assert "tech_stack.backend_frameworks" in sections

    def test_submit_tech_stack_multiple_subfields(self, mock_db_manager, mock_websocket_manager):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, _ = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        proposals = [
            {
                "section": "tech_stack.backend_frameworks",
                "drift_detected": True,
                "proposed_value": "FastAPI",
            },
            {
                "section": "tech_stack.databases_storage",
                "drift_detected": True,
                "proposed_value": "PostgreSQL 18",
            },
        ]
        kwargs, sections = service._build_update_kwargs(proposals)

        assert kwargs == {"tech_stack": {"backend_frameworks": "FastAPI", "databases_storage": "PostgreSQL 18"}}
        assert "tech_stack.backend_frameworks" in sections
        assert "tech_stack.databases_storage" in sections

    def test_submit_architecture_subfield(self, mock_db_manager, mock_websocket_manager):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, _ = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        proposals = [
            {
                "section": "architecture.api_style",
                "drift_detected": True,
                "proposed_value": "GraphQL",
            }
        ]
        kwargs, sections = service._build_update_kwargs(proposals)

        assert kwargs == {"architecture": {"api_style": "GraphQL"}}
        assert "architecture.api_style" in sections

    def test_tech_stack_full_dict_still_works(self, mock_db_manager, mock_websocket_manager):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        db_manager, _ = mock_db_manager
        service = ProductTuningService(db_manager, TENANT_KEY, websocket_manager=mock_websocket_manager)

        full_dict = {
            "programming_languages": "Python 3.12",
            "backend_frameworks": "FastAPI",
            "frontend_frameworks": "Vue 3",
            "databases_storage": "PostgreSQL",
            "infrastructure": "Docker",
            "dev_tools": "ruff",
        }
        proposals = [
            {
                "section": "tech_stack",
                "drift_detected": True,
                "proposed_value": full_dict,
            }
        ]
        kwargs, sections = service._build_update_kwargs(proposals)

        assert kwargs == {"tech_stack": full_dict}
        assert "tech_stack" in sections


class TestValidSectionsDottedKeys:

    def test_valid_dotted_tech_stack_key(self):
        from giljo_mcp.tools.submit_tuning_review import VALID_SECTIONS

        assert "tech_stack.backend_frameworks" in VALID_SECTIONS
        assert "tech_stack.frontend_frameworks" in VALID_SECTIONS
        assert "tech_stack.programming_languages" in VALID_SECTIONS
        assert "tech_stack.databases_storage" in VALID_SECTIONS
        assert "tech_stack.infrastructure" in VALID_SECTIONS
        assert "tech_stack.dev_tools" in VALID_SECTIONS

    def test_valid_dotted_architecture_key(self):
        from giljo_mcp.tools.submit_tuning_review import VALID_SECTIONS

        assert "architecture.primary_pattern" in VALID_SECTIONS
        assert "architecture.design_patterns" in VALID_SECTIONS
        assert "architecture.api_style" in VALID_SECTIONS
        assert "architecture.architecture_notes" in VALID_SECTIONS
        assert "architecture.coding_conventions" in VALID_SECTIONS

    def test_invalid_dotted_key_rejected(self):
        from giljo_mcp.tools.submit_tuning_review import VALID_SECTIONS

        assert "tech_stack.nonexistent" not in VALID_SECTIONS
        assert "architecture.nonexistent" not in VALID_SECTIONS
