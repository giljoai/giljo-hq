# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9365b — the baton mixin is composed in, not copied.

``get_my_turn``, ``pass_baton`` and ``has_active_loop_directive`` moved off
``CommThreadService`` when the operator alias pushed that module past its shrink-only
size budget. The move is pure relocation: their behaviour is covered where it already
was — ``test_be9207_per_participant_baton.py`` for the multi-lane baton, the BE-9292a
boundary suite for reachability and the operator alias over the wire, FE-6140's suites
for loop directives.

What those suites CANNOT catch is the failure mode an extraction introduces: a
redefinition left behind on ``CommThreadService`` would shadow the mixin copy, every
behavioural test would keep passing against the shadow, and the mixin would sit there
looking authoritative while being dead. The two copies then drift, and the first symptom
is a fix applied to the file nobody runs.

Same guard the enrichment mixin carries, for the same reason. Cheap, and it fails the
moment someone "helpfully" pastes a method back.

Parallel-safe: pure identity assertions, no DB, no module-level mutable state.
"""

from __future__ import annotations

import pytest

from giljo_mcp.services._comm_thread_baton_mixin import CommThreadBatonMixin
from giljo_mcp.services.comm_thread_service import CommThreadService


BATON_METHODS = ("get_my_turn", "pass_baton", "has_active_loop_directive")


def test_the_service_composes_the_baton_mixin():
    assert issubclass(CommThreadService, CommThreadBatonMixin)


@pytest.mark.parametrize("name", BATON_METHODS)
def test_each_baton_method_is_served_by_the_mixin_and_not_shadowed(name):
    """Identity, not merely presence — ``hasattr`` would pass against a shadow."""
    assert getattr(CommThreadService, name) is getattr(CommThreadBatonMixin, name)


def test_the_mixin_owns_no_session_plumbing_of_its_own():
    """It borrows the service's ``_resolve_tenant`` / ``_scoped_session`` / ``_repo``.

    A mixin that grew its own would be a second, divergent way to open a tenant-scoped
    session — the thing the single-plumbing rule exists to prevent — and it would stop
    being a pure extraction.
    """
    own = vars(CommThreadBatonMixin)
    assert "_resolve_tenant" not in own
    assert "_scoped_session" not in own
    assert "__init__" not in own
