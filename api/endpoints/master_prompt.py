# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""The board-level "Launch staged..." master prompt (FE-9555).

One POST returns BOTH halves of the confirm dialog: the missions being approved
and the single copyable master prompt built from them. One call on purpose --
the list the user READ and the list the prompt DRIVES have to be the same list,
and assembling the mission list client-side from cached board rows while the
prompt is built server-side from fresh rows is precisely how those two diverge
without anyone noticing.

Its own module rather than an addition to ``api/endpoints/prompts.py``, which
is already at the repository's per-file size limit. Mounted under the same
``/api/v1/prompts`` prefix, so the route reads as part of the same family.

Edition Scope: Both.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.http.url_resolver import get_public_url
from giljo_mcp.models import Project, User
from giljo_mcp.platform_registry import VALID_EXECUTION_MODES
from giljo_mcp.prompts.master_prompt_builder import build_master_prompt
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)
router = APIRouter()

# The board caps a run at the same 5 projects the sequence-run record does, so a
# selection that could never be recorded is refused before a prompt is minted for it.
MAX_MASTER_PROMPT_PROJECTS = 5


class MasterPromptProject(BaseModel):
    """One project as the confirm dialog lists it."""

    project_id: str
    taxonomy_alias: str
    name: str
    mission: str


class MasterPromptRequest(BaseModel):
    project_ids: list[str] = Field(min_length=1, max_length=MAX_MASTER_PROMPT_PROJECTS)
    execution_mode: str

    @field_validator("execution_mode")
    @classmethod
    def _must_be_a_real_mode(cls, value: str) -> str:
        # Ruling 6 binds BOTH doors. The dialog asks the question; accepting an
        # omitted or unknown mode here would let the UI door quietly default,
        # which is the exact behaviour the harness door just stopped doing.
        if value not in VALID_EXECUTION_MODES:
            raise ValueError(f"must be one of {sorted(VALID_EXECUTION_MODES)}")
        return value


class MasterPromptResponse(BaseModel):
    prompt: str
    projects: list[MasterPromptProject]
    execution_mode: str


@router.post("/master", response_model=MasterPromptResponse)
async def build_board_master_prompt(
    request: MasterPromptRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> MasterPromptResponse:
    """Mint the conductor seed for a set of staged projects selected on the board.

    Nothing is written and nothing is launched. Ruling 4: the UI door never
    executes -- it prepares prompts and crosses gates. The pasted session creates
    the ``sequence_run`` record itself via ``link_projects``.
    """
    logger.info(
        "User %s requested a master prompt for %d project(s)",
        sanitize(current_user.username),
        len(request.project_ids),
    )

    result = await db.execute(
        select(Project).where(
            Project.id.in_(request.project_ids),
            Project.tenant_key == current_user.tenant_key,
        )
    )
    by_id = {project.id: project for project in result.scalars().all()}

    # ALL-or-nothing, deliberately. A partial answer would return a prompt that
    # silently drops projects the user selected and believes are in the run --
    # and, for an id belonging to another tenant, would be the difference between
    # a 404 and leaking that tenant's project name and mission text into a prompt.
    missing = [pid for pid in request.project_ids if pid not in by_id]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{len(missing)} of the selected projects were not found.",
        )

    # Rendered in the order ASKED FOR, not the order the database returned. The
    # board's selection order is a decision the user already made (possibly by
    # sorting on roadmap order), and re-sorting here would override it silently.
    projects = [
        MasterPromptProject(
            project_id=pid,
            taxonomy_alias=by_id[pid].taxonomy_alias or "",
            name=by_id[pid].name or "",
            mission=by_id[pid].mission or "",
        )
        for pid in request.project_ids
    ]

    try:
        prompt = build_master_prompt(
            projects=[p.model_dump() for p in projects],
            execution_mode=request.execution_mode,
            mcp_url=get_public_url(),
            # The dashboard's copy button targets a terminal the server cannot
            # sniff, so the CE-0035 ToolSearch bootstrap is included: a Claude Code
            # session without it cannot make its first tool call, while any other
            # harness reads one extra line it can ignore. Wrong in the harmless
            # direction rather than the broken one.
            harness_is_claude=True,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return MasterPromptResponse(prompt=prompt, projects=projects, execution_mode=request.execution_mode)
