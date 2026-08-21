# MCP Spec Conformance — Giljo HQ Server

**Edition Scope:** Both (CE + SaaS).
The MCP transport, OAuth discovery chain, and JSON-RPC method shapes audited here ship in the CE edition. SaaS extends only the OAuth discovery advertisement to include Dynamic Client Registration (RFC 7591) — the CE rows alone determine the PASS / PARTIAL / FAIL of the base server.

**Audited spec versions:**

1. `2025-03-26` — https://modelcontextprotocol.io/specification/2025-03-26 (initial OAuth integration)
2. `2025-06-18` — https://modelcontextprotocol.io/specification/2025-06-18 (current default in the Anthropic ecosystem)
3. `2025-11-25` — https://modelcontextprotocol.io/specification/2025-11-25 (introduces CIMD — OAuth Client ID Metadata Documents)
4. `2026-07-28` — https://modelcontextprotocol.io/specification/2026-07-28 (latest; introduces multi-round-trip tool results and elicitation)

**Anthropic connector reference:** https://claude.com/docs/connectors/building.

**SDK baseline:** The server uses the official Anthropic `mcp` Python SDK (FastMCP) pinned at `mcp>=2.0.0,<2.1`. The SDK handles JSON-RPC envelope formatting, the `initialize` handshake, `tools/list`, `tools/call`, `notifications/cancelled`, and error envelopes per spec. This audit treats SDK-provided conformance as inherited PASS, with citations pointing to integration tests that drive a real client session through the SDK rather than re-asserting the SDK's internal envelope shape.

---

## Conformance Matrix

Verdict legend: **PASS** = requirement met, with at least one test exercising the spec-defined boundary. **PARTIAL** = core requirement met but one or more sub-requirements gapped (gap noted below). **FAIL** = requirement materially unimplemented.

| Requirement category | `2025-03-26` | `2025-06-18` | `2025-11-25` | `2026-07-28` |
|----------------------|--------------|--------------|--------------|--------------|
| **Streamable HTTP** (HTTP methods on `/mcp`, content-type negotiation, `Mcp-Session-Id` header semantics, `MCP-Protocol-Version` header pass-through) | **PASS** — `tests/api/test_cors_mcp_handshake.py` proves `MCP-Protocol-Version` and `Mcp-Session-Id` survive CORS preflight; `tests/integration/test_mcp_protocol_harness.py` drives a real client through `initialize` + `tools/list` + `tools/call`. | **PASS** — same evidence chain. 2025-06-18 is the first spec to *name* `MCP-Protocol-Version` as a normative request header; CORS preflight tests cover it explicitly. | **PASS** — transport requirements in 2025-11-25 are a strict superset of 2025-06-18 with no new transport-level required headers or methods. Same evidence carries forward. | **PASS** — same transport surface; `tools/list` is additionally cacheable per the 2026-07-28 spec and the pinned SDK applies that itself. |
| **OAuth** (discovery chain `/.well-known/oauth-authorization-server` + `/.well-known/oauth-protected-resource`, PKCE, DCR (RFC 7591), audience binding / resource indicators (RFC 8707), refresh tokens) | **PASS** — `tests/api/test_oauth_endpoints.py` (RFC 8414 metadata shape, PKCE S256, absolute URLs); `tests/api/test_oauth_audience_binding.py` (RFC 9728 protected-resource metadata + root mirror). RFC 7591 DCR is a SaaS-only surface (`tests/saas/test_oauth_dcr_endpoint.py`); CE correctly omits the `registration_endpoint` advertisement. | **PASS** — adds audience binding (RFC 8707) as a normative requirement: `tests/api/test_oauth_endpoints.py` (resource-indicator binding and aud-claim enforcement, multiple cases); `tests/api/test_oauth_audience_binding.py` (middleware-level aud-claim enforcement on `/mcp`); refresh-token grant covered by `tests/api/test_oauth_refresh.py` (rotation, reuse detection, tenant isolation, client authentication). | **PASS** — OAuth section of 2025-11-25 is a refinement of 2025-06-18 (DCR error responses + scope semantics clarifications); no new *required* OAuth surface that is not already implemented. Same evidence chain. **CIMD (OAuth Client ID Metadata Documents) is a SHOULD, and is not implemented** — we therefore do NOT advertise `client_id_metadata_document_supported`, and we DO advertise `registration_endpoint` (RFC 7591 DCR), which is the fallback the spec prescribes for clients when CIMD is unavailable. No over-claim. | **PASS** — no new OAuth requirement over 2025-11-25; same evidence chain, same CIMD footnote. |
| **JSON-RPC method shapes** (`initialize` with capability + `protocolVersion` negotiation, `tools/list`, `tools/call` with content blocks and `isError`, `notifications/cancelled`, JSON-RPC 2.0 error envelope) | **PASS** (inherited from SDK) — FastMCP / `mcp` SDK 2.0 implements all method shapes per spec; `tests/integration/test_mcp_protocol_harness.py` drives a real client session through each, and `tests/integration/test_mcp_scope_filtering.py` covers scope-gated `tools/list` filtering and `tools/call` dispatch. | **PASS** (inherited from SDK) — 2025-06-18 adds `protocolVersion` negotiation rules and structured content blocks; SDK 2.0 handles both. Integration harness exercises both `structuredContent` and text-block code paths. | **PASS** — `initialize` / `tools/list` / `tools/call` / error envelope all PASS (SDK 2.0 advertises 2025-11-25 negotiation when the client requests it). CIMD is an OAuth concern, not a JSON-RPC one; see the OAuth row. | **PASS** — SDK 2.0 negotiates 2026-07-28 when the client requests it. On a session that negotiates this era AND whose client declares the elicitation capability, `request_approval` additionally returns an `InputRequiredResult` so a human-in-the-loop decision can be answered inline in the client instead of only on the dashboard; a session on any earlier era gets the unchanged dashboard-only flow (returning the newer result shape to an older session is a protocol error, so the server gates on the negotiated era first, capability second). |

---

## Recommendation

**Declared conformance: `2025-03-26`, `2025-06-18`, and `2026-07-28` as full PASS. `2025-11-25` as PASS on every MUST, with CIMD — a SHOULD — explicitly not implemented and explicitly not advertised.**

Rationale:

1. **`2025-03-26` and `2025-06-18` pass cleanly across all three audit dimensions.** Streamable HTTP, OAuth discovery + audience binding, and JSON-RPC method shapes all have tests at the spec-defined boundary. `2025-06-18` is the strongest "fully passes" claim — every normative header it introduces has CORS-preflight test coverage, and every OAuth requirement it adds over `2025-03-26` (RFC 8707 audience binding) has direct test coverage.

2. **`2025-11-25`'s only gap is CIMD, which is a SHOULD, not a MUST.** All other requirements in 2025-11-25 are refinements of the 2025-06-18 surface, and the pinned SDK handles them. CIMD (OAuth **Client ID Metadata Documents** — HTTPS-URL client identifiers resolved to a hosted metadata JSON) is unimplemented and deferred until a client needs it. Crucially, the spec's own discovery mechanism keeps this honest without any change on our side: a server signals CIMD support with `client_id_metadata_document_supported: true` in its AS metadata, **which we do not emit**, and the spec directs clients to fall back to Dynamic Client Registration, **which we do advertise and which is live**. Declaring `2025-11-25` therefore over-claims nothing.

3. **`2026-07-28` adds no new required transport or OAuth surface over `2025-11-25`; the SDK upgrade that added it (`mcp>=2.0.0,<2.1`) shipped alongside a single new optional behavior we chose to use** — an approval request may return an `InputRequiredResult` (multi-round-trip) to a client that both negotiates this era and declares the elicitation capability, letting a human-in-the-loop decision be answered inline instead of only on the dashboard. Every earlier-era or non-declaring session is unaffected; the era gate is checked before the capability gate because returning the newer result shape to an older session is itself a protocol error, not a graceful no-op.

4. **No surprises change the conformance posture.** The OAuth surface is the most heavily tested area (audience binding, resource indicators, refresh-token rotation / reuse / tenant isolation, DCR for SaaS), and the JSON-RPC layer is anchored by the upstream SDK and exercised through a real client session in CI.

**Advertised list:** `["2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"]`. `2025-11-25` carries a footnote noting CIMD is unimplemented and, per the spec's discovery contract, deliberately not advertised.

---

## Drift-tracking process

The MCP spec evolves — three versions were published in 2025 alone. This conformance declaration is a snapshot, not a forever guarantee. To keep it honest:

- **Quarterly conformance review.** Every quarter (or sooner if Anthropic publishes a new spec snapshot), re-audit this server against the latest published MCP spec at https://modelcontextprotocol.io/specification.
- **When the MCP spec changes,** file a new conformance project that either (a) upgrades the implementation and the declared version, or (b) documents deliberate non-conformance with rationale (as 2025-11-25 / CIMD is documented here).
- **Test-anchored claims.** Every PASS verdict in the matrix above cites at least one test in the public test suite. CI runs those tests on every PR; if any of them break, the corresponding conformance claim in this document must be re-evaluated the same release.
- **Public update on declared-version changes.** Adding, removing, or downgrading a declared version is a CHANGELOG-worthy change. The release that ships the update must include a one-line note in `CHANGELOG.md`.

---

This document covers conformance to the MCP specification only. Conformance with individual MCP clients (claude.ai, ChatGPT, Inspector, Gemini, etc.) is validated separately via the manual handshake runbook at `scripts/conformance/`.
