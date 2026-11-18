# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import bcrypt
import pytest

from api.endpoints.mcp_session import MCPSessionManager
from giljo_mcp.database import tenant_isolation_bypass, tenant_session_context
from giljo_mcp.models import Product, Project
from giljo_mcp.models.auth import User
from giljo_mcp.repositories.product_repository import ProductRepository
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.services.oauth_refresh_service import issue_refresh_token, new_family_id
from giljo_mcp.services.product_lifecycle_service import ProductLifecycleService
from giljo_mcp.services.product_service import ProductService
from giljo_mcp.services.project_helpers import mark_staging_complete, stamp_launch
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.services.settings_service import TenantSkillsAckService
from giljo_mcp.services.start_list_service import get_start_list
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

CLAUDE_AI_CLIENT_ID = "https://claude.ai/oauth/mcp-oauth-client-metadata"


class _Account:

    def __init__(self, session, db_manager):
        self.session = session
        self.db_manager = db_manager
        self.tenant_key = TenantManager.generate_tenant_key()
        session.info["tenant_key"] = self.tenant_key
        self.tm = TenantManager()
        self.tm.set_current_tenant(self.tenant_key)
        self.products = ProductService(db_manager, self.tenant_key, test_session=session)
        self.lifecycle = ProductLifecycleService(db_manager, self.tenant_key, test_session=session)
        self.projects = ProjectService(db_manager=db_manager, tenant_manager=self.tm, test_session=session)

    async def read(self):
        with tenant_session_context(self.session, self.tenant_key):
            return await get_start_list(self.session, self.tenant_key)

    async def connect_tool(self, client_name: str = "claude-code") -> None:
        with tenant_session_context(self.session, self.tenant_key):
            await MCPSessionManager(self.session).create_session(
                tenant_key=self.tenant_key,
                user_id=None,
                client_info={"name": client_name, "version": "1.0.0"},
                auth_method="oauth_jwt",
            )

    async def grant_oauth(self, *, lifetime_seconds: int, client_id: str = CLAUDE_AI_CLIENT_ID) -> None:
        suffix = uuid.uuid4().hex[:8]
        user = User(
            id=str(uuid.uuid4()),
            username=f"fe0072a_{suffix}",
            email=f"fe0072a_{suffix}@example.com",
            password_hash=bcrypt.hashpw(b"Test1234!", bcrypt.gensalt()).decode(),
            role="developer",
            tenant_key=self.tenant_key,
            is_active=True,
            created_at=datetime.now(UTC),
        )
        self.session.add(user)
        await self.session.flush()
        with tenant_session_context(self.session, self.tenant_key):
            await issue_refresh_token(
                self.session,
                family_id=new_family_id(),
                client_id=client_id,
                tenant_key=self.tenant_key,
                user_id=user.id,
                scope=None,
                aud="https://example.test/mcp",
                lifetime_seconds=lifetime_seconds,
            )

    async def run_giljo_setup_ack(self) -> None:
        await TenantSkillsAckService(self.session, self.tenant_key).acknowledge("1.0.0")

    async def make_product(self, name: str):
        return await self.products.create_product(name=name)

    async def make_project(self, product_id: str, name: str | None = None) -> Project:
        detail = await self.projects.create_project(
            name=name or f"proj {uuid.uuid4().hex[:6]}",
            mission="m",
            product_id=product_id,
            tenant_key=self.tenant_key,
        )
        return await self.session.get(Project, detail.id)

    async def stage(self, project: Project) -> None:
        await mark_staging_complete(self.session, project, source="test")
        await self.session.flush()

    async def launch(self, project: Project) -> None:
        stamp_launch(project)
        await self.session.flush()

    async def close(self, project: Project, *, review: bool = True) -> None:
        await self.projects.complete_project(
            project_id=project.id,
            summary="done",
            key_outcomes=[],
            decisions_made=[],
            tenant_key=self.tenant_key,
            git_commits=[],
        )
        await self.session.refresh(project)
        if review:
            await self.projects.mark_project_reviewed(project.id, self.tenant_key)
            await self.session.refresh(project)

    async def everything_done(self) -> None:
        await self.connect_tool()
        await self.run_giljo_setup_ack()
        product = await self.make_product(f"Everything {uuid.uuid4().hex[:6]}")
        project = await self.make_project(product.id)
        await self.stage(project)
        await self.launch(project)
        await self.close(project)


@pytest.fixture
def account(db_session, db_manager) -> _Account:
    return _Account(db_session, db_manager)


async def test_empty_account_has_nothing_done(account):
    result = await account.read()

    assert result.done_count == 0
    rows = result.rows
    assert rows.tool_connected.model_dump() == {"done": False, "live": False, "tool_name": None}
    assert rows.skills_installed.model_dump() == {"done": False}
    assert rows.product_exists.model_dump() == {"done": False, "product_name": None}
    assert rows.project_created.model_dump() == {"done": False, "project_id": None, "project_name": None}
    assert rows.project_staged.model_dump() == {"done": False, "has_project": False, "mode": None, "requested": False}
    assert rows.project_built.model_dump() == {"done": False, "in_progress": False, "awaiting_review": False}




async def test_a_connected_claude_code_session_ticks_row_one_live_and_names_the_tool(account):
    await account.connect_tool("claude-code")

    row = (await account.read()).rows.tool_connected

    assert row.model_dump() == {"done": True, "live": True, "tool_name": "Claude Code"}


async def test_two_different_tools_tick_live_with_no_name(account):
    await account.connect_tool("claude-code")
    await account.connect_tool("codex-mcp-client")

    row = (await account.read()).rows.tool_connected

    assert (row.done, row.live, row.tool_name) == (True, True, None)


async def test_a_live_hosted_chat_app_grant_ticks_live_and_names_it(account):
    await account.grant_oauth(lifetime_seconds=3600)

    row = (await account.read()).rows.tool_connected

    assert row.model_dump() == {"done": True, "live": True, "tool_name": "Claude"}


async def test_an_expired_grant_ticks_row_one_but_not_live(account):
    await account.grant_oauth(lifetime_seconds=-60)

    row = (await account.read()).rows.tool_connected

    assert (row.done, row.live, row.tool_name) == (True, False, None)


async def test_skills_ack_alone_ticks_row_one_as_connected_before(account):
    await account.run_giljo_setup_ack()

    result = await account.read()

    assert (result.rows.tool_connected.done, result.rows.tool_connected.live) == (True, False)
    assert result.rows.skills_installed.done is True
    assert result.done_count == 2


async def test_an_api_key_tool_idle_past_48h_that_never_ran_setup_reads_not_connected(account):
    row = (await account.read()).rows.tool_connected

    assert (row.done, row.live) == (False, False)




async def test_skills_row_ticks_only_after_giljo_setup_wrote_its_ack(account):
    assert (await account.read()).rows.skills_installed.done is False

    await account.run_giljo_setup_ack()

    assert (await account.read()).rows.skills_installed.done is True




@pytest.mark.parametrize("blank", ["", "   "])
async def test_the_tours_nameless_draft_does_not_tick_row_three(account, blank):
    await account.make_product(blank)

    row = (await account.read()).rows.product_exists

    assert row.model_dump() == {"done": False, "product_name": None}


async def test_a_named_product_ticks_row_three_and_reports_its_name(account):
    await account.make_product("Atlas")

    row = (await account.read()).rows.product_exists

    assert row.model_dump() == {"done": True, "product_name": "Atlas"}


async def test_a_nameless_draft_next_to_a_named_product_reports_the_named_one(account):
    await account.make_product("")
    await account.make_product("Atlas")

    assert (await account.read()).rows.product_exists.product_name == "Atlas"


async def test_the_default_product_names_row_three_over_a_newer_one(account):
    older = await account.make_product("Older")
    await account.make_product("Newer")
    await account.lifecycle.set_default_product(older.id)

    assert (await account.read()).rows.product_exists.product_name == "Older"


async def test_without_a_default_the_newest_named_product_names_the_row(account):
    await account.make_product("Older")
    await account.make_product("Newer")

    assert (await account.read()).rows.product_exists.product_name == "Newer"


async def test_a_soft_deleted_product_does_not_tick_row_three(account):
    product = await account.make_product("Gone")
    await account.lifecycle.delete_product(product.id)

    assert (await account.read()).rows.product_exists.done is False




async def test_a_new_project_sets_has_project_but_not_staged(account):
    product = await account.make_product("Atlas")
    await account.make_project(product.id)

    row = (await account.read()).rows.project_staged

    assert (row.done, row.has_project) == (False, True)


async def test_plain_staged_status_does_not_tick_row_four(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id)
    project.staging_status = "staged"
    await account.session.flush()

    assert (await account.read()).rows.project_staged.done is False


async def test_staging_complete_ticks_row_four(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id)
    await account.stage(project)

    row = (await account.read()).rows.project_staged

    assert (row.done, row.has_project) == (True, True)


async def test_a_launch_stamp_alone_ticks_row_four_even_after_a_restage_cleared_the_status(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id)
    await account.launch(project)
    project.staging_status = None
    await account.session.flush()

    assert (await account.read()).rows.project_staged.done is True


async def test_a_soft_deleted_staged_project_counts_for_nothing(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id)
    await account.stage(project)
    await account.projects.deletion.delete_project(project.id, broadcast=False)

    row = (await account.read()).rows.project_staged

    assert (row.done, row.has_project) == (False, False)




async def test_a_completed_project_with_no_launch_stamp_does_not_tick_row_five(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id)
    await account.close(project)
    assert project.ever_launched_at is None

    assert (await account.read()).rows.project_built.done is False


async def test_a_launched_but_not_completed_project_does_not_tick_row_five(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id)
    await account.launch(project)

    assert (await account.read()).rows.project_built.done is False


async def test_a_launched_and_closed_project_ticks_rows_four_and_five(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id)
    await account.launch(project)
    await account.close(project)

    result = await account.read()

    assert result.rows.project_built.done is True
    assert result.rows.project_staged.done is True


async def test_a_soft_deleted_built_project_stays_finished(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id)
    await account.launch(project)
    await account.close(project)
    await account.projects.deletion.delete_project(project.id, broadcast=False)

    assert (await account.read()).rows.project_built.done is True




async def test_done_count_is_the_number_of_ticked_rows(account):
    await account.everything_done()

    result = await account.read()

    assert result.done_count == 6
    assert result.rows.tool_connected.model_dump() == {"done": True, "live": True, "tool_name": "Claude Code"}
    assert result.rows.skills_installed.done is True
    assert result.rows.product_exists.done is True
    assert result.rows.project_staged.model_dump()["done"] is True
    assert result.rows.project_built.done is True


async def test_a_second_tenant_with_everything_done_leaves_the_first_at_zero_and_back(db_session, db_manager):
    first = _Account(db_session, db_manager)
    second = _Account(db_session, db_manager)
    await second.everything_done()

    assert (await first.read()).done_count == 0
    assert (await first.read()).rows.product_exists.product_name is None
    assert (await first.read()).rows.tool_connected.tool_name is None
    assert (await second.read()).done_count == 6

    await first.make_product("First only")

    assert (await first.read()).done_count == 1
    assert (await second.read()).rows.product_exists.product_name != "First only"


async def test_a_hosted_session_with_no_live_grant_ticks_live_but_stays_nameless(account):
    await account.connect_tool("Anthropic/ClaudeAI")

    row = (await account.read()).rows.tool_connected

    assert (row.done, row.live, row.tool_name) == (True, True, None)


async def test_the_repository_reads_carry_their_own_tenant_filter_with_the_session_guard_off(db_session, db_manager):
    first = _Account(db_session, db_manager)
    second = _Account(db_session, db_manager)
    await second.everything_done()

    with tenant_isolation_bypass(
        db_session, reason="FE-0072a: prove the explicit tenant filter", models=(Product, Project)
    ):
        name = await ProductRepository().get_start_list_product_name(db_session, first.tenant_key)
        facts = await ProjectRepository().get_start_list_project_facts(db_session, first.tenant_key)
        theirs = await ProjectRepository().get_start_list_project_facts(db_session, second.tenant_key)

    assert name is None
    assert (facts.project_id, facts.staged, facts.in_progress, facts.built) == (None, False, False, False)
    assert (theirs.project_id is not None, theirs.staged, theirs.built) == (True, True, True)
