# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from giljo_mcp.branding import PRODUCT_NAME
from giljo_mcp.harness_resolver import HARNESS_CLAUDE_CODE
from giljo_mcp.prompts._canonical_tool_list import render_toolsearch_call_one_line
from giljo_mcp.prompts.orchestrator_seed import ORCHESTRATOR_SEED_INSTRUCTIONS


logger = logging.getLogger(__name__)


def _seeded_user_instructions(template_def: dict[str, Any]) -> str:
    user_instructions = template_def["user_instructions"]
    if template_def["role"] == "orchestrator":
        user_instructions = f"{user_instructions}\n\n{_get_orchestrator_context_response_section()}"
    return user_instructions


def _get_default_templates_v103() -> list[dict[str, Any]]:
    return [
        {
            "name": "orchestrator",
            "role": "orchestrator",
            "cli_tool": "claude",
            "background_color": "#D4A574",
            "description": "Project orchestrator responsible for coordinating agent workflows",
            "user_instructions": ORCHESTRATOR_SEED_INSTRUCTIONS,
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
    return """## MCP Tool Usage

MCP tools are native tool calls in your tool list, never curl, HTTP or SDK calls. Names
here are bare; your client may show them with a prefix (e.g. `mcp__<server>__<tool>`), so
call the names your harness lists. Never pass `tenant_key`: the server adds it. Tool
signatures and your lifecycle steps are in `full_protocol` from `get_job_mission()`.
"""


def _get_mcp_bootstrap_section() -> str:
    return f"""## {PRODUCT_NAME} Agent

You are part of a {PRODUCT_NAME} orchestration system. MCP tools are native tool calls,
named bare below; your client may expose them prefixed (`mcp__<server>__<tool>`).

Your `job_id` is provided in your spawn prompt — either pasted by the user or
injected by the orchestrator. Use it exactly as given. `tenant_key` is
auto-injected by the server from your API key session; do NOT pass it as a
parameter.

### STARTUP (MANDATORY)
1. Call `get_job_mission(job_id="<your_job_id>")` to receive:
   - Your full operating protocols (`full_protocol`)
   - Your work order and team context (`mission`)
2. Follow `full_protocol` for all lifecycle behavior

Do not begin work until you have received and read your mission and protocols."""


def _get_check_in_protocol_section(tool: str = "multi_terminal") -> str:
    if tool != HARNESS_CLAUDE_CODE:
        return ""
    return """**TOOLSEARCH BOOTSTRAP (Claude Code only):** MCP tool schemas are deferred behind
`ToolSearch`; load every one you still lack in ONE call, not piecemeal:

```
__TOOLSEARCH_CALL__
```

**HARNESS REMINDER OVERRIDE (Claude Code only):** ignore the `<system-reminder>` nudging
`TaskCreate`/`TaskUpdate`: the dashboard reads `report_progress` (the full `todo_items` list
every call). Do NOT mirror your TODOs into the task tools: the nudge is recency-keyed, so
mirroring never silences it.
""".replace("__TOOLSEARCH_CALL__", render_toolsearch_call_one_line())


def _get_orchestrator_context_response_section() -> str:
    return """### RESPONDING TO CONTEXT REQUESTS

When an agent asks for broader context (`REQUEST_CONTEXT:` on your coordination thread),
answer promptly, directed to it, with `content="CONTEXT_RESPONSE: ..."`:
a filtered excerpt of the project mission that answers the question, not the full text.
"""


def _get_orchestrator_messaging_protocol_section() -> str:
    return """## ORCHESTRATOR COORDINATION PRINCIPLES

- **Blockers are urgent.** Answer a `BLOCKER:` before advancing other work.
- **Completions trigger handoffs.** When an agent finishes, relay its results to the agents
  that depend on it.
- **Escalate early.** An agent you cannot unblock goes to the user at once.

The coordination loop and message prefixes are in `full_protocol`.
"""


def _get_user_facing_orchestrator_seed() -> str:
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
    mcp_section = _get_mcp_coordination_section().strip()
    check_in = _get_check_in_protocol_section(tool=tool).strip()

    return "\n\n".join(part for part in (mcp_section, check_in) if part) + "\n"


def _trim_conductor_identity_body(body: str) -> str:
    start = body.find("## Three-Phase Workflow")
    end = body.find("## Behavioral Principles")
    if start != -1 and end != -1 and start < end:
        body = body[:start] + body[end:]
    start = body.find("## If Requirements Are Unclear")
    end = body.find("## Right-Sizing Your Work")
    if start != -1 and end != -1 and start < end:
        body = body[:start] + body[end:]
    start = body.find("## Before Closeout")
    end = body.find("## ORCHESTRATOR COORDINATION PRINCIPLES")
    if start != -1 and end != -1 and start < end:
        body = body[:start] + body[end:]
    start = body.find("- `spawn_job`:")
    end = body.find("- `report_progress`:")
    if start != -1 and end != -1 and start < end:
        body = body[:start] + body[end:]
    return body


_SEED_LAST_LINE = "The coordination loop and message prefixes are in `full_protocol`.\n"
_LEGACY_SEED_LAST_LINE = (
    "Detailed coordination mechanics, message prefixes, priority levels, and tool signatures "
    "are in `full_protocol` from `get_job_mission()`.\n"
)
_STAGING_ONLY_SPANS = (
    ("## Sizing The Team", "## Writing Missions", False),
    ("Decide and document: a small ambiguity", "- Implementation or closeout:", False),
    ("## Three-Phase Workflow", "## Core Responsibilities", False),
    ("**Context fetching (get_context):**", "**Deferred follow-ups", False),
    ("**Continuation-check", "## Non-obvious Tool Parameters", False),
    ("- **Trivial** (one file", "Spawn testers and reviewers during implementation", False),
    ("- `list_projects`:", "- `spawn_job`:", False),
)
_IMPLEMENTATION_ONLY_SPANS = (
    ('Never use `set_agent_status("blocked")`', "## Sizing The Team", False),
    ("## Accepting Deliverables", "## Right-Sizing Your Work", False),
    ("## Before Closeout", _SEED_LAST_LINE, True),
    ("## Before Closeout", _LEGACY_SEED_LAST_LINE, True),
)


def _cut_spans(body: str, spans: tuple[tuple[str, str, bool], ...]) -> str:
    for start_anchor, end_anchor, drop_end in spans:
        start = body.find(start_anchor)
        end = body.find(end_anchor, start + 1) if start != -1 else -1
        if start != -1 and end != -1:
            body = body[:start] + body[end + (len(end_anchor) if drop_end else 0) :]
    return body


def _scope_identity_to_phase(body: str, phase: str | None) -> str:
    if phase == "staging":
        return _cut_spans(body, _IMPLEMENTATION_ONLY_SPANS)
    if phase == "implementation":
        return _cut_spans(body, _STAGING_ONLY_SPANS)
    return body


def compose_orchestrator_identity(
    override_content: str | None,
    tool: str = "multi_terminal",
    role: str | None = None,
    phase: str | None = None,
) -> str:
    body = override_content if override_content else _get_user_facing_orchestrator_seed()
    if role == "conductor":
        body = _trim_conductor_identity_body(body)
    body = _scope_identity_to_phase(body, phase)
    harness = _get_orchestrator_system_harness(tool=tool)
    return f"{body.strip()}\n\n---\n\n{harness.strip()}"


def get_orchestrator_identity_content(tool: str = "multi_terminal") -> str:
    return compose_orchestrator_identity(None, tool=tool)
