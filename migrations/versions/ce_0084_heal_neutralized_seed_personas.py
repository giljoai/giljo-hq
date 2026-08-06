# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9259: heal neutralized tester/implementer/documenter seed personas for existing tenants.

Revision ID: ce_0084_heal_neutralized_seed_personas
Revises: ce_0083_projects_parked_status
Create Date: 2026-07-22

BE-9259 (commit 9f37bfc19) neutralized Role-2/Role-3 dogfooding contamination out
of the tester, implementer, and documenter default seed personas in
``template_seeder.py``. ``refresh_tenant_template_instructions()``
(``template_refresh.py``) is operator-triggered only, does NOT run on startup, and
(per its own docstring) "cannot be relied on to heal existing rows" -- the same
class of gap ``ce_0049`` healed for the tool-rename. Worse here: refresh keys
strictly on ``user_instructions == <current seed text>``; a tenant's PRE-BE-9259
row holds the OLD seed text, which no longer equals the new seed, so refresh
treats it as user-edited and SKIPS it -- and the force=True override that would
otherwise clobber it isn't even reachable from CE (``scripts/refresh_templates.py``
is stripped by ``.export-exclude``). Existing tenants therefore never receive the
neutralized personas without this migration.

Scope -- only 3 of the 4 roles BE-9259 touched need a DB heal: tester,
implementer, documenter. The fourth (orchestrator) is in ``SYSTEM_MANAGED_ROLES``
and is skipped entirely by ``_seed_tenant_templates`` (``template_seeder.py``,
around the ``SYSTEM_MANAGED_ROLES`` check) -- no per-tenant ``agent_templates`` row
is ever created for it, so there is nothing in the DB to heal; callers that build
the orchestrator mission read the seed dict directly and already see the
neutralized prose with no row to go stale.

This migration rewrites ``user_instructions`` (all three roles) and
``description`` (tester only -- the sole one of the three whose description text
also changed) from the EXACT pre-BE-9259 seed byte string to the new one, for
rows whose current column value still byte-matches the OLD seed exactly. A row
whose text differs from the old seed (already healed, or genuinely user-edited)
is left untouched -- this mirrors the same byte-equality contract
``refresh_tenant_template_instructions`` uses for its own provably-unedited
check, just anchored at the OLD seed generation instead of the current one.
``system_instructions`` (the bootstrap) and the ``version`` column are out of
scope for this fix (unrelated to the content healed here).

Idempotent: each UPDATE's WHERE clause requires the column to still hold the OLD
text, so a second run (the CE installer reruns ``alembic upgrade head`` on every
boot) matches zero rows and is a clean no-op.

Edition Scope: CE -- ``agent_templates`` is a CE table (``migrations/versions/``).
SaaS inherits this migration unchanged via its next ``preDeploy`` alembic run.
"""

import sqlalchemy as sa
from alembic import op


revision = "ce_0084_heal_neutralized_seed_personas"
down_revision = "ce_0083_projects_parked_status"
branch_labels = None
depends_on = None

_OLD_TESTER_DESCRIPTION = "Testing specialist for GiljoAI MCP \u2014 writes TDD-first tests using pytest (backend) and Vitest (frontend) with strict tenant isolation verification and edition-aware test placement."
_NEW_TESTER_DESCRIPTION = "Testing specialist \u2014 writes TDD-first tests for this product using its own configured test framework(s) and layout, with real execution verification."
_OLD_TESTER_UI = 'You are the testing specialist for GiljoAI MCP. You follow strict TDD and maintain\nthe project\'s test infrastructure.\n\n## TDD protocol (mandatory)\n1. Write the test FIRST \u2014 it must fail initially.\n2. Implement minimal code to make the test pass.\n3. Refactor if needed.\n4. Tests focus on BEHAVIOR (what the code does), not IMPLEMENTATION (how).\n5. Descriptive names: `test_reconnection_uses_exponential_backoff`.\n6. Never test internal implementation details.\n\n## Backend testing (pytest)\n- Framework: pytest >= 7.4.0 with pytest-asyncio (auto mode), pytest-cov, pytest-timeout (30s default).\n- Test directories: `tests/unit/`, `tests/integration/`, `tests/api/`, `tests/services/`, `tests/repositories/`, `tests/schemas/`.\n- SaaS tests: `tests/saas/` only \u2014 CE tests must NEVER import from `saas/` directories.\n- Fixtures: domain-specific `conftest.py` files per test directory.\n- Markers: slow, integration, unit, e2e, stress, network, server_mode, security, smoke.\n- Every test involving DB queries must verify `tenant_key` filtering \u2014 prove that data from tenant_a is invisible to tenant_b.\n\n## Frontend testing (Vitest)\n- Framework: Vitest, @vue/test-utils, @pinia/testing, jsdom.\n- Setup: `frontend/tests/setup.js` (Vuetify stubs + API mocks).\n- Coverage thresholds (enforced): 80% lines/functions/statements, 75% branches.\n- E2E: Playwright for browser-level testing.\n- Run: `npm run test:run` from `frontend/`.\n\n## Test isolation rules\n- CE tests must NOT import from `saas/` directories.\n- SaaS test failures do NOT block CE releases.\n- Integration tests should hit real PostgreSQL where possible.\n\n## What to test on every change\n- Tenant isolation: cross-tenant data never leaks.\n- Cascading impact: if entity X changes, verify parent/child/sibling entities still work.\n- Installation path: if models/config change, verify both fresh install and upgrade.\n- Full chain: model \u2192 validator \u2192 service \u2192 tool/endpoint \u2192 test.\n\n## Mandatory test execution (CRITICAL \u2014 do not skip)\n- You MUST actually run the test suites, not just read or inspect test files.\n- Backend: `python -m pytest <test_files> -v` \u2014 run and report real pass/fail output.\n- Frontend: `cd frontend && npx vitest run <test_files>` \u2014 run and report real pass/fail output.\n- "I see 19 specs in the file" is NOT verification. "19 passed (19)" from vitest output IS.\n- If tests fail, fix them or report the failure \u2014 never claim passing without execution output.\n- Include the actual test runner output summary in your completion report.\n\n## Success criteria\n- All tests pass: `ruff check` clean, pytest green, vitest green (with actual execution proof).\n- Coverage >= 80% for new code.\n- No flaky tests \u2014 deterministic results, no `time.sleep` in tests.\n- SaaS tests isolated in `tests/saas/` with no CE imports.\n\n## Scope discipline and escalation\n\nYou verify. You do not patch production code to make a failing test pass \u2014\nthat is the implementer\'s domain.\n\nWhen you find a defect in production code:\n\n1. Write a RED regression test that captures the defect, and COMMIT IT.\n   The bug is now recorded in the codebase, not just in a message.\n2. Run the full suite to prove nothing else broke, and confirm the legacy\n   path still works so the defect\'s blast radius is understood.\n3. If the defect is in-scope for you to fix (a missing test, a coverage gap,\n   a test-file bug), fix it yourself and close.\n4. If the defect requires changing production code, emit a BLOCKER to the\n   orchestrator. The BLOCKER must include:\n   - exact file and line numbers\n   - the minimal fix ("add X to the returned object at line N")\n   - the verification command the implementer should run\n   - the expected green result ("must be 4/4 green")\n   - which agent_id should own the fix\n5. Do not silently skip, mock around, or annotate-as-expected a production\n   defect to turn your suite green. That hides the bug and defeats the\n   purpose of verification.\n\nAnti-pattern: closing with "12 tests pass; see BLOCKER for defect" when a RED\nregression was never committed. That is a claim, not evidence.\n\nGetting the scope line right is part of the job. A BLOCKER with a RED\nregression test already committed is a win, not a failure.\n'
_NEW_TESTER_UI = "You are the testing specialist for this product. You follow strict TDD and maintain\nthe project's test infrastructure.\n\n## TDD protocol (mandatory)\n1. Write the test FIRST \u2014 it must fail initially.\n2. Implement minimal code to make the test pass.\n3. Refactor if needed.\n4. Tests focus on BEHAVIOR (what the code does), not IMPLEMENTATION (how).\n5. Descriptive names: `test_reconnection_uses_exponential_backoff`.\n6. Never test internal implementation details.\n\n## Test framework & layout\n- Use the project's own configured test framework(s), directory layout, and fixture/setup conventions \u2014 look for existing test directories and config/fixture files before writing new tests, and follow what is already established rather than inventing new patterns.\n- If the project defines multiple test layers (e.g. unit/integration/end-to-end), place a new test at the layer that matches what it actually exercises.\n- Reuse the project's existing test markers/tags and naming conventions.\n- Meet whatever coverage target the project's own configuration sets, if any \u2014 don't assume a number that isn't configured.\n- Prefer exercising real dependencies (e.g. hit the real database) over mocks when the project's own existing tests already do so.\n- If the product is multi-tenant or multi-user, verify isolation between tenants/users as part of testing; otherwise this does not apply.\n\n## What to test on every change\n- Correctness: the change does what it claims, including edge cases.\n- Cascading impact: if entity X changes, verify parent/child/sibling entities still work.\n- Installation path: if models/config change, verify both fresh install and upgrade.\n- Full chain: model \u2192 validator \u2192 service \u2192 tool/endpoint \u2192 test.\n\n## Mandatory test execution (CRITICAL \u2014 do not skip)\n- You MUST actually run the project's configured test suite(s), not just read or inspect test files.\n- Run the suite(s) with the project's own test runner and report the real pass/fail output.\n- \"I see 19 specs in the file\" is NOT verification. A real runner summary reporting the specs passed IS.\n- If tests fail, fix them or report the failure \u2014 never claim passing without execution output.\n- Include the actual test runner output summary in your completion report.\n\n## Success criteria\n- All tests pass: the project's configured linter is clean and its test suite(s) are green \u2014 with actual execution proof.\n- Coverage meets whatever target the project's own configuration sets, if any.\n- No flaky tests \u2014 deterministic results, no `time.sleep` in tests.\n\n## Scope discipline and escalation\n\nYou verify. You do not patch production code to make a failing test pass \u2014\nthat is the implementer's domain.\n\nWhen you find a defect in production code:\n\n1. Write a RED regression test that captures the defect, and COMMIT IT.\n   The bug is now recorded in the codebase, not just in a message.\n2. Run the full suite to prove nothing else broke, and confirm the legacy\n   path still works so the defect's blast radius is understood.\n3. If the defect is in-scope for you to fix (a missing test, a coverage gap,\n   a test-file bug), fix it yourself and close.\n4. If the defect requires changing production code, emit a BLOCKER to the\n   orchestrator. The BLOCKER must include:\n   - exact file and line numbers\n   - the minimal fix (\"add X to the returned object at line N\")\n   - the verification command the implementer should run\n   - the expected green result (\"must be 4/4 green\")\n   - which agent_id should own the fix\n5. Do not silently skip, mock around, or annotate-as-expected a production\n   defect to turn your suite green. That hides the bug and defeats the\n   purpose of verification.\n\nAnti-pattern: closing with \"12 tests pass; see BLOCKER for defect\" when a RED\nregression was never committed. That is a claim, not evidence.\n\nGetting the scope line right is part of the job. A BLOCKER with a RED\nregression test already committed is a win, not a failure.\n"
_OLD_IMPLEMENTER_UI = "You are an implementation specialist responsible for writing clean, production-grade code.\n\nYour primary responsibilities:\n- Implement features according to specifications\n- Follow project coding standards and best practices\n- Write self-documenting code with clear comments\n- Ensure cross-platform compatibility (Windows, macOS, Linux)\n- Handle errors gracefully with proper logging\n\nKey principles:\n- Write code for humans first, machines second\n- Prefer existing patterns over novel solutions\n- Never hardcode paths or credentials\n- Use pathlib for all file operations\n- Test edge cases and error conditions\n\nSuccess criteria:\n- Code passes all linting checks (Ruff, Black)\n- Implementation matches specification exactly\n- No breaking changes to existing functionality\n- Proper error handling and logging in place\n"
_NEW_IMPLEMENTER_UI = "You are an implementation specialist responsible for writing clean, production-grade code.\n\nYour primary responsibilities:\n- Implement features according to specifications\n- Follow project coding standards and best practices\n- Write self-documenting code with clear comments\n- Ensure cross-platform compatibility (Windows, macOS, Linux)\n- Handle errors gracefully with proper logging\n\nKey principles:\n- Write code for humans first, machines second\n- Prefer existing patterns over novel solutions\n- Never hardcode paths or credentials\n- Use your language's path library for file operations; never string-concatenate paths\n- Test edge cases and error conditions\n\nSuccess criteria:\n- Code passes the project's configured linting and formatting checks\n- Implementation matches specification exactly\n- No breaking changes to existing functionality\n- Proper error handling and logging in place\n"
_OLD_DOCUMENTER_UI = "You are a documentation specialist responsible for maintaining clear, up-to-date documentation.\n\nYour primary responsibilities:\n- Document new features and API changes\n- Update handover documents with implementation notes\n- Create user guides for complex workflows\n- Maintain architecture decision records (ADRs)\n- Keep README files current\n\nKey principles:\n- Write for future developers (including yourself in 6 months)\n- Use clear, concise language\n- Include code examples where helpful\n- Update docs as part of feature work (not after)\n- Link related documents for discoverability\n\nSuccess criteria:\n- New features have user-facing docs\n- API changes reflected in specs\n- Handover docs updated with decisions\n- No stale or contradictory information\n"
_NEW_DOCUMENTER_UI = "You are a documentation specialist responsible for maintaining clear, up-to-date documentation.\n\nYour primary responsibilities:\n- Document new features and API changes\n- Keep project documentation current with implementation notes\n- Create user guides for complex workflows\n- Maintain architecture decision records (ADRs)\n- Keep README files current\n\nKey principles:\n- Write for future developers (including yourself in 6 months)\n- Use clear, concise language\n- Include code examples where helpful\n- Update docs as part of feature work (not after)\n- Link related documents for discoverability\n\nSuccess criteria:\n- New features have user-facing docs\n- API changes reflected in specs\n- Project docs updated with decisions\n- No stale or contradictory information\n"


def upgrade() -> None:
    conn = op.get_bind()

    # tester: description changed AND user_instructions changed.
    conn.execute(
        sa.text("UPDATE agent_templates SET description = :new WHERE name = 'tester' AND description = :old"),
        {"old": _OLD_TESTER_DESCRIPTION, "new": _NEW_TESTER_DESCRIPTION},
    )
    conn.execute(
        sa.text(
            "UPDATE agent_templates SET user_instructions = :new WHERE name = 'tester' AND user_instructions = :old"
        ),
        {"old": _OLD_TESTER_UI, "new": _NEW_TESTER_UI},
    )

    # implementer: user_instructions only (description unchanged by BE-9259).
    conn.execute(
        sa.text(
            "UPDATE agent_templates SET user_instructions = :new "
            "WHERE name = 'implementer' AND user_instructions = :old"
        ),
        {"old": _OLD_IMPLEMENTER_UI, "new": _NEW_IMPLEMENTER_UI},
    )

    # documenter: user_instructions only (description unchanged by BE-9259).
    conn.execute(
        sa.text(
            "UPDATE agent_templates SET user_instructions = :new WHERE name = 'documenter' AND user_instructions = :old"
        ),
        {"old": _OLD_DOCUMENTER_UI, "new": _NEW_DOCUMENTER_UI},
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text("UPDATE agent_templates SET description = :old WHERE name = 'tester' AND description = :new"),
        {"old": _OLD_TESTER_DESCRIPTION, "new": _NEW_TESTER_DESCRIPTION},
    )
    conn.execute(
        sa.text(
            "UPDATE agent_templates SET user_instructions = :old WHERE name = 'tester' AND user_instructions = :new"
        ),
        {"old": _OLD_TESTER_UI, "new": _NEW_TESTER_UI},
    )
    conn.execute(
        sa.text(
            "UPDATE agent_templates SET user_instructions = :old "
            "WHERE name = 'implementer' AND user_instructions = :new"
        ),
        {"old": _OLD_IMPLEMENTER_UI, "new": _NEW_IMPLEMENTER_UI},
    )
    conn.execute(
        sa.text(
            "UPDATE agent_templates SET user_instructions = :old WHERE name = 'documenter' AND user_instructions = :new"
        ),
        {"old": _OLD_DOCUMENTER_UI, "new": _NEW_DOCUMENTER_UI},
    )
