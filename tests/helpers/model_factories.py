# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.models.base import generate_uuid
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.products import Product, VisionDocument
from giljo_mcp.models.projects import Project
from giljo_mcp.models.templates import AgentTemplate


__all__ = [
    "make_agent_execution",
    "make_agent_template",
    "make_product",
    "make_product_memory_entry",
    "make_project",
    "make_vision_document",
    "strict_result",
]

TEST_TENANT_KEY = "tk_factory_test"


def _build(model: type, defaults: dict[str, Any], overrides: dict[str, Any]) -> Any:
    values = {**defaults, **overrides}
    for column in model.__table__.columns:
        if column.nullable or column.name in values:
            continue
        default = column.default
        if default is None or not hasattr(default, "arg"):
            continue
        values[column.name] = default.arg(None) if default.is_callable else default.arg
    return model(**values)


def make_project(**overrides: Any) -> Project:
    defaults: dict[str, Any] = {
        "tenant_key": TEST_TENANT_KEY,
        "product_id": "test-product-id",
        "name": "Test Project",
        "description": "Test project description",
        "mission": "Test project mission",
        "status": ProjectStatus.ACTIVE,
    }
    return _build(Project, defaults, overrides)


def make_product(**overrides: Any) -> Product:
    defaults: dict[str, Any] = {
        "tenant_key": TEST_TENANT_KEY,
        "name": "Test Product",
        "target_platforms": [],
        "product_memory": {},
        "vision_analysis_complete": False,
    }
    return _build(Product, defaults, overrides)


def make_agent_execution(**overrides: Any) -> AgentExecution:
    defaults: dict[str, Any] = {
        "tenant_key": TEST_TENANT_KEY,
        "job_id": generate_uuid(),
        "agent_display_name": "test-agent",
    }
    return _build(AgentExecution, defaults, overrides)


def make_agent_template(**overrides: Any) -> AgentTemplate:
    defaults: dict[str, Any] = {
        "tenant_key": TEST_TENANT_KEY,
        "name": "test-agent",
        "system_instructions": "Test system instructions",
    }
    return _build(AgentTemplate, defaults, overrides)


def make_product_memory_entry(**overrides: Any) -> ProductMemoryEntry:
    defaults: dict[str, Any] = {
        "tenant_key": TEST_TENANT_KEY,
        "product_id": "test-product-id",
        "sequence": 1,
        "entry_type": "project_closeout",
        "source": "closeout_v1",
        "timestamp": datetime.now(UTC),
        "key_outcomes": [],
        "decisions_made": [],
        "git_commits": [],
        "deliverables": [],
        "metrics": {},
        "priority": 3,
        "significance_score": 0.5,
        "tags": [],
        "deleted_by_user": False,
    }
    return _build(ProductMemoryEntry, defaults, overrides)


def make_vision_document(**overrides: Any) -> VisionDocument:
    defaults: dict[str, Any] = {
        "tenant_key": TEST_TENANT_KEY,
        "product_id": "test-product-id",
        "document_name": "Test Vision",
        "created_at": datetime.now(UTC),
    }
    return _build(VisionDocument, defaults, overrides)


_NOT_TOLD = object()


class _StrictResult:

    __slots__ = ("_answers", "_label")

    def __init__(self, label: str, answers: dict[str, Any]) -> None:
        self._label = label
        self._answers = answers

    def _answer(self, accessor: str) -> Any:
        value = self._answers.get(accessor, _NOT_TOLD)
        if value is _NOT_TOLD:
            told = ", ".join(sorted(self._answers)) or "nothing"
            raise AssertionError(
                f"INF-9399: {self._label} was asked for `{accessor}` but was only told "
                f"about: {told}.\n"
                f"The code under test is running a query this fake was never set up "
                f"for -- most likely one that was just added. Decide what that query "
                f"should honestly answer and pass it to strict_result(), e.g. "
                f"strict_result({accessor}=None).\n"
                f"Do NOT swap in a bare MagicMock: it would answer this query with a "
                f"truthy mock and the test would pass while asserting nothing. "
                f"See tests/helpers/model_factories.py."
            )
        return value

    def first(self) -> Any:
        return self._answer("first")

    def scalar_one_or_none(self) -> Any:
        return self._answer("scalar_one_or_none")

    def scalar_one(self) -> Any:
        return self._answer("scalar_one")

    def scalar(self) -> Any:
        return self._answer("scalar")

    def fetchall(self) -> Any:
        return self._answer("fetchall")

    def all(self) -> Any:
        return self._answer("all")

    def scalars(self) -> _StrictResult:
        return _StrictResult(
            f"{self._label}.scalars()",
            {
                accessor.removeprefix("scalars_"): value
                for accessor, value in self._answers.items()
                if accessor.startswith("scalars_")
            },
        )

    def __iter__(self):
        if "all" in self._answers:
            return iter(self._answers["all"])
        told = ", ".join(sorted(self._answers)) or "nothing"
        raise AssertionError(
            f"INF-9399: {self._label} was ITERATED (`for row in result:`) but was only "
            f"told about: {told}.\n"
            f"Iteration yields the same rows as `all()`, so tell it `all=[...]` with "
            f"what that query honestly returns -- `all=[]` if the honest answer is "
            f"'no rows'.\n"
            f"Do NOT swap in a bare MagicMock: it iterates as empty by default, which "
            f"looks like a deliberate 'no rows' and is really 'nobody decided'. "
            f"See tests/helpers/model_factories.py."
        )


def strict_result(label: str = "this fake query result", **answers: Any) -> _StrictResult:
    return _StrictResult(label, answers)
