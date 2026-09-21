# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any

from sqlalchemy import select

from giljo_mcp.exceptions import (
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.sequence_runs import (
    VALID_RUN_STATUSES,
    SequenceRun,
)
from giljo_mcp.services.sequence_run_live_filter import (
    filter_runs_by_product,
    filter_runs_with_live_members,
)
from giljo_mcp.services.sequence_run_serialization import serialize_sequence_run


class SequenceRunQueryMixin:

    async def find_active_run_for_project(
        self,
        *,
        project_id: str,
        tenant_key: str,
    ) -> dict[str, Any] | None:
        try:
            active_statuses = ("pending", "running", "stalled")
            async with self._get_session(tenant_key) as session:
                stmt = (
                    select(SequenceRun)
                    .where(
                        SequenceRun.tenant_key == tenant_key,
                        SequenceRun.status.in_(active_statuses),
                        SequenceRun.project_ids.contains([project_id]),
                    )
                    .order_by(SequenceRun.updated_at.desc())
                    .limit(1)
                )
                result = await session.execute(stmt)
                run = result.scalar_one_or_none()
                if run is None:
                    return None
                return _serialize(run)
        except (BaseGiljoError, ResourceNotFoundError, ValidationError):
            raise
        except Exception as exc:
            self._logger.exception("Failed to find active sequence_run for project")
            raise BaseGiljoError(
                message=str(exc), context={"operation": "find_active_run_for_project", "project_id": project_id}
            ) from exc

    async def find_active_run_for_conductor(
        self,
        *,
        conductor_agent_id: str,
        tenant_key: str,
    ) -> dict[str, Any] | None:
        try:
            active_statuses = ("pending", "running", "stalled")
            async with self._get_session(tenant_key) as session:
                stmt = (
                    select(SequenceRun)
                    .where(
                        SequenceRun.tenant_key == tenant_key,
                        SequenceRun.status.in_(active_statuses),
                        SequenceRun.conductor_agent_id == conductor_agent_id,
                    )
                    .order_by(SequenceRun.updated_at.desc())
                    .limit(1)
                )
                result = await session.execute(stmt)
                run = result.scalar_one_or_none()
                return _serialize(run) if run is not None else None
        except (BaseGiljoError, ResourceNotFoundError, ValidationError):
            raise
        except Exception as exc:
            self._logger.exception("Failed to find active sequence_run for conductor")
            raise BaseGiljoError(
                message=str(exc),
                context={"operation": "find_active_run_for_conductor", "conductor_agent_id": conductor_agent_id},
            ) from exc

    async def _scope_runs_to_product(
        self,
        *,
        session,
        runs: list[SequenceRun],
        tenant_key: str,
        product_id: str | None,
        operation: str,
    ) -> list[SequenceRun]:
        if not product_id:
            return runs

        from giljo_mcp.services.product_service import ProductService

        product_service = ProductService(
            db_manager=self.db_manager,
            tenant_key=tenant_key,
            test_session=self._session,
        )
        product = await product_service.resolve_binding_product(
            product_id, operation=operation, action="listed", write=False
        )
        return await filter_runs_by_product(
            session=session,
            runs=runs,
            tenant_key=tenant_key,
            product_id=str(product.id),
        )

    async def list_active(
        self,
        *,
        tenant_key: str | None = None,
        statuses: tuple[str, ...] = ("pending", "running", "stalled"),
        product_id: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(
                    message="tenant_key is required", context={"operation": "list_active_sequence_runs"}
                )
            invalid = [s for s in statuses if s not in VALID_RUN_STATUSES]
            if invalid:
                raise ValidationError(
                    message=f"Invalid status filter {invalid}. Valid: {sorted(VALID_RUN_STATUSES)}",
                    context={"field": "status", "valid": sorted(VALID_RUN_STATUSES)},
                )
            async with self._get_session(effective_tenant_key) as session:
                stmt = (
                    select(SequenceRun)
                    .where(
                        SequenceRun.tenant_key == effective_tenant_key,
                        SequenceRun.status.in_(tuple(statuses)),
                    )
                    .order_by(SequenceRun.updated_at.desc())
                )
                result = await session.execute(stmt)
                runs = list(result.scalars().all())
                live_runs = await filter_runs_with_live_members(
                    session=session,
                    runs=runs,
                    tenant_key=effective_tenant_key,
                )
                live_runs = await self._scope_runs_to_product(
                    session=session,
                    runs=live_runs,
                    tenant_key=effective_tenant_key,
                    product_id=product_id,
                    operation="list_active_sequence_runs",
                )
                return [_serialize(r) for r in live_runs]
        except (BaseGiljoError, ResourceNotFoundError, ValidationError):
            raise
        except Exception as exc:
            self._logger.exception("Failed to list active sequence_runs")
            raise BaseGiljoError(message=str(exc), context={"operation": "list_active_sequence_runs"}) from exc

    async def list_review_pending(
        self,
        *,
        tenant_key: str | None = None,
        limit: int = 25,
        product_id: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(
                    message="tenant_key is required", context={"operation": "list_review_pending_sequence_runs"}
                )
            active_statuses = ("pending", "running", "stalled")
            async with self._get_session(effective_tenant_key) as session:
                stmt = (
                    select(SequenceRun)
                    .where(
                        SequenceRun.tenant_key == effective_tenant_key,
                        SequenceRun.status.notin_(active_statuses),
                    )
                    .order_by(SequenceRun.updated_at.desc())
                    .limit(limit)
                )
                result = await session.execute(stmt)
                runs = list(result.scalars().all())
                pending = [r for r in runs if _has_unreviewed_completed_member(r)]
                pending = await self._scope_runs_to_product(
                    session=session,
                    runs=pending,
                    tenant_key=effective_tenant_key,
                    product_id=product_id,
                    operation="list_review_pending_sequence_runs",
                )
                return [_serialize(r) for r in pending]
        except (BaseGiljoError, ResourceNotFoundError, ValidationError):
            raise
        except Exception as exc:
            self._logger.exception("Failed to list review-pending sequence_runs")
            raise BaseGiljoError(message=str(exc), context={"operation": "list_review_pending_sequence_runs"}) from exc

    async def get(self, *, run_id: str, tenant_key: str | None = None) -> dict[str, Any]:
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(message="tenant_key is required", context={"operation": "get_sequence_run"})

            async with self._get_session(effective_tenant_key) as session:
                result = await session.execute(
                    select(SequenceRun).where(
                        SequenceRun.id == run_id,
                        SequenceRun.tenant_key == effective_tenant_key,
                    )
                )
                run = result.scalar_one_or_none()
                if run is None:
                    raise ResourceNotFoundError(
                        message="sequence_run not found",
                        context={"run_id": run_id, "tenant_key": effective_tenant_key},
                    )
                return _serialize(run)
        except (BaseGiljoError, ResourceNotFoundError, ValidationError):
            raise
        except Exception as exc:
            self._logger.exception("Failed to get sequence_run")
            raise BaseGiljoError(message=str(exc), context={"operation": "get_sequence_run"}) from exc


def _has_unreviewed_completed_member(run: SequenceRun) -> bool:
    statuses = run.project_statuses if isinstance(run.project_statuses, dict) else {}
    reviewed = set(run.reviewed_project_ids or [])
    return any(status == "completed" and pid not in reviewed for pid, status in statuses.items())


_serialize = serialize_sequence_run
