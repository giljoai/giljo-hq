# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json

import pytest

from api.app_state import state
from api.event_bus import EventBus
from api.websocket import WebSocketManager
from api.websocket_event_listener import WebSocketEventListener
from tests.api.test_be9755_template_proposals_api import BASE, _account, _h


pytestmark = pytest.mark.asyncio

EVENT = "template:proposal_decided"


class _Tab:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        return None


def _tab(mgr: WebSocketManager, client_id: str, tenant_key: str) -> _Tab:
    tab = _Tab()
    mgr.active_connections[client_id] = tab
    mgr.auth_contexts[client_id] = {"tenant_key": tenant_key}
    mgr._index_tenant_connection(client_id, tenant_key)
    return tab


async def _wired(monkeypatch, acct: dict) -> tuple[_Tab, _Tab, _Tab]:
    bus, mgr = EventBus(), WebSocketManager()
    await WebSocketEventListener(bus, mgr).start()
    monkeypatch.setattr(state, "event_bus", bus, raising=False)
    return (
        _tab(mgr, "same-1", acct["tenant_key"]),
        _tab(mgr, "same-2", acct["tenant_key"]),
        _tab(mgr, "other", "tk_someone_else"),
    )


def _decided(tab: _Tab) -> list[dict]:
    return [m for m in tab.sent if m.get("type") == EVENT]


@pytest.mark.parametrize("action", ["apply", "reject"])
async def test_decision_reaches_every_tab_of_the_tenant_only(api_client, db_manager, monkeypatch, action):
    acct = await _account(db_manager)
    own_1, own_2, foreign = await _wired(monkeypatch, acct)

    resp = await api_client.post(f"{BASE}/{acct['template_proposal']}/{action}", headers=_h(acct["member"]))

    assert resp.status_code == 200, resp.text
    for tab in (own_1, own_2):
        [msg] = _decided(tab)
        assert msg["data"]["proposal_id"] == acct["template_proposal"]
        assert msg["data"]["action"] == action
        assert msg["data"]["tenant_key"] == acct["tenant_key"]
    assert foreign.sent == []


async def test_a_refused_decision_sends_nothing(api_client, db_manager, monkeypatch):
    acct = await _account(db_manager)
    own_1, _own_2, foreign = await _wired(monkeypatch, acct)

    resp = await api_client.post(f"{BASE}/{acct['additions_proposal']}/apply", headers=_h(acct["member"]))

    assert resp.status_code == 403
    assert own_1.sent == [] and foreign.sent == []
