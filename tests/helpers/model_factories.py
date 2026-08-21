# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Stand-ins for ORM models and query results that drift LOUDLY (INF-9399).

THE RULE, in one line: **do not build a mock to stand in for an ORM row.**
Build a real transient model instance with a factory from this module. For a
query result, use :func:`strict_result`, which answers only what you told it.

Edition Scope: Both (test-only helper).

Why this module exists
----------------------
A bare ``MagicMock()`` answers *any* attribute with another truthy mock, so it
diverges from the model it is impersonating the moment that model changes --
and it never says so. Four separate lanes paid for this in the 2026-08-09
sprint alone, when ``Project.product_id`` was added and production code began
branching on it::

    if project.product_id:          # a real product-less row: None -> skipped
        ...extra product-scoped query...

Every affected test meant "a project with no product". A real row answers
``None``. Their mocks answered a truthy child mock, so the extra query ran --
which in the two call-order-dispatched suites shifted every subsequent query
index by one, and in the two one-``execute()``-answers-everything suites made
the fake claim a product existed and then that nothing was enabled, yielding
zero templates. Each site was repaired by hand-pinning the new attribute.
Hand-pinning does not survive the *next* column.

SPEC'ING IS NOT THE FIX. This is the part that surprises people, and it is why
this module exists instead of a one-line "use create_autospec" rule::

    # after `product_id` is added to the model -- no test edited:
    MagicMock()                        -> truthy child mock   WRONG, silently
    MagicMock(spec=Project)            -> truthy child mock   WRONG, silently
    create_autospec(Project)           -> truthy child mock   WRONG, silently
    Project()                          -> None                correct

A spec constrains *which* attributes exist, not what they answer. Because a
declarative model declares its columns as CLASS attributes, a spec'd mock
happily auto-vivifies each new column as a truthy child mock. 360 memory
sequence 550 (BE-6130b) recorded this same trap; it stayed a discovery rather
than a convention, and the sprint paid for it again.

Spec'ing still beats bare for the *other* drift directions -- a removed or
renamed column raises ``AttributeError`` on a spec'd mock and is answered
silently by a bare one -- so ``create_autospec`` keeps its existing job for
behavioural collaborators (services, ``ToolAccessor``, sessions), where there
is no cheap real object and signature fidelity is the point. See
``tests/helpers/mcp_dispatch.py``. It is simply not the tool for a data row.

Worked before / after
---------------------
Before -- the shape the sprint had to repair by hand::

    project = MagicMock()
    project.id = PROJECT_ID
    project.name = "Test Project"
    project.status = ProjectStatus("active")
    project.tenant_key = TENANT_KEY
    project.execution_mode = "multi_terminal"
    project.staging_status = None
    project.updated_at = None
    project.product_id = None       # <- added 2026-08-09, by hand, after a red

After -- the same test, and the pin is gone because it is now implied::

    project = make_project(
        id=PROJECT_ID,
        name="Test Project",
        status=ProjectStatus("active"),
        tenant_key=TENANT_KEY,
        execution_mode="multi_terminal",
    )

``product_id`` reads ``None`` because nobody set it, which is what an unset
nullable column *is*. The next nullable column added to ``Project`` arrives
correctly shaped in every test using this factory, with no edit -- and a column
that is removed or renamed raises ``AttributeError`` where it is read, while a
typo'd field name raises ``TypeError`` at construction instead of quietly
creating an attribute nothing will ever read.

The one thing to know about transient instances
-----------------------------------------------
SQLAlchemy applies ``default=`` at FLUSH, not at construction, so a bare
``Project()`` has ``id=None``, ``alias=None`` and ``status=None`` -- unlike a
real row. That is exactly the gap these factories close: they supply the values
the database would have supplied, in one place, so callers do not each guess.
NULLABLE columns are deliberately left unset, because there the transient
instance and the real row usually agree on ``None``.

USUALLY, not always -- INF-9417 measured the exception. A nullable column that
carries a ``server_default`` reads that default on a real row and ``None`` here,
so the two do NOT agree: ``ProductMemoryEntry.tags`` is ``[]`` in the database
and ``None`` on a bare instance. Those columns are named in the per-model
``defaults`` below wherever a factory covers them, exactly as the NOT NULL
server-default columns are. ``_build`` does not derive them automatically on
purpose: doing so would change what the existing factories answer for already
-shipped columns (``Project.early_termination`` among them), which is a
behaviour change to tested code and needs its own reproduced failure first.

These are plain objects. No session, no DB, no I/O. A test that needs a
persisted row should use a real session (``TransactionalTestContext`` in
``tests/helpers/test_db_helper.py``), not this module.
"""

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

# Recognisable in a failure message, and obviously not production data.
TEST_TENANT_KEY = "tk_factory_test"


def _build(model: type, defaults: dict[str, Any], overrides: dict[str, Any]) -> Any:
    """Construct ``model`` with the values a real row would carry.

    Fills any NOT NULL column still unset from the column's OWN declared Python
    default -- so a NOT NULL column added to a model later is picked up here
    without editing this file, which is the same self-maintaining property the
    factories give their callers. Columns whose only default lives in the
    database (``server_default`` with no Python default) cannot be derived and
    must be named in the per-model ``defaults`` below;
    ``test_inf9399_model_factory_shape.py`` fails if one is ever missed.

    NULLABLE columns are deliberately left alone: there the transient instance
    and a real row already agree on ``None``.
    """
    values = {**defaults, **overrides}
    for column in model.__table__.columns:
        if column.nullable or column.name in values:
            continue
        default = column.default
        if default is None or not hasattr(default, "arg"):
            continue
        # SQLAlchemy wraps a callable default so it takes an execution context,
        # even when the underlying function takes none -- `generate_uuid()` alone
        # raises "missing 1 required positional argument: 'ctx'". Passing None is
        # how you invoke it outside a flush.
        values[column.name] = default.arg(None) if default.is_callable else default.arg
    return model(**values)


def make_project(**overrides: Any) -> Project:
    """A transient :class:`Project` shaped like a real row.

    Supplies the primary key, ``tenant_key``, the NOT NULL columns and the
    flush-time defaults (``alias``, ``status``) that a bare ``Project()`` would
    leave as ``None``. Every NULLABLE column is left unset on purpose, so it
    reads ``None`` exactly as an unset column does in the database.

    ``overrides`` go straight to the declarative constructor, so a field name
    that is not a column raises ``TypeError`` here rather than silently
    becoming an attribute the code under test will never read.

    BE-9437 made ``product_id`` NOT NULL, so it joins the named columns above --
    with the caveat every NOT NULL **foreign key** in this module carries, and
    which ``make_product_memory_entry`` and ``make_vision_document`` already live
    with: the placeholder makes the TRANSIENT instance truthful, and nothing more.
    A test that FLUSHES a project must override it with a real ``products.id``,
    because no string this module can invent will satisfy the FK.
    """
    defaults: dict[str, Any] = {
        "tenant_key": TEST_TENANT_KEY,
        # NOT NULL since BE-9437 -- a project belongs to a product. Same
        # placeholder idiom as the other FK-carrying factories here.
        "product_id": "test-product-id",
        "name": "Test Project",
        "description": "Test project description",
        "mission": "Test project mission",
        # Not the column's own default (INACTIVE). A test that says nothing about
        # lifecycle almost always means a live project, and the alternative is
        # every caller repeating it.
        "status": ProjectStatus.ACTIVE,
    }
    return _build(Project, defaults, overrides)


def make_product(**overrides: Any) -> Product:
    """A transient :class:`Product` shaped like a real row. See :func:`make_project`.

    ``target_platforms``, ``product_memory`` and ``vision_analysis_complete`` are
    named explicitly because their only default lives in the database
    (``server_default``), so nothing here can derive them.
    """
    defaults: dict[str, Any] = {
        "tenant_key": TEST_TENANT_KEY,
        "name": "Test Product",
        "target_platforms": [],
        "product_memory": {},
        "vision_analysis_complete": False,
    }
    return _build(Product, defaults, overrides)


def make_agent_execution(**overrides: Any) -> AgentExecution:
    """A transient :class:`AgentExecution` shaped like a real row. See :func:`make_project`.

    ``job_id`` and ``agent_display_name`` are named because they are NOT NULL with
    no default of their own -- a real execution always belongs to a job and always
    has a name to show. ``job_id`` is generated per call rather than fixed, because
    two executions built by one test are two different agents and a shared job id
    would make them look like siblings.

    ``id`` and ``agent_id`` are deliberately NOT named: both are NOT NULL carrying
    their own ``generate_uuid`` default, which :func:`_build` applies, so every
    execution arrives with a distinct identity and no caller has to invent one.
    """
    defaults: dict[str, Any] = {
        "tenant_key": TEST_TENANT_KEY,
        "job_id": generate_uuid(),
        "agent_display_name": "test-agent",
    }
    return _build(AgentExecution, defaults, overrides)


def make_agent_template(**overrides: Any) -> AgentTemplate:
    """A transient :class:`AgentTemplate` shaped like a real row. See :func:`make_project`."""
    defaults: dict[str, Any] = {
        "tenant_key": TEST_TENANT_KEY,
        "name": "test-agent",
        # The column's own default is the empty string, which no real seeded
        # template carries and which silently satisfies "has instructions" checks.
        "system_instructions": "Test system instructions",
    }
    return _build(AgentTemplate, defaults, overrides)


def make_product_memory_entry(**overrides: Any) -> ProductMemoryEntry:
    """A transient :class:`ProductMemoryEntry` shaped like a real row. See :func:`make_project`.

    The six NOT NULL columns with no default of their own are named, as usual. So
    are the NINE columns that are NULLABLE but carry a ``server_default`` --
    ``key_outcomes`` through ``deleted_by_user`` -- and that pairing is the reason
    this docstring is longer than its siblings.

    A nullable column normally needs no help: the transient instance and the real
    row agree on ``None``. **A nullable column with a server_default does not.** A
    real row reads ``[]`` / ``{}`` / ``3`` / ``0.5`` / ``False``; the transient
    instance reads ``None``, and code that iterates ``entry.tags`` or compares
    ``entry.priority`` would meet a value production never produces. That is the
    INF-9399 defect from the other side -- not a truthy mock where ``None`` belongs,
    but ``None`` where a real value belongs -- so these are supplied here for the
    same reason ``make_product`` names its three.
    """
    defaults: dict[str, Any] = {
        "tenant_key": TEST_TENANT_KEY,
        "product_id": "test-product-id",
        "sequence": 1,
        "entry_type": "project_closeout",
        "source": "closeout_v1",
        "timestamp": datetime.now(UTC),
        # Nullable, but a real row carries the server-side default, not NULL.
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
    """A transient :class:`VisionDocument` shaped like a real row. See :func:`make_project`.

    ``created_at`` is named because it is NOT NULL with only a ``server_default``
    (``func.now()``), which is a SQL clause nothing here can evaluate.

    ``deleted_at`` is deliberately NOT named, and that is the point of using this
    factory rather than a mock: BE-6130b added that column, and a spec'd
    ``VisionDocument`` mock auto-vivifies it to a truthy child -- which makes
    ``vision_hash._active_sorted_docs`` drop the document from the aggregate and
    yields the empty-output failure the fixtures used to hand-pin against. An
    unset nullable column reads ``None`` here, so the pin is not needed.
    """
    defaults: dict[str, Any] = {
        "tenant_key": TEST_TENANT_KEY,
        "product_id": "test-product-id",
        "document_name": "Test Vision",
        "created_at": datetime.now(UTC),
    }
    return _build(VisionDocument, defaults, overrides)


_NOT_TOLD = object()


class _StrictResult:
    """A SQLAlchemy ``Result`` stand-in that answers ONLY what it was told.

    See :func:`strict_result`.
    """

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

    # -- result-level accessors ------------------------------------------
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

    # -- scalars() sub-result --------------------------------------------
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
        # A Result yields rows when iterated, which is the same set `all()`
        # returns -- so `all=` serves both. Reported separately because being
        # told "you were asked for `all`" when you wrote `for row in result:`
        # sends the reader looking for a call that is not there.
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
    """A query-result stand-in that refuses to answer what it was not told.

    A ``MagicMock()`` result answers every accessor of every query with a
    truthy mock, so one fake silently services queries the test never
    considered. That is how the 2026-08-09 sites came to claim a product
    existed and then that nothing was enabled -- neither statement was
    something the test author wrote.

    Pass the accessors this result should serve; anything else raises with a
    message naming what was asked. A newly added query then fails loudly at the
    moment it appears, instead of being handed a plausible-looking lie::

        result = strict_result(scalars_all=[template], first=None)
        session.execute = AsyncMock(return_value=result)

    Accessors: ``first``, ``scalar_one_or_none``, ``scalar_one``, ``scalar``,
    ``fetchall``, ``all``, and the ``scalars_``-prefixed forms (``scalars_all``,
    ``scalars_first``, ``scalars_one_or_none``) for ``.scalars()``.

    Answering ``None`` is a real answer and is honoured; only accessors you did
    not mention at all raise.
    """
    return _StrictResult(label, answers)
