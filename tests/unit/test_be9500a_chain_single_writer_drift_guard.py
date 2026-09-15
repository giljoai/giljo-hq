# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    bypassing_source = (
        "async def create_sequence_run(request, current_user, session=Depends(get_session)):\n"
        "    run = SequenceRun(project_ids=request.project_ids, tenant_key=current_user.tenant_key)\n"
        "    session.add(run)\n"
        "    await session.commit()\n"
        "    return run\n"
    )
    assert "SequenceRunService" not in bypassing_source
    assert "SequenceRun(" in bypassing_source, "the fixture itself must exhibit the violation it is meant to catch"
