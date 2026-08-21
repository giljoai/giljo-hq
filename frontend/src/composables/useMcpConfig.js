// eslint-allow giljo-internal/no-manual-api-url-composition
// (sanctioned: returns literal MCP-server URL string for AI-tool config files, not frontend HTTP base — see ADR-001)
/**
 * Shared MCP configuration generation composable (Handover 0855d)
 *
 * The single source of truth for MCP connection commands/JSON. Consumed by the
 * setup wizard's connect step and the /tools connect directory (both via
 * ConnectToolCard.vue). Originally extracted from the standalone configurator
 * modal that FE-9225 retired; the generators outlived it unchanged.
 *
 * Tool ID conventions:
 *   - Setup wizard uses: claude_code, codex_cli, gemini_cli, antigravity_cli
 *   - Legacy modal uses: claude, codex, gemini, generic_mcp, antigravity
 *   - Claude Desktop uses claude_desktop in both (JSON output, distinct from Claude Code CLI).
 *   Both are supported via normalizeToolId().
 */

import { MCP_ALIAS } from '@/branding'

/**
 * Normalize tool IDs between wizard (claude_code) and legacy (claude) formats.
 * `claude_desktop` is preserved as-is (it has no legacy alias and produces JSON,
 * not a CLI command).
 * @param {string} toolId
 * @returns {string} canonical legacy ID (claude, codex, gemini, generic_mcp, antigravity, claude_desktop)
 */
export function normalizeToolId(toolId) {
  const map = {
    claude_code: 'claude',
    codex_cli: 'codex',
    gemini_cli: 'gemini',
    antigravity_cli: 'antigravity',
    // Setup wizard IDs for the two tools added in the connect redesign (FE-9204).
    // `opencode` has no legacy alias (its own generators); `generic` folds into the
    // existing `generic_mcp` legacy id so it reuses generateGenericMcpConfig().
    generic: 'generic_mcp',
  }
  return map[toolId] || toolId
}

/**
 * Detect platform from user agent.
 * @returns {'windows'|'unix'}
 */
export function detectPlatform() {
  if (typeof navigator !== 'undefined' && /win/i.test(navigator.platform)) {
    return 'windows'
  }
  return 'unix'
}

/**
 * Build the server URL that AI coding tools will connect to.
 *
 * Preferred usage (INF-5012): pass `backendConfig` from GET /api/v1/config/frontend
 * so we honor reverse-proxy deployments (Cloudflare Tunnel, nginx) where the
 * public URL has no explicit port.
 *
 * Heuristic:
 *  1. If `backendConfig` is provided and `window.location.hostname === backendConfig.host`,
 *     the browser is already on the correct public host — return `window.location.origin`.
 *     This produces the right scheme + host + (omitted) port for proxied deployments.
 *  2. If `backendConfig` is provided but browser is on a different host (out-of-band
 *     config rendering), compose `protocol://host[:port]`, omitting the port when it is
 *     the implicit default for the protocol (443 for https, 80 for http).
 *  3. Fallback (no backendConfig): legacy behavior — window.location.hostname +
 *     (window.location.port || '7272'). Kept for backward compat with callers that
 *     do not yet pass config.
 *
 * @param {string|object} [hostnameOrConfig]
 *        Legacy: hostname string. New: backendConfig object `{host, port, protocol, ssl_enabled}`.
 * @param {string} [port]  - Legacy port override (ignored when first arg is an object).
 * @returns {string} e.g. "https://mcp.example.com" or "http://localhost:7272"
 */
export function buildServerUrl(hostnameOrConfig, port) {
  // ADR-001 does NOT apply here: this function returns a literal MCP-server URL
  // string for AI-tool config files (e.g. `claude mcp add ...` snippets shown to
  // the user), not the frontend's own HTTP client base. Manual protocol/host/port
  // composition is the correct behavior — the eslint rule
  // `no-manual-api-url-composition` allowlists this file by path.
  // Path 1+2: backendConfig object passed in.
  if (hostnameOrConfig && typeof hostnameOrConfig === 'object') {
    const cfg = hostnameOrConfig
    const protocol = cfg.protocol || (window.location.protocol === 'https:' ? 'https' : 'http')
    const host = cfg.host || window.location.hostname
    const cfgPort = cfg.port

    // Browser is already on the target host — trust window.location.origin.
    // This automatically omits the port for proxy-fronted deployments where the
    // backend's internal port differs from the public-facing port.
    if (host && window.location.hostname === host) {
      return window.location.origin
    }

    // Out-of-band composition: omit implicit default ports.
    const isImplicitHttps = protocol === 'https' && Number(cfgPort) === 443
    const isImplicitHttp = protocol === 'http' && Number(cfgPort) === 80
    if (!cfgPort || isImplicitHttps || isImplicitHttp) {
      return `${protocol}://${host}`
    }
    return `${protocol}://${host}:${cfgPort}`
  }

  // Path 3: legacy string-based signature.
  const h = hostnameOrConfig || window.location.hostname
  const p = port || window.location.port || '7272'
  const protocol = window.location.protocol === 'https:' ? 'https' : 'http'
  return `${protocol}://${h}:${p}`
}

/**
 * True when the backend serves its own TLS (a self-signed / private cert).
 * This is what triggers the cert-trust UI step — Node.js tools need to trust
 * the backend's CA.
 * Cloudflare/nginx-proxied deployments report ssl_enabled=false even though the
 * public URL is https, because their TLS is terminated by the proxy, not the backend.
 * @param {object} [backendConfig] - `{ssl_enabled: bool, ...}` from GET /api/v1/config/frontend
 * @returns {boolean}
 */
export function isBackendHttps(backendConfig) {
  return backendConfig?.ssl_enabled === true
}

// ─── Config generation per tool ───────────────────────────────────

/**
 * Generate Claude Code CLI MCP add command.
 */
export function generateClaudeConfig(serverUrl, apiKey) {
  return `claude mcp add --scope user --transport http ${MCP_ALIAS} ${serverUrl}/mcp --header "Authorization: Bearer ${apiKey}"`
}

/**
 * Generate Claude Desktop MCP config JSON (mcp-remote bridge over HTTP transport).
 *
 * Source of truth: this output is what the user pastes into
 * claude_desktop_config.json. It MUST match the backend generator in
 * api/endpoints/ai_tools.py → get_claude_desktop_config byte-for-byte for the
 * same inputs (pretty-printed, 2-space indent, key order preserved).
 *
 * Claude Desktop can't speak HTTP MCP natively — it spawns `npx mcp-remote`
 * which forwards Authorization. Bearer token is read from the AUTH_HEADER env
 * var so the literal key never appears in argv.
 *
 * @param {string} serverUrl - GiljoAI server URL (no trailing slash).
 * @param {string} apiKey - User's API key (or "<YOUR_API_KEY>" placeholder).
 * @param {object} [options]
 * @param {boolean} [options.selfSigned=false] - When true, inject
 *   NODE_TLS_REJECT_UNAUTHORIZED="0" so the bridge accepts a self-signed
 *   (self-signed / private) cert. Only set when isBackendHttps(backendConfig) is true.
 *   Never set for plain HTTP or proxied HTTPS (publicly-signed cert).
 * @returns {string} Pretty-printed JSON string ready to drop into
 *   claude_desktop_config.json.
 */
// eslint-disable-next-line giljo-internal/no-orphaned-exports -- imported by src/composables/__tests__/useMcpConfig.spec.js, which the rule's __tests__/ exclusion skips
export function generateClaudeDesktopConfig(serverUrl, apiKey, options = {}) {
  const selfSigned = options.selfSigned === true
  const env = { AUTH_HEADER: `Bearer ${apiKey}` }
  if (selfSigned) {
    env.NODE_TLS_REJECT_UNAUTHORIZED = '0'
  }
  const config = {
    mcpServers: {
      [MCP_ALIAS]: {
        command: 'npx',
        args: [
          'mcp-remote',
          `${serverUrl}/mcp`,
          '--header',
          'Authorization:${AUTH_HEADER}',
        ],
        env,
      },
    },
  }
  return JSON.stringify(config, null, 2)
}

/**
 * Generate Codex CLI MCP add command.
 * Codex reads bearer token from env var at runtime.
 */
export function generateCodexConfig(serverUrl) {
  return `codex mcp add ${MCP_ALIAS} --url ${serverUrl}/mcp --bearer-token-env-var GILJO_API_KEY`
}

// ─── OAuth-flavored generators (BE-6157) ──────────────────────────
// These emit the `mcp add` command WITHOUT any Authorization header / API key.
// The CLI then runs its OWN OAuth handshake (browser-based) against the server's
// /oauth endpoints — no bearer key is embedded. Verified syntax 2026-06-20.
// Mirrored byte-for-byte by the matching get_*_oauth_config() in
// api/endpoints/ai_tools.py (the canonical reference).

/**
 * Generate Claude Code CLI MCP add command for the OAuth flow (no bearer header).
 * The CLI opens the browser to authorize; if the browser does not open it prints
 * the URL, or you can authenticate at claude.ai and it syncs.
 */
export function generateClaudeOAuthConfig(serverUrl) {
  return `claude mcp add --transport http ${MCP_ALIAS} ${serverUrl}/mcp --scope user`
}

/**
 * Generate Codex CLI MCP add command for the OAuth flow (no bearer env var).
 * Codex auto-detects OAuth on add.
 */
export function generateCodexOAuthConfig(serverUrl) {
  return `codex mcp add ${MCP_ALIAS} --url ${serverUrl}/mcp`
}

/**
 * Generate Gemini CLI MCP add command for the OAuth flow (no Authorization header).
 */
export function generateGeminiOAuthConfig(serverUrl) {
  return `gemini mcp add --scope user --transport http ${MCP_ALIAS} ${serverUrl}/mcp`
}

/**
 * Generate OpenCode MCP add command for the OAuth flow (no bearer header) (FE-9204).
 * OpenCode registers the server, then runs its own browser sign-in via `mcp auth`.
 *
 * FE-9383: the URL is passed with `--url`, NOT positionally. OpenCode's `mcp add`
 * takes only the server NAME as a positional; a bare URL after it is an unexpected
 * extra positional and OpenCode answers with its help text instead of connecting.
 * Verified against a live OpenCode connect, 2026-08-08.
 */
export function generateOpenCodeOAuthConfig(serverUrl) {
  return `opencode mcp add ${MCP_ALIAS} --url ${serverUrl}/mcp && opencode mcp auth ${MCP_ALIAS}`
}

/**
 * Claude Desktop OAuth has no CLI `mcp add` command — the connector is added in
 * the app/web settings and runs OAuth in the browser. Emit a short real
 * instruction (NOT a fake command). serverUrl is intentionally unused — the
 * connector is added by name in settings, not by URL.
 * @returns {string}
 */
export function generateClaudeDesktopOAuthConfig() {
  return 'Add the GiljoAI connector in Claude Desktop or claude.ai settings; it runs OAuth in the browser.'
}

/**
 * Generate Gemini CLI MCP add command.
 */
export function generateGeminiConfig(serverUrl, apiKey) {
  return `gemini mcp add -t http -H "Authorization: Bearer ${apiKey}" ${MCP_ALIAS} ${serverUrl}/mcp`
}

/**
 * Generate OpenCode MCP add command for the bearer (API-key) flow (FE-9204).
 * Same `mcp add` as the OAuth variant plus an Authorization header — no separate
 * `mcp auth` browser step is needed when a key is supplied.
 *
 * FE-9383: OpenCode's flag syntax differs from Claude Code's in TWO ways, and this
 * generator previously got both wrong — an OpenCode user's very first command failed
 * twice over. (1) The URL rides on `--url`, never positionally. (2) Headers are
 * `KEY=VALUE`, so it is `Authorization=Bearer <key>`; the colon form Claude Code
 * uses does not parse. Verified against a live OpenCode connect, 2026-08-08.
 */
export function generateOpenCodeConfig(serverUrl, apiKey) {
  return `opencode mcp add ${MCP_ALIAS} --url ${serverUrl}/mcp --header "Authorization=Bearer ${apiKey}"`
}

/**
 * Generate Generic MCP JSON config snippet (streamable-http, plain headers).
 * Used by the standalone modal for any MCP-compatible client not covered by
 * a dedicated generator, AND by the setup wizard's "Generic MCP client" tool
 * (FE-9204) — the wizard id `generic` normalizes to `generic_mcp`.
 */
// eslint-disable-next-line giljo-internal/no-orphaned-exports -- referenced internally by generateConfigForTool() and imported in tests/unit/composables/useMcpConfig.spec.js (outside src/)
export function generateGenericMcpConfig(serverUrl, apiKey) {
  return JSON.stringify({
    [MCP_ALIAS]: {
      transport: 'streamable-http',
      url: `${serverUrl}/mcp`,
      headers: { Authorization: `Bearer ${apiKey}` },
    },
  }, null, 2)
}

/**
 * Generate Antigravity CLI MCP config JSON.
 *
 * Source of truth: this output MUST be byte-identical to the backend generator
 * api/endpoints/ai_tools.py → get_antigravity_config() (commit 28cb6c0b4).
 * Shape: { mcpServers: { giljo_hq: { serverUrl, headers: { Authorization } } } }
 * Key order and 2-space indent are significant — see byte-parity spec.
 *
 * This `serverUrl`-based config is the SUPPORTED connection path (streamable HTTP,
 * bearer key). TSK-9089: Antigravity also has a "raw HTTP" connection mode whose
 * `initialize` request omits the streamable-HTTP Accept header, so the server replies
 * 406 Not Acceptable — the handshake never completes, no MCP session is minted, and the
 * client's identity is never captured (it then works initialize-less, which is why tool
 * calls still succeed while the session row is absent). Accepted, not fixed: use the
 * generated config below rather than raw mode. If you're debugging a 406 from an
 * Antigravity connect, this is why.
 *
 * @param {string} serverUrl - GiljoAI server URL (no trailing slash).
 * @param {string} apiKey - User's API key (or "<YOUR_API_KEY>" placeholder).
 * @returns {string} Pretty-printed JSON string ready to paste into .antigravity/mcp.json.
 */
export function generateAntigravityConfig(serverUrl, apiKey) {
  return JSON.stringify({
    mcpServers: {
      [MCP_ALIAS]: {
        serverUrl: `${serverUrl}/mcp`,
        headers: {
          Authorization: `Bearer ${apiKey}`,
        },
      },
    },
  }, null, 2)
}

/**
 * Dispatch to the right generator.
 * Accepts both wizard IDs (claude_code) and legacy IDs (claude).
 * @param {string} toolId
 * @param {string} serverUrl
 * @param {string} apiKey
 * @param {object} [options] - Tool-specific options. For claude_desktop:
 *   `{ selfSigned: boolean }` to enable NODE_TLS_REJECT_UNAUTHORIZED.
 *   `{ authMethod: 'oauth' | 'bearer' }` (default 'bearer') selects the OAuth
 *   variant for OAuth-capable tools. Tools without an OAuth variant
 *   (antigravity, generic_mcp) always fall back to the bearer generator.
 * @returns {string}
 */
export function generateConfigForTool(toolId, serverUrl, apiKey, options = {}) {
  const id = normalizeToolId(toolId)
  if (options.authMethod === 'oauth') {
    switch (id) {
      case 'claude':
        return generateClaudeOAuthConfig(serverUrl)
      case 'claude_desktop':
        return generateClaudeDesktopOAuthConfig()
      case 'codex':
        return generateCodexOAuthConfig(serverUrl)
      case 'gemini':
        return generateGeminiOAuthConfig(serverUrl)
      case 'opencode':
        return generateOpenCodeOAuthConfig(serverUrl)
      // antigravity + generic_mcp have NO OAuth variant — fall through to bearer.
    }
  }
  switch (id) {
    case 'claude':
      return generateClaudeConfig(serverUrl, apiKey)
    case 'claude_desktop':
      return generateClaudeDesktopConfig(serverUrl, apiKey, options)
    case 'codex':
      return generateCodexConfig(serverUrl)
    case 'gemini':
      return generateGeminiConfig(serverUrl, apiKey)
    case 'opencode':
      return generateOpenCodeConfig(serverUrl, apiKey)
    case 'generic_mcp':
      return generateGenericMcpConfig(serverUrl, apiKey)
    case 'antigravity':
      return generateAntigravityConfig(serverUrl, apiKey)
    default:
      return `Use these values with your tool:\n- Base URL: ${serverUrl}\n- Header: Authorization: Bearer ${apiKey}`
  }
}

// ─── Environment variable helpers ─────────────────────────────────

/**
 * Generate Codex env var command for a given platform.
 * @param {string} apiKey
 * @param {'windows'|'unix'} platform
 * @returns {string}
 */
export function generateCodexEnvVar(apiKey, platform) {
  const key = apiKey || 'YOUR_API_KEY'
  if (platform === 'windows') {
    return `setx GILJO_API_KEY "${key}"\n$env:GILJO_API_KEY="${key}"`
  }
  return `echo 'export GILJO_API_KEY="${key}"' >> ~/.bashrc && export GILJO_API_KEY="${key}"`
}

// ─── Certificate trust commands ───────────────────────────────────

export const CERT_TRUST_WINDOWS = '$env:NODE_OPTIONS = "--use-system-ca"; [System.Environment]::SetEnvironmentVariable(\'NODE_OPTIONS\', \'--use-system-ca\', \'User\')'
export const CERT_TRUST_UNIX = 'mkdir -p ~/.giljo && cp ~/Downloads/giljo-server-cert.pem ~/.giljo/giljo-server-cert.pem && export NODE_EXTRA_CA_CERTS="$HOME/.giljo/giljo-server-cert.pem"'

/**
 * @param {'windows'|'unix'} platform
 * @returns {string}
 */
export function getCertTrustCommand(platform) {
  return platform === 'windows' ? CERT_TRUST_WINDOWS : CERT_TRUST_UNIX
}

// ─── Tool metadata ────────────────────────────────────────────────

/**
 * Per-tool auth-capability metadata (BE-6157).
 *
 * Keyed by canonical legacy tool id (the output of normalizeToolId). Drives
 * which auth method(s) the UI offers and which it defaults to. The generators
 * remain the source of truth for the actual command/JSON; this map only
 * describes capability + default.
 *
 * Verified by live testing 2026-06-20. Mirrored in
 * api/endpoints/ai_tools.py → AUTH_CAPABILITIES (keep in sync).
 *
 * Fields per tool:
 *   - vendor:           display vendor name.
 *   - supports_oauth:   tool can run its own OAuth handshake.
 *   - supports_bearer:  tool accepts an Authorization: Bearer key.
 *   - default_auth:     'oauth' | 'bearer' — which the UI should preselect.
 *   - oauth_quirk_note: short note shown alongside the OAuth option ('' if none).
 */
export const AUTH_CAPABILITIES = {
  claude: {
    vendor: 'Anthropic',
    supports_oauth: true,
    supports_bearer: true,
    default_auth: 'oauth',
    oauth_quirk_note:
      'If the browser does not open, the URL is printed; or authenticate at claude.ai and it syncs.',
  },
  claude_desktop: {
    vendor: 'Anthropic',
    supports_oauth: true,
    supports_bearer: true,
    default_auth: 'oauth',
    oauth_quirk_note: '',
  },
  codex: {
    vendor: 'OpenAI',
    supports_oauth: true,
    supports_bearer: true,
    default_auth: 'oauth',
    oauth_quirk_note: 'OAuth auto-detected on add.',
  },
  gemini: {
    vendor: 'Google',
    supports_oauth: true,
    supports_bearer: true,
    default_auth: 'oauth',
    oauth_quirk_note: '',
  },
  // OpenCode (FE-9204): sign-in-capable, also accepts a bearer key. FE-only entry
  // — api/endpoints/ai_tools.py AUTH_CAPABILITIES is a test-only mirror with no
  // runtime tool-id validation, so no backend parity is required (verified FE-9204).
  opencode: {
    vendor: 'OpenCode',
    supports_oauth: true,
    supports_bearer: true,
    default_auth: 'oauth',
    oauth_quirk_note: '',
  },
  antigravity: {
    vendor: 'Google',
    supports_oauth: false,
    supports_bearer: true,
    default_auth: 'bearer',
    oauth_quirk_note: 'Antigravity has no OAuth; bearer key in mcp_config.json only.',
  },
  generic_mcp: {
    vendor: 'Other',
    supports_oauth: false,
    supports_bearer: true,
    default_auth: 'bearer',
    oauth_quirk_note: '',
  },
}

/**
 * Look up auth-capability metadata for a tool id.
 * Accepts both wizard IDs (claude_code) and legacy IDs (claude).
 * @param {string} toolId
 * @returns {object|null} the capability entry, or null for an unknown tool.
 */
export function getAuthCapabilities(toolId) {
  return AUTH_CAPABILITIES[normalizeToolId(toolId)] || null
}

/**
 * Human-readable name for API key generation.
 * @param {string} toolId - Either wizard or legacy ID
 * @returns {string}
 */
export function makeKeyName(toolId) {
  const id = normalizeToolId(toolId)
  const map = {
    claude: 'Claude Code CLI',
    claude_desktop: 'Claude Desktop',
    codex: 'Codex CLI',
    gemini: 'Gemini',
    opencode: 'OpenCode',
    generic_mcp: 'Generic MCP',
    antigravity: 'Antigravity CLI',
  }
  return `${map[id] || 'AI Agent'} prompt key`
}
