# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest
from pydantic import ValidationError

from api.endpoints.auth import SetupStateUpdate




class TestSetupStateUpdateValidation:

    def test_valid_all_fields(self):
        update = SetupStateUpdate(
            setup_selected_tools=["claude_code", "cursor"],
            setup_step_completed=3,
            setup_complete=True,
        )
        assert update.setup_selected_tools == ["claude_code", "cursor"]
        assert update.setup_step_completed == 3
        assert update.setup_complete is True

    def test_valid_partial_step_only(self):
        update = SetupStateUpdate(setup_step_completed=2)
        assert update.setup_step_completed == 2
        assert update.setup_selected_tools is None
        assert update.setup_complete is None

    def test_valid_empty_tools_list(self):
        update = SetupStateUpdate(setup_selected_tools=[])
        assert update.setup_selected_tools == []

    def test_valid_step_zero(self):
        update = SetupStateUpdate(setup_step_completed=0)
        assert update.setup_step_completed == 0

    def test_valid_step_four(self):
        update = SetupStateUpdate(setup_step_completed=4)
        assert update.setup_step_completed == 4

    def test_valid_all_none(self):
        update = SetupStateUpdate()
        assert update.setup_selected_tools is None
        assert update.setup_step_completed is None
        assert update.setup_complete is None

    def test_rejects_step_five(self):
        with pytest.raises(ValidationError) as exc_info:
            SetupStateUpdate(setup_step_completed=5)
        assert "less than or equal to 4" in str(exc_info.value)

    def test_rejects_negative_step(self):
        with pytest.raises(ValidationError) as exc_info:
            SetupStateUpdate(setup_step_completed=-1)
        assert "greater than or equal to 0" in str(exc_info.value)

    def test_rejects_step_large_value(self):
        with pytest.raises(ValidationError):
            SetupStateUpdate(setup_step_completed=100)


class TestTutorialReentryValidation:

    def test_valid_beat_range(self):
        assert SetupStateUpdate(learning_beat=1).learning_beat == 1
        assert SetupStateUpdate(learning_beat=6).learning_beat == 6

    def test_rejects_beat_zero_and_seven(self):
        with pytest.raises(ValidationError):
            SetupStateUpdate(learning_beat=0)
        with pytest.raises(ValidationError):
            SetupStateUpdate(learning_beat=7)

    def test_valid_router_choices(self):
        for door in ("A", "B", "C", "D"):
            assert SetupStateUpdate(router_choice=door).router_choice == door

    def test_rejects_unknown_router_choice(self):
        with pytest.raises(ValidationError):
            SetupStateUpdate(router_choice="E")
        with pytest.raises(ValidationError):
            SetupStateUpdate(router_choice="a")

    def test_defaults_are_none(self):
        update = SetupStateUpdate()
        assert update.learning_beat is None
        assert update.router_choice is None




@pytest.mark.asyncio
async def test_patch_setup_state_full_update(api_client, auth_headers):
    response = await api_client.patch(
        "/api/auth/me/setup-state",
        headers=auth_headers,
        json={
            "setup_step_completed": 2,
            "setup_selected_tools": ["claude_code"],
            "setup_complete": False,
        },
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["setup_step_completed"] == 2
    assert data["setup_selected_tools"] == ["claude_code"]
    assert data["setup_complete"] is False


@pytest.mark.asyncio
async def test_patch_setup_state_partial_step_only(api_client, auth_headers):
    response = await api_client.patch(
        "/api/auth/me/setup-state",
        headers=auth_headers,
        json={"setup_step_completed": 3},
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["setup_step_completed"] == 3


@pytest.mark.asyncio
async def test_patch_setup_state_complete_flag(api_client, auth_headers):
    response = await api_client.patch(
        "/api/auth/me/setup-state",
        headers=auth_headers,
        json={"setup_complete": True, "setup_step_completed": 4},
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["setup_complete"] is True
    assert data["setup_step_completed"] == 4


@pytest.mark.asyncio
async def test_patch_setup_state_invalid_step_rejected(api_client, auth_headers):
    response = await api_client.patch(
        "/api/auth/me/setup-state",
        headers=auth_headers,
        json={"setup_step_completed": 5},
    )
    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_patch_setup_state_unauthenticated(api_client):
    response = await api_client.patch(
        "/api/auth/me/setup-state",
        headers={"Cookie": "csrf_token=t", "X-CSRF-Token": "t"},
        json={"setup_step_completed": 1},
    )
    assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_get_active_api_keys_empty(api_client, auth_headers):
    response = await api_client.get(
        "/api/auth/api-keys/active",
        headers=auth_headers,
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0


@pytest.mark.asyncio
async def test_get_active_api_keys_unauthenticated(api_client):
    response = await api_client.get("/api/auth/api-keys/active")
    assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_get_me_includes_setup_fields(api_client, auth_headers):
    response = await api_client.get(
        "/api/auth/me",
        headers=auth_headers,
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()

    assert "setup_complete" in data, "Response should include setup_complete field"
    assert "setup_selected_tools" in data, "Response should include setup_selected_tools field"
    assert "setup_step_completed" in data, "Response should include setup_step_completed field"

    assert data["setup_complete"] is False, "Default setup_complete should be False"
    assert data["setup_step_completed"] == 0, "Default setup_step_completed should be 0"




@pytest.mark.asyncio
async def test_patch_tutorial_reentry_state_persists_and_echoes(api_client, auth_headers):
    response = await api_client.patch(
        "/api/auth/me/setup-state",
        headers=auth_headers,
        json={"learning_beat": 3, "router_choice": "D"},
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["learning_beat"] == 3
    assert data["router_choice"] == "D"


@pytest.mark.asyncio
async def test_patch_learning_beat_six_boundary_roundtrips(api_client, auth_headers):
    patch_response = await api_client.patch(
        "/api/auth/me/setup-state",
        headers=auth_headers,
        json={"learning_beat": 6},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["learning_beat"] == 6

    me_response = await api_client.get("/api/auth/me", headers=auth_headers)
    assert me_response.status_code == 200
    assert me_response.json()["learning_beat"] == 6


@pytest.mark.asyncio
async def test_patch_tutorial_reentry_rejects_out_of_range(api_client, auth_headers):
    beat_response = await api_client.patch(
        "/api/auth/me/setup-state",
        headers=auth_headers,
        json={"learning_beat": 7},
    )
    assert beat_response.status_code == 422

    door_response = await api_client.patch(
        "/api/auth/me/setup-state",
        headers=auth_headers,
        json={"router_choice": "X"},
    )
    assert door_response.status_code == 422


@pytest.mark.asyncio
async def test_patch_setup_state_tolerates_unknown_fields(api_client, auth_headers):
    response = await api_client.patch(
        "/api/auth/me/setup-state",
        headers=auth_headers,
        json={"learning_beat": 2, "some_future_field": "ignored"},
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    assert response.json()["learning_beat"] == 2


@pytest.mark.asyncio
async def test_get_me_includes_tutorial_reentry_fields(api_client, auth_headers):
    response = await api_client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "learning_beat" in data
    assert "router_choice" in data


@pytest.mark.asyncio
async def test_tutorial_reentry_roundtrip_via_me(api_client, auth_headers):
    patch_response = await api_client.patch(
        "/api/auth/me/setup-state",
        headers=auth_headers,
        json={"learning_beat": 5, "router_choice": "B"},
    )
    assert patch_response.status_code == 200

    me_response = await api_client.get("/api/auth/me", headers=auth_headers)
    assert me_response.status_code == 200
    data = me_response.json()
    assert data["learning_beat"] == 5
    assert data["router_choice"] == "B"


@pytest.mark.asyncio
async def test_setup_state_roundtrip(api_client, auth_headers):
    patch_response = await api_client.patch(
        "/api/auth/me/setup-state",
        headers=auth_headers,
        json={
            "setup_step_completed": 2,
            "setup_selected_tools": ["claude_code", "windsurf"],
            "setup_complete": False,
        },
    )
    assert patch_response.status_code == 200

    me_response = await api_client.get("/api/auth/me", headers=auth_headers)
    assert me_response.status_code == 200
    data = me_response.json()
    assert data["setup_step_completed"] == 2
    assert data["setup_selected_tools"] == ["claude_code", "windsurf"]
    assert data["setup_complete"] is False




def test_setup_state_update_refuses_false_for_intro_video_seen():
    assert SetupStateUpdate(intro_video_seen=True).intro_video_seen is True
    assert SetupStateUpdate().intro_video_seen is None
    with pytest.raises(ValidationError):
        SetupStateUpdate(intro_video_seen=False)


@pytest.mark.asyncio
async def test_get_me_returns_intro_video_seen_false_and_created_at_for_a_new_user(api_client, auth_headers):
    response = await api_client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["intro_video_seen"] is False
    assert isinstance(data["created_at"], str) and data["created_at"]


@pytest.mark.asyncio
async def test_patch_intro_video_seen_true_saves_and_roundtrips(api_client, auth_headers):
    response = await api_client.patch("/api/auth/me/setup-state", headers=auth_headers, json={"intro_video_seen": True})
    assert response.status_code == 200, response.text
    assert response.json()["intro_video_seen"] is True

    me = await api_client.get("/api/auth/me", headers=auth_headers)
    assert me.json()["intro_video_seen"] is True


@pytest.mark.asyncio
async def test_patch_intro_video_seen_false_is_422_and_saves_nothing(api_client, auth_headers):
    assert (
        await api_client.patch("/api/auth/me/setup-state", headers=auth_headers, json={"intro_video_seen": True})
    ).status_code == 200

    response = await api_client.patch(
        "/api/auth/me/setup-state", headers=auth_headers, json={"intro_video_seen": False}
    )
    assert response.status_code == 422, response.text

    me = await api_client.get("/api/auth/me", headers=auth_headers)
    assert me.json()["intro_video_seen"] is True


@pytest.mark.asyncio
async def test_intro_video_seen_is_scoped_to_the_calling_user(api_client, auth_headers, db_manager):
    from uuid import uuid4

    from giljo_mcp.auth.jwt_manager import JWTManager
    from giljo_mcp.models import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    suffix = uuid4().hex[:8]
    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async() as session:
        org = Organization(name=f"Other {suffix}", slug=f"other-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        other = User(
            username=f"other_{suffix}",
            email=f"other_{suffix}@example.com",
            password_hash="x",
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(other)
        await session.commit()
        other_id = other.id
        token = JWTManager.create_access_token(
            user_id=other_id, username=other.username, role="developer", tenant_key=tenant_key
        )
    other_headers = {
        "Cookie": f"access_token={token}; csrf_token={auth_headers['X-CSRF-Token']}",
        "X-CSRF-Token": auth_headers["X-CSRF-Token"],
    }

    saved = await api_client.patch("/api/auth/me/setup-state", headers=auth_headers, json={"intro_video_seen": True})
    assert saved.status_code == 200

    other_me = await api_client.get("/api/auth/me", headers=other_headers)
    assert other_me.json()["intro_video_seen"] is False

    spoof = await api_client.patch(
        "/api/auth/me/setup-state",
        headers=other_headers,
        json={"intro_video_seen": True, "user_id": "someone-else", "tenant_key": "tk_other"},
    )
    assert spoof.status_code == 200
    mine = await api_client.get("/api/auth/me", headers=auth_headers)
    assert mine.json()["intro_video_seen"] is True
    assert mine.json()["tenant_key"] != "tk_other"




def test_setup_state_update_accepts_both_values_for_guide_closed():
    assert SetupStateUpdate(guide_closed=True).guide_closed is True
    assert SetupStateUpdate(guide_closed=False).guide_closed is False
    assert SetupStateUpdate().guide_closed is None


@pytest.mark.asyncio
async def test_get_me_returns_guide_closed_false_for_a_new_user(api_client, auth_headers):
    response = await api_client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["guide_closed"] is False


@pytest.mark.asyncio
async def test_patch_guide_closed_writes_both_ways_and_roundtrips(api_client, auth_headers):
    closed = await api_client.patch("/api/auth/me/setup-state", headers=auth_headers, json={"guide_closed": True})
    assert closed.status_code == 200, closed.text
    assert closed.json()["guide_closed"] is True
    assert (await api_client.get("/api/auth/me", headers=auth_headers)).json()["guide_closed"] is True

    reopened = await api_client.patch("/api/auth/me/setup-state", headers=auth_headers, json={"guide_closed": False})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["guide_closed"] is False
    assert (await api_client.get("/api/auth/me", headers=auth_headers)).json()["guide_closed"] is False


@pytest.mark.asyncio
async def test_patch_without_guide_closed_leaves_it_alone(api_client, auth_headers):
    await api_client.patch("/api/auth/me/setup-state", headers=auth_headers, json={"guide_closed": True})

    other = await api_client.patch("/api/auth/me/setup-state", headers=auth_headers, json={"setup_step_completed": 1})

    assert other.status_code == 200, other.text
    assert other.json()["guide_closed"] is True


@pytest.mark.asyncio
async def test_patch_guide_closed_rejects_a_non_boolean(api_client, auth_headers):
    response = await api_client.patch("/api/auth/me/setup-state", headers=auth_headers, json={"guide_closed": "banana"})
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_guide_closed_is_scoped_to_the_calling_user(api_client, auth_headers, db_manager):
    from uuid import uuid4

    from giljo_mcp.auth.jwt_manager import JWTManager
    from giljo_mcp.models import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    suffix = uuid4().hex[:8]
    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async() as session:
        org = Organization(name=f"Other {suffix}", slug=f"other-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        other = User(
            username=f"other_{suffix}",
            email=f"other_{suffix}@example.com",
            password_hash="x",
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(other)
        await session.commit()
        token = JWTManager.create_access_token(
            user_id=other.id, username=other.username, role="developer", tenant_key=tenant_key
        )
    other_headers = {
        "Cookie": f"access_token={token}; csrf_token={auth_headers['X-CSRF-Token']}",
        "X-CSRF-Token": auth_headers["X-CSRF-Token"],
    }

    saved = await api_client.patch("/api/auth/me/setup-state", headers=auth_headers, json={"guide_closed": True})
    assert saved.status_code == 200

    assert (await api_client.get("/api/auth/me", headers=other_headers)).json()["guide_closed"] is False

    spoof = await api_client.patch(
        "/api/auth/me/setup-state",
        headers=other_headers,
        json={"guide_closed": False, "user_id": "someone-else", "tenant_key": "tk_other"},
    )
    assert spoof.status_code == 200
    assert (await api_client.get("/api/auth/me", headers=auth_headers)).json()["guide_closed"] is True
