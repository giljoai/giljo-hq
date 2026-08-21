# tests/helpers

Shared test infrastructure. Two of these you will need often; the rest are
guards that run themselves.

## Reach for these when writing a test

| Helper | Use it when |
|---|---|
| **`model_factories.py`** | You need a stand-in for an ORM row or a query result. **Do not build a mock for either.** `make_project()` / `make_product()` / `make_agent_template()` return real transient instances, and `strict_result(...)` returns a query result that answers only what you told it. |
| **`test_db_helper.py`** | Your test touches the database. `TransactionalTestContext` rolls back at teardown; the suite runs under `pytest-xdist`, so this is not optional. |
| **`mcp_session_fixture.py`** | Your test drives the MCP boundary over the SDK's in-memory transport. Import `create_connected_server_and_client_session` **from here, never from `mcp.shared.memory`** — the SDK removes it in 2.0, and this seam is what keeps that a one-file change. `test_inf9422_mcp_session_seam.py` fails the suite if you bypass it. |
| `mcp_dispatch.py` | You are driving an autospec'd `ToolAccessor` through the MCP boundary and need its service sub-objects wired with real signatures. |
| `bash_resolver.py` | Your test shells out and needs a portable `bash`. |
| `route_surface.py` | You are asserting over the effective API route surface. |
| `banned_prose_tokens.py` | You are checking agent-facing prose for banned tokens. |

## Why `model_factories` exists, in one paragraph

A bare `MagicMock()` answers *any* attribute with another truthy mock, so it
diverges from the model it is impersonating the moment that model changes, and
never says so. Four lanes hit this in the 2026-08-09 sprint when
`Project.product_id` was added: every affected test meant "a project with no
product", a real row answers `None`, and the mocks answered a truthy child mock
that sent the code down a branch nobody intended. **Spec'ing does not fix it** —
a declarative model declares its columns as class attributes, so
`MagicMock(spec=Project)` and `create_autospec(Project)` both auto-vivify each
new column as a truthy child mock, exactly as wrongly as a bare mock. A real
transient instance answers `None`, because that is what an unset column is.

The full reasoning, the worked before/after, and the one caveat worth knowing
(SQLAlchemy applies `default=` at flush, not construction) are in the
`model_factories.py` module docstring. Its claims are pinned by
`test_inf9399_model_factory_shape.py`.

## Guards that live here

`test_be9288_schema_drift_guard.py`, `test_tsk9381_*.py`,
`test_inf9399_model_factory_shape.py`, `test_inf9422_mcp_session_seam.py`.
These are tests, not utilities — you do not import them.
