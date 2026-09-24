# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import BinaryExpression, BindParameter

from .models import (
    AgentExecution,
    AgentJob,
    AgentTemplate,
    AgentTodoItem,
    APIKey,
    ApiMetrics,
    CommParticipant,
    CommThread,
    CommThreadProjectTag,
    DownloadToken,
    MCPContextIndex,
    MCPSession,
    McpToolCallMetric,
    Message,
    MessageAcknowledgment,
    MessageCompletion,
    MessageRecipient,
    Notification,
    Organization,
    OrgMembership,
    Product,
    ProductAgentAssignment,
    ProductArchitecture,
    ProductMemoryEntry,
    ProductTechStack,
    ProductTestConfig,
    Project,
    Roadmap,
    RoadmapItem,
    SequenceRun,
    Settings,
    SetupState,
    Task,
    TaxonomyType,
    TemplateArchive,
    TenantSkillsAck,
    User,
    UserApproval,
    UserFieldPriority,
    VisionDocument,
)
from .models.oauth import OAuthAuthorizationCode, OAuthRefreshToken, OAuthRevokedToken
from .signals import SIGNAL_UNSCOPED_WRITE, publish_signal
from .tenant import TenantManager


logger = logging.getLogger(__name__)


_CE_TENANT_SCOPED_MODELS = frozenset(
    {
        APIKey,
        AgentExecution,
        AgentJob,
        AgentTemplate,
        AgentTodoItem,
        ApiMetrics,
        CommParticipant,
        CommThread,
        CommThreadProjectTag,
        DownloadToken,
        MCPSession,
        MCPContextIndex,
        McpToolCallMetric,
        Message,
        MessageAcknowledgment,
        MessageCompletion,
        MessageRecipient,
        Notification,
        OAuthAuthorizationCode,
        OAuthRevokedToken,
        OAuthRefreshToken,
        OrgMembership,
        Organization,
        Product,
        ProductAgentAssignment,
        ProductArchitecture,
        ProductMemoryEntry,
        ProductTechStack,
        ProductTestConfig,
        Project,
        Roadmap,
        RoadmapItem,
        SequenceRun,
        Settings,
        SetupState,
        Task,
        TaxonomyType,
        TemplateArchive,
        TenantSkillsAck,
        User,
        UserApproval,
        UserFieldPriority,
        VisionDocument,
    }
)

_REGISTERED_TENANT_SCOPED_MODELS: set[type] = set()


_TENANT_SCOPED_CACHE: dict[str, Any] = {"models": frozenset(), "tables": {}}


_WALK_MEMO_MODELS: dict[Any, frozenset[type[Any]]] = {}
_WALK_MEMO_PREDICATE: dict[Any, frozenset[type[Any]]] = {}
_WALK_MEMO_MAX = 4096


def _clear_walk_memo() -> None:
    _WALK_MEMO_MODELS.clear()
    _WALK_MEMO_PREDICATE.clear()


def _statement_cache_key(statement: Any) -> Any | None:
    generate = getattr(statement, "_generate_cache_key", None)
    if generate is None:
        return None
    try:
        cache_key = generate()
    except Exception:  # noqa: BLE001 -- defensive: an uncacheable construct => fall back to walk
        return None
    return None if cache_key is None else cache_key.key


def _all_tenant_scoped_models() -> frozenset[type]:
    return _TENANT_SCOPED_CACHE["models"]


def _all_tenant_scoped_tables() -> dict:
    return _TENANT_SCOPED_CACHE["tables"]


def register_tenant_scoped_models(*models: type) -> None:
    _REGISTERED_TENANT_SCOPED_MODELS.update(models)
    union = _CE_TENANT_SCOPED_MODELS | frozenset(_REGISTERED_TENANT_SCOPED_MODELS)
    _TENANT_SCOPED_CACHE["models"] = union
    _TENANT_SCOPED_CACHE["tables"] = {m.__table__: m for m in union if hasattr(m, "__table__")}
    _clear_walk_memo()


register_tenant_scoped_models()


def __getattr__(name: str):
    if name == "TENANT_SCOPED_MODELS":
        return _all_tenant_scoped_models()
    if name == "TENANT_SCOPED_TABLES":
        return dict(_all_tenant_scoped_tables())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


TENANT_BYPASS_MODELS_KEY = "tenant_isolation_bypass_models"
TENANT_BYPASS_REASON_KEY = "tenant_isolation_bypass_reason"
TENANT_CONTEXT_SOURCE_KEY = "tenant_key_source"


class TenantIsolationError(RuntimeError):
    pass


_TENANT_GUARD_MODE_ENV = "GILJO_TENANT_GUARD_MODE"
_TENANT_GUARD_AUDIT_MODE = "audit"

_AUDIT_WARN_SEEN: set[tuple[str | None, frozenset[str]]] = set()
_AUDIT_WARN_SEEN_MAX = 2048


def _guard_mode() -> str:
    return os.getenv(_TENANT_GUARD_MODE_ENV, "enforce").strip().lower()


def _best_effort_request_path(session: Session) -> str | None:
    path = session.info.get("request_path")
    return path if isinstance(path, str) and path else None


def _audit_warn(
    session: Session,
    *,
    reason: str,
    models: frozenset[type[Any]],
    execute_state: ORMExecuteState,
    unscoped_write: bool = False,
) -> None:
    model_names = sorted(model.__name__ for model in models)
    path = _best_effort_request_path(session)
    dedupe_key = (path, frozenset(model_names))
    if dedupe_key in _AUDIT_WARN_SEEN:
        return
    if len(_AUDIT_WARN_SEEN) >= _AUDIT_WARN_SEEN_MAX:
        _AUDIT_WARN_SEEN.clear()
    _AUDIT_WARN_SEEN.add(dedupe_key)

    if execute_state.is_select:
        statement_type = "select"
    elif execute_state.is_update:
        statement_type = "update"
    elif execute_state.is_delete:
        statement_type = "delete"
    else:
        statement_type = "unknown"

    logger.warning(
        "tenant guard audit: %s | models=%s | statement_type=%s%s",
        reason,
        model_names,
        statement_type,
        f" | path={path}" if path else "",
    )

    if unscoped_write:
        publish_signal(
            SIGNAL_UNSCOPED_WRITE,
            {"models": model_names, "statement_type": statement_type, "path": path},
        )


def _table_model(element: Any) -> type[Any] | None:
    original = getattr(element, "original", element)
    return _all_tenant_scoped_tables().get(original)


def _tenant_models_for_statement_uncached(statement: Any) -> frozenset[type[Any]]:
    models: set[type[Any]] = set()
    scoped_models = _all_tenant_scoped_models()
    for description in getattr(statement, "column_descriptions", ()) or ():
        entity = description.get("entity")
        if entity in scoped_models:
            models.add(entity)

    table = getattr(statement, "table", None)
    model = _table_model(table)
    if model is not None:
        models.add(model)

    for element in visitors.iterate(statement):
        model = _table_model(element)
        if model is not None:
            models.add(model)
    return frozenset(models)


def _tenant_models_for_statement(statement: Any) -> frozenset[type[Any]]:
    key = _statement_cache_key(statement)
    if key is None:
        return _tenant_models_for_statement_uncached(statement)
    cached = _WALK_MEMO_MODELS.get(key)
    if cached is not None:
        return cached
    result = _tenant_models_for_statement_uncached(statement)
    if len(_WALK_MEMO_MODELS) >= _WALK_MEMO_MAX:
        _WALK_MEMO_MODELS.clear()
    _WALK_MEMO_MODELS[key] = result
    return result


def _tenant_column_model(column: Any) -> type[Any] | None:
    for model in _all_tenant_scoped_tables().values():
        tenant_column = model.__table__.c.tenant_key
        if column is tenant_column or getattr(column, "shares_lineage", lambda _other: False)(tenant_column):
            return model
    return None


def _models_with_tenant_predicate_uncached(statement: Any) -> frozenset[type[Any]]:
    models: set[type[Any]] = set()
    for element in visitors.iterate(statement):
        if not isinstance(element, BinaryExpression) or element.operator is not operators.eq:
            continue
        left_model = _tenant_column_model(element.left)
        right_model = _tenant_column_model(element.right)
        if left_model is not None:
            models.add(left_model)
        if right_model is not None:
            models.add(right_model)
    return frozenset(models)


def _models_with_tenant_predicate(statement: Any) -> frozenset[type[Any]]:
    key = _statement_cache_key(statement)
    if key is None:
        return _models_with_tenant_predicate_uncached(statement)
    cached = _WALK_MEMO_PREDICATE.get(key)
    if cached is not None:
        return cached
    result = _models_with_tenant_predicate_uncached(statement)
    if len(_WALK_MEMO_PREDICATE) >= _WALK_MEMO_MAX:
        _WALK_MEMO_PREDICATE.clear()
    _WALK_MEMO_PREDICATE[key] = result
    return result


def _bind_operand_values(element: Any, parameters: Any) -> frozenset[str]:
    if not isinstance(element, BindParameter):
        return frozenset()
    if isinstance(element.value, str):
        return frozenset({element.value})
    rows = parameters if isinstance(parameters, (list, tuple)) else ([parameters] if parameters else [])
    resolved: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get(element.key)
        if isinstance(value, str):
            resolved.add(value)
    return frozenset(resolved)


def _tenant_predicate_values(statement: Any, parameters: Any = None) -> frozenset[str]:
    values: set[str] = set()
    for element in visitors.iterate(statement):
        if not isinstance(element, BinaryExpression) or element.operator is not operators.eq:
            continue
        left_model = _tenant_column_model(element.left)
        right_model = _tenant_column_model(element.right)
        if left_model is not None:
            values |= _bind_operand_values(element.right, parameters)
        if right_model is not None:
            values |= _bind_operand_values(element.left, parameters)
    return frozenset(values)


def _tenant_criteria(model: type[Any], tenant_key: str):
    return with_loader_criteria(model, lambda cls: cls.tenant_key == tenant_key, include_aliases=True)


def _bypass_covers(session: Session, models: frozenset[type[Any]]) -> bool:
    bypass_models = session.info.get(TENANT_BYPASS_MODELS_KEY)
    if not bypass_models:
        return False
    reason = session.info.get(TENANT_BYPASS_REASON_KEY)
    if not isinstance(reason, str) or not reason.strip():
        raise TenantIsolationError("Tenant isolation bypass requires a non-empty reason")
    missing = models.difference(bypass_models)
    if missing:
        names = ", ".join(sorted(model.__name__ for model in missing))
        raise TenantIsolationError(f"Tenant isolation bypass does not cover: {names}")
    return True


@contextmanager
def tenant_isolation_bypass(
    session: AsyncSession | Session,
    *,
    reason: str,
    models: tuple[type[Any], ...] | frozenset[type[Any]],
) -> Iterator[None]:
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Tenant isolation bypass reason is required")
    model_set = frozenset(models)
    invalid = model_set.difference(_all_tenant_scoped_models())
    if invalid:
        names = ", ".join(sorted(model.__name__ for model in invalid))
        raise ValueError(f"Tenant isolation bypass models are not tenant-scoped: {names}")

    previous_models = session.info.get(TENANT_BYPASS_MODELS_KEY)
    previous_reason = session.info.get(TENANT_BYPASS_REASON_KEY)
    session.info[TENANT_BYPASS_MODELS_KEY] = model_set
    session.info[TENANT_BYPASS_REASON_KEY] = reason.strip()
    try:
        yield
    finally:
        if previous_models is None:
            session.info.pop(TENANT_BYPASS_MODELS_KEY, None)
        else:
            session.info[TENANT_BYPASS_MODELS_KEY] = previous_models
        if previous_reason is None:
            session.info.pop(TENANT_BYPASS_REASON_KEY, None)
        else:
            session.info[TENANT_BYPASS_REASON_KEY] = previous_reason


@contextmanager
def tenant_session_context(session: AsyncSession | Session, tenant_key: str) -> Iterator[None]:
    previous_tenant = session.info.get("tenant_key")
    previous_source = session.info.get(TENANT_CONTEXT_SOURCE_KEY)
    previous_context_tenant = TenantManager.get_current_tenant()
    context_tenant_set = TenantManager.validate_tenant_key(tenant_key)
    session.info["tenant_key"] = tenant_key
    session.info[TENANT_CONTEXT_SOURCE_KEY] = "service"
    if context_tenant_set:
        TenantManager.set_current_tenant(tenant_key)
    try:
        yield
    finally:
        if context_tenant_set:
            if previous_context_tenant:
                TenantManager.set_current_tenant(previous_context_tenant)
            else:
                TenantManager.clear_current_tenant()
        if previous_tenant is None:
            session.info.pop("tenant_key", None)
        else:
            session.info["tenant_key"] = previous_tenant
        if previous_source is None:
            session.info.pop(TENANT_CONTEXT_SOURCE_KEY, None)
        else:
            session.info[TENANT_CONTEXT_SOURCE_KEY] = previous_source


@event.listens_for(Session, "do_orm_execute")
def _enforce_tenant_scope(execute_state: ORMExecuteState) -> None:
    if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
        return
    if execute_state.is_column_load:
        return

    models = _tenant_models_for_statement(execute_state.statement)
    if not models:
        return

    session = execute_state.session
    if _bypass_covers(session, models):
        return

    audit_mode = _guard_mode() == _TENANT_GUARD_AUDIT_MODE

    explicit_tenant_models = _models_with_tenant_predicate(execute_state.statement)
    if session.info.get(TENANT_CONTEXT_SOURCE_KEY) == "flush" and explicit_tenant_models:
        explicit_tenant_values = _tenant_predicate_values(execute_state.statement, execute_state.parameters)
        session_tenant_key = session.info.get("tenant_key")
        if not explicit_tenant_values or explicit_tenant_values != {session_tenant_key}:
            names = ", ".join(sorted(model.__name__ for model in models))
            message = (
                f"Tenant context required for ORM statement touching: {names}; "
                "flush-derived tenant context cannot authorize explicit tenant predicates"
            )
            if audit_mode:
                _audit_warn(session, reason=message, models=models, execute_state=execute_state)
                return
            raise TenantIsolationError(message)
    session_tenant_key = session.info.get("tenant_key")
    tenant_key = session_tenant_key or TenantManager.get_current_tenant()
    if not tenant_key:
        names = ", ".join(sorted(model.__name__ for model in models))
        message = f"Tenant context required for ORM statement touching: {names}"
        if explicit_tenant_models:
            message = f"{message}; explicit tenant predicates do not provide tenant context"
        if audit_mode:
            _audit_warn(session, reason=message, models=models, execute_state=execute_state)
            return
        raise TenantIsolationError(message)

    session.info["tenant_key"] = tenant_key
    if execute_state.is_select:
        execute_state.statement = execute_state.statement.options(
            *[_tenant_criteria(model, tenant_key) for model in models]
        )
        return

    statement_table = getattr(execute_state.statement, "table", None)
    target_model = _table_model(statement_table) if statement_table is not None else None
    if target_model is not None and target_model in models:
        execute_state.statement = execute_state.statement.where(target_model.tenant_key == tenant_key)
        return

    explicit_tenant_values = (
        _tenant_predicate_values(execute_state.statement, execute_state.parameters)
        if explicit_tenant_models
        else frozenset()
    )
    caller_scoped_to_this_tenant = bool(explicit_tenant_models) and explicit_tenant_values == {tenant_key}

    names = ", ".join(sorted(model.__name__ for model in models))
    message = f"would have blocked: no tenant predicate injectable for UPDATE/DELETE touching: {names}"
    if explicit_tenant_models:
        explicit_names = ", ".join(sorted(model.__name__ for model in explicit_tenant_models))
        message = f"{message}; statement carries an explicit tenant predicate on: {explicit_names}"
        if not caller_scoped_to_this_tenant:
            message = f"{message}; predicate value(s) {sorted(explicit_tenant_values)} do not match this tenant"
    _audit_warn(
        session,
        reason=message,
        models=models,
        execute_state=execute_state,
        unscoped_write=not caller_scoped_to_this_tenant,
    )
    if not caller_scoped_to_this_tenant and not audit_mode:
        raise TenantIsolationError(message)
    return


@event.listens_for(Session, "after_flush")
def _record_single_tenant_flush(session: Session, _flush_context: Any) -> None:
    if session.info.get("tenant_key") and session.info.get(TENANT_CONTEXT_SOURCE_KEY) != "flush":
        return

    scoped_models = _all_tenant_scoped_models()
    tenant_keys = {
        obj.tenant_key
        for obj in session.new.union(session.dirty)
        if type(obj) in scoped_models and getattr(obj, "tenant_key", None)
    }
    if len(tenant_keys) == 1:
        session.info["tenant_key"] = tenant_keys.pop()
        session.info[TENANT_CONTEXT_SOURCE_KEY] = "flush"
