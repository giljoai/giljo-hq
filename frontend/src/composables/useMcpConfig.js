// eslint-allow giljo-internal/no-manual-api-url-composition

import { MCP_ALIAS } from '@/branding'

export function normalizeToolId(toolId) {
  const map = {
    claude_code: 'claude',
    codex_cli: 'codex',
    generic: 'generic_mcp',
  }
  return map[toolId] || toolId
}

export function detectPlatform() {
  if (typeof navigator !== 'undefined' && /win/i.test(navigator.platform)) {
    return 'windows'
  }
  return 'unix'
}

export function buildServerUrl(hostnameOrConfig) {
  if (hostnameOrConfig && typeof hostnameOrConfig === 'object') {
    const cfg = hostnameOrConfig
    const protocol = cfg.protocol || (window.location.protocol === 'https:' ? 'https' : 'http')
    const host = cfg.host || window.location.hostname
    const cfgPort = cfg.port

    if (host && window.location.hostname === host) {
      return window.location.origin
    }

    const isImplicitHttps = protocol === 'https' && Number(cfgPort) === 443
    const isImplicitHttp = protocol === 'http' && Number(cfgPort) === 80
    if (!cfgPort || isImplicitHttps || isImplicitHttp) {
      return `${protocol}://${host}`
    }
    return `${protocol}://${host}:${cfgPort}`
  }

  throw new Error('buildServerUrl needs the backend config object')
}


export function generateClaudeConfig(serverUrl, apiKey) {
  return `claude mcp add --scope user --transport http ${MCP_ALIAS} ${serverUrl}/mcp --header "Authorization: Bearer ${apiKey}"`
}

// eslint-disable-next-line giljo-internal/no-orphaned-exports -- imported by src/composables/__tests__/useMcpConfig.spec.js, which the rule's __tests__/ exclusion skips
export function generateClaudeDesktopConfig(serverUrl, apiKey) {
  const env = { AUTH_HEADER: `Bearer ${apiKey}` }
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

export function generateCodexConfig(serverUrl) {
  return `codex mcp add ${MCP_ALIAS} --url ${serverUrl}/mcp --bearer-token-env-var GILJO_API_KEY`
}


export function generateClaudeOAuthConfig(serverUrl) {
  return `claude mcp add --transport http ${MCP_ALIAS} ${serverUrl}/mcp --scope user`
}

export function generateCodexOAuthConfig(serverUrl) {
  return `codex mcp add ${MCP_ALIAS} --url ${serverUrl}/mcp`
}

export function generateOpenCodeOAuthConfig(serverUrl) {
  return `opencode mcp add ${MCP_ALIAS} --url ${serverUrl}/mcp\nopencode mcp auth ${MCP_ALIAS}`
}

export function generateClaudeDesktopOAuthConfig() {
  return 'Add the GiljoAI connector in Claude Desktop or claude.ai settings; it runs OAuth in the browser.'
}

export function generateOpenCodeConfig(serverUrl, apiKey) {
  return `opencode mcp add ${MCP_ALIAS} --url ${serverUrl}/mcp --header "Authorization=Bearer ${apiKey}"`
}

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
      case 'opencode':
        return generateOpenCodeOAuthConfig(serverUrl)
    }
  }
  switch (id) {
    case 'claude':
      return generateClaudeConfig(serverUrl, apiKey)
    case 'claude_desktop':
      return generateClaudeDesktopConfig(serverUrl, apiKey)
    case 'codex':
      return generateCodexConfig(serverUrl)
    case 'opencode':
      return generateOpenCodeConfig(serverUrl, apiKey)
    case 'generic_mcp':
      return generateGenericMcpConfig(serverUrl, apiKey)
    default:
      return `Use these values with your tool:\n- Base URL: ${serverUrl}\n- Header: Authorization: Bearer ${apiKey}`
  }
}


export function generateCodexEnvVar(apiKey, platform) {
  const key = apiKey || 'YOUR_API_KEY'
  if (platform === 'windows') {
    return `setx GILJO_API_KEY "${key}"\n$env:GILJO_API_KEY="${key}"`
  }
  return `echo 'export GILJO_API_KEY="${key}"' >> ~/.bashrc\nexport GILJO_API_KEY="${key}"`
}


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
  opencode: {
    vendor: 'OpenCode',
    supports_oauth: true,
    supports_bearer: true,
    default_auth: 'oauth',
    oauth_quirk_note: '',
  },
  generic_mcp: {
    vendor: 'Other',
    supports_oauth: false,
    supports_bearer: true,
    default_auth: 'bearer',
    oauth_quirk_note: '',
  },
}

export function getAuthCapabilities(toolId) {
  return AUTH_CAPABILITIES[normalizeToolId(toolId)] || null
}

export function makeKeyName(toolId) {
  const id = normalizeToolId(toolId)
  const map = {
    claude: 'Claude Code CLI',
    claude_desktop: 'Claude Desktop',
    codex: 'Codex CLI',
    opencode: 'OpenCode',
    generic_mcp: 'Generic MCP',
  }
  return `${map[id] || 'AI Agent'} prompt key`
}
