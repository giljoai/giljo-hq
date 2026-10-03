# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status

from api.endpoints._boundary_types import IdPath, IdQuery
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.domain.project_status import LIFECYCLE_FINISHED_STATUSES, ProjectStatus
from giljo_mcp.models import User
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.utils.log_sanitizer import sanitize

from .dependencies import get_project_service
from .models import (
    AgentJobDetail,
    MemoryEntryDetail,
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectReviewResponse,
    ProjectUpdate,
)


ProjectSortKey = Literal["series_number", "name", "created_at", "completed_at", "status", "staging_status", "roadmap"]


logger = logging.getLogger(__name__)
router = APIRouter()

_ACTIVE_LIFECYCLE_STATUSES: list[str] = sorted(
    {s.value for s in ProjectStatus} - {s.value for s in LIFECYCLE_FINISHED_STATUSES}
)


def _to_project_response(
    proj,
    *,
    agents: list | None = None,
    agent_count: int | None = None,
    message_count: int | None = None,
) -> ProjectResponse:
    return ProjectResponse(
        id=str(proj.id),
        alias=getattr(proj, "alias", "") or "",
        name=proj.name,
        description=proj.description,
        mission=proj.mission or "",
        status=proj.status,
        staging_status=getattr(proj, "staging_status", None),
        product_id=proj.product_id,
        created_at=proj.created_at,
        updated_at=proj.updated_at,
        completed_at=proj.completed_at,
        implementation_launched_at=getattr(proj, "implementation_launched_at", None),
        reviewed_at=getattr(proj, "reviewed_at", None),
        review_pending=getattr(proj, "review_pending", False),
        agent_count=agent_count if agent_count is not None else getattr(proj, "agent_count", 0),
        message_count=message_count if message_count is not None else getattr(proj, "message_count", 0),
        execution_mode=proj.execution_mode,
        auto_checkin_enabled=getattr(proj, "auto_checkin_enabled", False),
        auto_checkin_interval=getattr(proj, "auto_checkin_interval", 10),
        agents=agents if agents is not None else [],
        project_type_id=proj.project_type_id,
        project_type=proj.project_type,
        series_number=proj.series_number,
        subseries=proj.subseries,
        taxonomy_alias=proj.taxonomy_alias,
        hidden=getattr(proj, "hidden", False),
        successor_project_id=getattr(proj, "successor_project_id", None),
    )


@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project: ProjectCreate,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    """
    Create a new project.

    Uses ProjectService for all database operations.

    Args:
        project: Project creation request
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        ProjectResponse with created project details

    Raises:
        HTTPException 400: Project creation failed
        HTTPException 403: User not authorized
    """
    logger.debug("User %s creating project: %s", sanitize(current_user.username), sanitize(project.name))

    mission = project.mission
    if project.project_type_id and project.bootstrap_template_vars is not None:
        resolved_type = await project_service.get_project_type_by_id(
            type_id=project.project_type_id,
            tenant_key=current_user.tenant_key,
        )
        if resolved_type is not None and (resolved_type.abbreviation or "").upper() == "CTX":
            mission = await project_service.render_ctx_bootstrap_mission(
                product_id=project.product_id,
                tenant_key=current_user.tenant_key,
                bootstrap_template_vars=project.bootstrap_template_vars,
            )

    created_project = await project_service.create_project(
        name=project.name,
        mission=mission,
        description=project.description or "",
        product_id=project.product_id,
        tenant_key=current_user.tenant_key,
        status=project.status,
        project_type_id=project.project_type_id,
        series_number=project.series_number,
        subseries=project.subseries,
    )

    logger.info("Created project %s for tenant %s", created_project.id, sanitize(current_user.tenant_key))

    return _to_project_response(created_project, agents=[], agent_count=0, message_count=0)


@router.get("/", response_model=list[ProjectListResponse])
async def list_projects(
    response: Response,
    status_filter: IdQuery = None,
    product_id: IdQuery = None,
    include_completed: bool = Query(
        default=False,
        description=(
            "When false (default) the dashboard list returns only active-lifecycle "
            "projects, excluding completed/cancelled/terminated/deleted. Set true to "
            "show all archived projects too. Ignored when status_filter is given."
        ),
    ),
    include_hidden: bool = Query(
        default=False,
        description=(
            "When false (default) hidden projects are excluded at the SQL "
            "layer (server-side offload). Set true to return both hidden and visible "
            "rows. Ignored when hidden_only=true."
        ),
    ),
    hidden_only: bool = Query(
        default=False,
        description=(
            "When true, return ONLY hidden projects (the Projects page "
            "'Show hidden' view). Pair with include_completed=true to list hidden "
            "rows across all lifecycle statuses. Wins over include_hidden."
        ),
    ),
    statuses: list[str] | None = Query(
        default=None,
        description=(
            "Repeatable multi-status filter driving the dashboard Status "
            "multi-select (e.g. ?statuses=active&statuses=inactive). When given it "
            "wins over the single status_filter and the include_completed default. "
            "Omit to keep the prior single-status / lifecycle-default behavior."
        ),
    ),
    search: str | None = Query(
        default=None,
        max_length=200,
        description=(
            "Case-insensitive substring search across name, id, and the "
            "taxonomy alias (e.g. 'BE-50'). Applied at the SQL layer."
        ),
    ),
    sort: ProjectSortKey | None = Query(
        default=None,
        description=(
            "Server-side sort column key (series_number, name, created_at, "
            "completed_at, status, staging_status). Also 'roadmap' -- orders "
            "by each project's roadmap position (roadmap_items.sort_order), the same "
            "ordering /roadmap renders; projects not on the roadmap sort last. "
            "Only honored alongside limit/offset pagination."
        ),
    ),
    sort_dir: Literal["asc", "desc"] | None = Query(
        default=None,
        description="Sort direction ('asc' | 'desc'). Defaults to ascending.",
    ),
    limit: int | None = Query(
        default=None,
        ge=1,
        le=200,
        description="Opt-in page size. When omitted the endpoint returns the full set.",
    ),
    offset: int | None = Query(
        default=None,
        ge=0,
        description="Opt-in row offset for pagination (pairs with limit).",
    ),
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> list[ProjectListResponse]:
    """
    List all projects for current tenant, optionally scoped to a product.

    Defaults to active-lifecycle, non-hidden projects (the same status exclusion
    the MCP ``list_projects`` tool applies); pass ``status_filter`` to query a
    specific status, or ``include_completed=true`` to show archived projects too.

    Hidden is an orthogonal per-row axis. By default hidden rows are
    excluded server-side; ``hidden_only=true`` returns only hidden rows (the
    Projects-page "Show hidden" view, a pure read — it never re-tags), and
    ``include_hidden=true`` returns both.

    Returns the thin ``ProjectListResponse`` wire shape: per-row
    ``mission``/``description`` are NOT emitted on the list — the dashboard
    fetches those lazily on row-open via the single-project detail endpoint.

    Args:
        status_filter: Optional explicit status filter (wins over the default)
        product_id: Optional product ID to scope results
        include_completed: Include completed/cancelled/archived projects
        include_hidden: Include hidden rows alongside visible ones
        hidden_only: Return only hidden rows (wins over include_hidden)
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        List of ProjectListResponse objects (no per-row mission/description)
    """
    logger.debug(
        "User %s listing projects (status=%s, product=%s, include_completed=%s, include_hidden=%s, hidden_only=%s)",
        sanitize(current_user.username),
        sanitize(str(status_filter)),
        sanitize(str(product_id)),
        sanitize(str(include_completed)),
        sanitize(str(include_hidden)),
        sanitize(str(hidden_only)),
    )

    if statuses:
        effective_status: str | list[str] | None = statuses
    elif status_filter is not None:
        effective_status = status_filter
    elif include_completed:
        effective_status = None
    else:
        effective_status = _ACTIVE_LIFECYCLE_STATUSES

    if hidden_only:
        hidden_filter: bool | None = True
    elif include_hidden:
        hidden_filter = None
    else:
        hidden_filter = False

    projects = await project_service.list_projects(
        status=effective_status,
        tenant_key=current_user.tenant_key,
        include_cancelled=True,
        product_id=product_id,
        hidden=hidden_filter,
        search=search,
        sort_key=sort,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )

    if limit is not None or offset is not None:
        total = await project_service.count_projects(
            status=effective_status,
            tenant_key=current_user.tenant_key,
            include_cancelled=True,
            product_id=product_id,
            hidden=hidden_filter,
            search=search,
        )
    else:
        total = len(projects)
    response.headers["X-Total-Count"] = str(total)

    logger.info(f"Found {len(projects)} projects for tenant {current_user.tenant_key}")

    return [
        ProjectListResponse(
            id=proj.id,
            alias="",
            name=proj.name,
            status=proj.status,
            staging_status=proj.staging_status,
            product_id=proj.product_id,
            created_at=proj.created_at,
            updated_at=proj.updated_at,
            completed_at=proj.completed_at,
            implementation_launched_at=proj.implementation_launched_at,
            agent_count=0,
            message_count=0,
            agents=[],
            execution_mode=proj.execution_mode,
            project_type_id=proj.project_type_id,
            project_type=proj.project_type,
            series_number=proj.series_number,
            subseries=proj.subseries,
            taxonomy_alias=proj.taxonomy_alias,
            hidden=getattr(proj, "hidden", False),
        )
        for proj in projects
    ]


@router.get("/deleted", response_model=list[ProjectListResponse])
async def get_deleted_projects(
    product_id: IdQuery = None,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> list[ProjectListResponse]:
    """
    Get soft-deleted projects for recovery.

    Returns projects with status='deleted' and deleted_at timestamp set.
    These projects can be recovered within 10 days of deletion.

    Returns the thin ``ProjectListResponse`` wire shape: the deleted
    list, like the main list, omits per-row mission/description.

    Args:
        product_id: Optional product ID to scope results
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        List of ProjectListResponse for deleted projects (no mission/description)

    Raises:
        HTTPException 500: Failed to list deleted projects
    """
    logger.debug(f"User {sanitize(current_user.username)} listing deleted projects (product={sanitize(product_id)})")

    projects = await project_service.list_projects(
        status="deleted", tenant_key=current_user.tenant_key, product_id=product_id
    )

    logger.info(f"Found {len(projects)} deleted projects for tenant {current_user.tenant_key}")

    return [
        ProjectListResponse(
            id=proj.id,
            alias="",
            name=proj.name,
            status=proj.status,
            staging_status=proj.staging_status,
            product_id=proj.product_id,
            created_at=proj.created_at,
            updated_at=proj.updated_at,
            completed_at=proj.completed_at,
            implementation_launched_at=proj.implementation_launched_at,
            agent_count=0,
            message_count=0,
            execution_mode=proj.execution_mode,
            agents=[],
            project_type_id=proj.project_type_id,
            project_type=proj.project_type,
            series_number=proj.series_number,
            subseries=proj.subseries,
            taxonomy_alias=proj.taxonomy_alias,
            hidden=getattr(proj, "hidden", False),
        )
        for proj in projects
    ]


@router.get("/active", response_model=list[ProjectResponse])
async def get_active_project(
    product_id: IdQuery = None,
    include_unreviewed: bool = False,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> list[ProjectResponse]:
    """
    Get the active project(s) for the user's tenant, scoped to product_id.

    Returns a list — empty if no project is active in scope.
    ``include_unreviewed=true`` (the Jobs board's read) also returns completed
    projects no human has reviewed yet, marked ``review_pending``.
    ``product_id`` scopes the read to one product; omitting it reads across the
    whole tenant for callers with no product context. Several projects may be
    active at once.

    Args:
        product_id: Optional product ID to scope the read
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        List of ProjectResponse for the active project(s) in scope
    """
    logger.debug(f"User {current_user.username} fetching active project (product={sanitize(str(product_id))})")

    projects = await project_service.query.get_active_projects(
        product_id=product_id, include_unreviewed=include_unreviewed
    )

    if not projects:
        logger.info(f"No active projects found for tenant {current_user.tenant_key}")
        return []

    logger.info(f"Retrieved {len(projects)} active project(s) for tenant {current_user.tenant_key}")

    return [_to_project_response(proj) for proj in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    """
    Get project details by ID.

    Args:
        project_id: Project UUID or alias
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        ProjectResponse with project details

    Raises:
        HTTPException 404: Project not found
    """
    logger.debug("User %s getting project %s", sanitize(current_user.username), sanitize(project_id))

    proj = await project_service.get_project(project_id=project_id, tenant_key=current_user.tenant_key)

    logger.info(f"Retrieved project {sanitize(project_id)} for tenant {sanitize(current_user.tenant_key)}")

    agents_from_service = proj.agents

    return _to_project_response(
        proj, agents=agents_from_service, agent_count=proj.agent_count or len(agents_from_service)
    )


@router.get("/{project_id}/review", response_model=ProjectReviewResponse)
async def get_project_review(
    project_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectReviewResponse:
    """
    Get project details with agent jobs and 360 memory entries for review.

    Returns the base project data plus associated agent jobs (from agent_jobs/agent_executions)
    and 360 memory entries (from product_memory_entries WHERE project_id matches).

    Args:
        project_id: Project UUID or alias
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        ProjectReviewResponse with project, agent_jobs, and memory_entries
    """
    logger.debug("User %s getting project review %s", sanitize(current_user.username), sanitize(project_id))

    proj = await project_service.get_project(project_id=project_id, tenant_key=current_user.tenant_key)
    agents_from_service = proj.agents

    project_resp = _to_project_response(
        proj, agents=agents_from_service, agent_count=proj.agent_count or len(agents_from_service)
    )

    agent_details = await project_service.query.get_project_agent_details(
        project_id=project_id, tenant_key=current_user.tenant_key
    )
    memory_entries = await project_service.query.get_project_memory_entries(
        project_id=project_id, tenant_key=current_user.tenant_key
    )

    return ProjectReviewResponse(
        project=project_resp,
        agent_jobs=[AgentJobDetail(**aj) for aj in agent_details],
        memory_entries=[MemoryEntryDetail(**me) for me in memory_entries],
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: IdPath,
    updates: ProjectUpdate,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    """
    Update project fields.

    Supports updating: name, description, mission, status.
    Only provided fields are updated (partial updates supported).

    Args:
        project_id: Project UUID
        updates: Fields to update
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        ProjectResponse with updated project

    Raises:
        HTTPException 404: Project not found
        HTTPException 400: Update failed
    """
    logger.debug("User %s updating project %s", sanitize(current_user.username), sanitize(project_id))

    update_dict = updates.dict(exclude_unset=True)

    if not update_dict:
        detail = await project_service.get_project(project_id=project_id, tenant_key=current_user.tenant_key)
        response = _to_project_response(
            detail, agents=[], agent_count=detail.agent_count, message_count=detail.message_count
        )
    else:
        proj = await project_service.update_project(project_id=project_id, updates=update_dict)
        response = _to_project_response(proj, agents=[], agent_count=0, message_count=0)

    logger.info(f"Updated project {sanitize(project_id)}")

    return response
