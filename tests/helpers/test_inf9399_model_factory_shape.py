# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""The model-factory convention's claims, as tests rather than as prose (INF-9399).

``tests/helpers/model_factories.py`` makes four promises about why a real
transient instance beats a mock for an ORM stand-in. A docstring that promises
something no test checks is the same species of problem this module exists to
close, so each promise is pinned here.

The contrast tests are the load-bearing ones. They pin what a spec'd mock
actually does, so that "simplify this to create_autospec" cannot be done later
without a named check going red -- which is the exact simplification the
project record itself proposed before it was measured.

Edition Scope: Both (test-only).
"""

from unittest.mock import MagicMock, create_autospec

import pytest

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models.projects import Project
from giljo_mcp.models.templates import AgentTemplate
from tests.helpers.model_factories import (
    make_agent_execution,
    make_agent_template,
    make_product,
    make_product_memory_entry,
    make_project,
    make_vision_document,
    strict_result,
)


class TestAnUnsetNullableColumnReadsNone:
    """The 2026-08-09 regression, in one assertion per stand-in style."""

    def test_the_factory_answers_none_for_a_column_nobody_set(self):
        # `project_type_id` is nullable. A real UNTYPED project holds NULL there,
        # and production code branches on exactly this (taxonomy_alias, the
        # serial allocator, uq_project_taxonomy_active's NULLS NOT DISTINCT).
        # This example used to be `product_id`; BE-9437 made that column NOT NULL
        # -- a project belongs to a product -- so it moved to the NOT NULL side of
        # this module and could no longer demonstrate the nullable case.
        assert make_project().project_type_id is None

    def test_a_column_added_later_needs_no_edit_here(self):
        # Every nullable column the factory does not name reads None. This is the
        # property that makes the convention survive the NEXT column, and it is
        # asserted over the model's own column list rather than a hand-written one,
        # so it keeps covering columns that do not exist yet.
        named = {"id", "tenant_key", "product_id", "name", "alias", "description", "mission", "status"}
        project = make_project()
        for column in Project.__table__.columns:
            if column.name in named or not column.nullable:
                continue
            assert getattr(project, column.name) is None, (
                f"Project.{column.name} is nullable and unset, so it must read None. "
                f"A truthy value here is the INF-9399 defect."
            )

    def test_a_spec_would_not_have_saved_us(self):
        # THE CONTRAST THAT JUSTIFIES THE WHOLE MODULE. A spec constrains which
        # attributes exist, not what they answer: a declarative model declares its
        # columns as CLASS attributes, so a spec'd mock auto-vivifies each one as a
        # truthy child mock. Both of these are the defect, not the fix.
        assert MagicMock(spec=Project).product_id is not None
        assert bool(create_autospec(Project, instance=True).product_id) is True


class TestDriftIsLoud:
    def test_a_typo_raises_at_construction(self):
        with pytest.raises(TypeError, match="prodcut_id"):
            make_project(prodcut_id=None)

    def test_a_column_the_model_does_not_have_raises_when_read(self):
        with pytest.raises(AttributeError):
            _ = make_project().column_that_does_not_exist

    def test_a_mock_stays_silent_for_both(self):
        # The same two drift directions, on the stand-in style being replaced.
        mock = MagicMock(prodcut_id=None)  # accepted, no error
        assert mock.column_that_does_not_exist is not None


class TestTheFactorySuppliesWhatTheDatabaseWould:
    """SQLAlchemy applies ``default=`` at FLUSH, so a bare transient instance is
    not a drop-in truth either. Closing that gap is why these are factories and
    not a bare constructor call."""

    def test_a_bare_instance_is_missing_its_flush_time_defaults(self):
        bare = Project()
        assert bare.id is None
        assert bare.alias is None
        assert bare.status is None

    def test_the_factory_supplies_them(self):
        project = make_project()
        assert project.id
        assert project.alias
        assert project.status is ProjectStatus.ACTIVE

    def test_not_null_columns_are_populated_for_every_factory(self):
        for made in (
            make_project(),
            make_product(),
            make_agent_template(),
            make_agent_execution(),
            make_product_memory_entry(),
            make_vision_document(),
        ):
            for column in made.__table__.columns:
                if column.nullable or column.name in {"created_at", "updated_at"}:
                    continue
                assert getattr(made, column.name) is not None, (
                    f"{type(made).__name__}.{column.name} is NOT NULL, so a real row "
                    f"always has a value and the factory must supply one."
                )

    def test_overrides_win_over_the_defaults(self):
        assert make_agent_template(name="reviewer").name == "reviewer"
        assert make_project(status=ProjectStatus.COMPLETED).status is ProjectStatus.COMPLETED


class TestStrictResultAnswersOnlyWhatItWasTold:
    def test_it_serves_what_it_was_given(self):
        template = make_agent_template()
        result = strict_result(scalars_all=[template], first=None)
        assert result.scalars().all() == [template]
        assert result.first() is None

    def test_an_unanticipated_query_is_loud_and_names_itself(self):
        result = strict_result(scalars_all=[])
        with pytest.raises(AssertionError) as exc:
            result.scalar_one_or_none()
        message = str(exc.value)
        # The message has to carry the accessor asked for and the way out, because
        # this fires on someone who has just added a query and does not yet know
        # why their unrelated-looking test went red.
        assert "scalar_one_or_none" in message
        assert "model_factories" in message

    def test_told_none_is_a_real_answer_and_not_confused_with_untold(self):
        result = strict_result(first=None)
        assert result.first() is None
        with pytest.raises(AssertionError):
            result.fetchall()

    def test_a_bare_mock_answers_the_unanticipated_query_instead(self):
        # The behaviour being replaced: one fake silently services a query the
        # test author never considered, and the suite stays green.
        assert MagicMock().scalar_one_or_none() is not None

    def test_iteration_is_served_by_all(self):
        row = object()
        assert list(strict_result(all=[row])) == [row]

    def test_iteration_without_an_answer_says_it_was_iterated(self):
        # A bare mock iterates as empty by default, which reads like a deliberate
        # "no rows" and is really "nobody decided" -- that is precisely what made
        # the 0813 site claim a product's junction was populated but all-disabled.
        with pytest.raises(AssertionError, match="ITERATED"):
            list(strict_result(first=None))
        assert list(MagicMock()) == []  # the silent behaviour being replaced


class TestTheFactoriesAreCheap:
    def test_they_build_plain_objects_with_no_session(self):
        # No DB, no session, no I/O -- these are safe in a unit test.
        assert isinstance(make_project(), Project)
        assert isinstance(make_agent_template(), AgentTemplate)
