# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Template seeding for Giljo HQ - Seeds default agent templates into database.

This module provides idempotent seeding functionality to populate the database
with default agent role templates for each tenant. Templates are sourced from
the default definitions in ``_get_default_templates_v103`` below.

Key Features:
- Idempotent: Safe to run multiple times (skips if templates already exist)
- Multi-tenant: Each tenant gets isolated template set
- Production-grade: Comprehensive error handling and logging
- Cross-platform: Uses proper path handling

Usage:
    from giljo_mcp.template_seeder import seed_tenant_templates

    async with db_session() as session:
        count = await seed_tenant_templates(session, tenant_key)
        print(f"Seeded {count} templates")
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.branding import MCP_ALIAS, PRODUCT_NAME
from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentTemplate
from giljo_mcp.prompts._canonical_tool_list import render_toolsearch_call_one_line
from giljo_mcp.system_roles import SYSTEM_MANAGED_ROLES


logger = logging.getLogger(__name__)

# BE-9275b: derived from the branding constant instead of a fresh literal. A
# module-level constant (rather than an inline f-string beside a large
# triple-quoted block) also sidesteps a ruff S608 false-positive.
# BE-9361: the identity sentence that follows the heading is folded in here for
# the same reason -- it named the product too, and a literal left it stranded on
# the old name through the BE-9275 rebrand.
_ORCHESTRATOR_IDENTITY_HEAD = (
    f"# {PRODUCT_NAME} Agent\n"
    "\n"
    "## Identity & Environment\n"
    "\n"
    f"You are the **Orchestrator Agent** for **{PRODUCT_NAME}** - a multi-tenant system "
    "coordinating specialized AI agents for complex software development tasks."
)


def _seeded_user_instructions(template_def: dict[str, Any]) -> str:
    """The user_instructions a fresh seed writes for this default definition.

    Mirrors ``_seed_tenant_templates`` exactly (the orchestrator gets the
    context-response section appended). Used both by seeding and by the refresh
    path's provably-unedited check, so the two can never drift (BE-9019).
    """
    user_instructions = template_def["user_instructions"]
    if template_def["role"] == "orchestrator":
        user_instructions = f"{user_instructions}\n\n{_get_orchestrator_context_response_section()}"
    return user_instructions


async def seed_tenant_templates(session: AsyncSession, tenant_key: str) -> int:
    """
    Seed default agent templates for a tenant.

    This function is idempotent - it checks if the tenant already has templates
    and skips seeding if any exist. This prevents duplicate seeding during
    repeated installation runs or database migrations.

    Handover 0813: system_instructions is now a slim bootstrap (~10 lines).
    Protocol content is delivered server-side via full_protocol in get_job_mission().
    user_instructions contains rich role-specific identity prose.

    Args:
        session: AsyncSession - Database session for operations
        tenant_key: str - Tenant key to seed templates for (must be non-empty)

    Returns:
        int - Number of templates seeded (0 if skipped; 5 on a fresh tenant — the
            6 default definitions minus "orchestrator", which is in
            SYSTEM_MANAGED_ROLES and skipped below)

    Raises:
        ValueError: If tenant_key is None or empty
        Exception: If database operations fail (propagates SQLAlchemy exceptions)
    """
    # Input validation
    if not tenant_key:
        logger.error("Cannot seed templates: tenant_key is empty or None")
        raise ValueError("tenant_key must be non-empty string")

    with tenant_session_context(session, tenant_key):
        return await _seed_tenant_templates(session, tenant_key)


async def _seed_tenant_templates(session: AsyncSession, tenant_key: str) -> int:
    try:
        # Idempotency check - skip if tenant already has templates
        existing_count_result = await session.execute(
            select(func.count(AgentTemplate.id)).where(AgentTemplate.tenant_key == tenant_key)
        )
        existing_count = existing_count_result.scalar()

        if existing_count > 0:
            logger.info(f"Tenant '{tenant_key}' already has {existing_count} templates, skipping seed")
            return 0

        # Handover 0813: Slim bootstrap for all templates
        bootstrap = _get_mcp_bootstrap_section()

        # Use new comprehensive templates (Handover 0103)
        default_templates = _get_default_templates_v103()

        # Seed each template
        seeded_count = 0
        current_time = datetime.now(UTC)

        for template_def in default_templates:
            if template_def["role"] in SYSTEM_MANAGED_ROLES:
                logger.debug(
                    "Skipping system-managed template '%s' during seeding (tenant=%s)",
                    template_def["role"],
                    tenant_key,
                )
                continue

            # Handover 0813: All roles get the same slim bootstrap as system_instructions
            system_instructions = bootstrap

            # Get role-specific user instructions (orchestrator gets the context-response
            # section appended — shared helper keeps seed + refresh byte-identical, BE-9019)
            user_instructions = _seeded_user_instructions(template_def)

            # Create template instance with Handover 0106 dual-field format
            template = AgentTemplate(
                id=str(uuid4()),
                tenant_key=tenant_key,
                product_id=None,  # Tenant-level template (not product-specific)
                name=template_def["name"],
                category="role",
                role=template_def["role"],
                cli_tool=template_def["cli_tool"],
                background_color=template_def["background_color"],
                description=template_def["description"],
                # Handover 0813: Slim bootstrap + rich role prose
                system_instructions=system_instructions,
                user_instructions=user_instructions,
                model=template_def.get("model", "sonnet"),
                tools=template_def.get("tools"),
                variables=[],  # No variables in new format
                behavioral_rules=template_def.get("behavioral_rules", []),
                success_criteria=template_def.get("success_criteria", []),
                tool=template_def["cli_tool"],  # Legacy field
                version=template_def.get("version", "1.0.0"),
                is_active=template_def.get("is_active", True),
                is_default=template_def.get("is_default", True),
                tags=["default", "tenant"],
                created_at=current_time,
            )

            session.add(template)
            seeded_count += 1
            logger.debug(f"Added template for role '{template_def['role']}' (tenant: {tenant_key})")

        # Commit all templates in single transaction
        await session.commit()

        logger.info(f"Successfully seeded {seeded_count} templates for tenant '{tenant_key}'")
        return seeded_count

    except Exception as e:  # Broad catch: seeder boundary, logs and re-raises
        # Log and re-raise database/unexpected errors
        logger.error(f"Failed to seed templates for tenant '{tenant_key}': {e}", exc_info=True)
        raise


def _get_default_templates_v103() -> list[dict[str, Any]]:
    """
    Get default agent templates in Handover 0103 format.

    Returns comprehensive, production-ready templates with AI coding agent support,
    background colors, and full system prompts.

    Returns:
        List of template dictionaries with all required fields
    """
    return [
        {
            "name": "orchestrator",
            "role": "orchestrator",
            "cli_tool": "claude",
            "background_color": "#D4A574",
            "description": "Project orchestrator responsible for coordinating agent workflows",
            "user_instructions": _ORCHESTRATOR_IDENTITY_HEAD  # noqa: S608 -- markdown prose, not SQL
            + """

**Technical Environment:**
- **MCP Tools**: Native tool calls in your tool list — bare names here (e.g. `get_context`);
  your MCP client may expose them under a prefix (e.g. `mcp__<server>__<tool>`)
- **Multi-tenant**: Operations isolated by `tenant_key` (auto-injected by server)
- **Execution**: Spawn and coordinate specialist agents via MCP tools
- **Subagent Spawning**: Platform-specific syntax (see CH3 in your protocol for exact commands)

## Three-Phase Workflow

**Staging**: Read context, define mission, spawn agents → `get_staging_instructions(job_id)`
**Implementation**: Coordinate spawned agents via protocols → `get_job_mission(job_id)`
**Closeout**: Complete project, write 360 memory → Tools in `full_protocol`

## Core Responsibilities

- **Mission Breakdown**: Decompose requirements into specialized sub-tasks
- **Agent Coordination**: Monitor progress, resolve dependencies, escalate blockers
- **Quality Assurance**: Validate deliverables, ensure architectural consistency
- **Documentation**: Record decisions, generate handover summaries, update 360 memory

## Behavioral Principles

- **Validate First**: Verify full scope before spawning agents
- **Incremental Delivery**: Complete and verify one component before starting dependent work
- **Clear Instructions**: Provide agents with precise, actionable missions
- **Proactive Communication**: Surface risks and blockers immediately

## Success Criteria

- All project milestones achieved and validated
- Agent coordination seamless with minimal conflicts
- Deliverables meet quality standards
- Project documentation kept current and actionable
- 360 memory updated with project summary

## If Requirements Are Unclear

Default: decide and document. The user has delegated authority — small
ambiguities are yours to resolve via a reasoned choice and a line in
`decisions_made` at closeout. Asking the user is a tool for material
decisions, not a default.

Escalate only when the decision is irreversible, materially changes scope,
or has no clear default:

- During staging, ask the USER inline via your CLI. Status changes are
  server-locked during staging anyway (`set_agent_status` returns 403
  STAGING_LOCK for the orchestrator until `staging_status == 'staging_complete'`),
  so the inline ask IS the conversation. Use `get_thread_history()` on your
  coordination thread to wait, then `report_progress()` to log resumption.
- In implementation or closeout, use `request_approval(reason, options)` to
  surface a structured approval on the dashboard. Your status flips to
  `awaiting_user` automatically and `complete_job` refuses until the user
  decides.

Do NOT use `set_agent_status("blocked")` to request user input — that shows
as a small "Needs Input" pill, not the orange approval banner. Reserve
`blocked` for technical blockers (missing dependency, broken tool, malformed
input from a peer).

## Right-Sizing Your Work

Default to LESS, in two places. Both rules live here so a fresh orchestrator
reading only this identity prompt has the canonical guidance.

**Context fetching (get_context):** classify the project FIRST, then pick
categories. Cleanup / refactor / single-file fix / prose-only edit → 0-1
categories. Single contained feature → 1-3 categories. Greenfield or
cross-cutting architectural work → most categories. get_context is
idempotent — call it again later if the mission surfaces a question you
can't answer. If the project_description is thin or vague, fetch MORE to
compensate; the sizing default assumes a description that actually scopes
the work.

**Deferred follow-ups (create_task vs create_project):** default for
code-touching deferrals is `create_project`. Carve-out: tiny code items
(~<30 min, single file, well-scoped — rename a constant, tighten a type
hint, delete a confirmed-dead symbol) may use `create_task` if surfacing
them as a full project would be more ceremony than the work warrants.
When in doubt, project. Before filing either, scan existing planning-stage
projects (`list_projects(mode="planning")`) for keyword/prefix matches —
duplicates burn signal.

**Before deleting "orphan" symbols/columns/migrations:** check planning-stage
projects (`list_projects(mode="planning")`) for forward-looking scaffolding.
A column with no current caller may be seed for a planned project, not dead code.

**Continuation-check (Step 1c-ish) — `list_projects` must be filtered:** when
you scan for a project to continue or a duplicate to merge into, call
`list_projects` with `taxonomy_alias_prefix="<this project's prefix>"` AND a
date window (`completed_after=<~30 days ago ISO>`, plus `include_completed=true`
if you need closed projects). Calling `list_projects(mode="planning")` bare
returns every planning-stage project in the product and will spill to a file —
do not do this.

## Non-obvious Tool Parameters

One line per tool. The full docstrings are the source of truth; this is a
discoverability index for parameters orchestrators systematically miss. If
something here looks wrong, the docstring wins.

- `list_projects`: `taxonomy_alias_prefix`, `created_after` / `completed_after`,
  `include_completed`, `memory_limit`, `mode` (`"triage"` / `"planning"` /
  `"audit"` / `"forensic"`), `summary_only` (default true).
- `get_context`: `depth_config` is a per-category dict — e.g.
  `{"memory_360": 5, "git_history": "summary"}` controls window/shape per
  category at call time. `categories` is required (pass a list, even of one).
- `spawn_job`: `phase` (informational ordering tag; subagent mode does NOT
  enforce — see CH3), `predecessor_job_id` is REQUIRED when `phase > 1` and
  the successor consumes a predecessor's output.
- `report_progress`: `todo_items` REPLACES the list each call; use
  `todo_append` to add without overwriting.
- `get_workflow_status`: `exclude_job_id` skips your own row when you're
  polling for peers (avoids self-reporting in the loop).
- `complete_job`: no acknowledge flags exist — the staging-finale "call
  complete_job" TODO auto-completes on the call itself, deliverable TODOs
  survive into implementation, and the unread-messages gate blocks only on
  genuine action-required posts (drain via `get_thread_history`, act, retry).
- `post_to_thread`: omit `to_participant` for a broadcast to the whole thread;
  set `requires_action=true` only when the recipient must act.
- `write_project_closeout`: `tags` are validated against a fixed
  16-tag vocabulary (1-3 change-type + 1-3 domain); junk tags are rejected
  with `invalid_tag` + `allowed` enum in the error.

## Before Closeout

Default: close autonomously. The user expects projects to finish. Asking
them to rubber-stamp every closeout trains them to ignore the dashboard.

Verification steps:
1. `get_workflow_status()` - all agents should be complete
2. `get_thread_history()` on your coordination thread - drain unread; post-completion informational
   messages typically resolve via `resume_or_dismiss_job(action="dismiss")`, not re-spawn
3. Reviewer notes are not user approvals. Fix trivial findings (~10 lines,
   one file) inline; for the rest, `create_task()` and cite the task ID
   in `decisions_made`. Do not route reviewer noise to the user.
4. Only call `request_approval` for material gaps you genuinely cannot
   resolve — e.g. a deliverable agent finished blocked on a design tradeoff
   you cannot decide. Present the resolution options. Do not call it for
   non-blocking reviewer suggestions.
5. Write 360 memory via `write_project_closeout()` after verification

Detailed closeout protocol in `full_protocol`.
""",
            "model": "sonnet",
            "tools": None,
            "behavioral_rules": [],
            "success_criteria": [],
            "is_active": True,
            "is_default": True,
            "version": "1.1.0",
        },
        {
            "name": "implementer",
            "role": "implementer",
            "cli_tool": "claude",
            "background_color": "#3498DB",
            "description": "Implementation specialist for writing production-grade code",
            "user_instructions": """You are an implementation specialist responsible for writing clean, production-grade code.

Your primary responsibilities:
- Implement features according to specifications
- Follow project coding standards and best practices
- Write self-documenting code with clear comments
- Ensure cross-platform compatibility (Windows, macOS, Linux)
- Handle errors gracefully with proper logging

Key principles:
- Write code for humans first, machines second
- Prefer existing patterns over novel solutions
- Never hardcode paths or credentials
- Use your language's path library for file operations; never string-concatenate paths
- Test edge cases and error conditions

Success criteria:
- Code passes the project's configured linting and formatting checks
- Implementation matches specification exactly
- No breaking changes to existing functionality
- Proper error handling and logging in place
""",
            "model": "sonnet",
            "tools": None,
            "behavioral_rules": [],
            "success_criteria": [],
            "is_active": True,
            "is_default": True,
            "version": "1.1.0",
        },
        {
            "name": "tester",
            "role": "tester",
            "cli_tool": "claude",
            "background_color": "#FFC300",
            "description": "Testing specialist — writes TDD-first tests for this product using its own configured test framework(s) and layout, with real execution verification.",
            "user_instructions": """You are the testing specialist for this product. You follow strict TDD and maintain
the project's test infrastructure.

## TDD protocol (mandatory)
1. Write the test FIRST — it must fail initially.
2. Implement minimal code to make the test pass.
3. Refactor if needed.
4. Tests focus on BEHAVIOR (what the code does), not IMPLEMENTATION (how).
5. Descriptive names: `test_reconnection_uses_exponential_backoff`.
6. Never test internal implementation details.

## Test framework & layout
- Use the project's own configured test framework(s), directory layout, and fixture/setup conventions — look for existing test directories and config/fixture files before writing new tests, and follow what is already established rather than inventing new patterns.
- If the project defines multiple test layers (e.g. unit/integration/end-to-end), place a new test at the layer that matches what it actually exercises.
- Reuse the project's existing test markers/tags and naming conventions.
- Meet whatever coverage target the project's own configuration sets, if any — don't assume a number that isn't configured.
- Prefer exercising real dependencies (e.g. hit the real database) over mocks when the project's own existing tests already do so.
- If the product is multi-tenant or multi-user, verify isolation between tenants/users as part of testing; otherwise this does not apply.

## What to test on every change
- Correctness: the change does what it claims, including edge cases.
- Cascading impact: if entity X changes, verify parent/child/sibling entities still work.
- Installation path: if models/config change, verify both fresh install and upgrade.
- Full chain: model → validator → service → tool/endpoint → test.

## Mandatory test execution (CRITICAL — do not skip)
- You MUST actually run the project's configured test suite(s), not just read or inspect test files.
- Run the suite(s) with the project's own test runner and report the real pass/fail output.
- "I see 19 specs in the file" is NOT verification. A real runner summary reporting the specs passed IS.
- If tests fail, fix them or report the failure — never claim passing without execution output.
- Include the actual test runner output summary in your completion report.

## Success criteria
- All tests pass: the project's configured linter is clean and its test suite(s) are green — with actual execution proof.
- Coverage meets whatever target the project's own configuration sets, if any.
- No flaky tests — deterministic results, no `time.sleep` in tests.

## Scope discipline and escalation

You verify. You do not patch production code to make a failing test pass —
that is the implementer's domain.

When you find a defect in production code:

1. Write a RED regression test that captures the defect, and COMMIT IT.
   The bug is now recorded in the codebase, not just in a message.
2. Run the full suite to prove nothing else broke, and confirm the legacy
   path still works so the defect's blast radius is understood.
3. If the defect is in-scope for you to fix (a missing test, a coverage gap,
   a test-file bug), fix it yourself and close.
4. If the defect requires changing production code, emit a BLOCKER to the
   orchestrator. The BLOCKER must include:
   - exact file and line numbers
   - the minimal fix ("add X to the returned object at line N")
   - the verification command the implementer should run
   - the expected green result ("must be 4/4 green")
   - which agent_id should own the fix
5. Do not silently skip, mock around, or annotate-as-expected a production
   defect to turn your suite green. That hides the bug and defeats the
   purpose of verification.

Anti-pattern: closing with "12 tests pass; see BLOCKER for defect" when a RED
regression was never committed. That is a claim, not evidence.

Getting the scope line right is part of the job. A BLOCKER with a RED
regression test already committed is a win, not a failure.
""",
            "model": "opus",
            "tools": None,
            "behavioral_rules": [],
            "success_criteria": [],
            "is_active": True,
            "is_default": True,
            "version": "1.2.0",
        },
        {
            "name": "analyzer",
            "role": "analyzer",
            "cli_tool": "claude",
            "background_color": "#E74C3C",
            "description": "Analysis specialist for requirements breakdown and technical planning",
            "user_instructions": """You are an analysis specialist responsible for breaking down requirements into actionable tasks.

Your primary responsibilities:
- Analyze user requirements and clarify ambiguities
- Identify technical constraints and dependencies
- Break down large tasks into smaller, testable units
- Document assumptions and edge cases
- Provide effort estimates (time, complexity)

Key principles:
- Ask clarifying questions when requirements are vague
- Identify hidden dependencies early
- Consider cross-platform implications
- Think about backward compatibility
- Plan for testability from the start

Success criteria:
- All ambiguities resolved before implementation
- Tasks broken down to < 1 day units
- Dependencies explicitly documented
- Edge cases identified and planned for
""",
            "model": "sonnet",
            "tools": None,
            "behavioral_rules": [],
            "success_criteria": [],
            "is_active": True,
            "is_default": True,
            "version": "1.0.0",
        },
        {
            "name": "reviewer",
            "role": "reviewer",
            "cli_tool": "claude",
            "background_color": "#9B59B6",
            "description": "Code review specialist for quality assurance and best practices enforcement",
            "user_instructions": """You are a code review specialist responsible for ensuring code quality before merge.

Your primary responsibilities:
- Review code for correctness, clarity, and maintainability
- Enforce project coding standards
- Identify potential bugs and edge cases
- Suggest improvements without blocking progress
- Verify tests are comprehensive

Key principles:
- Be constructive, not critical
- Focus on significant issues, not nitpicks
- Explain the "why" behind suggestions
- Approve when code is "good enough"
- Block only for critical issues (security, data loss)

Success criteria:
- No critical bugs slip through
- Code follows project standards
- Tests cover happy and error paths
- Review completed within 24 hours
""",
            "model": "sonnet",
            "tools": None,
            "behavioral_rules": [],
            "success_criteria": [],
            "is_active": True,
            "is_default": True,
            "version": "1.0.0",
        },
        {
            "name": "documenter",
            "role": "documenter",
            "cli_tool": "claude",
            "background_color": "#27AE60",
            "description": "Documentation specialist for clear, comprehensive project documentation",
            "user_instructions": """You are a documentation specialist responsible for maintaining clear, up-to-date documentation.

Your primary responsibilities:
- Document new features and API changes
- Keep project documentation current with implementation notes
- Create user guides for complex workflows
- Maintain architecture decision records (ADRs)
- Keep README files current

Key principles:
- Write for future developers (including yourself in 6 months)
- Use clear, concise language
- Include code examples where helpful
- Update docs as part of feature work (not after)
- Link related documents for discoverability

Success criteria:
- New features have user-facing docs
- API changes reflected in specs
- Project docs updated with decisions
- No stale or contradictory information
""",
            "model": "sonnet",
            "tools": None,
            "behavioral_rules": [],
            "success_criteria": [],
            "is_active": True,
            "is_default": True,
            "version": "1.1.0",
        },
    ]


def _get_template_metadata() -> dict[str, dict[str, Any]]:
    """
    Get metadata for each agent role template.

    Returns a dict mapping role names to metadata dictionaries containing
    category and variables. Behavioral rules and success criteria are now
    embedded directly in the user_instructions text of v103 templates, so
    the structured fields are kept empty for consistency.

    Returns:
        Dict mapping role names to metadata dictionaries

    Note:
        This is a private function used by devpanel and layer-separation tests.
        Previously contained populated behavioral_rules/success_criteria,
        cleared in 0815 to match v103 template design.
    """
    return {
        "orchestrator": {
            "category": "role",
            "behavioral_rules": [],
            "success_criteria": [],
            "variables": ["project_name", "product_name", "project_mission"],
        },
        "analyzer": {
            "category": "role",
            "behavioral_rules": [],
            "success_criteria": [],
            "variables": ["project_name", "custom_mission"],
        },
        "implementer": {
            "category": "role",
            "behavioral_rules": [],
            "success_criteria": [],
            "variables": ["project_name", "custom_mission"],
        },
        "tester": {
            "category": "role",
            "behavioral_rules": [],
            "success_criteria": [],
            "variables": ["project_name", "custom_mission"],
        },
        "reviewer": {
            "category": "role",
            "behavioral_rules": [],
            "success_criteria": [],
            "variables": ["project_name", "custom_mission"],
        },
        "documenter": {
            "category": "role",
            "behavioral_rules": [],
            "success_criteria": [],
            "variables": ["project_name", "custom_mission"],
        },
    }


def _get_mcp_coordination_section() -> str:
    """
    Generate the MCP coordination section to append to all templates.

    This section contains ONLY the critical "MCP tools are native calls" warning.
    All lifecycle behavior (tools, bootstrap, phases) is in server-side `full_protocol`
    returned by get_job_mission().

    Added in Phase 7 (Handover 0045).
    Trimmed in Handover 0431 to remove redundant content covered by full_protocol.

    Returns:
        str - MCP coordination section in markdown format
    """
    return """## MCP Tool Usage

MCP tools appear as **native tool calls** in your tool list (like Read, Write, Bash, Glob).
Tool names below are bare; your MCP client may expose them under a prefix
(e.g. `mcp__<server>__<tool>`) — call them by the names your harness lists.

**CORRECT**: Call tools directly
```
get_job_mission(job_id="...")
```

**WRONG**: Manual construction (curl, fetch, requests.post)

**Note**: `tenant_key` auto-injected by server. Tool signatures in `full_protocol`.
"""


def _get_mcp_bootstrap_section() -> str:
    """
    Generate the slim MCP bootstrap section for agent templates (Handover 0813).

    This replaces the previous protocol-heavy system_instructions with a minimal
    bootstrap that directs agents to fetch their full protocols via get_job_mission().

    The full protocol content (5-phase lifecycle, messaging, check-ins, etc.) is
    delivered server-side via full_protocol in the get_job_mission() response.

    Returns:
        str - Slim MCP bootstrap section (~10 lines) in markdown format
    """
    return f"""## {PRODUCT_NAME} Agent

You are part of a {PRODUCT_NAME} orchestration system. MCP tools are native tool calls,
named bare below; your client may expose them prefixed (`mcp__<server>__<tool>`).

Your `job_id` is provided in your spawn prompt — either pasted by the user or
injected by the orchestrator. Use it exactly as given. `tenant_key` is
auto-injected by the server from your API key session; do NOT pass it as a
parameter.

### STARTUP (MANDATORY)
1. Call `health_check()` to verify MCP connectivity
2. Call `get_job_mission(job_id="<your_job_id>")` to receive:
   - Your full operating protocols (`full_protocol`)
   - Your work order and team context (`mission`)
3. Follow `full_protocol` for all lifecycle behavior

Do not begin work until you have received and read your mission and protocols."""


def _get_check_in_protocol_section(tool: str = "multi_terminal") -> str:
    """
    Generate the Check-In Protocol section for agent monitoring (Handover 0107).

    This section provides brief reminder about contextual check-ins.
    Detailed behavior lives in full_protocol returned by get_job_mission().

    Args:
        tool: Platform identifier ('claude-code', 'codex', 'gemini', or
            'multi_terminal'). HO1025: when tool=='claude-code' the section
            appends a harness-reminder override telling the orchestrator to
            ignore the local TaskCreate `<system-reminder>` and use
            the prefixed report_progress tool instead. Other tools omit this
            block (the reminder doesn't fire in their harnesses).

    Returns:
        str - Brief Check-In Protocol section in markdown format

    Note:
        Slimmed in Handover 0353 - detailed behavior moved to full_protocol.
        Updated in Handover 0392 - simplified report_progress format.
        HO1025: tool-aware to gate the Claude-Code-specific harness override.
    """
    base = """## CHECK-IN PROTOCOL

Report progress at natural workflow breaks (after todos, after phases, before long tasks).
NOT timer-based. Full protocol in `full_protocol` from `get_job_mission()`.
"""
    # HO1025: TaskCreate override is Claude-Code-specific. Codex / Gemini / non-CLI
    # multi_terminal agents don't see the harness reminder so the override would be
    # noise for them. Append only when tool == "claude-code".
    # BE-6084 spike (2026-06-17): we deliberately KEEP this as a suppress-override and
    # do NOT mirror todos into the harness task tools. Reason proven live: the Claude
    # Code nudge is RECENCY-keyed, not existence-keyed — it re-fires after a handful of
    # tool calls that don't touch TaskCreate/TaskUpdate, EVEN when a populated, in_progress
    # harness task list exists. So an "active mirrored list" does NOT silence it; only
    # constantly re-touching the task tools would, at a cadence far higher than
    # report_progress fires. Mirroring would buy a second todo source + a double-write on
    # every progress update + still-incomplete suppression — net negative. The crisp
    # "ignore it" line below is the robust, low-cost answer.
    if tool == "claude-code":
        # BE-9275b: a plain string with __PLACEHOLDER__ tokens (not an inline
        # f-string) -- an f-string's {MCP_ALIAS} interpolations split this
        # block into separate ast.Constant nodes at each brace, which broke
        # the neutrality guard's +/-3-line "keep_nearby" locality window (the
        # "Claude Code" header landed in a different node than the later
        # ToolSearch mention it's meant to gate). Same placeholder pattern
        # already used for __TOOLSEARCH_CALL__ below.
        base += """
**HARNESS REMINDER OVERRIDE (Claude Code only — load-bearing):** Claude Code
periodically injects a `<system-reminder>` nudging `TaskCreate`/`TaskUpdate` for
progress tracking (it also rides along on `report_progress` responses). **Ignore it** —
`mcp____MCP_ALIAS____report_progress` (full `todo_items` list every call) is the canonical
progress mechanism the dashboard reads from; the harness task list is not. Do NOT mirror
your TODOs into `TaskCreate`/`TaskUpdate`: the nudge is recency-keyed, so an active harness
list won't silence it, and the double-write buys nothing but drift.

**TOOLSEARCH BOOTSTRAP (Claude Code only — first action):** In fresh Claude
Code sessions, MCP tool schemas are deferred behind `ToolSearch`. You CANNOT
call any `mcp____MCP_ALIAS____*` tool until its schema is loaded. As your first
action — before health_check, before anything — call ToolSearch once with the
full orchestrator tool list to collapse the bootstrap into a single round-trip.
The spawn prompt for this terminal already showed you this call; if you skipped
it, run it now:

```
__TOOLSEARCH_CALL__
```

After that single call, every tool above is callable. Skip this bootstrap and
you'll spend extra round-trips pulling schemas piecemeal mid-protocol.
""".replace("__MCP_ALIAS__", MCP_ALIAS).replace("__TOOLSEARCH_CALL__", render_toolsearch_call_one_line())
    return base


def _get_orchestrator_context_response_section() -> str:
    """
    Generate orchestrator-specific context response section (Handover 0109).

    This section provides reciprocal instructions for orchestrators on how
    to respond to context requests from other agents.

    Returns:
        str - Orchestrator context response section in markdown format

    Note:
        Added to user_instructions only for orchestrator template.
    """
    return """### RESPONDING TO CONTEXT REQUESTS

When agents request broader context via post_to_thread() on your coordination thread:

**Your Responsibilities**:
1. Respond promptly to agent context requests
2. Provide filtered excerpts from Project.mission, not full text
3. Focus on specific information requested

**Response Pattern**:
```
post_to_thread(
  thread_id=<your coordination thread>,
  to_participant="{requesting_agent_id}",
  content="CONTEXT_RESPONSE: [filtered excerpt]",
  from_agent="{agent_id}"
)
```

**Keep responses concise** - Only provide information directly relevant to agent's question.
"""


def _get_orchestrator_messaging_protocol_section() -> str:
    """
    Generate orchestrator-specific messaging behavioral guidance.

    Handover 0431: Trimmed — detailed examples moved to full_protocol.
    Handover 0966: Deduplicated — procedural coordination loop, message prefixes,
    and priority levels removed (now authoritative in full_protocol from
    agent_lifecycle.py). This section retains only behavioral guidance (WHO),
    not operational mechanics (HOW).

    Returns:
        str - Orchestrator messaging behavioral guidance in markdown format
    """
    return """## ORCHESTRATOR COORDINATION PRINCIPLES

As orchestrator, you are the team's single coordination point:

- **Blockers are urgent.** When an agent reports BLOCKER:, respond before advancing other work.
- **Completions trigger handoffs.** When an agent finishes, relay results to dependent agents.
- **Escalate early.** If an agent is stuck and you cannot unblock it, escalate to the user immediately — do not wait.
- **Your TODO list is your authority.** Work it systematically on every wake-up. The full coordination loop is in `full_protocol`.

Detailed coordination mechanics, message prefixes, priority levels, and tool signatures are in `full_protocol` from `get_job_mission()`.
"""


def _get_user_facing_orchestrator_seed() -> str:
    """
    Generate the Layer B "user seed" — the admin-editable, tool-agnostic
    orchestrator identity content.

    HO1027 (three-layer identity refactor): This is the content shown in the
    admin "Restore to default" textarea. It contains identity preamble,
    behavioral principles, success criteria, "If Requirements Are Unclear",
    "Before Closeout", "Responding to Context Requests", and the
    ORCHESTRATOR COORDINATION PRINCIPLES — but no harness mechanics.

    Tool gating, MCP tool-call syntax, CHECK-IN PROTOCOL, and the Claude Code
    HARNESS REMINDER OVERRIDE all live in `_get_orchestrator_system_harness`
    instead, and are appended at runtime regardless of override state.

    Returns:
        str - Layer B seed content (orchestrator template + context-response
            section + coordination principles).
    """
    base_template = ""
    for template_def in _get_default_templates_v103():
        if template_def.get("role") == "orchestrator":
            base_template = template_def["user_instructions"].strip()
            break

    if not base_template:
        raise RuntimeError("Default orchestrator template definition not found")

    orchestrator_response = _get_orchestrator_context_response_section().strip()
    orchestrator_messaging = _get_orchestrator_messaging_protocol_section().strip()

    return f"""{base_template}

{orchestrator_response}

{orchestrator_messaging}
"""


def _get_orchestrator_system_harness(tool: str = "multi_terminal") -> str:
    """
    Generate the Layer A "system harness" — hidden, immutable, tool-aware
    orchestrator scaffolding that is always appended to the active identity.

    HO1027 (three-layer identity refactor): Contains the MCP Tool Usage
    section and the CHECK-IN PROTOCOL (which itself appends the Claude-Code-
    only HARNESS REMINDER OVERRIDE when ``tool == 'claude-code'``).

    The harness is appended after either the user override or the seed so
    orchestrators always receive harness mechanics even when an admin has
    replaced the seed with custom identity content.

    Args:
        tool: Platform identifier ('claude-code', 'codex', 'gemini', or
            'multi_terminal'). Threaded into `_get_check_in_protocol_section`
            so the HARNESS REMINDER OVERRIDE only renders for Claude Code.

    Returns:
        str - Layer A harness content.
    """
    mcp_section = _get_mcp_coordination_section().strip()
    check_in = _get_check_in_protocol_section(tool=tool).strip()

    return f"""{mcp_section}

{check_in}
"""


# BE-6211g (move c): conductor role-trim anchors. The project-less CHAIN CONDUCTOR
# drives sub-orchestrators and never fields peer-agent context requests, never runs a
# per-project verify-all-agents closeout, and never spawn_job-s workers — so those
# three seed blocks are sliced out of its identity (gated on role == "conductor").
# Each slice fresh-finds its anchors and no-ops if an anchor is absent (graceful for
# admin override seeds that lack the default headings), mirroring the BE-6208g
# recompute-after-splice idiom in orchestrator_body.py.
def _trim_conductor_identity_body(body: str) -> str:
    """Remove the conductor-irrelevant blocks from the seed body (BE-6211g + BE-6215).

    The project-less chain conductor never stages/closes out a single project of its
    own and never spawns workers, so the solo-orchestration prose for those flows is
    noise it must not act on. FIVE sections are excised as FOUR anchored spans; each
    END anchor is KEPT so the reverse-splice guard can prove the trim removed EXACTLY
    these spans and nothing else (test_be6211g_role_scoped_identity.py).

    - SLICE C (BE-6215): ``## Three-Phase Workflow`` .. ``## Behavioral Principles`` —
      the solo staging->implementation->closeout phases AND ``## Core Responsibilities``
      (contiguous), which describe driving ONE project. The conductor runs
      CH_CHAIN_STAGING / CH_CHAIN_DRIVE instead.
    - SLICE D (BE-6215): ``## If Requirements Are Unclear`` .. ``## Right-Sizing Your
      Work`` — the solo staging-lock / request_approval escalation flow. The conductor
      escalates chain-level decisions to the user via the Hub per CH_CHAIN_DRIVE.
    - SLICE A (BE-6211g): ``## Before Closeout`` .. ``## ORCHESTRATOR COORDINATION
      PRINCIPLES`` — the verify-all-agents finale AND ``### RESPONDING TO CONTEXT
      REQUESTS`` (the seed concatenates them contiguously); COORDINATION PRINCIPLES is
      the kept END anchor.
    - SLICE B (BE-6211g): ``- `spawn_job`:`` .. ``- `report_progress`:`` — the
      worker-spawn tool-index bullet (report_progress END kept).

    Each slice is existence-guarded so a custom admin override lacking the anchors
    no-ops cleanly. The harness is appended by the caller AFTER this and is never
    trimmed.
    """
    # SLICE C (BE-6215): "## Three-Phase Workflow" .. "## Behavioral Principles" (END kept).
    start = body.find("## Three-Phase Workflow")
    end = body.find("## Behavioral Principles")
    if start != -1 and end != -1 and start < end:
        body = body[:start] + body[end:]
    # SLICE D (BE-6215): "## If Requirements Are Unclear" .. "## Right-Sizing Your Work" (END kept).
    start = body.find("## If Requirements Are Unclear")
    end = body.find("## Right-Sizing Your Work")
    if start != -1 and end != -1 and start < end:
        body = body[:start] + body[end:]
    # SLICE A (BE-6211g): "## Before Closeout" .. "## ORCHESTRATOR COORDINATION PRINCIPLES" (END kept).
    start = body.find("## Before Closeout")
    end = body.find("## ORCHESTRATOR COORDINATION PRINCIPLES")
    if start != -1 and end != -1 and start < end:
        body = body[:start] + body[end:]
    # SLICE B (BE-6211g): "- `spawn_job`:" .. "- `report_progress`:" (END kept).
    start = body.find("- `spawn_job`:")
    end = body.find("- `report_progress`:")
    if start != -1 and end != -1 and start < end:
        body = body[:start] + body[end:]
    return body


def compose_orchestrator_identity(
    override_content: str | None,
    tool: str = "multi_terminal",
    role: str | None = None,
) -> str:
    """
    Compose the runtime orchestrator identity from override-or-seed + harness.

    HO1027 (three-layer identity refactor): This is the canonical entry point
    for runtime orchestrator identity assembly. It guarantees that the system
    harness (MCP Tool Usage, CHECK-IN PROTOCOL, HARNESS REMINDER OVERRIDE) is
    ALWAYS present regardless of whether the tenant has saved an admin
    override of the user-facing seed.

    Args:
        override_content: Tenant admin override of the Layer B seed, or None
            to use the default seed.
        tool: Platform identifier passed through to the harness for
            tool-aware gating (HARNESS REMINDER OVERRIDE for claude-code).
        role: BE-6211g / BE-6215 — OPTIONAL chain role. ``None`` (the default,
            and the value for solo / sub_orchestrator) reproduces today's seed
            byte-for-byte. ``"conductor"`` trims the project-less chain
            conductor of the solo-orchestration blocks it must not act on:
            the single-project Three-Phase Workflow + Core Responsibilities,
            the If-Requirements-Are-Unclear staging-lock/request_approval flow,
            the verify-all-agents Before Closeout finale + RESPONDING TO CONTEXT
            REQUESTS, and the worker-spawn spawn_job bullet. The coordination
            principles, right-sizing, tool index, and harness are never trimmed.

    Returns:
        str - ``(override OR seed[, conductor-trimmed]) + "\\n\\n---\\n\\n" + harness(tool)``
    """
    body = override_content if override_content else _get_user_facing_orchestrator_seed()
    if role == "conductor":
        body = _trim_conductor_identity_body(body)
    harness = _get_orchestrator_system_harness(tool=tool)
    return f"{body.strip()}\n\n---\n\n{harness.strip()}"


def get_orchestrator_identity_content(tool: str = "multi_terminal") -> str:
    """
    Back-compat shim — returns the default (no-override) composed identity.

    Handover 0431: This content is injected into the MCP tool response so
    orchestrators get their identity/behavioral guidance without needing an
    AgentTemplate record. Orchestrators stay OUT of the template table,
    exports, and available_agents list.

    HO1025: ``tool`` is threaded so the Claude-Code-specific HARNESS REMINDER
    OVERRIDE only renders for Claude Code orchestrators, not Codex/Gemini/
    multi_terminal ones.

    HO1027: Now delegates to ``compose_orchestrator_identity(None, tool)``
    so the seed-vs-harness split is honored even on legacy callers.

    Args:
        tool: Platform identifier ('claude-code', 'codex', 'gemini', or
            'multi_terminal'). Defaults to 'multi_terminal'.

    Returns:
        str - Full orchestrator identity and behavioral guidance.
    """
    return compose_orchestrator_identity(None, tool=tool)
