# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


from api import app_state
from api.app import app
from tests.fixtures.base_fixtures import restored_app_state


_SENTINEL = object()


def test_first_assigns_app_state_and_leaves_it():
    app_state.state.db_manager = _SENTINEL
    app_state.state.connections["guard"] = _SENTINEL
    app_state.state.degraded_services.append("guard")
    app_state.state.guard_only_attribute = _SENTINEL
    app.state.db_manager = _SENTINEL
    app.state.guard_only_entry = _SENTINEL


def test_second_sees_none_of_it():
    assert app_state.state.db_manager is not _SENTINEL
    assert "guard" not in app_state.state.connections
    assert "guard" not in app_state.state.degraded_services
    assert not hasattr(app_state.state, "guard_only_attribute")
    assert getattr(app.state, "db_manager", None) is not _SENTINEL
    assert not hasattr(app.state, "guard_only_entry")


def test_restore_keeps_the_value_present_at_entry():
    owner_value = object()
    with restored_app_state():
        app_state.state.db_manager = owner_value
        with restored_app_state():
            app_state.state.db_manager = _SENTINEL
        assert app_state.state.db_manager is owner_value


def test_restore_keeps_the_fastapi_app_state_present_at_entry():
    owner_value = object()
    with restored_app_state():
        app.state.db_manager = owner_value
        with restored_app_state():
            app.state.db_manager = _SENTINEL
        assert app.state.db_manager is owner_value


def test_restore_puts_back_the_registered_websocket_manager():
    from giljo_mcp.app_registry import service_registry

    before = service_registry.get_websocket_manager()
    with restored_app_state():
        service_registry.set_websocket_manager(object())
    assert service_registry.get_websocket_manager() is before
