# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Unit tests for the context-tuning-due banner gate (FE-9202 + BE-9218 cadence).

Covers ``context_tuning_banner.compute_context_tuning_due`` at its own layer.

BE-9218 ratified the F2 "design-stands" boundary: the banner is now gated on the
user's ``tuning_reminder_threshold`` (count-based staleness) instead of the fixed
14-day/336h time cadence FE-9202 shipped. Two groups of tests:

- ``TestComputeContextTuningDue`` — the emitter's gate CONTRACT, with the owning
  ``check_tuning_staleness`` patched at its call site (fast, no DB). Fires iff the
  preference is on AND the product is stale; the projects count rides into the
  payload. Includes the two observable-change cases that pin the FE-9202→BE-9218
  reversal (old+active-but-below-threshold no longer fires; recently-tuned-in-time
  but above-threshold now fires).
- ``TestThresholdGovernsCadence`` — the end-to-end demonstration that the banner
  interval follows a NON-default ``tuning_reminder_threshold``, driving the REAL
  ``check_tuning_staleness`` (only the repos + session are mocked), per the DoD.

Parallel-safe: no module-level mutable state; every dependency patched via the
function-scoped monkeypatch fixture or a local mock db-manager.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from api.startup import context_tuning_banner as ctb


def _product(*, name="Acme", pid="prod-1", tuning_state=None):
    # The emitter no longer reads tuning_state directly (BE-9218: the threshold +
    # anchor live inside check_tuning_staleness), so id + name are all the gate needs.
    return SimpleNamespace(id=pid, name=name, tuning_state=tuning_state)


def _patch_gate(monkeypatch, *, product, user_id="user-1", staleness):
    async def _get_active(_self, *, eager_load=True):
        return product

    async def _resolve(_db_manager, _tenant_key):
        return user_id

    async def _staleness(_self, *, product_id, user_id):
        return staleness

    monkeypatch.setattr("giljo_mcp.services.product_service.ProductService.get_default_product", _get_active)
    monkeypatch.setattr(ctb, "_resolve_active_user_id", _resolve)
    monkeypatch.setattr(
        "giljo_mcp.services.product_tuning_service.ProductTuningService.check_tuning_staleness",
        _staleness,
    )


class TestComputeContextTuningDue:
    @pytest.mark.asyncio
    async def test_due_when_stale(self, monkeypatch):
        # Preference on + stale by the threshold -> banner fires, projects count
        # carried into the payload.
        _patch_gate(
            monkeypatch,
            product=_product(),
            staleness={"is_stale": True, "projects_since_tune": 5, "threshold": 3, "enabled": True},
        )
        due = await ctb.compute_context_tuning_due(db_manager=object(), tenant_key="t1")
        assert due == {"product_id": "prod-1", "product_name": "Acme", "projects_since_tune": 5}

    @pytest.mark.asyncio
    async def test_none_when_not_stale_below_threshold(self, monkeypatch):
        # OBSERVABLE CHANGE (FE-9202 -> BE-9218): under the old 14-day gate an
        # old, active product fired even below the count threshold. Now the banner
        # is count-gated: is_stale=False (projects_since < threshold) -> no banner,
        # regardless of wall-clock age.
        _patch_gate(
            monkeypatch,
            product=_product(),
            staleness={"is_stale": False, "projects_since_tune": 5, "threshold": 10, "enabled": True},
        )
        assert await ctb.compute_context_tuning_due(db_manager=object(), tenant_key="t1") is None

    @pytest.mark.asyncio
    async def test_due_when_stale_even_if_recently_tuned_in_time(self, monkeypatch):
        # OBSERVABLE CHANGE (the inverse): under the old gate a tune within the last
        # 14 days suppressed the banner regardless of activity. Now, if enough
        # projects completed since that tune (is_stale=True), the banner fires — time
        # no longer suppresses it.
        _patch_gate(
            monkeypatch,
            product=_product(),
            staleness={"is_stale": True, "projects_since_tune": 12, "threshold": 3, "enabled": True},
        )
        due = await ctb.compute_context_tuning_due(db_manager=object(), tenant_key="t1")
        assert due is not None
        assert due["projects_since_tune"] == 12

    @pytest.mark.asyncio
    async def test_none_when_preference_off(self, monkeypatch):
        # User disabled the reminder -> suppressed even when stale.
        _patch_gate(
            monkeypatch,
            product=_product(),
            staleness={"is_stale": True, "projects_since_tune": 20, "threshold": 3, "enabled": False},
        )
        assert await ctb.compute_context_tuning_due(db_manager=object(), tenant_key="t1") is None

    @pytest.mark.asyncio
    async def test_none_when_no_active_product(self, monkeypatch):
        _patch_gate(monkeypatch, product=None, staleness={"enabled": True, "is_stale": True, "projects_since_tune": 5})
        assert await ctb.compute_context_tuning_due(db_manager=object(), tenant_key="t1") is None

    @pytest.mark.asyncio
    async def test_none_when_no_user(self, monkeypatch):
        _patch_gate(
            monkeypatch,
            product=_product(),
            user_id=None,
            staleness={"enabled": True, "is_stale": True, "projects_since_tune": 5},
        )
        assert await ctb.compute_context_tuning_due(db_manager=object(), tenant_key="t1") is None

    @pytest.mark.asyncio
    async def test_legacy_anchor_shape_does_not_error(self, monkeypatch):
        # Old-shape tuning_state (last_tuned_at present, last_tuned_at_sequence
        # absent) reaches the gate; check_tuning_staleness tolerates it (reads
        # sequence 0). The emitter must not choke on the legacy product either.
        legacy = _product(tuning_state={"last_tuned_at": "2026-01-01T00:00:00+00:00"})
        _patch_gate(
            monkeypatch,
            product=legacy,
            staleness={"is_stale": True, "projects_since_tune": 7, "threshold": 3, "enabled": True},
        )
        due = await ctb.compute_context_tuning_due(db_manager=object(), tenant_key="t1")
        assert due is not None and due["projects_since_tune"] == 7


def _mock_db_manager():
    """A db-manager whose get_session_async yields an AsyncMock session.

    Mirrors the fixture in tests/services/test_product_tuning_service.py so the real
    check_tuning_staleness can run with only the repos mocked.
    """
    session = AsyncMock()
    session.info = {}  # tenant_session_context save/restore target
    async_cm = AsyncMock()
    async_cm.__aenter__ = AsyncMock(return_value=session)
    async_cm.__aexit__ = AsyncMock(return_value=False)
    db_manager = Mock()
    db_manager.get_session_async = Mock(return_value=async_cm)
    return db_manager, session


class TestThresholdGovernsCadence:
    """End-to-end: the banner interval follows a NON-default tuning_reminder_threshold.

    Drives the REAL ProductTuningService.check_tuning_staleness (repos + session
    mocked) so a genuine threshold value decides whether the banner fires. Same
    activity (5 projects since a never-tuned product's creation), two non-default
    thresholds, opposite outcomes.
    """

    @staticmethod
    def _run(monkeypatch, *, threshold, next_sequence):
        db_manager, _session = _mock_db_manager()
        product = _product(tuning_state=None)  # never tuned -> last_tuned_at_sequence 0

        async def _get_active(_self, *, eager_load=True):
            return product

        async def _resolve(_db_manager, _tenant_key):
            return "user-1"

        user = SimpleNamespace(
            id="user-1",
            tenant_key="t1",
            notification_preferences={
                "context_tuning_reminder": True,
                "tuning_reminder_threshold": threshold,
            },
        )

        monkeypatch.setattr("giljo_mcp.services.product_service.ProductService.get_default_product", _get_active)
        monkeypatch.setattr(ctb, "_resolve_active_user_id", _resolve)
        monkeypatch.setattr(
            "giljo_mcp.repositories.product_repository.ProductRepository.get_by_id",
            AsyncMock(return_value=product),
        )
        monkeypatch.setattr(
            "giljo_mcp.repositories.user_repository.UserRepository.get_user_by_id",
            AsyncMock(return_value=user),
        )
        monkeypatch.setattr(
            "giljo_mcp.repositories.product_memory_repository.ProductMemoryRepository.get_next_sequence",
            AsyncMock(return_value=next_sequence),
        )
        return ctb.compute_context_tuning_due(db_manager=db_manager, tenant_key="t1")

    @pytest.mark.asyncio
    async def test_low_threshold_fires(self, monkeypatch):
        # threshold=3 (non-default), 5 projects since creation -> stale -> fires.
        due = await self._run(monkeypatch, threshold=3, next_sequence=6)
        assert due is not None
        assert due["projects_since_tune"] == 5

    @pytest.mark.asyncio
    async def test_high_threshold_suppresses(self, monkeypatch):
        # threshold=100 (non-default), same 5 projects -> not stale -> no banner.
        due = await self._run(monkeypatch, threshold=100, next_sequence=6)
        assert due is None


class TestPayloadValidator:
    def test_valid_payload_roundtrips(self):
        from giljo_mcp.schemas.jsonb_notification_payloads import validate_notification_payload

        out = validate_notification_payload(
            "system.context_tuning_due",
            {"product_id": "p1", "product_name": "Acme", "projects_since_tune": 3},
        )
        assert out == {"product_id": "p1", "product_name": "Acme", "projects_since_tune": 3}

    def test_missing_field_rejected(self):
        import pydantic

        from giljo_mcp.schemas.jsonb_notification_payloads import validate_notification_payload

        with pytest.raises(pydantic.ValidationError):
            validate_notification_payload("system.context_tuning_due", {"product_id": "p1"})

    def test_extra_field_rejected(self):
        import pydantic

        from giljo_mcp.schemas.jsonb_notification_payloads import validate_notification_payload

        with pytest.raises(pydantic.ValidationError):
            validate_notification_payload(
                "system.context_tuning_due",
                {"product_id": "p1", "product_name": "Acme", "projects_since_tune": 3, "extra": "x"},
            )
