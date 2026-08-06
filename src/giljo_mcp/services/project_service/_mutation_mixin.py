# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Project write-path / lifecycle mixin for ProjectService (BE-6042c split).

Holds create / mission-update / update plus the lifecycle facades that delegate
to the composed sub-services (lifecycle / launch). Composed into
``ProjectService``; references ``self.*`` / ``self._*`` only. Behavior is
byte-identical to the pre-split single-file class.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError

from giljo_mcp.domain.project_status import (
    IMMUTABLE_PROJECT_STATUSES,
    LIFECYCLE_FINISHED_STATUSES,
    ProjectStatus,
)
from giljo_mcp.exceptions import (
    AlreadyExistsError,
    BaseGiljoError,
    ProjectStateError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.projects import Project
from giljo_mcp.platform_registry import ACCEPTED_EXECUTION_MODES, mode_csv
from giljo_mcp.schemas.service_responses import (
    ProjectCompleteResult,
    ProjectData,
    ProjectDetail,
    ProjectLaunchResult,
    ProjectMissionUpdateResult,
)
from giljo_mcp.services.project_helpers import _build_ws_project_data
from giljo_mcp.services.protocol_survival import build_mission_update_footer
from giljo_mcp.utils.log_sanitizer import sanitize


# Fields that are always writable regardless of project status.
# These are UI/display preferences (archive, visibility) — not project data.
ALWAYS_MUTABLE_FIELDS: frozenset[str] = frozenset({"hidden"})

# BE-9157: the exact field set of the supersede lifecycle transition. When an
# update touches ONLY these (with status == superseded), it is permitted even on
# an immutable (completed/cancelled) project — marking shipped work as
# replaced-by-successor is an audit action, not a data edit.
_SUPERSEDE_TRANSITION_FIELDS: frozenset[str] = frozenset({"status", "successor_project_id"})


class MutationMixin:
    """Project create / update / lifecycle methods. Composed into ProjectService."""

    async def create_project(
        self,
        name: str,
        mission: str,
        description: str = "",
        product_id: str | None = None,
        tenant_key: str | None = None,
        status: str = "inactive",
        project_type_id: str | None = None,
        series_number: int | None = None,
        subseries: str | None = None,
    ) -> ProjectDetail:
        """
        Create a new project.

        Args:
            name: Project name (required)
            mission: AI-generated mission statement (required)
            description: Human-written project description (default: "")
            product_id: Parent product ID if project belongs to a product
            tenant_key: Tenant key for multi-tenancy (auto-generated if not provided)
            status: Initial project status (default: "inactive")
            project_type_id: Project type ID for taxonomy classification (Handover 0440a)
            series_number: Sequential number within a project type (Handover 0440a)
            subseries: Single-letter subseries suffix (Handover 0440a)

        Returns:
            ProjectDetail: The created project, fully materialized inside the
            creating session (BE-9326). Deliberately NOT the live ORM row —
            callers read it after the session has closed.

        Raises:
            BaseGiljoError: When project creation fails

        """
        try:
            # BE-3002b: resolve tenant context (param, else the auth-set global
            # context) and raise loudly when none is resolvable — NEVER silently
            # mint a phantom tenant. A forgotten tenant_key on this INSERT would
            # otherwise orphan the project under an invisible auto-minted key,
            # bypassing the tenant guard (which does not inspect INSERTs). Mirrors
            # update_project_mission / update_project. Real callers always supply
            # a key (HTTP: current_user.tenant_key) or set context (MCP adapter).
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()
            if not tenant_key:
                raise ValidationError(
                    message="No tenant context available",
                    context={"operation": "create_project", "name": name},
                )

            # BE-9215: name column is String(255). Cap at the owning-service write
            # so every transport (REST, create_project_for_mcp) gets a clean 422
            # instead of a raw StringDataRightTruncation 500 from the DB.
            if name is not None and len(name) > 255:
                raise ValidationError(
                    message=f"Project name exceeds 255 character limit (got {len(name)}).",
                    context={"operation": "create_project"},
                )

            async with self._get_session(tenant_key) as session:
                # Validate taxonomy format: series 1-9999, subseries single letter
                if series_number is not None and (series_number < 1 or series_number > 9999):
                    raise ValidationError(
                        message="Series number must be between 1 and 9999.",
                        context={"series_number": series_number},
                    )
                if subseries is not None and (len(subseries) != 1 or not subseries.isalpha()):
                    raise ValidationError(
                        message="Subseries must be a single letter (a-z).",
                        context={"subseries": subseries},
                    )

                # Auto-assign series_number when not provided (Handover 0837a)
                # BE-6049b: ONE global counter shared across tasks AND projects
                # per (tenant_key, product_id) — every tag (FE/BE/TSK) draws from
                # the same continue-upward sequence, so a BE project created after
                # task FE-0017 gets serial 18. Lock matching rows in both tables to
                # prevent concurrent duplicates, then compute max+1 over the ACTIVE
                # pool. FOR UPDATE can't be used with aggregates.
                # BE-6079: the >9999 exhaustion cap (decision D) now lives in the
                # allocator (get_next_series_number_shared), so EVERY auto-assign
                # path is gated by one check — no inline per-service cap needed.
                if series_number is None:
                    await self._repo.lock_rows_for_series_shared(session, tenant_key, product_id)
                    series_number = await self._repo.get_next_series_number_shared(session, tenant_key, product_id)

                # Application-level duplicate check before insert
                else:
                    is_dup = await self._repo.check_duplicate_taxonomy(
                        session, tenant_key, product_id, project_type_id, series_number, subseries
                    )
                    if is_dup:
                        raise AlreadyExistsError(
                            message="Taxonomy combination already in use. Please choose a different series number or suffix.",
                            context={"name": name, "tenant_key": tenant_key},
                        )

                # Create project entity
                now = datetime.now(UTC)
                project = Project(
                    name=name,
                    mission=mission,
                    description=description,
                    tenant_key=tenant_key,
                    product_id=product_id,
                    status=status,
                    project_type_id=project_type_id,
                    series_number=series_number,
                    subseries=subseries,
                    updated_at=now,  # Explicitly set since DB schema may not have DEFAULT
                )

                await self._repo.add(session, project)
                await session.commit()
                await self._repo.refresh(session, project)

                # Handover 0440a: Eagerly load project_type relationship for taxonomy_alias.
                # BE-9326: unconditional — this used to run only when a
                # project_type_id was supplied, so an un-typed create returned a
                # row whose ``project_type`` was never loaded.
                project = await self._repo.get_with_project_type(session, tenant_key, project.id)

                self._logger.info(
                    f"Created project {sanitize(project.id)} with status '{sanitize(status)}' "
                    f"and tenant key {sanitize(tenant_key)}"
                )

                # Broadcast WebSocket event so all browsers refresh the project list
                if self._websocket_manager:
                    try:
                        await self._websocket_manager.broadcast_project_update(
                            project_id=project.id,
                            update_type="created",
                            project_data=_build_ws_project_data(project),
                            tenant_key=tenant_key,
                        )
                    except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                        self._logger.warning(f"WebSocket broadcast failed: {ws_error}")

                # BE-9326: build the response HERE, while the session is still
                # open, and return that instead of the live ORM row. The REST
                # endpoint used to receive the raw ``Project`` and read
                # ``proj.project_type`` -- a lazy relationship -- from the shared
                # response builder after the session had closed, so a successful
                # INSERT surfaced as a 500 and the caller never learned the id of
                # the row it had just created. Returning a fully materialized
                # DTO (what every other ProjectService read already does) closes
                # the whole class: no attribute of the result can trigger a load
                # after the session is gone.
                return self._build_created_project_detail(project)

        except IntegrityError as e:
            if "uq_project_taxonomy" in str(e):
                raise AlreadyExistsError(
                    message="Taxonomy combination already in use. Please choose a different series number or suffix.",
                    context={"name": name, "tenant_key": tenant_key},
                ) from e
            self._logger.exception("Failed to create project")
            raise BaseGiljoError(
                message=f"Failed to create project: {e!s}", context={"name": name, "tenant_key": tenant_key}
            ) from e
        except BaseGiljoError:
            # Re-raise domain errors (AlreadyExistsError, ValidationError, etc.) unchanged.
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to create project")
            raise BaseGiljoError(
                message=f"Failed to create project: {e!s}", context={"name": name, "tenant_key": tenant_key}
            ) from e

    async def update_project_mission(
        self, project_id: str, mission: str, tenant_key: str | None = None
    ) -> ProjectMissionUpdateResult:
        """
        Update the mission field after orchestrator analysis.

        This method also broadcasts the mission update via in-process WebSocketManager
        for real-time UI updates.

        Args:
            project_id: Project UUID
            mission: Updated mission statement
            tenant_key: Tenant key for multi-tenant isolation (uses context if not provided)

        Returns:
            Dict with success status

        Raises:
            ValidationError: No tenant context available
            ResourceNotFoundError: When project not found
            BaseGiljoError: When operation fails

        """
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()
            if not tenant_key:
                raise ValidationError(
                    message="No tenant context available",
                    context={"operation": "update_project_mission", "project_id": project_id},
                )
            async with self._get_session(tenant_key) as session:
                # Fetch project to validate state before writing
                project = await self._repo.get_by_id(session, tenant_key, project_id)

                if not project:
                    raise ResourceNotFoundError(
                        message="Project not found or access denied",
                        context={"project_id": project_id, "tenant_key": tenant_key},
                    )

                # Guard: block writes to immutable projects
                if project.status in IMMUTABLE_PROJECT_STATUSES:
                    raise ProjectStateError(
                        message=f"Cannot modify project in '{project.status.value}' status. "
                        "Only inactive and active projects can be updated.",
                        context={"project_id": project_id, "status": project.status.value},
                    )

                # Handover 0425: set staging_status to 'staging' on initial mission writes.
                # BE-fix-staging-revert: Don't downgrade once staging is complete --
                # orchestrators legitimately rewrite the project mission after agents
                # have spawned (scope clarifications, deferrals, plan refinements), and
                # rewinding staging breaks the implementation prompt endpoint with 404.
                project.mission = mission
                if project.staging_status != "staging_complete":
                    project.staging_status = "staging"
                project.updated_at = datetime.now(UTC)

                await session.commit()

                # Broadcast mission update via WebSocketManager
                await self._broadcast_mission_update(project_id, mission, project.tenant_key)

                return ProjectMissionUpdateResult(
                    message="Mission updated successfully",
                    project_id=project_id,
                    # BE-9083b: breadcrumb footer from LIVE lifecycle phase.
                    lifecycle_footer=build_mission_update_footer(
                        phase=("implementation" if project.implementation_launched_at is not None else "staging")
                    ),
                )

        except (ResourceNotFoundError, ValidationError, ProjectStateError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to update mission")
            raise BaseGiljoError(
                message=f"Failed to update mission: {e!s}", context={"project_id": project_id, "tenant_key": tenant_key}
            ) from e

    async def set_early_termination(self, project_id: str, tenant_key: str | None = None) -> None:
        """
        Flag a project for early (user-initiated) termination.

        BE-3006c: routes the ``early_termination`` write through the owning
        ProjectService so the termination-prompt API endpoint never writes or
        commits directly (single-writer rule + TRANSACTION_OWNERSHIP_CONVENTION).
        The owning ``_get_session`` scope commits.

        Args:
            project_id: Project UUID
            tenant_key: Tenant key for multi-tenant isolation (uses context if not provided)

        Raises:
            ValidationError: No tenant context available
            ResourceNotFoundError: When project not found
            BaseGiljoError: When operation fails
        """
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()
            if not tenant_key:
                raise ValidationError(
                    message="No tenant context available",
                    context={"operation": "set_early_termination", "project_id": project_id},
                )
            async with self._get_session(tenant_key) as session:
                project = await self._repo.get_by_id(session, tenant_key, project_id)
                if not project:
                    raise ResourceNotFoundError(
                        message="Project not found or access denied",
                        context={"project_id": project_id, "tenant_key": tenant_key},
                    )
                project.early_termination = True
                project.updated_at = datetime.now(UTC)
                await session.commit()
        except (ResourceNotFoundError, ValidationError):
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to set early_termination")
            raise BaseGiljoError(
                message=f"Failed to set early_termination: {e!s}",
                context={"project_id": project_id, "tenant_key": tenant_key},
            ) from e

    async def complete_project(
        self,
        project_id: str,
        summary: str,
        key_outcomes: list[str],
        decisions_made: list[str],
        git_commits: list[dict] | None = None,
        tenant_key: str | None = None,
        db_session: Any | None = None,
    ) -> ProjectCompleteResult:
        """Facade: delegates to ProjectLifecycleService."""
        return await self.lifecycle.complete_project(
            project_id,
            summary,
            key_outcomes,
            decisions_made,
            tenant_key=tenant_key,
            db_session=db_session,
            git_commits=git_commits,
        )

    async def activate_project(
        self,
        project_id: str,
        force: bool = False,
        websocket_manager: Any | None = None,
        tenant_key: str | None = None,
    ) -> Project:
        """Facade: delegates to ProjectLifecycleService."""
        return await self.lifecycle.activate_project(project_id, force, websocket_manager, tenant_key)

    async def deactivate_project(
        self,
        project_id: str,
        tenant_key: str | None = None,
        websocket_manager: Any | None = None,
    ) -> Project:
        """Facade: delegates to ProjectLifecycleService."""
        return await self.lifecycle.deactivate_project(project_id, tenant_key, websocket_manager)

    def _apply_project_updates(self, project, updates: dict[str, Any]) -> None:
        """Apply validated field updates to a project model.

        Args:
            project: Project SQLAlchemy model instance
            updates: Dict of field name -> value to apply

        Raises:
            ProjectStateError: Cannot change execution mode after implementation has launched
        """
        # execution_mode is a prompt-injection toggle: it changes only how prompts
        # are RENDERED, and every downstream reader (staging-prompt generation,
        # get_staging_instructions, spawn_job, get_job_mission) resolves it
        # LIVE. It is therefore freely changeable — back and forth — until the user
        # actually LAUNCHES implementation (the Implement button / the orchestrator
        # Play button, both of which call launch-implementation), which stamps
        # implementation_launched_at and brings agents online with prompts already
        # rendered for the chosen mode. Changing it after that point would desync
        # running agents, so that — and only that — is locked. Re-staging clears
        # implementation_launched_at (project_staging_service) and unlocks it.
        #
        # Supersedes Handover 0343's mission-based lock, which keyed on the wrong
        # signal: "mission exists" froze staged-but-not-launched projects (and legacy
        # rows born with a default mode) so the user could never correct the mode
        # after staging. Keying on implementation_launched_at also subsumes the
        # NULL-state carve-out — a pre-launch change is allowed whether the current
        # mode is NULL or already chosen.
        if "execution_mode" in updates and project.implementation_launched_at is not None:
            raise ProjectStateError(
                message=(
                    "Cannot change execution mode after implementation has launched. Re-stage the project to change it."
                ),
                context={"project_id": str(project.id)},
            )

        # Handover 0904/0960: Validate auto check-in interval (minutes)
        if "auto_checkin_interval" in updates and updates["auto_checkin_interval"] not in (5, 10, 15, 20, 30, 40, 60):
            raise ValidationError(
                message="auto_checkin_interval must be one of: 5, 10, 15, 20, 30, 40, 60 minutes",
                error_code="VALIDATION_ERROR",
                context={"project_id": str(project.id), "value": updates["auto_checkin_interval"]},
            )

        # NULL-state: execution_mode may only be SET to a real mode via PATCH (the
        # dashboard pills emit one of the four). Reject None / unknown so a client
        # cannot write an unselected or garbage mode that the boundary gates would
        # then block. An OMITTED execution_mode is dropped upstream by
        # exclude_unset and never reaches here, so this does not force a mode on
        # unrelated PATCHes.
        if "execution_mode" in updates and updates["execution_mode"] not in ACCEPTED_EXECUTION_MODES:
            raise ValidationError(
                message=f"execution_mode must be one of: {mode_csv()}",
                error_code="VALIDATION_ERROR",
                context={"project_id": str(project.id), "value": updates["execution_mode"]},
            )

        # Update allowed fields (Handover 0260: Added execution_mode)
        # Handover 0412: Added status, completed_at for archive endpoint
        # Handover 0440a: Added project_type_id, series_number, subseries for taxonomy
        # Handover 0904: Added auto_checkin_enabled, auto_checkin_interval
        allowed_fields = {
            "name",
            "description",
            "mission",
            "execution_mode",
            "status",
            "completed_at",
            "project_type_id",
            "series_number",
            "subseries",
            "auto_checkin_enabled",
            "auto_checkin_interval",
            "hidden",
            # BE-9157: successor pointer, set when marking a project superseded.
            "successor_project_id",
        }
        previous_status = project.status

        for field, value in updates.items():
            if field in allowed_fields:
                setattr(project, field, value)

        now = datetime.now(UTC)

        # BE-9343: the backend owns completed_at on a lifecycle transition. It used
        # to be written only ``if field in updates``, so a caller doing everything
        # right -- update_project(status="completed") -- produced status=completed
        # with completed_at NULL, and the dashboard hid it by falling back to
        # updated_at. Nobody is asked to supply the field; this is the chokepoint
        # every MCP and REST write through update_project flows through. It is NOT
        # the only terminal write path -- closeout, staging-cancel and soft-delete
        # set a terminal status directly -- so it does not mean the backend always
        # stamps.
        #
        # Additive, never an override: an explicitly supplied completed_at and an
        # already-set value both win, so a completed project later marked
        # superseded keeps its real date. No production caller currently supplies
        # one; the branch guards the allowlisted field. Do NOT delete it as dead
        # scaffolding -- completed_at is in allowed_fields, so dropping the guard
        # would silently turn the additive rule into an override rule for the next
        # caller that does pass a date (BE-9343 audit F3 removed the last such
        # caller, the archive endpoint).
        # Symmetric on the way back out -- leaving a terminal status clears the
        # date, mirroring continue_working. That branch is genuinely reachable:
        # terminated and deleted are lifecycle-finished but NOT immutable, so the
        # generic write path can move them back to active/inactive.
        if "status" in updates and "completed_at" not in updates:
            if project.status in LIFECYCLE_FINISHED_STATUSES:
                if project.completed_at is None:
                    project.completed_at = now
            elif previous_status in LIFECYCLE_FINISHED_STATUSES:
                project.completed_at = None

        project.updated_at = now

    @staticmethod
    def _build_created_project_detail(project) -> ProjectDetail:
        """Materialize a just-created project into a session-independent DTO.

        BE-9326: called INSIDE ``create_project``'s session, so every attribute
        is read while the row is still attached. ``project`` must have been
        fetched with ``project_type`` eagerly loaded.

        A freshly created project has no agents and no staging/launch history,
        so those fields are their empty values by construction rather than by
        query — mirroring the ``agents=[] / agent_count=0 / message_count=0``
        the REST create endpoint has always passed.
        """
        return ProjectDetail(
            id=str(project.id),
            alias=project.alias,
            name=project.name,
            mission=project.mission,
            description=project.description,
            status=project.status,
            staging_status=project.staging_status,
            implementation_launched_at=(
                project.implementation_launched_at.isoformat() if project.implementation_launched_at else None
            ),
            product_id=project.product_id,
            tenant_key=project.tenant_key,
            execution_mode=project.execution_mode,
            auto_checkin_enabled=project.auto_checkin_enabled,
            auto_checkin_interval=project.auto_checkin_interval,
            cancellation_reason=project.cancellation_reason,
            early_termination=project.early_termination,
            created_at=project.created_at.isoformat() if project.created_at else None,
            updated_at=project.updated_at.isoformat() if project.updated_at else None,
            completed_at=project.completed_at.isoformat() if project.completed_at else None,
            agents=[],
            agent_count=0,
            message_count=0,
            # Handover 0440a: Taxonomy fields
            project_type_id=project.project_type_id,
            project_type=project.project_type,
            series_number=project.series_number,
            subseries=project.subseries,
            taxonomy_alias=project.taxonomy_alias,
            hidden=project.hidden is True,
            successor_project_id=project.successor_project_id,
        )

    @staticmethod
    def _build_project_data(project) -> ProjectData:
        """Build ProjectData response from a Project model instance."""
        return ProjectData(
            id=project.id,
            name=project.name,
            status=project.status,
            mission=project.mission,
            description=project.description,
            execution_mode=project.execution_mode,
            auto_checkin_enabled=project.auto_checkin_enabled,
            auto_checkin_interval=project.auto_checkin_interval,
            cancellation_reason=project.cancellation_reason,
            early_termination=project.early_termination,
            created_at=project.created_at.isoformat() if project.created_at else None,
            updated_at=project.updated_at.isoformat() if project.updated_at else None,
            completed_at=project.completed_at.isoformat() if project.completed_at else None,
            product_id=project.product_id,
            # Handover 0440a: Taxonomy fields
            project_type_id=project.project_type_id,
            project_type=project.project_type,
            series_number=project.series_number,
            subseries=project.subseries,
            taxonomy_alias=project.taxonomy_alias,
            hidden=project.hidden is True,
            successor_project_id=project.successor_project_id,
        )

    async def update_project(
        self,
        project_id: str,
        updates: dict[str, Any],
        websocket_manager: Any | None = None,
    ) -> ProjectData:
        """
        Update project fields.

        Updates all provided fields (name, description, mission).
        This is the fixed version that handles multiple fields, not just mission.

        Args:
            project_id: Project UUID
            updates: Dict of field updates (allowed: name, description, mission, config_data)
            websocket_manager: Deprecated -- ignored. Uses self._websocket_manager instead.

        Returns:
            Updated project data dictionary

        Raises:
            ResourceNotFoundError: Project not found
            ProjectStateError: Cannot change execution mode after implementation has launched

        """
        tenant_key = self.tenant_manager.get_current_tenant()
        async with self._get_session(tenant_key) as session:
            # Fetch project
            # Handover 0440a: Eagerly load project_type for taxonomy_alias property
            project = await self._repo.get_by_id_with_type(
                session, self.tenant_manager.get_current_tenant(), project_id
            )

            if not project:
                raise ResourceNotFoundError(message="Project not found", context={"project_id": project_id})

            # Guard: block data writes to immutable projects.
            # ALWAYS_MUTABLE_FIELDS (e.g. hidden/archive) bypass this guard —
            # they are UI display preferences, not project data mutations.
            # BE-9157 carve-out: marking a project ``superseded`` (optionally with
            # its successor pointer) is a lifecycle AUDIT transition, not a data
            # edit, and is a first-class use case ON already-shipped work — a
            # COMPLETED/CANCELLED project can later be marked replaced-by-successor.
            # So permit the exact supersede transition even from an immutable status.
            is_supersede_transition = (
                updates.get("status") == ProjectStatus.SUPERSEDED and updates.keys() <= _SUPERSEDE_TRANSITION_FIELDS
            )
            if (
                project.status in IMMUTABLE_PROJECT_STATUSES
                and not updates.keys() <= ALWAYS_MUTABLE_FIELDS
                and not is_supersede_transition
            ):
                raise ProjectStateError(
                    message=f"Cannot modify project in '{project.status.value}' status. "
                    "Only inactive and active projects can be updated.",
                    context={"project_id": project_id, "status": project.status.value},
                )

            # BE-5039 Phase 2b: validate status enum membership at the
            # service write boundary so callers get a clean 422
            # ValidationError instead of a 500 surfaced from the Postgres
            # ENUM cast. ProjectStatus accepts both raw strings and enum
            # members thanks to the ``str`` mixin.
            if "status" in updates and updates["status"] is not None:
                try:
                    updates["status"] = ProjectStatus(updates["status"])
                except ValueError as e:
                    raise ValidationError(
                        message=(
                            f"Invalid status '{updates['status']}'. "
                            f"Must be one of: {', '.join(sorted(s.value for s in ProjectStatus))}."
                        ),
                        context={"project_id": project_id, "status": updates["status"]},
                    ) from e

            # BE-9157: validate the successor pointer within-tenant. A project
            # cannot supersede itself, and the successor must be a real project
            # in the SAME tenant (the DB FK alone is not tenant-scoped, so the
            # cross-tenant guard lives here). ``None`` clears the pointer.
            if updates.get("successor_project_id"):
                successor_id = updates["successor_project_id"]
                if successor_id == project_id:
                    raise ValidationError(
                        message="A project cannot supersede itself.",
                        context={"project_id": project_id},
                    )
                successor = await self._repo.get_by_id(session, tenant_key, successor_id)
                if not successor:
                    raise ValidationError(
                        message="Successor project not found or access denied.",
                        context={"project_id": project_id, "successor_project_id": successor_id},
                    )

            # BE-9215: name column is String(255). Reject an over-long rename with
            # a clean 422 at the write boundary rather than a DB truncation 500.
            if updates.get("name") is not None and len(updates["name"]) > 255:
                raise ValidationError(
                    message=f"Project name exceeds 255 character limit (got {len(updates['name'])}).",
                    context={"project_id": project_id},
                )

            self._apply_project_updates(project, updates)

            try:
                await session.commit()
            except IntegrityError as e:
                if "uq_project_taxonomy" in str(e):
                    raise AlreadyExistsError(
                        message="Taxonomy combination already in use. Please choose a different series number or suffix.",
                        context={"project_id": project_id},
                    ) from e
                # BE-9016 (Sentry GILJOAI-BACKEND-A): update_project lets status
                # -> active through directly, unlike the deliberate activate_project
                # path (api/endpoints/projects/lifecycle.py) which deactivates the
                # sibling first. Catching here (at commit) also covers the race of
                # two agents activating different projects for the same product at
                # once -- a pre-write check alone cannot. Approach-a (clean reject)
                # is CHOSEN over auto-deactivating the sibling: silently deactivating
                # a project that may have running agents is a dangerous side effect;
                # activation stays the deliberate path.
                if "idx_project_single_active_per_product" in str(e):
                    raise AlreadyExistsError(
                        message=(
                            "Another project is already active for this product. "
                            "Deactivate it first, or use the activate endpoint, "
                            "which handles this automatically."
                        ),
                        error_code="ANOTHER_PROJECT_ACTIVE",
                        context={"project_id": project_id},
                    ) from e
                raise
            await self._repo.refresh(session, project)

            # Reload project_type relationship (expired after commit)
            if project.project_type_id:
                project = await self._repo.get_with_project_type(
                    session, self.tenant_manager.get_current_tenant(), project.id
                )

            self._logger.info(f"Updated project {sanitize(project_id)}")

            # Broadcast WebSocket event (use constructor-injected manager, not method param)
            ws = self._websocket_manager
            if ws:
                try:
                    await ws.broadcast_project_update(
                        project_id=project.id,
                        update_type="updated",
                        project_data=_build_ws_project_data(project),
                        tenant_key=self.tenant_manager.get_current_tenant(),
                    )
                except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                    self._logger.warning(f"WebSocket broadcast failed: {ws_error}")

            return self._build_project_data(project)

    async def launch_project(
        self,
        project_id: str,
        user_id: str | None = None,
        launch_config: dict[str, Any | None] = None,
        websocket_manager: Any | None = None,
    ) -> ProjectLaunchResult:
        """Facade: delegates to ProjectLaunchService (Handover 0950i)."""
        return await self.launch.launch_project(
            project_id,
            user_id,
            launch_config,
            websocket_manager,
            project_service=self,
        )
