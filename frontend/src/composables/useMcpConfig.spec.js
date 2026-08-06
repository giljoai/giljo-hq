/**
 * useMcpConfig.spec.js
 *
 * Tests for MCP config generation composable.
 * Edition scope: CE
 */
import { describe, it, expect } from 'vitest'
import {
  normalizeToolId,
  generateAntigravityConfig,
  generateConfigForTool,
  makeKeyName,
  AUTH_CAPABILITIES,
  getAuthCapabilities,
  generateClaudeOAuthConfig,
  generateCodexOAuthConfig,
  generateGeminiOAuthConfig,
  generateClaudeDesktopOAuthConfig,
  generateOpenCodeOAuthConfig,
  generateOpenCodeConfig,
  generateClaudeConfig,
  generateCodexConfig,
  generateGeminiConfig,
} from './useMcpConfig'

describe('normalizeToolId', () => {
  it('maps claude_code → claude', () => {
    expect(normalizeToolId('claude_code')).toBe('claude')
  })

  it('maps codex_cli → codex', () => {
    expect(normalizeToolId('codex_cli')).toBe('codex')
  })

  it('maps gemini_cli → gemini', () => {
    expect(normalizeToolId('gemini_cli')).toBe('gemini')
  })

  it('maps antigravity_cli → antigravity', () => {
    expect(normalizeToolId('antigravity_cli')).toBe('antigravity')
  })

  it('passes through claude_desktop unchanged', () => {
    expect(normalizeToolId('claude_desktop')).toBe('claude_desktop')
  })

  it('passes through unknown ids unchanged', () => {
    expect(normalizeToolId('generic_mcp')).toBe('generic_mcp')
  })

  it('maps the generic wizard id → generic_mcp (FE-9204)', () => {
    expect(normalizeToolId('generic')).toBe('generic_mcp')
  })

  it('passes through opencode unchanged (FE-9204)', () => {
    expect(normalizeToolId('opencode')).toBe('opencode')
  })
})

describe('generateAntigravityConfig (byte-parity)', () => {
  // BYTE-PARITY SPEC: output MUST be byte-identical to Python:
  //   json.dumps({"mcpServers": {"giljo_hq": {"serverUrl": serverUrl + "/mcp",
  //               "headers": {"Authorization": "Bearer " + api_key}}}}, indent=2)
  //
  // Backend reference: api/endpoints/ai_tools.py → get_antigravity_config()
  // Committed at: 28cb6c0b4

  it('emits JSON byte-identical to backend get_antigravity_config (placeholder key)', () => {
    const result = generateAntigravityConfig('https://giljo.example.com', '<YOUR_API_KEY>')
    const expected = [
      '{',
      '  "mcpServers": {',
      '    "giljo_hq": {',
      '      "serverUrl": "https://giljo.example.com/mcp",',
      '      "headers": {',
      '        "Authorization": "Bearer <YOUR_API_KEY>"',
      '      }',
      '    }',
      '  }',
      '}',
    ].join('\n')
    expect(result).toBe(expected)
  })

  it('substitutes a real server URL and token correctly', () => {
    const result = generateAntigravityConfig('http://localhost:7272', 'tok_abc123')
    const expected = [
      '{',
      '  "mcpServers": {',
      '    "giljo_hq": {',
      '      "serverUrl": "http://localhost:7272/mcp",',
      '      "headers": {',
      '        "Authorization": "Bearer tok_abc123"',
      '      }',
      '    }',
      '  }',
      '}',
    ].join('\n')
    expect(result).toBe(expected)
  })

  it('produces valid JSON', () => {
    const result = generateAntigravityConfig('https://example.com', 'key123')
    expect(() => JSON.parse(result)).not.toThrow()
    const parsed = JSON.parse(result)
    expect(parsed.mcpServers.giljo_hq.serverUrl).toBe('https://example.com/mcp')
    expect(parsed.mcpServers.giljo_hq.headers.Authorization).toBe('Bearer key123')
  })
})

describe('generateConfigForTool dispatch', () => {
  it('routes antigravity to generateAntigravityConfig', () => {
    const direct = generateAntigravityConfig('https://test.giljo.ai', 'key')
    const dispatched = generateConfigForTool('antigravity', 'https://test.giljo.ai', 'key')
    expect(dispatched).toBe(direct)
  })

  it('routes antigravity_cli (wizard id) to generateAntigravityConfig via normalizeToolId', () => {
    const direct = generateAntigravityConfig('https://test.giljo.ai', 'key')
    const dispatched = generateConfigForTool('antigravity_cli', 'https://test.giljo.ai', 'key')
    expect(dispatched).toBe(direct)
  })
})

describe('OAuth generators (BE-6157, byte-parity with ai_tools.py)', () => {
  // BYTE-PARITY: each string MUST be byte-identical to the matching
  // get_*_oauth_config() in api/endpoints/ai_tools.py for the same inputs.
  // The OAuth `mcp add` commands carry NO Authorization header / API key — the
  // CLI runs its own OAuth handshake.

  it('Claude OAuth command omits the bearer header', () => {
    const result = generateClaudeOAuthConfig('https://giljo.example.com')
    expect(result).toBe('claude mcp add --transport http giljo_hq https://giljo.example.com/mcp --scope user')
    expect(result).not.toContain('Authorization')
    expect(result).not.toContain('Bearer')
  })

  it('Codex OAuth command omits the bearer env var', () => {
    const result = generateCodexOAuthConfig('https://giljo.example.com')
    expect(result).toBe('codex mcp add giljo_hq --url https://giljo.example.com/mcp')
    expect(result).not.toContain('bearer-token-env-var')
  })

  it('Gemini OAuth command omits the bearer header', () => {
    const result = generateGeminiOAuthConfig('https://giljo.example.com')
    expect(result).toBe('gemini mcp add --scope user --transport http giljo_hq https://giljo.example.com/mcp')
    expect(result).not.toContain('Authorization')
    expect(result).not.toContain('Bearer')
  })

  it('Claude Desktop OAuth returns a real instruction, not a fake command', () => {
    const result = generateClaudeDesktopOAuthConfig()
    expect(result).toBe(
      'Add the GiljoAI connector in Claude Desktop or claude.ai settings; it runs OAuth in the browser.',
    )
    expect(result).not.toContain('mcp add')
  })

  it('OpenCode sign-in command registers then authenticates, no bearer (FE-9204)', () => {
    const result = generateOpenCodeOAuthConfig('https://giljo.example.com')
    expect(result).toBe('opencode mcp add giljo_hq https://giljo.example.com/mcp && opencode mcp auth giljo_hq')
    expect(result).not.toContain('Authorization')
    expect(result).not.toContain('Bearer')
  })

  it('OpenCode bearer command carries the Authorization header (FE-9204)', () => {
    const result = generateOpenCodeConfig('https://giljo.example.com', 'tok_abc')
    expect(result).toBe('opencode mcp add giljo_hq https://giljo.example.com/mcp --header "Authorization: Bearer tok_abc"')
  })
})

describe('generateConfigForTool authMethod dispatch (BE-6157)', () => {
  const URL = 'https://test.giljo.ai'
  const KEY = '<YOUR_API_KEY>'

  it('defaults to bearer when authMethod is omitted', () => {
    expect(generateConfigForTool('claude', URL, KEY)).toBe(generateClaudeConfig(URL, KEY))
  })

  it('routes claude oauth to the OAuth generator', () => {
    expect(generateConfigForTool('claude', URL, KEY, { authMethod: 'oauth' })).toBe(generateClaudeOAuthConfig(URL))
  })

  it('routes claude_code wizard id oauth via normalizeToolId', () => {
    expect(generateConfigForTool('claude_code', URL, KEY, { authMethod: 'oauth' })).toBe(generateClaudeOAuthConfig(URL))
  })

  it('routes codex oauth to the OAuth generator', () => {
    expect(generateConfigForTool('codex', URL, KEY, { authMethod: 'oauth' })).toBe(generateCodexOAuthConfig(URL))
  })

  it('routes gemini oauth to the OAuth generator', () => {
    expect(generateConfigForTool('gemini', URL, KEY, { authMethod: 'oauth' })).toBe(generateGeminiOAuthConfig(URL))
  })

  it('routes opencode oauth to the sign-in-plus-auth command (FE-9204)', () => {
    const result = generateConfigForTool('opencode', URL, KEY, { authMethod: 'oauth' })
    expect(result).toBe(`opencode mcp add giljo_hq ${URL}/mcp && opencode mcp auth giljo_hq`)
    expect(result).not.toContain('Authorization')
    expect(result).not.toContain('Bearer')
  })

  it('routes opencode bearer to the header command (FE-9204)', () => {
    expect(generateConfigForTool('opencode', URL, KEY)).toBe(
      `opencode mcp add giljo_hq ${URL}/mcp --header "Authorization: Bearer ${KEY}"`,
    )
  })

  it('routes the generic wizard id to the generic_mcp JSON emitter (FE-9204)', () => {
    expect(generateConfigForTool('generic', URL, KEY)).toBe(generateConfigForTool('generic_mcp', URL, KEY))
  })

  it('routes claude_desktop oauth to the instruction generator', () => {
    expect(generateConfigForTool('claude_desktop', URL, KEY, { authMethod: 'oauth' })).toBe(
      generateClaudeDesktopOAuthConfig(),
    )
  })

  it('falls back to bearer for antigravity (no OAuth variant) even when oauth requested', () => {
    expect(generateConfigForTool('antigravity', URL, KEY, { authMethod: 'oauth' })).toBe(
      generateConfigForTool('antigravity', URL, KEY),
    )
  })

  it('falls back to bearer for generic_mcp (no OAuth variant) even when oauth requested', () => {
    expect(generateConfigForTool('generic_mcp', URL, KEY, { authMethod: 'oauth' })).toBe(
      generateConfigForTool('generic_mcp', URL, KEY),
    )
  })

  it('still emits the bearer codex command unchanged', () => {
    expect(generateConfigForTool('codex', URL, KEY)).toBe(generateCodexConfig(URL))
  })

  it('still emits the bearer gemini command unchanged', () => {
    expect(generateConfigForTool('gemini', URL, KEY)).toBe(generateGeminiConfig(URL, KEY))
  })
})

describe('AUTH_CAPABILITIES metadata (BE-6157)', () => {
  it('covers exactly the seven connection tools (opencode added FE-9204)', () => {
    expect(Object.keys(AUTH_CAPABILITIES).sort()).toEqual(
      ['antigravity', 'claude', 'claude_desktop', 'codex', 'gemini', 'generic_mcp', 'opencode'],
    )
  })

  it('matches the verified capability matrix (2026-06-20; opencode FE-9204)', () => {
    const matrix = {
      claude: ['Anthropic', true, true, 'oauth'],
      claude_desktop: ['Anthropic', true, true, 'oauth'],
      codex: ['OpenAI', true, true, 'oauth'],
      gemini: ['Google', true, true, 'oauth'],
      opencode: ['OpenCode', true, true, 'oauth'],
      antigravity: ['Google', false, true, 'bearer'],
      generic_mcp: ['Other', false, true, 'bearer'],
    }
    for (const [id, [vendor, oauth, bearer, def]] of Object.entries(matrix)) {
      const cap = AUTH_CAPABILITIES[id]
      expect(cap.vendor).toBe(vendor)
      expect(cap.supports_oauth).toBe(oauth)
      expect(cap.supports_bearer).toBe(bearer)
      expect(cap.default_auth).toBe(def)
    }
  })

  it('default_auth is always a supported method', () => {
    for (const cap of Object.values(AUTH_CAPABILITIES)) {
      const supported = cap.default_auth === 'oauth' ? cap.supports_oauth : cap.supports_bearer
      expect(supported).toBe(true)
    }
  })

  it('every bearer-only tool carries no oauth default', () => {
    for (const cap of Object.values(AUTH_CAPABILITIES)) {
      if (!cap.supports_oauth) expect(cap.default_auth).toBe('bearer')
    }
  })

  it('getAuthCapabilities resolves wizard ids via normalizeToolId', () => {
    expect(getAuthCapabilities('claude_code')).toBe(AUTH_CAPABILITIES.claude)
    expect(getAuthCapabilities('antigravity_cli')).toBe(AUTH_CAPABILITIES.antigravity)
  })

  it('getAuthCapabilities returns null for unknown tools', () => {
    expect(getAuthCapabilities('not_a_tool')).toBeNull()
  })
})

describe('makeKeyName', () => {
  it('returns Antigravity prompt key for antigravity tool id', () => {
    expect(makeKeyName('antigravity')).toBe('Antigravity CLI prompt key')
  })

  it('returns Antigravity prompt key for antigravity_cli wizard id', () => {
    expect(makeKeyName('antigravity_cli')).toBe('Antigravity CLI prompt key')
  })
})
