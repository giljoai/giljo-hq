# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from types import SimpleNamespace

from api.endpoints.mcp_tools._tool_error_surface import redact_input_echo
from giljo_mcp.services.agent_status_tally import tally_agent_statuses


def test_tally_separates_holding_from_working_and_counts_closed() -> None:
    rows = [
        SimpleNamespace(job_id="a", status="working"),
        SimpleNamespace(job_id="b", status="working"),
        SimpleNamespace(job_id="c", status="closed"),
        SimpleNamespace(job_id="d", status="waiting"),
    ]
    todos = {"a": {"in_progress": 1}, "b": {"completed": 2}}

    tally = tally_agent_statuses(rows, todos)

    assert (tally.total, tally.active, tally.holding, tally.closed, tally.pending) == (4, 1, 1, 1, 1)


def test_redact_input_echo_keeps_the_reason_and_survives_brackets_in_the_value() -> None:
    message = "summary\n  Too long [type=string_too_long, input_value={'a': [1, 2]}, input_type=dict]"

    assert redact_input_echo(message) == "summary\n  Too long [type=string_too_long, input_type=dict]"
