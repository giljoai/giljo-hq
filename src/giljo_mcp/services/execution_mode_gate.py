# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Execution-mode selection gate (NULL-state redesign).

A project's ``execution_mode`` is NULL until the user explicitly picks one in the
dashboard. NULL means "not yet selected" -- a first-class, GATED state that must
never silently coerce to ``'multi_terminal'`` (that silent default shipped the
wrong orchestration mode). The boundary entry points -- staging prompt
generation, ``spawn_job``, ``get_staging_instructions`` and
``get_job_mission`` -- call :func:`execution_mode_selected` and refuse to
proceed when it returns ``False``. Because the refusal happens at the boundary, a
NULL never reaches the protocol-render layer, whose deliberate HO1020 fail-safes
(``.get(mode, "multi_terminal")``) map an *unknown* mode to the platform-neutral
protocol and stay untouched by this redesign.

Edition Scope: CE.
"""

from __future__ import annotations

from typing import Any

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.platform_registry import VALID_EXECUTION_MODES, mode_label_list


# The user-selectable orchestration modes. A project holds exactly one of these,
# or NULL (not yet selected). Single source: ``giljo_mcp.platform_registry`` --
# re-exported here so existing importers keep resolving the name.
__all__ = [
    "EXECUTION_MODE_NOT_SELECTED_MESSAGE",
    "VALID_EXECUTION_MODES",
    "effective_execution_mode",
    "execution_mode_not_selected_message",
    "execution_mode_selected",
    "require_execution_mode",
]


def effective_execution_mode(project_execution_mode: Any, chain_execution_mode: Any = None) -> Any:
    """Return the mode a project actually RUNS in — the CHAIN's when it is a member.

    BE-9335: a chain's execution mode is chosen once, for the whole chain, and is
    stored on the RUN (``sequence_runs.execution_mode``). ``projects.execution_mode``
    is the SOLO authority and the fallback. Every chain-member reader must resolve
    through here, because the failure this fixes was not a stale value but a
    DISAGREEMENT: the mission protocol header already resolved the run (BE-6177)
    while ``get_staging_instructions`` and the ``spawn_job`` bootstrap resolved the
    project column, so one member was told two different harnesses at once.

    Deliberately NOT gated on ``implementation_launched_at``. The per-project
    post-launch lock exists so a LIVE agent's harness cannot change under it; for a
    chain member that guarantee comes from the RUN's mode being frozen as soon as
    any member crosses that same launch gate (``refuse_mode_change_if_live``).
    Gating the RESOLVER on it instead would defeat the fix outright, because driving
    a chain LAUNCHES each member — the head is launched by the dashboard before the
    drive prompt is even copied — so every member would fall straight back to the
    divergent project column exactly when it matters. The lock therefore lives on
    the write, not the read.

    ``chain_execution_mode`` is None on the solo path (no active run), so the
    project column is returned unchanged and the solo render stays byte-identical.
    """
    chain_mode = str(chain_execution_mode).strip() if chain_execution_mode else ""
    return chain_mode or project_execution_mode


# Single user-facing instruction reused across the service-layer gates so the
# dashboard guidance is identical wherever the gate fires. The mode list is built
# from the PlatformRegistry so a new/removed platform updates this message
# automatically (BE-3010a: the literal list previously omitted Antigravity).
EXECUTION_MODE_NOT_SELECTED_MESSAGE = (
    "No execution mode is selected for this project. Open the project in the "
    f"GiljoAI dashboard, pick an execution mode ({mode_label_list()}), and stage "
    "it before continuing."
)


def execution_mode_not_selected_message(project_name: str | None = None) -> str:
    """The mode-not-selected guidance, naming the project when it is known (BE-9335).

    A chain has several members, so a refusal that says only "this project" leaves
    the user to work out which one stalled the chain. Falls back to the unnamed
    constant so callers without a loaded project are unchanged.
    """
    if not project_name:
        return EXECUTION_MODE_NOT_SELECTED_MESSAGE
    return EXECUTION_MODE_NOT_SELECTED_MESSAGE.replace("for this project.", f"for project '{project_name}'.", 1)


def execution_mode_selected(project: Any) -> bool:
    """Return ``True`` when ``project`` has a non-empty execution mode chosen.

    A loaded ORM ``Project`` always has the attribute, so ``getattr`` returns the
    column value (``None`` for a NULL row). A whitespace-only value is treated as
    unset. Callers gate on this to keep a NULL out of the dispatch/render layer.

    DELIBERATELY does NOT check membership in :data:`VALID_EXECUTION_MODES`. The
    division of labor is: this gate keeps a NULL/empty (unselected) mode out of
    rendering; an *unknown but non-empty* mode is the concern of the HO1020
    render-layer fail-safes (``.get(mode, "multi_terminal")``), which map it to
    the platform-neutral protocol. Tightening this to a membership check would
    turn a legacy/unknown mode into a hard block instead of that intended
    fallback — do not add ``in VALID_EXECUTION_MODES`` here. The write boundaries
    (staging Query regex + the ProjectService PATCH guard) are what keep stored
    modes within the valid set.
    """
    mode = getattr(project, "execution_mode", None)
    return bool(mode and str(mode).strip())


def require_execution_mode(project: Any, project_id: str, tenant_key: str) -> None:
    """Raise ``ValidationError`` when ``project`` has no execution mode selected.

    The spawn-boundary gate: refusing here dominates the downstream coercion sites
    so a NULL never silently becomes ``'multi_terminal'``. ``ValidationError`` is
    in ``spawn_job``'s re-raise allowlist, so it surfaces cleanly (not as a
    DatabaseError). Normal flow sets the mode at staging, so this is a backstop
    for out-of-band / legacy rows.
    """
    if not execution_mode_selected(project):
        raise ValidationError(
            message=execution_mode_not_selected_message(getattr(project, "name", None)),
            error_code="EXECUTION_MODE_NOT_SELECTED",
            context={"project_id": project_id, "tenant_key": tenant_key},
        )
