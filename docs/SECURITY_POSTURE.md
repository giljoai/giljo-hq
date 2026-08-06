# Giljo HQ — Security Posture

*Last updated: 2026-07-01*

This document is a plain-English summary of Giljo HQ's (a GiljoAI product) security posture,
written for non-engineers — product, sales, customer security reviewers, and
anyone who needs to understand what the server does and does not do with your
content. Engineering detail — including the grep-evidence audit (SEC-0002)
backing every claim below — lives in
[`docs/ARCHITECTURE.md`](ARCHITECTURE.md#trust-model--security-posture).

## The claim

Giljo HQ is a **passive coordination server**. AI reasoning happens on the
user's own machine with the user's own API keys; the GiljoAI server never runs
LLM inference, never executes user content as code, and never initiates
outbound calls carrying user content. A prompt-injection attack embedded in
user content therefore degenerates to a user-local attack — the attacker
attacks their own machine. There is no AI-specific server-side attack surface
to pivot from.

This property is formally audited and grep-verified as of 2026-04-23.

## What this means for you

- **Your code and prompts never leave your machine for AI processing.** Your
  AI coding tool (Claude Code, Codex CLI, Gemini CLI, or any MCP-compatible
  client) runs on your workstation, using your own API key. The GiljoAI
  server receives only structured tool calls and structured results — never
  raw prompts, never raw completions, never embeddings.
- **You pay for your own tokens, directly to your LLM provider.** There is
  no GiljoAI middleman marking up inference. There are no surprise LLM costs
  on your GiljoAI bill, because GiljoAI does not call an LLM on your behalf
  at all.
- **A prompt-injection attack is limited to the attacker's own machine.** If
  a malicious instruction is planted inside a document you upload or a
  description you write, it is read by your own local agent — not by ours.
  The blast radius is your local session, billed to your own API key,
  bounded by your own machine's permissions.
- **Your tenant is isolated from every other tenant at the database and
  routing layer.** Every read and every write filters by tenant key. A
  compromised agent authenticated as you cannot read, write, or leak any
  other tenant's data. This is enforced in code and covered by a regression
  test suite.
- **Single-IP spam is rate-limited.** A misbehaving client from one IP is
  capped at 300 requests per minute (per-IP, per-process). Per-tenant and
  per-org rate quotas are a feature of the hosted (SaaS) edition; the
  self-hosted (CE) edition relies on this per-IP limiter plus any edge
  (reverse-proxy / CDN) controls you put in front of it. Distributed
  (many-IP) abuse is an explicit roadmap item, not a silent gap.

## What the server does do

- Stores your project, product, and agent state in PostgreSQL, tenant-scoped.
- Serves that state back to your MCP client and your dashboard browser.
- Routes real-time events to your browser via PostgreSQL NOTIFY/LISTEN +
  WebSocket.
- Sends transactional email for registration and password reset.
- Polls GitHub on a timer for release metadata (hardcoded `api.github.com`
  URL; no user content ever enters the request).

## What the server does NOT do

- Run any LLM. No Anthropic, OpenAI, Google, Cohere, Mistral, Replicate,
  Together, or Gemini SDK is installed, imported, or loaded.
- Execute your content as code. No `eval`, no `exec`, no shell, no
  deserialization of untrusted input, no templating of user-authored text.
- Initiate any outbound HTTP request with your content in the URL, query,
  body, or headers.
- Forward your content to any third-party AI provider, analytics platform,
  or telemetry sink.
- Scan, sandbox, or filter your local agent — that's your machine, your
  rules.

## Deliberate non-goals

These are intentionally **not** in scope, and will not silently appear:

- Defending your local machine against your own prompt-injected content.
- Sandboxing your local AI coding tool.
- Scanning uploads for prompt-injection attempts.
- Running LLM inference on your behalf (doing so would invalidate every
  claim above and would trigger a full architectural review and customer
  notification).

## XSS hardening

Every user-controlled string the admin dashboard renders as HTML passes through a
single sanctioned sanitization pipeline (`useSanitizeMarkdown()` /
`sanitizeHtml()`). The underlying DOMPurify configuration is explicit, not
defaulted: an allow-list of tags and attributes, no data URIs, no inline event
handlers, and a restricted URI-scheme allow-list that blocks `javascript:`.
ESLint's `vue/no-v-html` rule is set to `error`, with a narrow per-file override
that sanctions only the four audited render sites; every `v-html` line carries
its own justification comment. The result is that introducing a new raw-HTML
sink is a deliberate, reviewed act — not an accidental one.

The operator ops panel is Flask + Jinja2 and relies on Jinja2's default
auto-escape for all tenant-sourced content; a grep sanity check of
`| safe`, `Markup(`, and `autoescape false` returned zero tenant-controlled
findings as of 2026-04-24.

## See also

- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#trust-model--security-posture)
  — the engineering-depth Trust Model section with the Server
  DOES / DOES NOT lists, rate-limit threat model, and blast-radius
  implications.
- [`docs/security/SEC-0001_upload_guardrails.md`](security/SEC-0001_upload_guardrails.md)
  — defence-in-depth reference for the vision-document upload boundary
  (TXT/MD allowlist, 5 MB cap, filename sanitizer, strict UTF-8, error
  contract).
- [`docs/architecture/tenant_scoping_rules.md`](architecture/tenant_scoping_rules.md)
  — the tenant-isolation rules that keep a compromised client inside its
  own tenant.
