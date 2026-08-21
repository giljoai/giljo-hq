# Giljo HQ: Architecture

*Last updated: 2026-08-20*

This document describes the technical architecture of Giljo HQ, a GiljoAI product, for developers
working on or integrating with the platform.

---

## Tech Stack

| Layer | Technology | Version |
|---|---|---|
| API server | FastAPI | >= 0.100.0 |
| ASGI runtime | Uvicorn | >= 0.23.0 |
| Data validation | Pydantic | >= 2.0.0 |
| ORM | SQLAlchemy | >= 2.0.0 |
| Migrations | Alembic | >= 1.12.0 |
| Database | PostgreSQL | 16 minimum, 18 recommended |
| Async DB driver | asyncpg | >= 0.29.0 |
| Frontend framework | Vue 3 | >= 3.5.40 |
| UI component library | Vuetify | >= 4.1.5 |
| Frontend build tool | Vite | >= 8.1.5 |
| State management | Pinia | >= 4.0.2 |
| Python runtime | Python | 3.12+ recommended |

---

## System Overview

```
AI Coding Tool (Claude Code / Codex CLI / Gemini CLI)
        |
        | MCP over HTTP/SSE
        v
   FastAPI Server (api/endpoints/mcp_sdk_server.py)
        |
        | Python function calls
        v
   Service Layer (src/giljo_mcp/services/)
        |
        | SQLAlchemy ORM
        v
   PostgreSQL 18
        |
        | NOTIFY/LISTEN
        v
   WebSocket Broker (api/broker/postgres_notify.py)
        |
        | WebSocket
        v
   Vue 3 Frontend (browser)
```

**AI coding tool:** Claude Code, Codex CLI, Gemini CLI, or any MCP-compatible client.
Connects to the MCP endpoint using an API key. Sends tool calls over HTTP/SSE.

**FastAPI server:** Handles all HTTP traffic. Exposes MCP tool endpoints, REST API
routes for the dashboard, WebSocket connections, and authentication endpoints.
Routes are registered in `api/app.py` via `include_router` calls.

**Service layer:** Contains all business logic. Services are called by endpoints and
call repositories for data access. No endpoint writes to the database directly.

**PostgreSQL:** Single source of truth. All tables include a `tenant_key` column.
The database also drives real-time push via `pg_notify`.

**WebSocket broker:** Listens on a PostgreSQL channel using `LISTEN`. When the server
calls `pg_notify`, the broker receives the payload and forwards it to all connected
WebSocket clients in the matching tenant. This keeps the Vue frontend in sync with
agent state changes without polling.

**Vue 3 frontend:** Single-page application served by the FastAPI server. Connects
to the WebSocket endpoint on load. Pinia stores receive WebSocket events and update
reactive state.

---

## Backend Layer

### Endpoints

Source: `api/endpoints/`

Each file in this directory corresponds to a domain area. Examples include:

- `mcp_sdk_server.py`: MCP tool definitions served over HTTP/SSE. All 29 public MCP
  tools are defined here. This is the primary integration point for AI coding tools.
- `projects.py`, `products.py`, `agent_jobs.py`, `messages.py`, `tasks.py`: REST
  endpoints for the dashboard frontend.
- `auth.py`, `auth_pin_recovery.py`, `oauth.py`: Authentication and session management.
- `users.py`, `user_settings.py`, `settings.py`: User and configuration management.
- `configuration.py`, `system_prompts.py`, `templates.py`: Context configuration.
- `statistics.py`: Usage and performance metrics.

SaaS-only endpoints live in `api/saas_endpoints/` and are never imported by CE code.

Middleware is registered in `api/app.py` in this order (outermost to innermost):
CORS, security headers, input validation, API metrics, rate limiting, auth, CSRF.

### Services

Source: `src/giljo_mcp/services/`

Services contain all business logic. Each service class takes a database session
(or session factory) as a dependency. Services raise exceptions on error; they never
return error dicts. Key services include:

- `project_lifecycle_service.py`: Project state transitions (staging, active,
  inactive, cancelled, closeout).
- `orchestration_service.py`, `mission_orchestration_service.py`: Agent coordination.
- `product_service.py`, `product_lifecycle_service.py`: Product CRUD and activation.
- `message_service.py`, `message_routing_service.py`: Message storage and routing.
- `task_service.py`: Task CRUD and status tracking.
- `auth_service.py`, `user_auth_service.py`: Authentication and credential management.
- `settings_service.py`, `config_service.py`: System and user configuration.
- `job_lifecycle_service.py`, `agent_job_manager.py`: Agent job state management.
- `project_closeout_service.py`, `project_summary_service.py`: Closeout and memory.

### Repositories

Source: `src/giljo_mcp/repositories/`

Repositories handle all direct database queries. Services call repositories; endpoints
do not call repositories directly. Every repository query filters by `tenant_key`.

- `agent_job_repository.py`: Agent job and execution records.
- `message_repository.py`: Project messages and conversation history.
- `context_repository.py`: Context assembly for prompt generation.
- `statistics_repository.py`, `job_statistics_repository.py`: Usage metrics.
- `vision_document_repository.py`: Vision document storage.
- `configuration_repository.py`: System and product configuration.
- `base.py`: Shared base repository with common query helpers.

### Models

Source: `src/giljo_mcp/models/`

SQLAlchemy ORM models using `DeclarativeBase`. Every table that stores user data
includes a `tenant_key` column with a database index. Multi-tenant isolation is
enforced at the model level via column constraints and at the service level via
mandatory filter arguments.

Key model files:

- `auth.py`: `User`, `APIKey`, `MCPSession`. Users have a `role` field with values
  `admin`, `developer`, or `viewer`.
- `products.py`: `Product`, `ProductTechStack`, `ProductArchitecture`,
  `ProductTestConfig`, `VisionDocument`.
- `projects.py`: `Project`, `ProjectType`.
- `agent_identity.py`: `AgentJob`, `AgentExecution`, `AgentTodoItem`.
- `tasks.py`: `Task`.
- `organizations.py`: Organization and membership (used in both CE and SaaS).
- `config.py`, `settings.py`, `templates.py`, `context.py`: Supporting data.

---

## Frontend Layer

### Views

Source: `frontend/src/views/`

Each view corresponds to a top-level page in the application:

- `DashboardView.vue`: Home dashboard with activity summary.
- `ProductsView.vue`, `ProductDetailView.vue`: Product list and detail editor.
- `ProjectsView.vue`, `ProjectLaunchView.vue`: Project board and launch workflow.
- `MessagesView.vue`: Agent message log.
- `TasksView.vue`: Task board.
- `McpIntegration.vue`: MCP connection setup and API key management.
- `SystemSettings.vue`, `UserSettings.vue`, `OrganizationSettings.vue`: Settings pages.
- `Users.vue`: User management (admin only).
- `Login.vue`, `CreateAdminAccount.vue`, `WelcomeView.vue`: Authentication and onboarding. `CreateAdminAccount.vue` is active only when `GILJO_MODE=ce` (CE fresh-install flow).

### Components

Source: `frontend/src/components/`

Reusable UI components. Components are organized by domain. They receive props and
emit events; they do not call APIs directly. API calls go through composables or
Pinia store actions.

### Composables and Stores

Source: `frontend/src/composables/`, `frontend/src/stores/`

Composables encapsulate reusable logic and follow the `use*` naming convention.
Examples:

- `useProjectMessages.js`: Message loading and pagination.
- `useProjectCloseout.js`: Closeout workflow state.
- `useProductActivation.js`: Product activation flow.
- `useWebSocket.js`: WebSocket connection lifecycle.
- `useTaskCrud.js`, `useTaskFilters.js`: Task board operations.
- `useTemplateData.js`: Agent template loading.
- `useStalenessMonitor.js`: Detects when displayed data may be stale.

Pinia stores manage global state:

- `agentJobsStore.js`: Agent job state for the Jobs page.
- `projects.js`: Project list and active project.
- `products.js`: Product list and active product.
- `messages.js`, `projectMessagesStore.js`: Message data.
- `tasks.js`: Task board data.
- `websocket.js`, `websocketEventRouter.js`: WebSocket connection and event routing.
- `notifications.js`: Toast notification queue.
- `user.js`, `orgStore.js`, `settings.js`, `systemStore.js`: Auth and configuration.

---

## Real-Time Communication

GiljoAI uses PostgreSQL `NOTIFY/LISTEN` combined with WebSockets to push updates to
the browser without polling.

**Write path:** When a service modifies state (agent status change, new message,
task update), it calls `pg_notify` with a JSON payload on a named channel.

**Broker:** `api/broker/postgres_notify.py` contains
`PostgresNotifyWebSocketEventBroker`. It holds a persistent asyncpg connection and
issues `LISTEN` on startup. When a notification arrives, the broker extracts the
tenant from the payload and calls `WebSocketManager.broadcast_event_to_tenant`.

**WebSocket manager:** `api/websocket.py` tracks active WebSocket connections keyed
by `client_id`. `broadcast_event_to_tenant` filters to connections belonging to the
target tenant and sends the JSON payload.

**Frontend:** `frontend/src/composables/useWebSocket.js` manages the client
connection. `frontend/src/stores/websocketEventRouter.js` receives events and routes
them to the appropriate Pinia store action.

This design supports multi-worker deployments: any worker can call `pg_notify` and
all connected clients receive the update regardless of which worker they are
connected to.

---

## Authentication

GiljoAI uses two authentication paths depending on the client type.

**Browser sessions:** Login via `POST /api/auth/login`. On success the server sets
an `access_token` httpOnly cookie containing a signed JWT. The browser cannot read
this cookie via JavaScript, which prevents XSS token theft. A separate `csrf_token`
cookie (not httpOnly) is set simultaneously. State-mutating requests must include
the CSRF token value in the `X-CSRF-Token` request header. The server validates that
the header value matches the cookie value (double-submit pattern).

**MCP clients:** AI coding tools authenticate using an API key passed as a query
parameter or Authorization header. API keys are stored hashed in the `api_keys`
table. Each key is scoped to a single user and inherits that user's `tenant_key`.

**Session context:** `MCPSession` records (table: `mcp_sessions`) persist
`tenant_key` and `project_id` across tool calls within a session. This allows the
MCP server to assemble context without the client re-sending project identifiers on
every call.

**Authorization:** Users have a `role` field with three values: `admin`, `developer`,
`viewer`. Admin-only endpoints check the role at the dependency level using FastAPI
dependencies in `api/dependencies.py`.

---

## Multi-Tenant Isolation

Every table that stores user data has a `tenant_key` column of type `VARCHAR(36)`.
Database indexes exist on every `tenant_key` column.

Isolation is enforced at three levels:

1. **Model level:** `tenant_key` has a `NOT NULL` constraint and an index on every
   relevant table.
2. **Repository level:** Every repository query includes a `WHERE tenant_key = ?`
   filter. The base repository in `src/giljo_mcp/repositories/base.py` provides
   shared helpers that enforce this.
3. **Service level:** `TenantManager` (`src/giljo_mcp/tenant.py`) validates and
   resolves tenant context before service operations run.

CE uses `tenant_key` as the isolation unit. SaaS adds Organization-level grouping
on top of this foundation.

For the architecture-level rules that endpoints must follow when handling tenant
data (admin-gate vs. tenant-scope, the role/mode orthogonality invariant, the
property-A/property-B regression discipline), see
[`docs/architecture/tenant_scoping_rules.md`](architecture/tenant_scoping_rules.md).

---

## Trust Model / Security Posture

<a id="trust-model-pitch"></a>

Giljo HQ is a **passive coordination server**. AI reasoning happens on the
user's own machine with the user's own API keys; the GiljoAI server never runs
LLM inference, never executes user content as code, and never initiates
outbound calls carrying user content. A prompt-injection attack embedded in
user content therefore degenerates to a user-local attack — the attacker
attacks their own machine. There is no AI-specific server-side attack surface
to pivot from. This property is formally audited and grep-verified (SEC-0002);
the evidence — the exact grep commands and the CI guard-rail that prevents
regressions — is enumerated in the Passive-Server Property definition below.

For a non-engineer summary of this posture suitable for customer security
reviews, see [`docs/SECURITY_POSTURE.md`](SECURITY_POSTURE.md).

### Passive-Server Property — definition

Three concrete, code-verifiable claims:

1. **No LLM inference server-side.** No import of `anthropic`, `openai`,
   `cohere`, `mistralai`, `replicate`, `together`, `google.generativeai`, or
   `google.genai` anywhere in `src/giljo_mcp/`, `api/`, or `ops_panel/`. No LLM
   API-key environment variables referenced. Vision document summarization is
   performed by the user's AI coding tool (via the `get_vision_doc` MCP tool);
   the server stores results but runs no inference.
   Enforced going forward by a ruff `flake8-tidy-imports.banned-api` gate in
   `pyproject.toml` that blocks any future LLM SDK import as a hard CI failure
   (landed as SEC-0002 Phase 3).
2. **No arbitrary code execution on user content.** Zero `eval()`, `exec()`,
   `pickle.load` on user-reachable paths, `yaml.load` (only `yaml.safe_load`),
   `subprocess(shell=True)`, `os.system`, or `os.popen` invocations in server
   code. Cross-reference: classic web-stack RCE audit SEC-0004 (2026-Q2),
   zero UNSAFE findings.
3. **No outbound HTTP initiated by user content.** Every outbound call in
   audited server code is operator-, admin-, or startup-initiated and hits a
   hardcoded `api.github.com` host. The enumerated sites span three modules:
   - `src/giljo_mcp/services/version_service.py` — GitHub release polling
     (hardcoded constant URL); two call sites in the same module.
   - `src/giljo_mcp/tools/_memory_helpers.py::_fetch_github_commits` — closeout
     commit fetch using admin-configured `product_memory['git_integration']`
     repo owner / name; no end-user-prompt content in URL, query, body, or
     headers.
   - `api/startup/update_checker.py` — 6-hour release-check loop (hardcoded
     constant URL).

### LLM locality

Inference runs on the user's own machine via their MCP-compatible client
(Claude Code, Codex CLI, Gemini CLI, or any other MCP tool). Tokens are paid
from the user's own API key. The server sees only structured tool calls and
their structured results — never raw model prompts, completions, embeddings,
or reasoning traces. "Your code and prompts never leave your machine for AI
processing" is literally true at the code level, not a marketing claim.

### Server DOES / DOES NOT (on user-submitted content)

User-submitted content means prompts, MCP tool arguments, uploaded vision
documents, and user-authored text fields (product descriptions, project
notes, messages).

**The server DOES:**

- Persist user content to PostgreSQL, tenant-scoped via `tenant_key` on every
  insert. No cross-tenant writes.
- Return user content in API responses, tenant-scoped at the repository layer
  and gated by `AuthMiddleware` (`api/app.py:396`).
- Route user content via WebSocket NOTIFY/LISTEN to tenant-subscribed clients
  only. A client receives events only for tenants it is authenticated for.
- Log user content through `log_sanitizer` (redacted/escaped so it cannot
  inject log lines or leak unsanitized into aggregated dashboards).
- Serve user-authored markdown back to the frontend as HTML sanitized via
  DOMPurify.
- Store structured git metadata (commit SHAs and messages) returned by
  GitHub — only when an admin has explicitly configured
  `product_memory['git_integration']` with an access token. The server reads
  from GitHub; it does not write user prompts to GitHub.

**The server does NOT:**

- Run user content through an LLM for summarization, reasoning, embedding, or
  classification. No LLM SDK is installed, imported, or loaded.
- Execute user content as code (no `eval`, no `exec`, no shell, no
  `pickle.load`, no `yaml.load` on user input).
- Initiate outbound HTTP with user content in URL, query, body, or headers.
  All four outbound sites use a hardcoded `api.github.com` host; only
  admin-configured strings or server-generated timestamps cross the wire.
- Execute JavaScript from user content on the server (no Node, no V8, no
  interpreter in the server process).
- Forward user content to any third-party AI provider, analytics service, or
  telemetry sink.
- Spawn subprocesses from user content. The only `subprocess.run` site in
  `api/` is admin-only (`openssl` cert generation), argv-form with hardcoded
  or admin-scoped arguments. The `/root-ca` endpoint serves the configured
  server certificate directly without spawning a subprocess. Agent
  spawning is client-side — the operator's local CLI spawns workers; the
  server returns only prompt templates.
- Write user content to disk as an executable or loadable file. Upload
  handling sanitizes filenames before any disk I/O (SEC-0001).

### Blast-radius implications

- **Prompt injection in user content is a user-local attack.** A malicious
  string inside a user's own product description or vision document is read by
  the user's own local agent. Any consequence lands on the machine running the
  agent, billed to the API key attached to that machine. No server-side
  pivot exists.
- **Compromised client agents still authenticate as their user.** A
  prompt-injected local agent can make authenticated API calls within its own
  tenant. Impact is bounded by tenant isolation and per-IP rate limiting
  (below).
- **Cross-tenant leakage is not reachable from user content.** Every
  repository query filters by `tenant_key`. An agent cannot read another
  tenant's data even if its prompt is hijacked. The architecture-level rules
  that guarantee this invariant are codified in
  [`docs/architecture/tenant_scoping_rules.md`](architecture/tenant_scoping_rules.md)
  (Rules 1–5, shipped SEC-0005a/b/c).

### Rate-limit threat model

Spam from a single compromised client is bounded by per-IP rate limiting:

- **Implementation:** `api/middleware/rate_limiter.py`, class
  `RateLimitMiddleware`. Sliding-window algorithm, 60-second window,
  `defaultdict(deque)` of request timestamps keyed by client IP.
- **Default limit:** 300 requests / minute / client IP, overridable via the
  `API_RATE_LIMIT` environment variable.
- **Registration:** `api/app.py:407`, conditional on
  `DISABLE_RATE_LIMIT != "true"`.
- **IP extraction order:** `X-Forwarded-For` first element → `X-Real-IP` →
  `request.client.host` → literal `"unknown"`. **Deployment constraint:**
  never expose this server without a trusted reverse proxy terminating
  `X-Forwarded-For`; the current `mcp.example.com` deployment sits behind
  Cloudflare Tunnel which sets these headers reliably.
- **Response on limit exceeded:** HTTP 429 with `Retry-After`,
  `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset`
  headers.

**What it DOES cover:** single-IP flood from a compromised or misbehaving
client agent; trivial single-source DoS; rate-limit signalling so
well-behaved clients can self-pace.

**What it does NOT cover:**

- **Distributed attack across many source IPs** — each new IP gets its own
  budget.
- **Per-tenant / per-org write quotas** — not part of the self-hosted (CE)
  edition, where the per-IP limiter above (plus any reverse-proxy / CDN edge
  controls the operator puts in front of it) is the only budget. Per-tenant
  and per-org-API-key rate quotas are a feature of the hosted (SaaS) edition,
  not a general property of the passive server. In every edition a noisy
  compromised client CANNOT affect other tenants' data (tenant isolation
  holds), only its own tenant's write budget.
- **Multi-worker / multi-replica sharing** — storage is per-process, so the
  effective limit across N workers is `N × 300 / min`. Single-process
  deployments are fine; any future scale-up must move the limiter to
  a shared store.
- **Expensive-endpoint weighting** — every endpoint counts equally.

### Cross-tenant rendering in operator views

Super-admin and ops-panel views render user content from multiple tenants
inside a single trusted browser session. This is the only place where
content from tenant A can reach the DOM of operator B. All user-content
rendering paths must route through the shared DOMPurify sanitizer. See
SEC-0003 (admin-view XSS hardening) for the active enforcement.

### Explicit non-goals

- Defending the user's local machine against their own prompt-injected
  content. The user owns their machine.
- Sandboxing the user's local agent. Out of scope; the agent is a
  client-side tool under the user's control.
- Scanning uploaded content for prompt-injection attempts. False-positive
  prone; not aligned with the threat model.
- Running LLM inference on behalf of users. Doing so would invalidate every
  passive-server claim above and require a fresh architectural review.

### Cross-references

- **SEC-0002 passive-server audit** — the grep-evidence backing every claim in
  this section is enumerated inline in the Passive-Server Property definition
  above; the full audit is retained as an internal operator artifact.
- [`docs/architecture/tenant_scoping_rules.md`](architecture/tenant_scoping_rules.md)
  — tenant-isolation invariants (SEC-0005a/b/c).
- SEC-0004 classic web-stack grep audit (2026-Q2) — zero UNSAFE findings on
  `eval`, `exec`, `pickle`, `yaml.load`, `shell=True`, `os.system`,
  `os.popen`.
- SEC-0003 admin-view XSS hardening — DOMPurify routing for cross-tenant
  rendering.

### Consequences for future changes

If any future feature requires the server to call an LLM — server-side
summarization, search embeddings, agent reasoning in CI, anything — it must
be called out explicitly in a handover and must include:

1. A re-evaluation of the blast-radius claims above.
2. An explicit opt-in surface (no implicit server-side LLM calls).
3. A budget and quota mechanism so customers do not inherit surprise LLM
   costs.
4. A refresh of this Trust Model section and
   [`docs/SECURITY_POSTURE.md`](SECURITY_POSTURE.md) to match the new
   reality.

Silent addition of `anthropic`, `openai`, or any LLM SDK import on the server
path is an architectural regression, not a feature. The ruff banned-api gate
will block the import; reviewers will block the PR; this document will block
the concept.

---

## Agent Lifecycle

### Project Phases

A project moves through three phases during its lifetime:

1. **Staging:** The project is queued for activation. The platform generates a
   staging prompt. The user pastes this into their AI coding tool to start the
   orchestrator.
2. **Implementation (active):** The orchestrator and subagents are running. Agent
   jobs update their status in real time. Messages and task updates stream to the
   dashboard.
3. **Closeout:** The orchestrator signals completion. GiljoAI writes a 360 Memory
   entry from the session summary and marks the project closed. The next project
   inherits this accumulated context.

Project statuses (canonical 6, BE-5039): `inactive`, `active`, `completed`, `cancelled`, `terminated`, `deleted`.

### Agent Job Statuses

Each agent execution (`AgentExecution` record) has one of these statuses:

| Status | Meaning |
|---|---|
| `waiting` | Spawned but not yet started |
| `working` | Actively processing a task |
| `blocked` | Waiting on another agent or user input |
| `idle` | Between tasks, ready for work |
| `sleeping` | Paused (rate limit or explicit wait) |
| `complete` | Finished successfully |
| `silent` | No updates received within silence threshold |
| `decommissioned` | Permanently shut down |

The `phase` column on `AgentJob` controls multi-terminal ordering. Jobs in phase 1
run first; jobs with the same phase number run in parallel.

---

## Edition Isolation

GiljoAI ships two editions from one repository:

- **Community Edition (CE):** Standard directories. Public.
- **SaaS Edition:** CE plus code in `saas/`, `saas_endpoints/`, `saas_middleware/`,
  and `frontend/src/saas/`. Private.

CE code never imports from any SaaS directory. SaaS extends CE via EventBus
subscriptions and conditional router registration. If all SaaS directories were
removed, CE must start, serve requests, and pass all tests without modification.

See `docs/EDITION_ISOLATION_GUIDE.md` for the full placement decision tree,
directory rules, and the SaaS extension pattern.
