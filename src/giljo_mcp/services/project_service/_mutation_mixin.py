# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
from giljo_mcp.services.project_service._lifecycle_redirects import (
    require_supersede_successor,
    route_active_inactive_status_transition,
    validate_supersede_successor,
)
from giljo_mcp.services.protocol_survival import build_mission_update_footer
from giljo_mcp.services.text_field_validation import require_non_blank
from giljo_mcp.utils.log_sanitizer import sanitize


ALWAYS_MUTABLE_FIELDS: frozenset[str] = frozenset({"hidden"})

_SUPERSEDE_TRANSITION_FIELDS: frozenset[str] = frozenset({"status", "successor_project_id"})


class MutationMixin:

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
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()
            if not tenant_key:
                raise ValidationError(
                    message="No tenant context available",
                    context={"operation": "create_project", "name": name},
                )

            require_non_blank(name, field="name", operation="create_project", entity="Project", max_length=255)

            if product_id is None or not str(product_id).strip():
                raise ValidationError(
                    message=(
                        "A project must belong to a product. Pass the product_id of one of your "
                        "own products (or omit it on the MCP tool to bind to the active product)."
                    ),
                    context={"operation": "create_project", "name": name},
                )

            async with self._get_session(tenant_key) as session:
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

                if series_number is None:
                    await self._repo.lock_rows_for_series_shared(session, tenant_key, product_id)
                    series_number = await self._repo.get_next_series_number_shared(session, tenant_key, product_id)

                else:
                    is_dup = await self._repo.check_duplicate_taxonomy(
                        session, tenant_key, product_id, project_type_id, series_number, subseries
                    )
                    if is_dup:
                        raise AlreadyExistsError(
                            message="Taxonomy combination already in use. Please choose a different series number or suffix.",
                            context={"name": name, "tenant_key": tenant_key},
                        )

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
                    updated_at=now,
                )

                await self._repo.add(session, project)
                await session.commit()
                await self._repo.refresh(session, project)

                project = await self._repo.get_with_project_type(session, tenant_key, project.id)

                self._logger.info(
                    f"Created project {sanitize(project.id)} with status '{sanitize(status)}' "
                    f"and tenant key {sanitize(tenant_key)}"
                )

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
            raise
        except Exception as e:
            self._logger.exception("Failed to create project")
            raise BaseGiljoError(
                message=f"Failed to create project: {e!s}", context={"name": name, "tenant_key": tenant_key}
            ) from e

    async def update_project_mission(
        self, project_id: str, mission: str, tenant_key: str | None = None
    ) -> ProjectMissionUpdateResult:
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()
            if not tenant_key:
                raise ValidationError(
                    message="No tenant context available",
                    context={"operation": "update_project_mission", "project_id": project_id},
                )
            async with self._get_session(tenant_key) as session:
                project = await self._repo.get_by_id(session, tenant_key, project_id)

                if not project:
                    raise ResourceNotFoundError(
                        message="Project not found or access denied",
                        context={"project_id": project_id, "tenant_key": tenant_key},
                    )

                if project.status in IMMUTABLE_PROJECT_STATUSES:
                    raise ProjectStateError(
                        message=f"Cannot modify project in '{project.status.value}' status. "
                        "Only inactive and active projects can be updated.",
                        context={"project_id": project_id, "status": project.status.value},
                    )

                project.mission = mission
                if project.staging_status != "staging_complete":
                    project.staging_status = "staging"
                project.updated_at = datetime.now(UTC)

                await session.commit()

                await self._broadcast_mission_update(project_id, mission, project.tenant_key)

                return ProjectMissionUpdateResult(
                    message="Mission updated successfully",
                    project_id=project_id,
                    lifecycle_footer=build_mission_update_footer(
                        phase=("implementation" if project.implementation_launched_at is not None else "staging")
                    ),
                )

        except (ResourceNotFoundError, ValidationError, ProjectStateError):
            raise
        except Exception as e:
            self._logger.exception("Failed to update mission")
            raise BaseGiljoError(
                message=f"Failed to update mission: {e!s}", context={"project_id": project_id, "tenant_key": tenant_key}
            ) from e

    async def set_early_termination(self, project_id: str, tenant_key: str | None = None) -> None:
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
        except Exception as e:
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
        return await self.lifecycle.activate_project(project_id, force, websocket_manager, tenant_key)

    async def deactivate_project(
        self,
        project_id: str,
        tenant_key: str | None = None,
        websocket_manager: Any | None = None,
    ) -> Project:
        return await self.lifecycle.deactivate_project(project_id, tenant_key, websocket_manager)

    def _apply_project_updates(self, project, updates: dict[str, Any]) -> None:
        if "execution_mode" in updates and project.implementation_launched_at is not None:
            raise ProjectStateError(
                message=(
                    "Cannot change execution mode after implementation has launched. Re-stage the project to change it."
                ),
                context={"project_id": str(project.id)},
            )

        if "auto_checkin_interval" in updates and updates["auto_checkin_interval"] not in (5, 10, 15, 20, 30, 40, 60):
            raise ValidationError(
                message="auto_checkin_interval must be one of: 5, 10, 15, 20, 30, 40, 60 minutes",
                error_code="VALIDATION_ERROR",
                context={"project_id": str(project.id), "value": updates["auto_checkin_interval"]},
            )

        if "execution_mode" in updates and updates["execution_mode"] not in ACCEPTED_EXECUTION_MODES:
            raise ValidationError(
                message=f"execution_mode must be one of: {mode_csv()}",
                error_code="VALIDATION_ERROR",
                context={"project_id": str(project.id), "value": updates["execution_mode"]},
            )

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
            "successor_project_id",
        }
        previous_status = project.status

        for field, value in updates.items():
            if field in allowed_fields:
                setattr(project, field, value)

        now = datetime.now(UTC)

        if "status" in updates and "completed_at" not in updates:
            if project.status in LIFECYCLE_FINISHED_STATUSES:
                if project.completed_at is None:
                    project.completed_at = now
            elif previous_status in LIFECYCLE_FINISHED_STATUSES:
                project.completed_at = None

        project.updated_at = now

    @staticmethod
    def _build_created_project_detail(project) -> ProjectDetail:
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
        tenant_key = self.tenant_manager.get_current_tenant()

        redirected = await route_active_inactive_status_transition(self, project_id, updates, websocket_manager)
        if redirected is not None:
            return redirected

        async with self._get_session(tenant_key) as session:
            project = await self._repo.get_by_id_with_type(
                session, self.tenant_manager.get_current_tenant(), project_id
            )

            if not project:
                raise ResourceNotFoundError(message="Project not found", context={"project_id": project_id})

            if "name" in updates:
                require_non_blank(updates["name"], field="name", operation="update_project", entity="Project")

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
                validate_supersede_successor(project_id, updates, successor)

            require_supersede_successor(project_id, updates)

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

            if project.project_type_id:
                project = await self._repo.get_with_project_type(
                    session, self.tenant_manager.get_current_tenant(), project.id
                )

            self._logger.info(f"Updated project {sanitize(project_id)}")

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
        return await self.launch.launch_project(
            project_id,
            user_id,
            launch_config,
            websocket_manager,
            project_service=self,
        )
