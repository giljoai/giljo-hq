# Live black-box E2E suite (`tests/e2e_live/`)

Black-box checks that hit a **deployed** Giljo HQ host through its real edge
(TLS termination, reverse proxy, ASGI app) and assert the standard public
contracts. This is the value localhost can't reproduce: it exercises the actual
HTTPS path, proxy header forwarding, and routing — not an in-process TestClient.

**Edition Scope: Both.** Every assertion targets a contract that holds in CE and
SaaS alike (TLS, `/health`, RFC 9728 OAuth metadata, OWASP security headers,
WebSocket upgrade). Only the *target host* differs.

## Gating — this suite is OFF by default

It is **skipped entirely** unless you opt in with an env flag, because it makes
real network calls:

| Env var | Required | Meaning |
|---|---|---|
| `GILJO_E2E_LIVE` | yes — set to `1` | Master switch. Unset/anything-else ⇒ the whole suite is collected but **skipped**, with zero network calls. |
| `GILJO_E2E_BASE_URL` | yes (when live) | Target base URL, e.g. `https://example.com`. **No default is committed** — operator topology never lives in the repo. If unset while live, every test skips cleanly. |
| `GILJO_E2E_TIMEOUT` | no (default `15`) | Per-call network timeout, seconds. |

With `GILJO_E2E_LIVE` unset, `pytest tests/e2e_live/` collects clean and reports
all tests as `SKIPPED` — safe to run anywhere, including CI, with no live host.

## Running it (against a host you operate)

```bash
GILJO_E2E_LIVE=1 GILJO_E2E_BASE_URL=https://your-host.example \
  ./.venv/Scripts/python.exe -m pytest tests/e2e_live/ -v
```

(On Linux use the platform venv path, e.g. `.venv/bin/python`.)

## What each test checks

| File | Contract |
|---|---|
| `test_tls.py` | TLS reachable; certificate chain + hostname valid; not expired. |
| `test_health.py` | `GET /health` → 200 with `{status, checks}` shape. |
| `test_oauth_metadata.py` | `GET /.well-known/oauth-protected-resource` → RFC 9728 JSON document with the advertised fields (not the SPA fallback). |
| `test_security_headers.py` | OWASP headers present (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, CSP, `Permissions-Policy`); HSTS on https. |
| `test_websocket.py` | `/ws/{client_id}` upgrade handshake is honored through the proxy (101, or a 401/403 auth-rejection — both prove the route + Upgrade forwarding). |

Each test is independent and individually skippable; all are read-only /
unauthenticated and need no test database.

## Notes

- Tests are sync (no event loop) and use only `httpx` (already a dependency) plus
  the stdlib (`ssl`, `socket`) — no new packages, no live credentials.
- The WebSocket test expects an unauthenticated handshake to be **rejected**
  (401/403) on a configured host — that is correct behavior and still proves the
  route + proxy path. A 404 or 5xx is a genuine failure.
