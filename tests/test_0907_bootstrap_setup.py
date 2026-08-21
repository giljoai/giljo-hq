# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for 0907: MCP Bootstrap Setup Tool (giljo_setup).

Tests the combined ZIP staging that bundles slash commands + agent templates
into a single download for first-time setup.
"""

import tomllib
import zipfile
from datetime import UTC
from unittest.mock import AsyncMock

import pytest

from giljo_mcp.file_staging import FileStaging
from giljo_mcp.models.templates import AgentTemplate
from tests.helpers.model_factories import make_agent_template, strict_result


def _make_template(name: str, role: str, description: str = "") -> AgentTemplate:
    """Create an AgentTemplate stand-in with required fields.

    INF-9399: a real transient instance, not a mock. The values are exactly the
    ones this file already used; what changes is that every column NOT named
    here reads None (or the factory's real-row default) instead of a truthy
    child mock, so a column added to the model later cannot silently steer these
    tests down a branch they never meant to take.
    """
    from datetime import datetime

    return make_agent_template(
        name=name,
        role=role,
        description=description or f"Agent for {role}",
        system_instructions=f"You are the {role} agent.",
        user_instructions=f"Handle {role} tasks.",
        behavioral_rules="Follow project conventions.",
        success_criteria="Deliver quality work.",
        model="sonnet",
        background_color=None,
        is_active=True,
        is_default=False,
        tenant_key="test-tenant",
        # BE-9420: cli_tool is NOT NULL with its own default="claude", so an
        # explicit None here modelled a row the database could never hold. Left
        # unset, the factory applies that default. ``tools`` IS nullable
        # ("null = inherit all"), so its None is a real shape and stays.
        tools=None,
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_exported_at=None,
    )


def _make_template_with_duplicate_bootstrap() -> AgentTemplate:
    """Create a template matching legacy rows with duplicated MCP startup prose."""
    bootstrap = """## GiljoAI MCP Agent

You are part of a GiljoAI MCP orchestration system. MCP tools are available as native
tool calls prefixed `mcp__giljo_mcp__*` in your tool list.

Your job credentials (`job_id`, `tenant_key`) are provided in your spawn prompt —
either pasted by the user or injected by the orchestrator. Use them exactly as given.

### STARTUP (MANDATORY)
1. Call `mcp__giljo_mcp__health_check()` to verify MCP connectivity
2. Call `mcp__giljo_mcp__get_job_mission(job_id="<your_job_id>", tenant_key="<your_tenant_key>")` to receive:
   - Your full operating protocols (`full_protocol`)
   - Your work order and team context (`mission`)
3. Follow `full_protocol` for all lifecycle behavior

Do not begin work until you have received and read your mission and protocols."""

    template = _make_template("Tester", "tester")
    template.system_instructions = bootstrap
    template.user_instructions = (
        f"{bootstrap}\n\n"
        "You are the testing specialist for GiljoAI MCP.   \n"
        "Run pytest and Vitest before reporting completion.      \n"
    )
    return template


def _make_template_with_compact_duplicate_bootstrap() -> AgentTemplate:
    """Create a template matching compact legacy rows from exported Codex agents."""
    template = _make_template("Tester", "tester")
    template.system_instructions = """## GiljoAI MCP Agent

You are part of a GiljoAI MCP orchestration system. MCP tools are available as native
tool calls prefixed `mcp__giljo_mcp__*` in your tool list.

### STARTUP (MANDATORY)
1. Call `mcp__giljo_mcp__health_check()` to verify MCP connectivity
2. Call `mcp__giljo_mcp__get_job_mission(job_id="<your_job_id>", tenant_key="<your_tenant_key>")`

Do not begin work until you have received and read your mission and protocols."""
    template.user_instructions = """## GiljoAI MCP Agent

  You are part of a GiljoAI MCP orchestration system. MCP tools are available as native tool calls prefixed
  `mcp__giljo_mcp__*`.

  ### STARTUP (MANDATORY)
  1. `mcp__giljo_mcp__health_check()`
  2. `mcp__giljo_mcp__get_job_mission(job_id=..., tenant_key=...)`
  3. Follow `full_protocol`.

  ## Role

  Testing specialist for GiljoAI MCP. You maintain the test infrastructure.
"""
    return template


def _make_template_with_regex_backslashes() -> AgentTemplate:
    """Create a template containing regex backslashes that must survive Codex TOML."""
    template = _make_template("Reviewer", "reviewer")
    template.user_instructions = (
        'Run: `grep -rn "from.*saas\\|from.*demo" src/ api/ frontend/src/ | grep -v "saas/\\|demo/"`'
    )
    return template


@pytest.fixture
def staging_dir(tmp_path):
    """Pre-created staging directory."""
    d = tmp_path / "staging"
    d.mkdir()
    return d


@pytest.fixture
def templates():
    """Two mock agent templates."""
    return [
        _make_template("Orchestrator", "orchestrator"),
        _make_template("Analyzer", "analyzer"),
    ]


@pytest.fixture
def mock_session(templates):
    """Mock async DB session that returns templates."""
    session = AsyncMock()
    session.info = {}  # tenant_session_context save/restore target
    # INF-9399: ONE result object answers EVERY query this session serves, so it
    # states what each of those queries honestly returns for the DB these fixtures
    # model -- one holding no product rows.
    #
    # This block is the case for the convention, written by its own history. Left
    # bare it answered every query with a truthy child mock, and it had to be
    # hand-pinned TWICE in two days: BE-9385a for the active-product lookup (the
    # mock claimed a product existed, then that it had no enabled agents, so the
    # ZIP shipped zero templates) and BE-9385b for the export-identity select,
    # which reads .first() DIRECTLY rather than through .scalars(). Each pin fixed
    # the query that had just landed and left the next one waiting. A query this
    # result was not told about now names itself instead of inventing an answer.
    result = strict_result(
        "the 0907 staging session result",
        scalars_all=templates,
        scalars_first=None,
        first=None,
    )
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


def test_the_fixture_models_a_row_the_database_could_hold():
    """BE-9420: no NOT NULL column may read None on the fixture instance.

    ``_make_template`` passed ``cli_tool=None`` explicitly, overriding the column's
    own ``default="claude"`` on a ``nullable=False`` column -- a shape no real row
    can ever have. Every test built on this fixture was therefore exercising the
    staging code against a template the database would have refused to store.

    Asserted across the whole NOT NULL set rather than ``cli_tool`` alone, because
    the instance is the wrong altitude for this: each of those columns is either
    named by the fixture or carries a Python default the factory applies, so the
    next override that nulls one out fails HERE instead of quietly reintroducing
    the same class of impossible row somewhere else in the file.
    """
    template = _make_template("Guard", "tester")

    nulled = sorted(
        column.name
        for column in AgentTemplate.__table__.columns
        if not column.nullable and getattr(template, column.name, None) is None
    )

    assert not nulled, (
        f"{nulled} are NOT NULL on agent_templates but read None on this fixture, "
        "so it models a row the database could never hold. Drop the explicit None "
        "override and let the column's own default apply."
    )


class TestStageCombinedSetup:
    """Test FileStaging.stage_combined_setup() for all 3 platforms."""

    @pytest.mark.asyncio
    async def test_claude_code_zip_structure(self, staging_dir, mock_session):
        """Claude Code ZIP contains commands/*.md and agents/*.md."""
        staging = FileStaging(db_session=mock_session)

        zip_path, msg = await staging.stage_combined_setup(
            staging_dir,
            "test-tenant",
            platform="claude_code",
        )

        assert zip_path is not None
        assert zip_path.exists()
        assert "Successfully staged" in msg

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            # Single /giljo command in commands/ directory (INF-6049a)
            assert "commands/giljo.md" in names
            # Agent templates are included in combined setup
            agent_files = [n for n in names if n.startswith("agents/")]
            assert len(agent_files) == 2

    @pytest.mark.asyncio
    async def test_gemini_cli_zip_structure(self, staging_dir, mock_session):
        """Gemini CLI ZIP contains commands/*.toml and agents/*.md."""
        staging = FileStaging(db_session=mock_session)

        zip_path, _ = await staging.stage_combined_setup(
            staging_dir,
            "test-tenant",
            platform="gemini_cli",
        )

        assert zip_path is not None

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            # Single /giljo command as TOML (INF-6049a)
            assert "commands/giljo.toml" in names
            # Agent templates included
            agent_files = [n for n in names if n.startswith("agents/")]
            assert len(agent_files) == 2

    @pytest.mark.asyncio
    async def test_codex_cli_zip_structure(self, staging_dir, mock_session):
        """Codex CLI ZIP contains skills/*/SKILL.md and agents/*.toml."""
        staging = FileStaging(db_session=mock_session)

        zip_path, _ = await staging.stage_combined_setup(
            staging_dir,
            "test-tenant",
            platform="codex_cli",
        )

        assert zip_path is not None

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            # Single $giljo skill (Codex's slash command format, INF-6049a)
            assert "skills/giljo/SKILL.md" in names
            # Agent templates as TOML
            agent_files = [n for n in names if n.startswith("agents/")]
            assert len(agent_files) == 2

    @pytest.mark.asyncio
    async def test_codex_agent_toml_content(self, staging_dir, mock_session):
        """Codex agent TOML files contain required fields."""
        staging = FileStaging(db_session=mock_session)

        zip_path, _ = await staging.stage_combined_setup(
            staging_dir,
            "test-tenant",
            platform="codex_cli",
        )

        with zipfile.ZipFile(zip_path) as zf:
            agent_files = [n for n in zf.namelist() if n.startswith("agents/")]
            for af in agent_files:
                content = zf.read(af).decode("utf-8")
                # Must have TOML-style key-value pairs
                assert "name =" in content
                assert "description =" in content
                assert "developer_instructions" in content
                assert "model =" not in content
                assert "model_reasoning_effort" not in content
                assert "gpt-5.3-codex" not in content
                parsed = tomllib.loads(content)
                assert parsed["name"]
                assert parsed["developer_instructions"]

    @pytest.mark.asyncio
    async def test_codex_standalone_agent_template_zip_uses_toml(self, staging_dir, mock_session):
        """Codex agent-template-only ZIP contains standalone TOML files, not agents.json."""
        staging = FileStaging(db_session=mock_session)

        zip_path, _ = await staging.stage_agent_templates(
            staging_dir,
            "test-tenant",
            platform="codex_cli",
        )

        assert zip_path is not None
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "agents.json" not in names
            agent_files = [n for n in names if n.startswith("agents/") and n.endswith(".toml")]
            assert len(agent_files) == 2
            for af in agent_files:
                parsed = tomllib.loads(zf.read(af).decode("utf-8"))
                assert parsed["name"].startswith("gil-")
                assert "model" not in parsed
                assert "model_reasoning_effort" not in parsed

    @pytest.mark.asyncio
    async def test_codex_agent_toml_dedupes_legacy_bootstrap(self, staging_dir):
        """Codex TOML removes legacy duplicated MCP startup blocks from role prose."""
        session = AsyncMock()
        session.info = {}  # tenant_session_context save/restore target
        # INF-9399: see the mock_session fixture -- same one-result-answers-everything
        # shape, same DB with no product rows.
        result = strict_result(
            scalars_all=[_make_template_with_duplicate_bootstrap()],
            scalars_first=None,
            first=None,
        )
        session.execute = AsyncMock(return_value=result)
        session.commit = AsyncMock()

        staging = FileStaging(db_session=session)

        zip_path, _ = await staging.stage_combined_setup(
            staging_dir,
            "test-tenant",
            platform="codex_cli",
        )

        with zipfile.ZipFile(zip_path) as zf:
            content = zf.read("agents/gil-tester.toml").decode("utf-8")

        parsed = tomllib.loads(content)
        instructions = parsed["developer_instructions"]
        # BE-9275b: the served bootstrap regenerates fresh from the current seed
        # (PRODUCT_NAME wording), so the duplicate-removal check anchors on that,
        # not the stale literal baked into this legacy-row fixture.
        from giljo_mcp.branding import PRODUCT_NAME

        assert instructions.count(f"You are part of a {PRODUCT_NAME} orchestration system") == 1
        assert "You are the testing specialist for GiljoAI MCP." in instructions
        assert all(line == line.rstrip() for line in instructions.splitlines())

    @pytest.mark.asyncio
    async def test_codex_agent_toml_dedupes_compact_legacy_bootstrap(self, staging_dir):
        """Codex TOML removes compact legacy MCP startup blocks from role prose."""
        session = AsyncMock()
        session.info = {}  # tenant_session_context save/restore target
        # INF-9399: see the mock_session fixture -- same one-result-answers-everything
        # shape, same DB with no product rows.
        result = strict_result(
            scalars_all=[_make_template_with_compact_duplicate_bootstrap()],
            scalars_first=None,
            first=None,
        )
        session.execute = AsyncMock(return_value=result)
        session.commit = AsyncMock()

        staging = FileStaging(db_session=session)

        for stage in (staging.stage_combined_setup, staging.stage_agent_templates):
            zip_path, _ = await stage(
                staging_dir,
                "test-tenant",
                platform="codex_cli",
            )

            with zipfile.ZipFile(zip_path) as zf:
                content = zf.read("agents/gil-tester.toml").decode("utf-8")

            parsed = tomllib.loads(content)
            instructions = parsed["developer_instructions"]
            from giljo_mcp.branding import PRODUCT_NAME

            assert instructions.count(f"You are part of a {PRODUCT_NAME} orchestration system") == 1
            assert "## Role" in instructions
            assert "Testing specialist for GiljoAI MCP." in instructions

    @pytest.mark.asyncio
    async def test_codex_agent_toml_escapes_regex_backslashes(self, staging_dir):
        """Codex setup ZIP emits TOML that parses when instructions contain regex backslashes."""
        session = AsyncMock()
        session.info = {}  # tenant_session_context save/restore target
        # INF-9399: see the mock_session fixture -- same one-result-answers-everything
        # shape, same DB with no product rows.
        result = strict_result(
            scalars_all=[_make_template_with_regex_backslashes()],
            scalars_first=None,
            first=None,
        )
        session.execute = AsyncMock(return_value=result)
        session.commit = AsyncMock()

        staging = FileStaging(db_session=session)

        zip_path, _ = await staging.stage_combined_setup(
            staging_dir,
            "test-tenant",
            platform="codex_cli",
        )

        with zipfile.ZipFile(zip_path) as zf:
            content = zf.read("agents/gil-reviewer.toml").decode("utf-8")

        parsed = tomllib.loads(content)
        assert "from.*saas\\|from.*demo" in parsed["developer_instructions"]
        assert "saas/\\|demo/" in parsed["developer_instructions"]

    @pytest.mark.asyncio
    async def test_zip_filename(self, staging_dir, mock_session):
        """Combined ZIP uses giljo_setup.zip filename."""
        staging = FileStaging(db_session=mock_session)

        zip_path, _ = await staging.stage_combined_setup(
            staging_dir,
            "test-tenant",
            platform="claude_code",
        )

        assert zip_path.name == "giljo_setup.zip"

    @pytest.mark.asyncio
    async def test_no_templates_still_includes_slash_commands(self, staging_dir):
        """If no agent templates exist, ZIP still contains slash commands."""
        session = AsyncMock()
        session.info = {}  # tenant_session_context save/restore target
        # INF-9399: this block was never hand-pinned by BE-9385a or BE-9385b, and I
        # assumed that meant the no-templates path short-circuits before the product
        # lookup. It does not -- file_staging.py:507 calls active_product_template_ids()
        # unconditionally, which reads .scalars().first(). So this fake HAS been
        # answering that query with a truthy child mock all along, claiming an active
        # product exists; the test passed anyway only because an empty template list
        # makes the outcome the same either way. Silently wrong, accidentally
        # harmless. The honest state for these fixtures is no active product.
        result = strict_result(scalars_all=[], scalars_first=None)
        session.execute = AsyncMock(return_value=result)

        staging = FileStaging(db_session=session)

        zip_path, _ = await staging.stage_combined_setup(
            staging_dir,
            "test-tenant",
            platform="claude_code",
        )

        assert zip_path is not None
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            # Single /giljo command present
            assert "commands/giljo.md" in names
            # No agent templates
            agent_files = [n for n in names if n.startswith("agents/")]
            assert len(agent_files) == 0

    @pytest.mark.asyncio
    async def test_invalid_platform_raises(self, staging_dir, mock_session):
        """Invalid platform raises ValueError."""
        staging = FileStaging(db_session=mock_session)

        with pytest.raises(ValueError, match="Unknown platform"):
            await staging.stage_combined_setup(
                staging_dir,
                "test-tenant",
                platform="invalid",
            )

    @pytest.mark.asyncio
    async def test_generic_zip_structure(self, staging_dir, mock_session):
        """Generic ZIP contains commands/*.md and agents/*.md without platform frontmatter."""
        staging = FileStaging(db_session=mock_session)

        zip_path, _ = await staging.stage_combined_setup(
            staging_dir,
            "test-tenant",
            platform="generic",
        )

        assert zip_path is not None

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            # Single /giljo command as plain MD reference (INF-6049a)
            cmd_files = [n for n in names if n.startswith("commands/")]
            assert cmd_files == ["commands/giljo_reference.md"]
            # Agent templates included in generic ZIP
            agent_files = [n for n in names if n.startswith("agents/")]
            assert len(agent_files) == 2

    @pytest.mark.asyncio
    async def test_updates_last_exported_at(self, staging_dir, mock_session, templates):
        """Combined setup updates agent template timestamps."""
        staging = FileStaging(db_session=mock_session)

        await staging.stage_combined_setup(
            staging_dir,
            "test-tenant",
            platform="claude_code",
        )

        # Commit should be called to persist export timestamps
        mock_session.commit.assert_awaited_once()
        # Templates should have timestamps set
        for t in templates:
            assert t.last_exported_at is not None
