# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from httpx import AsyncClient

from api.endpoints.chain_prompt_bootstrap import CHAIN_MEMBER_FALLBACK_PREAMBLE
from api.endpoints.prompts import _build_conductor_bootstrap, _conductor_mcp_url
from tests.api.test_fe9629_chain_member_play_prompt import _seed_chain


pytestmark = pytest.mark.asyncio

_GOLDEN_PREAMBLE = (
    "You are a member of a chain run by a conductor. This is a fallback prompt for this project only. "
    "Do not advance the chain yourself; the conductor decides the next step."
)


async def test_fallback_preamble_text_is_golden():
    assert CHAIN_MEMBER_FALLBACK_PREAMBLE == _GOLDEN_PREAMBLE


async def test_fallback_prompt_is_preamble_plus_the_shared_member_bootstrap(api_client: AsyncClient, db_manager):
    seed = await _seed_chain(db_manager)
    head = seed["members"][0]

    resp = await api_client.get(
        f"/api/v1/prompts/chain-member/{seed['head_pid']}",
        params={"fallback": "true"},
        headers=seed["headers"],
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    member_bootstrap = _build_conductor_bootstrap(
        identity={
            "agent_id": head["agent_id"],
            "job_id": head["job_id"],
            "run_id": seed["run_id"],
            "project_id": seed["head_pid"],
        },
        mcp_url=_conductor_mcp_url(),
        phase="staging",
        harness_is_claude=True,
    )
    prompt = resp.json()["prompt"]
    assert prompt.startswith(
        "You are a member of a chain run by a conductor. This is a fallback prompt for this project only."
    )
    assert prompt == f"{_GOLDEN_PREAMBLE}\n\n{member_bootstrap}"


async def test_member_prompt_without_the_flag_has_no_preamble(api_client: AsyncClient, db_manager):
    seed = await _seed_chain(db_manager)

    resp = await api_client.get(f"/api/v1/prompts/chain-member/{seed['head_pid']}", headers=seed["headers"])

    assert resp.status_code == 200
    assert "fallback prompt" not in resp.json()["prompt"]


async def test_fallback_for_a_non_member_is_refused(api_client: AsyncClient, db_manager):
    seed = await _seed_chain(db_manager)

    resp = await api_client.get(
        f"/api/v1/prompts/chain-member/{seed['solo_pid']}",
        params={"fallback": "true"},
        headers=seed["headers"],
    )
    assert resp.status_code == 404
