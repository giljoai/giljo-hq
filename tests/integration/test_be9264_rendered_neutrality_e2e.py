# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9264 -- rendered-output neutrality E2E proof (chain closer).

tests/unit/test_neutrality_guard.py scans SOURCE FILES for dogfooding
contamination (GiljoAI naming itself as the target product, this repo's
CE/SaaS rules asserted as customer rules, a hardcoded Python/pytest
toolchain, GitHub/Gitea host references, ...). That is necessary but not
sufficient: some contamination only appears once a template is actually
RENDERED for a specific product/harness combination (an ``if tool ==
"claude-code":`` gated block, a per-language example that only shows up
when tech_stack.programming_languages is filled in, ...). This suite closes
that gap by creating a synthetic FOREIGN-STACK product -- Go backend, no
frontend framework, GitLab-hosted repo on branch ``main``, macOS target,
single-tenant, empty test config -- through the REAL service layer
(ProductService, never raw ORM writes), then rendering the customer-reaching
prompt/template surfaces through their REAL code paths (no parallel
renderer) and asserting neutrality on the actual rendered strings.

Neutrality is asserted by IMPORTING the guard's own pattern engine
(``match_prose_line`` from test_neutrality_guard.py) rather than forking a
second copy of the pattern list -- a rendered string is treated as one big
multi-line "string constant" the same way the guard's AST scanner treats a
source literal, so the exact same keep-regexes/nearby-window logic applies.

Edition Scope: Both (test-only; no production behavior change).

Parallel-safe: DB-backed fixtures use the rolled-back ``db_session``
(TransactionalTestContext, via tests/conftest.py); fresh tenant_key per
test; no module-level mutable state.
"""

from __future__ import annotations

import typing
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.config.defaults import DEFAULT_FIELD_PRIORITY
from giljo_mcp.models.products import Product
from giljo_mcp.prompt_generation.serena_instructions import for_role
from giljo_mcp.services.product_service import ProductService
from giljo_mcp.services.product_tuning_service import ProductTuningService
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.services.protocol_builder import (
    _build_orchestrator_protocol,
    _generate_agent_protocol,
)
from giljo_mcp.template_seeder import _get_check_in_protocol_section, _get_default_templates_v103
from giljo_mcp.tenant import TenantManager, current_tenant
from giljo_mcp.tools.giljo_guide import build_giljo_guide
from tests.unit.neutrality_guard_baseline import BASELINE
from tests.unit.test_neutrality_guard import _NEARBY_WINDOW, match_prose_line


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Neutrality assertion helper -- IMPORTS the guard's pattern engine, does not
# fork it (BE-9264 mandate).


# Pre-existing, DOCUMENTED baseline offenders (tests/unit/neutrality_guard_baseline.py)
# are audited-but-not-yet-fixed static contamination -- this suite proves there is no
# NEW dynamic-rendering-only contamination, it does not re-litigate those. Reusing the
# baseline's own excerpts (rather than hardcoding a second copy) keeps the two scans
# in lockstep: shrink the baseline and this tolerance automatically tightens too.
_BASELINE_EXCERPTS = tuple(note.split(" :: ", 2)[-1] for _, note in BASELINE)


def _is_known_documented_offender(line_text: str) -> bool:
    return any(excerpt and (excerpt in line_text or line_text in excerpt) for excerpt in _BASELINE_EXCERPTS)


def _neutral_hits(text: str, *, allow: frozenset[str] = frozenset()) -> list[tuple[int, str, str]]:
    """Run the guard's pattern engine over a RENDERED runtime string.

    Mirrors ``test_neutrality_guard.scan_file``'s per-string-constant
    windowing (a nearby-window keep-regex sees +/-3 lines within the SAME
    string), but for a string produced by calling a real render function at
    test time, not an AST literal pulled from a source file.

    ``allow``: pattern_ids to skip entirely for THIS render -- used only when
    the render was deliberately requested FOR a harness that legitimately
    carries that pattern's vocabulary (e.g. calling a builder with
    ``tool="claude-code"`` legitimately renders "TodoWrite"/"ToolSearch";
    the corresponding non-claude render, checked separately with no
    allowance, is what actually proves the gating).
    """
    lines = text.split("\n")
    total_len = sum(len(ln) for ln in lines)
    hits: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        window = lines[max(0, i - _NEARBY_WINDOW) : i + _NEARBY_WINDOW + 1]
        for pattern_id in match_prose_line(line, string_len=total_len, window=window):
            if pattern_id in allow:
                continue
            if _is_known_documented_offender(line.strip()):
                continue
            hits.append((i + 1, pattern_id, line.strip()))
    return hits


def _assert_neutral(text: str, label: str, *, allow: frozenset[str] = frozenset()) -> None:
    hits = _neutral_hits(text, allow=allow)
    assert not hits, f"{label}: dogfooding contamination found in rendered output: {hits}"


# ---------------------------------------------------------------------------
# Fixtures -- synthetic FOREIGN-STACK product, created via the real service
# layer (never raw ORM writes).


@pytest_asyncio.fixture
async def foreign_stack_product(db_manager, db_session) -> tuple[Product, str]:
    """A Go/GitLab/macOS product, deliberately nothing like this repo's own stack."""
    tenant_key = TenantManager.generate_tenant_key()
    service = ProductService(db_manager, tenant_key, test_session=db_session)
    product = await service.create_product(
        name=f"Foreign Stack Product {uuid4().hex[:8]}",
        description=(
            "A synthetic foreign-stack product used to prove Giljo HQ's rendered "
            "prompts stay neutral for a completely different tech stack: Go backend, "
            "no frontend framework, GitLab-hosted repo (default branch main), macOS "
            "target, single-tenant, no CE/SaaS-style editions."
        ),
        tech_stack={
            "programming_languages": "Go",
            "backend_frameworks": "net/http (standard library)",
            "frontend_frameworks": "none (headless service)",
            "databases_storage": "PostgreSQL",
        },
        architecture={"primary_pattern": "modular monolith"},
        test_config={},
        product_memory={"git_integration": {"host": "gitlab", "default_branch": "main"}},
        target_platforms=["macos"],
    )
    return product, tenant_key


@pytest_asyncio.fixture
async def foreign_stack_project(db_manager, db_session, foreign_stack_product):
    """A project bound to the foreign-stack product, for the staging/thin-prompt renders."""
    product, tenant_key = foreign_stack_product
    manager = TenantManager()
    manager.set_current_tenant(tenant_key)
    token = current_tenant.set(tenant_key)
    try:
        project_service = ProjectService(db_manager=db_manager, tenant_manager=manager, test_session=db_session)
        project = await project_service.create_project(
            name="Foreign Stack Rendering Probe",
            mission="Render every customer-reaching prompt surface for a Go/GitLab/macOS product.",
            description="A throwaway vehicle project used only to drive the rendered-neutrality proof.",
            product_id=str(product.id),
            tenant_key=tenant_key,
        )
        yield project, product, tenant_key
    finally:
        current_tenant.reset(token)


# ---------------------------------------------------------------------------
# 1. The synthetic product itself, created through the REAL service layer.


async def test_product_created_via_real_service_layer(foreign_stack_product):
    product, tenant_key = foreign_stack_product
    assert isinstance(product, Product)
    assert product.tenant_key == tenant_key
    assert product.target_platforms == ["macos"]


# ---------------------------------------------------------------------------
# 2. template_seeder personas (all 6) -- seeded verbatim to every new tenant.


async def test_template_seeder_personas_neutral_and_role1_present():
    templates = _get_default_templates_v103()
    names = {t["name"] for t in templates}
    assert names == {"orchestrator", "implementer", "tester", "analyzer", "reviewer", "documenter"}

    for template in templates:
        text = template["user_instructions"]
        _assert_neutral(text, f"template_seeder persona '{template['name']}'")

    orchestrator_text = next(t["user_instructions"] for t in templates if t["name"] == "orchestrator")
    # Role-1 presence (over-correction check): the platform still brands
    # itself and still names its own tools/skills.
    assert "Giljo HQ" in orchestrator_text
    assert "get_staging_instructions" in orchestrator_text
    assert "get_job_mission" in orchestrator_text


async def test_check_in_protocol_todowrite_gated_by_harness():
    claude_render = _get_check_in_protocol_section(tool="claude-code")
    codex_render = _get_check_in_protocol_section(tool="codex")

    # harness_tool_names allowed ONLY on the claude-code variant -- it was
    # deliberately requested for that harness, so TodoWrite/ToolSearch text is
    # Role-1 EXPECTED there; the codex variant below is checked with no
    # allowance, which is what actually proves the gating.
    _assert_neutral(claude_render, "check-in protocol section (claude-code)", allow=frozenset({"harness_tool_names"}))
    _assert_neutral(codex_render, "check-in protocol section (codex)")

    # Role-1 presence: the claude-code render still carries its harness-specific
    # TaskCreate-override + ToolSearch bootstrap guidance (over-correction check).
    assert "TaskCreate" in claude_render
    assert "ToolSearch" in claude_render
    # The NON-claude render must carry neither.
    assert "TaskCreate" not in codex_render
    assert "ToolSearch" not in codex_render


# ---------------------------------------------------------------------------
# 3. Protocol sections via protocol_builder -- worker + orchestrator, for
#    claude-code AND a non-claude harness (codex).


async def test_worker_protocol_neutral_git_block_host_blind_and_todowrite_gated():
    common = {
        "job_id": str(uuid4()),
        "tenant_key": str(uuid4()),
        "agent_name": "implementer",
        "execution_mode": "multi_terminal",
        "git_integration_enabled": True,
        "job_type": "agent",
    }
    claude_render = _generate_agent_protocol(tool="claude-code", **common)
    codex_render = _generate_agent_protocol(tool="codex", **common)

    _assert_neutral(claude_render, "worker protocol (claude-code)", allow=frozenset({"harness_tool_names"}))
    _assert_neutral(codex_render, "worker protocol (codex)")

    for label, render in (("claude-code", claude_render), ("codex", codex_render)):
        # P4: worker_body git block -- host-agnostic framing (BE-9256).
        assert "Git Commit (REQUIRED - Git Integration Enabled)" in render, label
        assert "git add" in render, label
        assert "github" not in render.lower(), label
        assert "gitea" not in render.lower(), label

    # Role-1 presence vs. non-claude gating (BE-9260's task_list_phrase()):
    assert "TodoWrite" in claude_render
    assert "TodoWrite" not in codex_render


async def test_orchestrator_protocol_neutral_and_role1_present():
    common = {
        "cli_mode": True,
        "project_id": str(uuid4()),
        "orchestrator_id": str(uuid4()),
        "tenant_key": str(uuid4()),
        "git_integration_enabled": True,
        "include_implementation_reference": True,  # CH5 -- chapters_reference completion step
    }
    claude_chapters = _build_orchestrator_protocol(tool="claude-code", **common)
    codex_chapters = _build_orchestrator_protocol(tool="codex", **common)

    claude_render = "\n".join(str(v) for v in claude_chapters.values())
    codex_render = "\n".join(str(v) for v in codex_chapters.values())

    _assert_neutral(claude_render, "orchestrator protocol chapters (claude-code)")
    _assert_neutral(codex_render, "orchestrator protocol chapters (codex)")

    for render in (claude_render, codex_render):
        # Role-1 presence: Giljo HQ as the orchestration SYSTEM, tool
        # names and /giljo identifiers still present where expected.
        assert "spawn_job" in render
        assert "get_context" in render
        # CH5 (chapters_reference) completion step is included.
        assert "ch5_reference" in claude_chapters
        assert claude_chapters["ch5_reference"]


# ---------------------------------------------------------------------------
# 4. serena_instructions block -- conditional wording, no hardcoded language.


async def test_serena_instructions_neutral_and_conditional():
    for role in ("orchestrator", "implementer", "tester", "analyzer", "reviewer", "documenter"):
        text = for_role(role)
        _assert_neutral(text, f"serena_instructions for_role('{role}')")
        # BE-9260: conditional wording, never an unconditional "Python-only" claim.
        assert "if it is not registered" in text.lower() or "prefer them" in text.lower()
        assert "python-only in this" not in text.lower()


# ---------------------------------------------------------------------------
# 5. TUNING_PROMPT_TEMPLATE render -- for the REAL Go/GitLab/macOS product.


async def test_tuning_prompt_renders_neutral_for_foreign_stack_product(db_manager, db_session, foreign_stack_product):
    product, tenant_key = foreign_stack_product
    service = ProductTuningService(db_manager, tenant_key, test_session=db_session)

    async def _fake_user_configs(_session, _user_id):
        return DEFAULT_FIELD_PRIORITY, {}

    service._get_user_configs = _fake_user_configs  # boundary mock: user/toggle lookup is not under test here

    result = await service.assemble_tuning_prompt(
        product_id=str(product.id),
        user_id=str(uuid4()),
        sections=["tech_stack"],
    )
    prompt = result["prompt"]
    _assert_neutral(prompt, "TUNING_PROMPT_TEMPLATE render (foreign-stack product)")

    # The product's own (Go) data is reflected, not this repo's (Python) stack.
    assert "Go" in prompt
    assert "pytest" not in prompt.lower()

    # Multi-ecosystem test-discovery step (P3) renders correctly and stays
    # stack-neutral even for a non-Python product.
    assert "go test -list ." in prompt
    assert "collect-only" in prompt


# ---------------------------------------------------------------------------
# 6. Staging/thin prompts -- claude-code AND a non-claude harness (codex).


async def test_thin_prompt_neutral_and_todowrite_toolsearch_gated(foreign_stack_project):
    from giljo_mcp.prompts.staging_prompt_builder import StagingPromptBuilder

    project, product, _tenant_key = foreign_stack_project
    builder = StagingPromptBuilder()

    common = {
        "orchestrator_id": str(uuid4()),
        "agent_id": str(uuid4()),
        "project_id": str(project.id),
        "project": project,
        "product": product,
        "field_toggles": {},
        "depth_config": {},
    }
    claude_render = builder.build_thin_prompt(tool="claude-code", **common)
    codex_render = builder.build_thin_prompt(tool="codex", **common)

    _assert_neutral(claude_render, "thin prompt (claude-code)", allow=frozenset({"harness_tool_names"}))
    _assert_neutral(codex_render, "thin prompt (codex)")

    assert "TodoWrite" in claude_render
    assert "ToolSearch" in claude_render
    assert "TodoWrite" not in codex_render
    assert "ToolSearch" not in codex_render


# ---------------------------------------------------------------------------
# 7. giljo_guide text.


async def test_giljo_guide_neutral():
    guide_text = build_giljo_guide()["guide"]
    _assert_neutral(guide_text, "giljo_guide text")


# ---------------------------------------------------------------------------
# 8. ai_tools Terminal labels -- neutral, no Windows-only shell assumed.


async def test_ai_tools_terminal_labels_neutral():
    from api.endpoints.ai_tools import CONFIG_GENERATORS

    for tool_id, config in CONFIG_GENERATORS.items():
        label = config["file_location"]
        _assert_neutral(label, f"ai_tools CONFIG_GENERATORS['{tool_id}']['file_location']")
        assert "powershell" not in label.lower(), tool_id


# ---------------------------------------------------------------------------
# 9. GIT_COMMIT_TITLE_REQUIRED rejection hint -- neutral, actionable, host-blind.


async def test_git_commit_title_required_hint_neutral_and_actionable():
    from api.endpoints.mcp_tools._memory_tools import write_memory_entry, write_project_closeout
    from giljo_mcp.schemas.jsonb_validators import GIT_LOG_TITLED_COMMAND_HINT, GitCommitTitleRequiredError

    for fn in (write_project_closeout, write_memory_entry):
        hints = typing.get_type_hints(fn, include_extras=True)
        description = hints["git_commits"].__metadata__[0].description
        _assert_neutral(description, f"{fn.__name__} git_commits Field description")
        assert "git log --format=" in description
        assert "github" not in description.lower()
        assert "gitea" not in description.lower()

    message = str(GitCommitTitleRequiredError("deadbeef"))
    _assert_neutral(message, "GitCommitTitleRequiredError message")
    assert GIT_LOG_TITLED_COMMAND_HINT in message
    assert "github" not in message.lower()
    assert "gitea" not in message.lower()
