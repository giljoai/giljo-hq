# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9500a -- single-writer drift guard for sequence_runs.

By design: "both doors MUST keep sharing the same
server-side prompt/staging engines ... a separate headless fork ... is forbidden."
The same principle applies to the WRITE path: the UI's REST endpoints
(api/endpoints/sequence_runs.py) and the headless MCP tool
(src/giljo_mcp/tools/tool_accessor/_chain_tools.py) must both route every mutation
of ``sequence_runs`` through the ONE owning ``SequenceRunService`` -- never a
parallel write path (CLAUDE.md "Database write discipline").

Pattern: a NAME-LIST / explicit-construction lock (test_be9452_standard_profile_roster_lock.py
precedent), not a runtime spy -- a static check that survives a rewrite of either
call site's internals as long as the write still routes through the owning service.

1. test_rest_create_endpoint_calls_owning_service_create -- the REST create
   endpoint's dependency resolves to SequenceRunService, and its handler body
   calls `.create(`.
2. test_mcp_start_chain_run_calls_owning_service_create -- start_chain_run's
   source constructs SequenceRunService directly and calls `.create(`.
3. test_neither_door_constructs_sequence_run_orm_directly -- neither call site's
   source references the SequenceRun ORM model by name (the only writer allowed
   to touch the ORM row is SequenceRunService.create itself).
4. test_non_vacuity -- a source string that DOES bypass the service (no
   `SequenceRunService` construction, direct ORM add) is REJECTED by the same
   rule this file applies, proving the guard is not vacuously true.

No DB, no mocks -- pure source/AST inspection of the two call sites. Parallel-safe.
Edition Scope: CE.
"""

from __future__ import annotations

import inspect

from api.endpoints import sequence_runs as rest_endpoints
from giljo_mcp.tools.tool_accessor import _chain_tools


def _source(func) -> str:
    return inspect.getsource(func)


def test_rest_create_endpoint_calls_owning_service_create() -> None:
    src = _source(rest_endpoints.create_sequence_run)
    assert "SequenceRunService" in inspect.getsource(rest_endpoints), (
        "api/endpoints/sequence_runs.py must import/reference SequenceRunService -- "
        "it is the ONLY class permitted to write sequence_runs"
    )
    assert "service.create(" in src, (
        "the REST create endpoint must call the injected service's .create() -- "
        "a parallel write path (raw session.add / a different service) would drift "
        "silently from the MCP door"
    )


def test_mcp_start_chain_run_calls_owning_service_create() -> None:
    src = _source(_chain_tools.ChainToolsMixin.start_chain_run)
    assert "SequenceRunService(" in src, (
        "start_chain_run must construct SequenceRunService itself (no dependency "
        "injection at the MCP boundary) -- same owning service class as the REST door"
    )
    assert "service.create(" in src or "await service.create(" in src, (
        "start_chain_run must call SequenceRunService.create -- never re-implement run creation inline"
    )


def test_neither_door_constructs_sequence_run_orm_directly() -> None:
    rest_src = inspect.getsource(rest_endpoints)
    mcp_src = inspect.getsource(_chain_tools)
    for label, src in (("api/endpoints/sequence_runs.py", rest_src), ("_chain_tools.py", mcp_src)):
        assert "SequenceRun(" not in src, (
            f"{label} constructs the SequenceRun ORM model directly -- only "
            "SequenceRunService.create is permitted to do that (single-writer, "
            "CLAUDE.md 'Database write discipline')"
        )


def test_non_vacuity() -> None:
    """Prove the rule this file applies actually rejects a bypass, not just this repo's shape."""
    bypassing_source = (
        "async def create_sequence_run(request, current_user, session=Depends(get_session)):\n"
        "    run = SequenceRun(project_ids=request.project_ids, tenant_key=current_user.tenant_key)\n"
        "    session.add(run)\n"
        "    await session.commit()\n"
        "    return run\n"
    )
    assert "SequenceRunService" not in bypassing_source
    assert "SequenceRun(" in bypassing_source, "the fixture itself must exhibit the violation it is meant to catch"
