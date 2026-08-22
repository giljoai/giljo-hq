# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tenant-isolation guard: the fail-closed ``do_orm_execute`` enforcement path.

Extracted verbatim from ``database.py`` (BE-6063c) to keep that module under the
800-line CI guardrail; this is the cohesive security boundary (CE/SaaS model
registry, the per-query AST-walk classifier + its BE-6063c shape memo, the
bypass / context managers, and the SQLAlchemy event listeners). ``database.py``
re-exports every public name so external import paths
(``giljo_mcp.database.register_tenant_scoped_models``, ``TENANT_SCOPED_MODELS``,
``tenant_session_context``, ``TenantIsolationError`` ...) are unchanged.

The invariant this exists to hold: every UPDATE/DELETE reaching a tenant-scoped
table must carry a predicate binding it to the tenant whose context the session
is running under. The guard re-injects that predicate where it can, refuses the
statement where it cannot, and logs what it saw either way. Anything it could not
scope is also announced on ``signals.SIGNAL_UNSCOPED_WRITE`` -- a plain statement
of fact with no opinion about who, if anyone, is listening.

Edition-pure: imports ZERO ``saas/`` modules (Deletion Test). SaaS widens the
scoped set at import time via ``register_tenant_scoped_models``.
"""

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
    DownloadToken,
    MCPContextIndex,
    MCPSession,
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


# CE built-in tenant-scoped models -- the source of CE truth. Edition-pure: MUST
# NOT contain any SaaS-only model (CE core may not import from saas/). SaaS widens
# the allowed set at import time via register_tenant_scoped_models() (BE-6031a).
#
# SEC-9272 / SEC-9276 (registry coverage-gap sweep, see tests/security/
# test_sec9272_ce_tenant_registry_completeness.py): six CE models were found to carry
# a NOT NULL tenant_key with real, already caller-scoped bulk writes yet were
# invisible to this guard entirely -- not even audit-logged, unlike a registered
# model's benign Class-A no-match. All six are now registered.
#
# CommParticipant and CommThread were registered in SEC-9272: audited clean (all
# real write paths -- comm_thread_service.py's tenant_session_context, and
# comm_thread_repository.hard_delete's session.delete(), which fires a raw PK-only
# DELETE with no tenant_key predicate at the SQL level and is now guard-injected)
# and the full comm-thread test suite (82 tests) passes unchanged with them
# registered.
#
# Notification, Roadmap, RoadmapItem, and SequenceRun were audited the same way and
# registered in SEC-9276: their OWNING services (notification_service.py,
# roadmap_service.py, sequence_run_service.py) already thread tenant_key correctly
# on every write. Registering them surfaced a SEPARATE, pre-existing problem: ~20
# test files shared a single db_session/db_manager session across MULTIPLE tenants,
# or ran an autouse teardown that bulk-deleted the whole table with no tenant
# predicate at all (`delete(SequenceRun)`, no WHERE) -- both patterns were silently
# safe only because these models were guard-invisible. SEC-9276 fixed the affected
# test files (wrapped cross-tenant test setup/teardown in tenant_isolation_bypass,
# or moved cross-tenant seeding/verification into per-tenant
# tenant_session_context blocks) so the guard's coverage now extends to these four
# models with no loss of test signal.
#
# Configuration (models/config.py) was reviewed and deliberately EXCLUDED
# permanently: its tenant_key is nullable BY DESIGN (NULL = a global/system-default
# row that sits alongside per-tenant override rows in the same table -- see
# ConfigurationRepository.get_all_values_for_key). Registering it would make the
# guard inject `WHERE tenant_key = <this tenant>` on every SELECT touching the
# table whenever a tenant context is active, which would silently hide the global
# fallback row (`tenant_key IS NULL`) exactly when callers need the fallback most.
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
        DownloadToken,
        MCPSession,
        MCPContextIndex,
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

# SaaS extension seam (BE-6031a): SaaS registers tenant-scoped models here at import time via
# register_tenant_scoped_models. Empty in pure-CE installs, so the Deletion Test holds.
_REGISTERED_TENANT_SCOPED_MODELS: set[type] = set()


# Memoized live union (BE-6031a perf): tenant-isolation hot path (_enforce_tenant_scope runs per
# select/update/delete). Rebuilt ONLY by register_tenant_scoped_models() (CE built-ins frozen).
_TENANT_SCOPED_CACHE: dict[str, Any] = {"models": frozenset(), "tables": {}}


# Statement-shape walk memo (BE-6063c perf). The do_orm_execute guard ran a full
# ``visitors.iterate`` walk on EVERY execute (spike: 1.0 walk/execute, 47-83us pure-Python
# CPU/query on the single sync worker -- NOT amortized by SQLAlchemy's compiled-statement
# cache, which only caches SQL-string compilation). The walk's STRUCTURAL output is a pure
# function of statement SHAPE + the registered model set, so it is memoized keyed on
# SQLAlchemy's ``_generate_cache_key()`` -- which is tenant-INDEPENDENT (bind-parameter
# VALUES are excluded from the key) and collision-safe (distinct WHERE structures /
# aliased-vs-plain hash to distinct keys). The cached VALUE holds ONLY model sets; it NEVER
# embeds a tenant_key. The per-execute ``with_loader_criteria`` (which closes over tenant_key)
# and the explicit-predicate tenant VALUES are recomputed fresh every execute -- never cached.
# Invalidated wholesale whenever register_tenant_scoped_models() mutates the model set.
_WALK_MEMO_MODELS: dict[Any, frozenset[type[Any]]] = {}
_WALK_MEMO_PREDICATE: dict[Any, frozenset[type[Any]]] = {}
# Bounded so adversarial / high-cardinality statement shapes (e.g. raw text() with varying
# SQL) cannot grow the memo without limit. On overflow we clear (cheap; recomputes on miss).
_WALK_MEMO_MAX = 4096


def _clear_walk_memo() -> None:
    _WALK_MEMO_MODELS.clear()
    _WALK_MEMO_PREDICATE.clear()


def _statement_cache_key(statement: Any) -> Any | None:
    """Tenant-independent, collision-safe memo key for a statement, or None if uncacheable.

    Returns the hashable ``.key`` of SQLAlchemy's compiled-statement cache key. Some
    constructs opt out of caching (``_generate_cache_key()`` returns None) -- callers then
    fall back to the live walk. Any failure to produce a key degrades to None (walk), never
    to a wrong-but-cached answer.
    """
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
    """Register additional tenant-scoped models (SaaS extension seam, BE-6031a).

    Idempotent, additive-only: only WIDENS the allowed set; never weakens the per-call
    ``models=`` scoping in ``tenant_isolation_bypass``. SaaS calls this at import time so
    its reaper can bypass cross-tenant scans without CE importing a SaaS model. Rebuilds
    the memoized cache so readers honor the registration immediately (no-arg call rebuilds).

    Invalidates the BE-6063c statement-shape walk memo too: a memoized model set computed
    before a new model joined the scoped union would silently omit it (isolation drop).
    """
    _REGISTERED_TENANT_SCOPED_MODELS.update(models)
    union = _CE_TENANT_SCOPED_MODELS | frozenset(_REGISTERED_TENANT_SCOPED_MODELS)
    _TENANT_SCOPED_CACHE["models"] = union
    # hasattr filter: only mapped models give a table key; non-mapped still count for membership.
    _TENANT_SCOPED_CACHE["tables"] = {m.__table__: m for m in union if hasattr(m, "__table__")}
    _clear_walk_memo()


register_tenant_scoped_models()  # initialize cache at module load (registry empty here)


def __getattr__(name: str):
    # PEP 562 hook: expose the public names as the LIVE union (not a static snapshot)
    # so external readers (e.g. saas/auth/oauth_client.py) see SaaS registrations too.
    if name == "TENANT_SCOPED_MODELS":
        return _all_tenant_scoped_models()
    if name == "TENANT_SCOPED_TABLES":
        return dict(_all_tenant_scoped_tables())  # copy: external readers must not mutate the cache
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


TENANT_BYPASS_MODELS_KEY = "tenant_isolation_bypass_models"
TENANT_BYPASS_REASON_KEY = "tenant_isolation_bypass_reason"
TENANT_CONTEXT_SOURCE_KEY = "tenant_key_source"


class TenantIsolationError(RuntimeError):
    pass


# BE6004C-0: env-gated audit (observe-only) ramp for the fail-closed tenant guard.
# Default is "enforce". ONLY the literal "audit" disables raising; any other value
# (unset, empty, typo) falls through to enforce. Read on every call so tests can
# monkeypatch the env (do NOT cache at import).
_TENANT_GUARD_MODE_ENV = "GILJO_TENANT_GUARD_MODE"
_TENANT_GUARD_AUDIT_MODE = "audit"

# Bounded de-dupe set for audit warnings, keyed by (path, frozenset(model_names)).
# List endpoints and WS reconnect storms would otherwise flood the log (Risk R7).
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
    """Log a tenant-guard audit warning (de-duped).

    ``unscoped_write`` marks the case the guard could not scope to the active tenant, which
    is additionally announced on :data:`SIGNAL_UNSCOPED_WRITE`; the log line itself is
    identical regardless."""
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
        # Neutral announcement: the guard states what it saw and stops. Nothing is
        # registered in a plain install, so this is a no-op there (see signals.py).
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
    """Walk1 (BE-6063c-memoized): tenant-scoped models a statement touches.

    Pure function of statement shape + registered model set => memoizable on the
    tenant-independent cache key. A None key (uncacheable construct) runs the live walk.
    """
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
    """Walk2 (BE-6063c-memoized): models carrying an explicit ``tenant_key == ...`` predicate.

    WHICH models have a tenant predicate is structural (shape-dependent), so it is memoized.
    The tenant VALUES in those predicates are NOT cached here -- ``_tenant_predicate_values``
    re-reads bind params live every execute. This is walk2/_tenant_column_model, the spike's
    largest per-query contributor (O(models x binary-exprs)).
    """
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
    """Resolve a tenant_key-predicate operand's value(s) -- SEC-9272 FIX1.

    ``BindParameter.value`` is populated at STATEMENT-BUILD time for the common
    ``Model.tenant_key == "literal"`` shape (SQLAlchemy compiles the literal into
    the bind immediately), but stays ``None`` for a deferred ``bindparam("name")``
    bound later via ``session.execute(stmt, {"name": value})`` or an executemany
    ``params=[{...}, ...]`` list -- SQLAlchemy's idiomatic bulk UPDATE/DELETE shape.
    Reading ``.value`` alone (pre-FIX1 behavior) sees an empty value set for that
    shape, which the no-match branch's discriminator would then treat as
    not-scoped-to-this-tenant and falsely raise on an otherwise correctly-scoped
    write. Fall back to resolving by ``.key`` against the execute-time parameters:
    a single dict (``session.execute(stmt, {...})``) or an executemany list of
    dicts (``session.execute(stmt, [{...}, {...}])``) -- the caller is scoped to a
    value only if that value is present in EVERY row that carries the key, so a
    mixed-tenant executemany surfaces every distinct value here and the caller
    (``_tenant_predicate_values``) can still fail the ``== {tenant_key}`` check.
    """
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

    # SEC-9094: resolve the UPDATE/DELETE target model via the SAME unwrap the DETECTION walk
    # uses (_table_model unwraps an AnnotatedTable's .original), instead of a raw identity check.
    # A mapped-class bulk update(Model)/delete(Model) sets statement.table to an AnnotatedTable
    # that is not `is` model.__table__, so the old identity loop could not inject on it and the
    # write fell through to the warn branch below (the ~123/143 weekly benign warns). Routing
    # through _table_model injects on BOTH the raw-table shape (identical result -- same model)
    # AND the mapped-class shape. The `in models` guard keeps us from ever injecting on a model
    # the walk did not flag (target_model is guaranteed in `models` whenever it resolves, since
    # the walk adds _table_model(statement.table); the explicit check is defensive).
    statement_table = getattr(execute_state.statement, "table", None)
    target_model = _table_model(statement_table) if statement_table is not None else None
    if target_model is not None and target_model in models:
        execute_state.statement = execute_state.statement.where(target_model.tenant_key == tenant_key)
        return

    # TSK-9008 Step 2 (fail-closed, SEC-9156, shipped): the statement touches a tenant-scoped
    # model but no model's table matched the UPDATE/DELETE target, so no tenant predicate could
    # be injected. The explicit-predicate detail separates "truly unscoped write" (Class-B) from
    # "scoped by the caller but unmatched statement shape" (Class-A) -- after SEC-9094 the
    # remaining no-match cases are statements whose UPDATE/DELETE target table is not itself a
    # detected tenant model (e.g. a non-tenant target with a tenant-scoped model referenced only
    # via a subquery/join), where nothing is injectable. Class-B now RAISES (genuinely unscoped,
    # unless observe-only audit mode is set); Class-A stays warn-and-continue (the 23 observed
    # benign caller-scoped hits -- raising there would break legitimate writes).
    #
    # SEC-9272 (discriminator hardening, pre-existing weakness -- predates SEC-9156): this closes
    # the VALUE dimension only -- an explicit tenant predicate being PRESENT never meant the
    # predicate's VALUE was checked against THIS tenant. A caller bug (wrong variable threaded
    # into the query) or a statement that references a real OTHER tenant's row could carry a
    # syntactically-valid `tenant_key == <value>` predicate for a DIFFERENT tenant and still slip
    # through as "benign" Class-A. Cross-check the predicate's VALUE against the resolved
    # tenant_key for this execute (the same technique the flush-derived branch above already uses
    # via _tenant_predicate_values) -- only an explicit predicate whose value set is EXACTLY
    # {tenant_key} counts as caller-scoped-to-this-tenant; anything else (absent, or present-but-
    # wrong-tenant) is treated as Class-B. This does NOT touch the separate COVERAGE dimension --
    # whether EVERY touched model individually carries a matching predicate on its OWN tenant_key
    # column -- which stays exactly as SEC-9156 left it (explicit_tenant_models is a set of ANY
    # registered model with a matching predicate anywhere on the statement, not a per-model
    # completeness check); that is a separate, pre-existing, out-of-scope question with no live
    # caller shape that hits it.
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
    # SEC-9093 (D2), hardened by SEC-9272: a statement counts as unscoped when it carries no
    # explicit tenant predicate, OR carries one that does not resolve to THIS tenant. A
    # statement that IS explicitly scoped to this tenant stays log-only. _audit_warn fires
    # BEFORE the raise below so a blocked write is never silent.
    _audit_warn(
        session,
        reason=message,
        models=models,
        execute_state=execute_state,
        unscoped_write=not caller_scoped_to_this_tenant,
    )
    # An unscoped write fails closed -- but observe-only audit mode suppresses the raise (the
    # _audit_warn above still fires), exactly like the two sibling raises earlier in this
    # function, so GILJO_TENANT_GUARD_MODE=audit stays a working kill switch to stop a bad flip
    # without a redeploy.
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
