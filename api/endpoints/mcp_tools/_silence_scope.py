# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations


SILENCE_CLEARING_TOOLS: frozenset[str] = frozenset(
    {
        "report_progress",
        "get_job_mission",
        "get_staging_instructions",
        "set_agent_status",
        "request_approval",
    }
)

NON_SILENCE_CLEARING_TOOLS: frozenset[str] = frozenset(
    {
        "get_context",
        "get_agent_result",
        "close_job",
        "reactivate_job",
        "dismiss_reactivation",
        "update_job_mission",
        "complete_job",
    }
)
