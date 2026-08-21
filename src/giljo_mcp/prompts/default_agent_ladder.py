# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9402: what an orchestrator does when an agent template is not installed.

The prose this replaces told the orchestrator to STOP and report the mismatch,
and never to substitute a generic agent. That halted a whole run over a missing
FILE -- while every supported harness (Claude Code's Task tool, Codex's
spawn_agent) can run its own default subagent perfectly well. A missing install
is a setup gap to mention, not a reason to stop working.

So the rule is a LADDER, not a gate:

  1. Prefer the installed ``gil-*`` / ``.claude/agents/*`` template. It carries the
     tuned role, rules and success criteria, and it is still the right answer
     whenever it exists.
  2. If it is absent, spawn the harness's DEFAULT subagent and say so ONCE, using
     :data:`MISSING_AGENT_TEMPLATES_NOTICE`.

The trade-off is accepted deliberately: with no files installed, subagent-mode
agents run as task-only defaults, carrying no role prose from either channel.
The notice is what makes that self-explanatory, and it points at the one canonical
fix (``giljo_setup``) without a popup.

Extracted to a leaf module for the same reason as ``_canonical_tool_list``: the
notice is rendered by BOTH a harness prompt builder (``codex_prompt_builder``)
and a protocol chapter (``chapters_reference``), and two hand-copied versions
would drift. One constant, pinned by one test.
"""

from __future__ import annotations

from giljo_mcp.branding import PRODUCT_NAME


# The single line a harness emits when it falls to a default agent. One sentence
# of cause, one of remedy -- deliberately not a warning banner, because the run
# is proceeding normally.
MISSING_AGENT_TEMPLATES_NOTICE = (
    f"No {PRODUCT_NAME} agent templates installed — using default agents. Run giljo_setup to install tuned agents."
)
