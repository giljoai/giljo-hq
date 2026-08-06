# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.
"""SEC-9272 -- CE-side tenant-scope registration completeness (registry coverage gaps).

Mirrors ``tests/saas/test_imp9132_tenant_scope_registration_completeness.py``, which
made ``register_saas_tenant_scoped_models()`` a mechanically-enforced invariant for
SaaS models. No CE-side equivalent existed: ``_CE_TENANT_SCOPED_MODELS`` in
``src/giljo_mcp/tenant_guard.py`` was a hand-maintained frozenset with nothing to
catch a new CE model carrying ``tenant_key`` that nobody remembered to add. The
SEC-9156 follow-up review flagged exactly this as a registry coverage gap.

Fail-first proof (Museum Rule): this file's completeness test was RED against
pre-SEC-9272 ``tenant_guard.py`` for six real, currently-write-active CE models
that carry a NOT NULL ``tenant_key`` but were absent from ``_CE_TENANT_SCOPED_MODELS``
-- ``CommParticipant``, ``CommThread``, ``Notification``, ``Roadmap``,
``RoadmapItem``, ``SequenceRun``. SEC-9272 registered ``CommParticipant`` and
``CommThread`` (audited clean; the full comm-thread suite passes unchanged).
SEC-9276 registered the remaining four (``Notification``, ``Roadmap``,
``RoadmapItem``, ``SequenceRun``) after fixing the ~20 pre-existing test files
that shared a session across multiple tenants or ran an unscoped bulk-delete
teardown -- see the SEC-9272/SEC-9276 comment block above
``_CE_TENANT_SCOPED_MODELS`` in tenant_guard.py for the full per-model reasoning
and the fixed test-file list.

``Configuration`` carries a NULLABLE tenant_key (global rows use NULL) and is
deliberately, PERMANENTLY excluded both here and at the registry itself -- it is
the sole remaining entry in ``EXEMPT_CE_MODELS``.

Parallel-safety: importing ``giljo_mcp.models`` alone populates the full CE mapper
registry (every CE model module is imported transitively by that package's
``__init__``), so no ``pkgutil.walk_packages`` sweep is needed here the way the
SaaS-side test needs one for its lazily-imported ``saas/`` submodules.
"""

from __future__ import annotations

import giljo_mcp.models  # noqa: F401 -- import-for-side-effect, populates Base.registry.mappers
from giljo_mcp import database
from giljo_mcp.models.base import Base


# Fail-closed exemption map (mirrors the SaaS-side EXEMPT_GLOBALLY_RESOLVED contract): a CE
# model that carries a tenant_key column but is DELIBERATELY unregistered is listed here,
# class-name -> written reason. A model in NEITHER the registered union NOR this map fails the
# completeness test -- new CE tenant_key models are tenant-scoped by default.
#
# SEC-9276 registered the four temporary SEC-9272 deferrals (Notification, Roadmap,
# RoadmapItem, SequenceRun) after fixing their blocking test files; Configuration is the
# sole remaining entry, and it is a PERMANENT design exclusion, not a deferral.
EXEMPT_CE_MODELS: dict[str, str] = {
    "Configuration": (
        "PERMANENT: tenant_key is NULLABLE by design -- NULL rows are global/system-default "
        "config that sits alongside per-tenant override rows in the SAME table (see "
        "ConfigurationRepository.get_all_values_for_key). Registering it would make the guard "
        "inject `WHERE tenant_key = <this tenant>` on every SELECT touching the table whenever a "
        "tenant context is active, silently hiding the global fallback row exactly when callers "
        "need the fallback most. See src/giljo_mcp/tenant_guard.py, the SEC-9272 comment above "
        "_CE_TENANT_SCOPED_MODELS."
    ),
}


def _ce_tenant_scoped_mapped_classes() -> set[type]:
    """Every mapped class defined under giljo_mcp.* (excluding saas.*) that carries tenant_key."""
    found: set[type] = set()
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        module = getattr(cls, "__module__", "") or ""
        if not module.startswith("giljo_mcp.") or module.startswith("giljo_mcp.saas"):
            continue
        if "tenant_key" in mapper.columns:
            found.add(cls)
    return found


def test_every_ce_tenant_scoped_model_is_registered() -> None:
    """Walk the mapper registry: each CE model with tenant_key MUST be in the guard's union.

    A CE tenant-scoped model added without a matching entry in
    ``_CE_TENANT_SCOPED_MODELS`` (src/giljo_mcp/tenant_guard.py) now fails HERE, at CI,
    instead of silently sitting outside the guard's auto-enforcement forever (no crash,
    no log, no audit-warn -- an unregistered model is invisible to the guard entirely).
    """
    registered = set(database.TENANT_SCOPED_MODELS)
    ce_models = _ce_tenant_scoped_mapped_classes()

    unregistered = {cls.__name__ for cls in ce_models if cls not in registered and cls.__name__ not in EXEMPT_CE_MODELS}
    assert not unregistered, (
        "CE tenant-scoped model(s) carry a tenant_key column but are NEITHER registered in "
        "_CE_TENANT_SCOPED_MODELS (src/giljo_mcp/tenant_guard.py) NOR exempted in "
        f"EXEMPT_CE_MODELS: {sorted(unregistered)}. Register them, or -- only if the model has a "
        "deliberate reason not to be guard-enforced (e.g. a nullable/dual-mode tenant_key) -- add "
        "it to the exemption map with a written reason. Until registered, the tenant-isolation "
        "guard does not auto-enforce their tenant_key filtering at all -- not even audit-logged."
    )


def test_exempt_ce_models_are_real_and_unregistered() -> None:
    """Fail-closed hygiene on the CE exemption map (mirrors the SaaS-side stale-exemption check).

    Every exemption must (a) name a model that actually exists as a CE tenant_key mapped class,
    (b) carry a non-empty written reason, and (c) genuinely NOT be registered -- an exemption for
    a model that is in fact registered is stale and must be removed.
    """
    registered_names = {cls.__name__ for cls in set(database.TENANT_SCOPED_MODELS)}
    ce_names = {cls.__name__ for cls in _ce_tenant_scoped_mapped_classes()}

    for name, reason in EXEMPT_CE_MODELS.items():
        assert name in ce_names, f"EXEMPT_CE_MODELS names {name!r} which is not a CE tenant_key model"
        assert reason.strip(), f"EXEMPT_CE_MODELS[{name!r}] has an empty reason"
        assert name not in registered_names, f"{name!r} is exempted but IS registered -- remove the stale exemption"


def test_at_least_the_known_gap_models_are_scoped() -> None:
    """Guard against the registry walk silently finding nothing (import regression).

    Also pins the six SEC-9272 registry-coverage-gap models by name so a future refactor
    that renames/removes one of them is caught here rather than by the completeness test
    going quietly green because the model no longer exists to check.
    """
    ce_models = {cls.__name__ for cls in _ce_tenant_scoped_mapped_classes()}
    expected = {
        "CommParticipant",
        "CommThread",
        "Notification",
        "Roadmap",
        "RoadmapItem",
        "SequenceRun",
        "Configuration",
    }
    missing = expected - ce_models
    assert not missing, f"registry walk did not surface expected CE tenant-scoped models: {sorted(missing)}"
