# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for CH2 protocol injection and depth defaults consolidation (Handover 0823, 0823b).

Verifies:
1. DEFAULT_DEPTHS in fetch_context.py matches DEFAULT_DEPTH_CONFIG from defaults.py
2. CH2 protocol generates inline fetch_context() calls for enabled categories
3. Disabled categories are excluded from CH2
4. depth_config values are NOT snapshotted into fetch calls (Handover 0823b)
5. Framing text is generic, not depth-specific (Handover 0823b)
6. fetch_context reads user depth_config from DB when not provided (Handover 0823b)
"""

from giljo_mcp.config.defaults import DEFAULT_DEPTH_CONFIG as RAW_DEPTH_CONFIG


class TestDepthDefaultsConsolidation:
    """Phase 1: Verify single source of truth for depth defaults."""

    def test_fetch_context_defaults_match_canonical_defaults(self):
        """DEFAULT_DEPTHS in fetch_context.py must derive from DEFAULT_DEPTH_CONFIG in defaults.py."""
        from giljo_mcp.tools.context_tools.fetch_context import DEFAULT_DEPTHS

        # Handover 0840d: DEFAULT_DEPTH_CONFIG is now a flat dict with column-style keys
        canonical = RAW_DEPTH_CONFIG

        # memory_360 in DEFAULT_DEPTHS maps to memory_last_n_projects in canonical
        assert DEFAULT_DEPTHS["memory_360"] == canonical["memory_last_n_projects"], (
            f"memory_360 mismatch: fetch_context={DEFAULT_DEPTHS['memory_360']}, "
            f"defaults.py={canonical['memory_last_n_projects']}"
        )

        # git_history in DEFAULT_DEPTHS maps to git_commits in canonical
        assert DEFAULT_DEPTHS["git_history"] == canonical["git_commits"], (
            f"git_history mismatch: fetch_context={DEFAULT_DEPTHS['git_history']}, "
            f"defaults.py={canonical['git_commits']}"
        )

        # BE-9322: tech_stack in DEFAULT_DEPTHS maps to tech_stack_sections in canonical.
        # Before the fix these carried a hardcoded None -- a category can only be
        # resolved from the DB-stored user setting if its default entry exists.
        assert DEFAULT_DEPTHS["tech_stack"] == canonical["tech_stack_sections"], (
            f"tech_stack mismatch: fetch_context={DEFAULT_DEPTHS['tech_stack']}, "
            f"defaults.py={canonical['tech_stack_sections']}"
        )

        # vision_documents - same key
        assert DEFAULT_DEPTHS["vision_documents"] == canonical["vision_documents"]

    def test_canonical_defaults_have_expected_values(self):
        """Verify canonical defaults match handover 0823 decision."""
        canonical = RAW_DEPTH_CONFIG
        assert canonical["memory_last_n_projects"] == 3
        assert canonical["git_commits"] == 25
        assert canonical["vision_documents"] == "medium"


class TestCH2InlineFetchCalls:
    """Phase 2: Verify CH2 generates inline fetch_context() calls."""

    def _build_ch2(self, field_toggles=None, depth_config=None, product_id="prod-123", tenant_key="tk_test"):
        """Helper to build CH2 with test parameters."""
        from giljo_mcp.services.protocol_builder import _build_ch2_startup

        if field_toggles is None:
            field_toggles = {
                "product_core": True,
                "tech_stack": True,
                "memory_360": True,
                "vision_documents": True,
                "git_history": True,
                "architecture": True,
                "testing": True,
                "agent_templates": True,
                "project_description": True,
            }
        if depth_config is None:
            depth_config = {
                "memory_360": 3,
                "git_history": 25,
                "vision_documents": "medium",
                "agent_templates": "basic",
            }
        return _build_ch2_startup(
            orchestrator_id="orch-001",
            project_id="proj-001",
            field_toggles=field_toggles,
            depth_config=depth_config,
            product_id=product_id,
            tenant_key=tenant_key,
        )

    def test_ch2_contains_get_context_calls(self):
        """CH2 Step 2 must contain explicit get_context() calls."""
        ch2 = self._build_ch2()
        assert "get_context(" in ch2, "CH2 must contain get_context() calls"

    def test_ch2_implementation_todo_hoisted_to_step_1c(self):
        """HO1025: the Implementation TODO List guidance was previously buried
        inside Step 1b (Initialize Progress Tracking). Test-agent feedback flagged
        it as easy to skim past. Hoisted to its own labeled Step 1c so the
        orchestrator sees it as a standalone planning concern."""
        ch2 = self._build_ch2()
        assert "STEP 1c" in ch2
        assert "Plan Implementation Deliverables" in ch2
        # Step 1b should now ONLY mention deferral, not the TODO list shape
        assert "STEP 1b: Defer Progress Tracking" in ch2
        # The TODO list keywords must be in CH2 SOMEWHERE, but the structural
        # signal is the labeled step header.
        assert "PROJECT OUTCOME" in ch2

    def test_ch2_contains_context_fetch_philosophy(self):
        """HO1024: CH2 Step 2 must teach context-fetch judgment, not prescribe
        fetch-all. CE-0031 trimmed this section — the canonical right-sizing
        rule moved to the identity prompt's "Right-Sizing Your Work" section;
        CH2 now keeps the headline sizing heuristic + idempotency note + the
        thin-description inverse rule.
        """
        ch2 = self._build_ch2()
        # Sizing heuristic remains.
        assert "SIZE the project FIRST" in ch2 or "SIZING" in ch2
        # Idempotency safety-net language must surface so agents feel safe defaulting low.
        assert "idempotent" in ch2
        # Inverse heuristic: thin/vague descriptions → fetch BROADLY.
        assert "thin" in ch2 or "vague" in ch2
        assert "BROADLY" in ch2
        # Per-category usage hints must still render (now in compact form).
        assert "[" in ch2 and "]" in ch2
        # Regression guards: legacy framing must NOT return.
        assert "fetch all" not in ch2.lower()
        assert "essential context" not in ch2

    def test_ch2_includes_product_id_and_omits_tenant_key(self):
        """Each fetch call must include product_id. CE-0034 Task 3: tenant_key
        is auto-injected server-side; agent-visible protocol examples must
        NOT show explicit tenant_key="..." (mirrors the orchestrator identity
        claim that tenant_key never appears in agent prose)."""
        ch2 = self._build_ch2(product_id="prod-abc", tenant_key="tk_xyz")
        assert "prod-abc" in ch2
        assert "tk_xyz" not in ch2, "CE-0034 Task 3: tenant_key value must not appear in rendered CH2 examples"
        assert 'tenant_key="' not in ch2, (
            "CE-0034 Task 3: tenant_key arg must not appear in rendered CH2 get_context examples"
        )

    def test_ch2_enabled_categories_appear(self):
        """All enabled categories should have get_context calls in CH2."""
        toggles = {
            "product_core": True,
            "tech_stack": True,
            "memory_360": True,
            "project_description": True,  # inlined, should NOT appear as fetch
        }
        depth = {"memory_360": 3}
        ch2 = self._build_ch2(field_toggles=toggles, depth_config=depth)

        assert "product_core" in ch2
        assert "tech_stack" in ch2
        assert "memory_360" in ch2

    def test_ch2_disabled_categories_excluded(self):
        """Disabled categories must NOT appear as fetch calls."""
        toggles = {
            "product_core": True,
            "tech_stack": False,
            "memory_360": False,
            "vision_documents": False,
            "git_history": False,
            "architecture": False,
            "testing": False,
            "agent_templates": False,
            "project_description": True,
        }
        ch2 = self._build_ch2(field_toggles=toggles, depth_config={})

        # tech_stack is disabled, should not appear as a fetch call
        # We check that fetch_context(...tech_stack...) is NOT present
        assert 'categories=["tech_stack"]' not in ch2
        assert 'categories=["memory_360"]' not in ch2
        assert 'categories=["git_history"]' not in ch2

        # product_core IS enabled
        assert 'categories=["product_core"]' in ch2

    def test_ch2_inlined_fields_not_fetched(self):
        """project_description is inlined, should not appear as fetch call."""
        toggles = {"project_description": True, "product_core": True}
        ch2 = self._build_ch2(field_toggles=toggles, depth_config={})
        assert 'categories=["project_description"]' not in ch2

    def test_ch2_depth_config_not_in_memory_360_call(self):
        """memory_360 fetch call must NOT include depth_config (Handover 0823b)."""
        from giljo_mcp.services.protocol_sections.chapters_startup import _build_ch2_fetch_calls

        result = _build_ch2_fetch_calls(
            field_toggles={"memory_360": True},
            depth_config={"memory_360": 7},
            product_id="prod-123",
            tenant_key="tk_test",
        )
        # depth_config should NOT appear anywhere in the generated fetch calls
        assert "depth_config" not in result, "memory_360 fetch call should not contain depth_config (0823b)"

    def test_ch2_depth_config_not_in_git_history_call(self):
        """git_history fetch call must NOT include depth_config (Handover 0823b)."""
        from giljo_mcp.services.protocol_sections.chapters_startup import _build_ch2_fetch_calls

        result = _build_ch2_fetch_calls(
            field_toggles={"git_history": True},
            depth_config={"git_history": 50},
            product_id="prod-123",
            tenant_key="tk_test",
        )
        assert "depth_config" not in result, "git_history fetch call should not contain depth_config (0823b)"

    def test_ch2_depth_config_not_in_vision_call(self):
        """vision_documents fetch call must NOT include depth_config (Handover 0823b)."""
        from giljo_mcp.services.protocol_sections.chapters_startup import _build_ch2_fetch_calls

        result = _build_ch2_fetch_calls(
            field_toggles={"vision_documents": True},
            depth_config={"vision_documents": "full"},
            product_id="prod-123",
            tenant_key="tk_test",
        )
        assert "depth_config" not in result, "vision_documents fetch call should not contain depth_config (0823b)"

    def test_ch2_framing_memory_360_generic(self):
        """Framing text for memory_360 should be generic, not depth-specific (0823b).
        CE-0031 trimmed the framing copy — assert generic-ness, not exact wording."""
        toggles = {"memory_360": True}
        depth = {"memory_360": 3}
        ch2 = self._build_ch2(field_toggles=toggles, depth_config=depth)
        assert "Recent project closeouts" in ch2 or "project closeouts" in ch2
        assert "Last 3" not in ch2

    def test_ch2_framing_git_history_generic(self):
        """Framing text for git_history should be generic, not depth-specific (0823b).
        CE-0031 trimmed the framing copy."""
        toggles = {"git_history": True}
        depth = {"git_history": 50}
        ch2 = self._build_ch2(field_toggles=toggles, depth_config=depth)
        assert "Recent commits" in ch2
        assert "Last 50" not in ch2

    def test_ch2_non_depth_categories_omit_depth_config(self):
        """Categories without depth (product_core, tech_stack) should not have depth_config."""
        toggles = {"product_core": True, "tech_stack": True}
        ch2 = self._build_ch2(field_toggles=toggles, depth_config={})

        # Find product_core fetch call - it should NOT have depth_config
        lines = ch2.split("\n")
        for line in lines:
            if 'categories=["product_core"]' in line:
                assert "depth_config" not in line

    def test_ch2_count_matches_enabled_toggles(self):
        """Number of fetch calls should match number of enabled non-inlined categories."""
        toggles = {
            "product_core": True,
            "tech_stack": True,
            "memory_360": True,
            "vision_documents": False,
            "git_history": False,
            "architecture": False,
            "testing": False,
            "agent_templates": False,
            "project_description": True,  # inlined
        }
        depth = {"memory_360": 3}
        ch2 = self._build_ch2(field_toggles=toggles, depth_config=depth)

        # All 3 enabled categories should appear in fetch_context calls
        # (may be batched into fewer calls with batch fetch_context support)
        assert "product_core" in ch2
        assert "tech_stack" in ch2
        assert "memory_360" in ch2
        # Disabled categories should not appear
        assert "vision_documents" not in ch2 or "False" in ch2.split("vision_documents")[0].split("\n")[-1]

    def test_ch2_preserves_context_variables_block(self):
        """CH2 must keep the CONTEXT VARIABLES block."""
        ch2 = self._build_ch2()
        assert "CONTEXT VARIABLES" in ch2

    def test_ch2_preserves_other_steps(self):
        """CH2 must preserve steps 0, 1, 1b, 3-7."""
        ch2 = self._build_ch2()
        assert "STEP 0" in ch2
        assert "STEP 1:" in ch2
        assert "STEP 1b" in ch2
        assert "STEP 3" in ch2
        assert "STEP 4" in ch2

    def test_ch2_agent_templates_not_in_fetch_calls(self):
        """Handover 0967: agent_templates removed from CH2 fetch calls.
        Orchestrator gets slim roster from get_staging_instructions instead."""
        toggles = {"agent_templates": True}
        depth = {"agent_templates": "full"}
        ch2 = self._build_ch2(field_toggles=toggles, depth_config=depth)
        assert 'categories=["agent_templates"]' not in ch2


class TestResponseStructure:
    """Phase 3: Verify response no longer contains context_fetch_instructions."""

    # These tests verify the response from get_staging_instructions
    # but require DB fixtures. They are structural assertions on the protocol.

    def test_orchestrator_protocol_receives_toggles(self):
        """_build_orchestrator_protocol must accept and pass through toggle params."""
        from giljo_mcp.services.protocol_builder import _build_orchestrator_protocol

        field_toggles = {"product_core": True, "tech_stack": False}
        depth_config = {"memory_360": 3}

        result = _build_orchestrator_protocol(
            cli_mode=False,
            project_id="proj-123",
            orchestrator_id="orch-456",
            tenant_key="tk_test",
            field_toggles=field_toggles,
            depth_config=depth_config,
            product_id="prod-789",
        )

        # CH2 should contain the fetch calls
        ch2 = result["ch2_startup_sequence"]
        assert 'categories=["product_core"]' in ch2
        assert 'categories=["tech_stack"]' not in ch2


class TestFetchContextDepthFromDB:
    """Phase 4 (Handover 0823b): Verify fetch_context reads depth from DB at runtime."""

    @staticmethod
    def _make_mock_user(**depth_kwargs):
        """Create a mock User object with depth columns (Handover 0840d)."""
        from unittest.mock import MagicMock

        user = MagicMock()
        user.is_active = True
        user.tenant_key = "tk_test"
        # Set depth column defaults
        user.depth_vision_documents = depth_kwargs.get("vision_documents", "medium")
        user.depth_memory_last_n = depth_kwargs.get("memory_last_n_projects", 3)
        user.depth_git_commits = depth_kwargs.get("git_commits", 25)
        user.depth_agent_templates = depth_kwargs.get("agent_templates", "basic")
        user.depth_tech_stack_sections = depth_kwargs.get("tech_stack_sections", "all")
        user.depth_architecture = depth_kwargs.get("architecture_depth", "overview")
        return user

    def test_load_user_depth_config_normalizes_keys(self):
        """_load_user_depth_config must map DB keys to internal keys."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from giljo_mcp.tools.context_tools.fetch_context import _load_user_depth_config

        mock_user = self._make_mock_user(
            memory_last_n_projects=5,
            git_commits=50,
            vision_documents="full",
            agent_templates="full",
            tech_stack_sections="required",
        )

        # Mock the DB session and query
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.info = {}  # tenant_session_context save/restore target

        mock_db = MagicMock()
        mock_db.get_session_async = MagicMock(return_value=mock_session)

        result = asyncio.get_event_loop().run_until_complete(_load_user_depth_config("tk_test", mock_db))

        assert result is not None
        assert result["memory_360"] == 5
        assert result["git_history"] == 50
        assert result["vision_documents"] == "full"
        assert result["agent_templates"] == "full"
        # BE-9322: the DB-format key must map to the CATEGORY_TOOLS/effective_depths
        # key name ("tech_stack"), not pass through unmapped as
        # "tech_stack_sections" -- that mismatch was the root cause of the dead
        # control: fetch_context.py looked up effective_depths.get("tech_stack")
        # and always got None back.
        assert result["tech_stack"] == "required", (
            f"tech_stack_sections must normalize to the 'tech_stack' key, got keys={list(result.keys())}"
        )

    def test_load_user_depth_config_returns_none_when_no_user(self):
        """_load_user_depth_config returns None when no user found."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from giljo_mcp.tools.context_tools.fetch_context import _load_user_depth_config

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.info = {}  # tenant_session_context save/restore target

        mock_db = MagicMock()
        mock_db.get_session_async = MagicMock(return_value=mock_session)

        result = asyncio.get_event_loop().run_until_complete(_load_user_depth_config("tk_test", mock_db))

        assert result is None

    def test_load_user_depth_config_returns_defaults_when_columns_have_defaults(self):
        """_load_user_depth_config returns column defaults when user has default depth values."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from giljo_mcp.tools.context_tools.fetch_context import _load_user_depth_config

        mock_user = self._make_mock_user()  # Uses column defaults

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.info = {}  # tenant_session_context save/restore target

        mock_db = MagicMock()
        mock_db.get_session_async = MagicMock(return_value=mock_session)

        result = asyncio.get_event_loop().run_until_complete(_load_user_depth_config("tk_test", mock_db))

        # Handover 0840d: columns always have defaults, so result is never None when user exists
        assert result is not None
        assert result["memory_360"] == 3  # default
        assert result["vision_documents"] == "medium"  # default

    def test_load_user_depth_config_normalizes_vision_optional(self):
        """_load_user_depth_config maps vision_documents 'optional' to 'light'."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from giljo_mcp.tools.context_tools.fetch_context import _load_user_depth_config

        mock_user = self._make_mock_user(vision_documents="optional")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.info = {}  # tenant_session_context save/restore target

        mock_db = MagicMock()
        mock_db.get_session_async = MagicMock(return_value=mock_session)

        result = asyncio.get_event_loop().run_until_complete(_load_user_depth_config("tk_test", mock_db))

        assert result is not None
        assert result["vision_documents"] == "light"


class TestCH2CategoryMetadata:
    """CE-OPT-001: Verify category_metadata timestamps appear in CH2 fetch calls."""

    def test_fetch_calls_with_metadata_shows_modified(self):
        """_build_ch2_fetch_calls with category_metadata produces lines containing 'Modified:'."""
        from giljo_mcp.services.protocol_sections.chapters_startup import _build_ch2_fetch_calls

        result = _build_ch2_fetch_calls(
            field_toggles={"product_core": True, "tech_stack": True},
            depth_config={},
            product_id="prod-123",
            tenant_key="tk_test",
            category_metadata={
                "product_core": {"modified": "2026-04-13T20:22"},
                "tech_stack": {"modified": "2026-04-12T10:00"},
            },
        )
        assert "Modified: 2026-04-13T20:22" in result
        assert "Modified: 2026-04-12T10:00" in result

    def test_fetch_calls_without_metadata_no_modified(self):
        """_build_ch2_fetch_calls without category_metadata produces lines WITHOUT 'Modified:'."""
        from giljo_mcp.services.protocol_sections.chapters_startup import _build_ch2_fetch_calls

        result = _build_ch2_fetch_calls(
            field_toggles={"product_core": True, "tech_stack": True},
            depth_config={},
            product_id="prod-123",
            tenant_key="tk_test",
        )
        assert "Modified:" not in result

    def test_fetch_calls_memory_360_shows_entries_count(self):
        """memory_360 metadata with entries count appears as 'entries: N'."""
        from giljo_mcp.services.protocol_sections.chapters_startup import _build_ch2_fetch_calls

        result = _build_ch2_fetch_calls(
            field_toggles={"memory_360": True},
            depth_config={"memory_360": 3},
            product_id="prod-123",
            tenant_key="tk_test",
            category_metadata={
                "memory_360": {"modified": "2026-04-13T18:00", "entries": 7},
            },
        )
        assert "entries: 7" in result
        assert "Modified: 2026-04-13T18:00" in result

    def test_fetch_calls_metadata_partial_categories(self):
        """When metadata exists for only some categories, others show no suffix."""
        from giljo_mcp.services.protocol_sections.chapters_startup import _build_ch2_fetch_calls

        result = _build_ch2_fetch_calls(
            field_toggles={"product_core": True, "tech_stack": True},
            depth_config={},
            product_id="prod-123",
            tenant_key="tk_test",
            category_metadata={
                "product_core": {"modified": "2026-04-13T20:22"},
            },
        )
        # product_core has Modified, tech_stack does not. CE-0031 trimmed the
        # framing copy — match on a stable prefix instead of full sentence.
        lines = result.split("\n")
        product_core_framing = [line for line in lines if "Product name" in line]
        tech_stack_framing = [line for line in lines if "Languages" in line]

        assert len(product_core_framing) == 1
        assert "Modified:" in product_core_framing[0]
        assert len(tech_stack_framing) == 1
        assert "Modified:" not in tech_stack_framing[0]

    def test_protocol_text_allows_skipping_unchanged(self):
        """Protocol text must allow skipping unchanged categories when field_toggles provided.
        CE-0031 trimmed the "Skip aggressively" headline; semantics preserved by a "Skip
        categories whose Modified date hasn't changed" sentence."""
        from giljo_mcp.services.protocol_sections.chapters_startup import _build_ch2_startup

        ch2 = _build_ch2_startup(
            orchestrator_id="orch-001",
            project_id="proj-001",
            field_toggles={"product_core": True},
            depth_config={},
            product_id="prod-123",
            tenant_key="tk_test",
            category_metadata={"product_core": {"modified": "2026-04-13T20:22"}},
        )
        assert "Skip categories" in ch2 and "Modified date hasn't changed" in ch2
        assert "MUST call each one" not in ch2

    def test_protocol_text_backward_compat_without_metadata(self):
        """Without category_metadata, protocol text still allows the skip path."""
        from giljo_mcp.services.protocol_sections.chapters_startup import _build_ch2_startup

        ch2 = _build_ch2_startup(
            orchestrator_id="orch-001",
            project_id="proj-001",
            field_toggles={"product_core": True},
            depth_config={},
            product_id="prod-123",
            tenant_key="tk_test",
        )
        assert "Skip categories" in ch2 and "Modified date hasn't changed" in ch2
