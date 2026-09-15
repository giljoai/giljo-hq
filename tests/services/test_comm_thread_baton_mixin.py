# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.services._comm_thread_baton_mixin import CommThreadBatonMixin
from giljo_mcp.services.comm_thread_service import CommThreadService


BATON_METHODS = ("get_my_turn", "pass_baton", "has_active_loop_directive")


def test_the_service_composes_the_baton_mixin():
    assert issubclass(CommThreadService, CommThreadBatonMixin)


@pytest.mark.parametrize("name", BATON_METHODS)
def test_each_baton_method_is_served_by_the_mixin_and_not_shadowed(name):
    assert getattr(CommThreadService, name) is getattr(CommThreadBatonMixin, name)


def test_the_mixin_owns_no_session_plumbing_of_its_own():
    own = vars(CommThreadBatonMixin)
    assert "_resolve_tenant" not in own
    assert "_scoped_session" not in own
    assert "__init__" not in own
