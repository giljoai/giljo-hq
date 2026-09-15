# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations


RETIRED_TOOL_NAMES: dict[str, str] = {
    "await_my_turn": "get_my_turn(agent_id=..., wait_seconds=45)",
    "close_job": "finalize_job",
    "dismiss_reactivation": 'resume_or_dismiss_job(action="dismiss")',
    "get_vision_doc": "get_vision_document",
    "implement_project": "get_implementation_prompt",
    "pass_baton": "set_next_actor",
    "reactivate_job": 'resume_or_dismiss_job(action="resume")',
    "resolve_reactivation": "resume_or_dismiss_job",
    "search_threads": "list_threads(query=...)",
    "start_chain_run": "link_projects / unlink_projects",
    "update_roadmap_metadata": "save_roadmap",
}
