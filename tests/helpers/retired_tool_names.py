# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9563 -- the one list of tool names the product no longer answers to.

Two guards read this map: the cross-reference check over the registered tool
descriptions, and the scan of the agent-facing prompt/protocol prose. They were
separate lists once, which is how they drifted, so there is one list now.

WHY THIS LIVES IN ITS OWN MODULE, and not inside either test: it needs a single
owner, so that a mechanical rename sweep across the repo has one place to be
correct rather than two places to disagree.

Entries are validated by ``test_every_retired_key_is_actually_retired`` in
test_be9563_prompt_tool_names.py: every KEY must be ABSENT from the live registry
and every replacement must NAME a live tool, so a stale or mis-edited entry
fails loudly instead of silently passing.

MAINTAINING IT: when a tool is renamed, add ``old_name -> new call`` here in the
same PR. Write the replacement as the agent should CALL it, arguments included
where the rename moved one -- ``await_my_turn(agent_id)`` became
``get_my_turn(agent_id, wait_seconds=45)``, and a swept sentence that carried the
name across but dropped ``wait_seconds`` told agents to park on a call that
returns instantly (BE-9554's own sweep shipped that defect six times).
"""

from __future__ import annotations


# Retired MCP tool name -> how an agent should call the survivor instead.
RETIRED_TOOL_NAMES: dict[str, str] = {
    "await_my_turn": "get_my_turn(agent_id=..., wait_seconds=45)",
    "close_job": "finalize_job",
    # BE-9012d retired the message bus and merged the two reactivation exits. Neither
    # of these was RENAMED -- they were removed, which is why no rename sweep ever put
    # them on a list and why `send_message` was still being handed to users from the
    # frontend with nothing watching. Added at CI3's request (FE-9564) so the server
    # guard and the frontend guard read one map instead of two that can disagree.
    # `dismiss_reactivation` survives as a SERVICE method; it is only retired as a
    # TOOL name, which is the distinction every entry here draws.
    #
    # `send_message` IS a retired tool and is DELIBERATELY ABSENT. Its only live
    # mentions (frontend, MessageComposer.vue) read "mirrors the OLD BUS send_message
    # wake" -- a true sentence about a retired thing, and BE-9012d's own record of what
    # the Hub replaced. Listing it would force a lane to falsify true prose to go green,
    # which is the museum rule inverted. Measured on both surfaces before removing it:
    # zero non-docstring hits in src/ + api/, two historical notes in the frontend. Do
    # not re-add it without re-measuring; the gap is the decision, not an oversight.
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
