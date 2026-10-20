# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


from __future__ import annotations

import ast
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2] / "src" / "giljo_mcp" / "repositories"
FILES = (
    "agent_operations_repository.py",
    "_agent_heartbeat_silence_mixin.py",
    "_agent_unread_counts_mixin.py",
)
QUERY_BUILDERS = {"select", "update", "delete"}

CROSS_TENANT = {
    ("_agent_heartbeat_silence_mixin.py", "find_stale_working_agents"): (
        "system-wide silence monitor; runs under tenant_isolation_bypass"
    ),
    ("_agent_heartbeat_silence_mixin.py", "get_silence_threshold_setting"): "SystemSetting is a global table",
}


def _compares_tenant_key(node: ast.AST) -> bool:
    return any(
        isinstance(cmp, ast.Compare)
        and any(isinstance(side, ast.Attribute) and side.attr == "tenant_key" for side in (cmp.left, *cmp.comparators))
        for cmp in ast.walk(node)
    )


def _builds_query(stmt: ast.stmt) -> bool:
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in QUERY_BUILDERS
        for node in ast.walk(stmt)
    )


def _simple_statements(func: ast.AST):
    for node in ast.walk(func):
        if isinstance(node, ast.stmt) and not hasattr(node, "body"):
            yield node


def unfiltered_queries(source: str, filename: str) -> list[tuple[str, str]]:
    findings = []
    for func in ast.walk(ast.parse(source)):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        assigned: dict[str, list[ast.Assign]] = {}
        for stmt in _simple_statements(func):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        assigned.setdefault(target.id, []).append(stmt)
        for stmt in _simple_statements(func):
            if not _builds_query(stmt):
                continue
            names = {n.id for n in ast.walk(stmt) if isinstance(n, ast.Name)}
            reachable = [stmt, *(node for name in names for node in assigned.get(name, []))]
            if not any(_compares_tenant_key(node) for node in reachable):
                findings.append((func.name, ast.get_source_segment(source, stmt)))
    return findings


def _query_statement_count(source: str) -> int:
    return sum(
        1
        for func in ast.walk(ast.parse(source))
        if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef))
        for stmt in _simple_statements(func)
        if _builds_query(stmt)
    )


def test_every_query_in_the_agent_operations_files_is_tenant_filtered():
    unexpected = []
    seen_cross_tenant = set()
    for filename in FILES:
        source = (REPO_DIR / filename).read_text(encoding="utf-8")
        assert _query_statement_count(source) > 0, f"{filename}: no queries found -- the scan is not reading it"
        for func_name, text in unfiltered_queries(source, filename):
            if (filename, func_name) in CROSS_TENANT:
                seen_cross_tenant.add((filename, func_name))
            else:
                unexpected.append(f"{filename}::{func_name}: {text}")

    assert not unexpected, "queries with no tenant_key filter:\n" + "\n".join(unexpected)
    assert seen_cross_tenant == set(CROSS_TENANT), (
        f"CROSS_TENANT entries no longer unfiltered, remove them: {set(CROSS_TENANT) - seen_cross_tenant}"
    )


def test_the_scan_reports_a_query_with_no_tenant_filter():
    planted = (
        "async def leaky(session, job_id, tenant_key):\n"
        "    stmt = select(AgentExecution).where(AgentExecution.job_id == job_id, ~acked(tenant_key))\n"
        "    return await session.execute(stmt)\n"
        "async def scoped(session, job_id, tenant_key):\n"
        "    conditions = [AgentExecution.job_id == job_id, AgentExecution.tenant_key == tenant_key]\n"
        "    return await session.execute(update(AgentExecution).where(and_(*conditions)))\n"
    )
    assert unfiltered_queries(planted, "planted.py") == [
        ("leaky", "stmt = select(AgentExecution).where(AgentExecution.job_id == job_id, ~acked(tenant_key))")
    ]
