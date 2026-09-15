# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

from __future__ import annotations

import giljo_mcp.models  # noqa: F401 -- import-for-side-effect, populates Base.registry.mappers
from giljo_mcp import database
from giljo_mcp.models.base import Base


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
    registered_names = {cls.__name__ for cls in set(database.TENANT_SCOPED_MODELS)}
    ce_names = {cls.__name__ for cls in _ce_tenant_scoped_mapped_classes()}

    for name, reason in EXEMPT_CE_MODELS.items():
        assert name in ce_names, f"EXEMPT_CE_MODELS names {name!r} which is not a CE tenant_key model"
        assert reason.strip(), f"EXEMPT_CE_MODELS[{name!r}] has an empty reason"
        assert name not in registered_names, f"{name!r} is exempted but IS registered -- remove the stale exemption"


def test_at_least_the_known_gap_models_are_scoped() -> None:
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
