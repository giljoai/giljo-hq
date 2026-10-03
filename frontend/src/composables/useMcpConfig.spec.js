import { describe, it, expect } from 'vitest'
import {
  normalizeToolId,
  generateConfigForTool,
  makeKeyName,
  AUTH_CAPABILITIES,
  getAuthCapabilities,
  generateClaudeOAuthConfig,
  generateCodexOAuthConfig,
  generateClaudeDesktopOAuthConfig,
  generateOpenCodeOAuthConfig,
  generateOpenCodeConfig,
  generateClaudeConfig,
  generateCodexConfig,
} from './useMcpConfig'

describe('normalizeToolId', () => {
  it('maps claude_code → claude', () => {
    expect(normalizeToolId('claude_code')).toBe('claude')
  })

  it('maps codex_cli → codex', () => {
    expect(normalizeToolId('codex_cli')).toBe('codex')
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

describe('OAuth generators (BE-6157, byte-parity with ai_tools.py)', () => {

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

  it('Claude Desktop OAuth returns a real instruction, not a fake command', () => {
    const result = generateClaudeDesktopOAuthConfig()
    expect(result).toBe(
      'Add the GiljoAI connector in Claude Desktop or claude.ai settings; it runs OAuth in the browser.',
    )
    expect(result).not.toContain('mcp add')
  })

  it('OpenCode sign-in command registers then authenticates, no bearer (FE-9204)', () => {
    const result = generateOpenCodeOAuthConfig('https://giljo.example.com')
    expect(result).toBe('opencode mcp add giljo_hq --url https://giljo.example.com/mcp\nopencode mcp auth giljo_hq')
    expect(result).not.toContain('Authorization')
    expect(result).not.toContain('Bearer')
  })

  it('OpenCode bearer command carries the Authorization header (FE-9204)', () => {
    const result = generateOpenCodeConfig('https://giljo.example.com', 'tok_abc')
    expect(result).toBe('opencode mcp add giljo_hq --url https://giljo.example.com/mcp --header "Authorization=Bearer tok_abc"')
  })
})

describe('OpenCode command syntax (FE-9383)', () => {
  const URL = 'https://test.giljo.ai'
  const KEY = 'gk_live_example'

  it('passes the server URL with --url, never as a bare positional', () => {
    for (const cmd of [generateOpenCodeConfig(URL, KEY), generateOpenCodeOAuthConfig(URL)]) {
      expect(cmd).toContain(`--url ${URL}/mcp`)
      expect(cmd).not.toContain(`mcp add giljo_hq ${URL}`)
    }
  })

  it('emits the KEY=VALUE header form and never the colon form', () => {
    const cmd = generateOpenCodeConfig(URL, KEY)
    expect(cmd).toContain(`Authorization=Bearer ${KEY}`)
    expect(cmd).not.toContain('Authorization: Bearer')
    expect(cmd).not.toContain('Authorization:')
  })

  it('dispatches both auth methods to the corrected syntax', () => {
    expect(generateConfigForTool('opencode', URL, KEY)).toBe(generateOpenCodeConfig(URL, KEY))
    expect(generateConfigForTool('opencode', URL, KEY, { authMethod: 'oauth' })).toBe(
      generateOpenCodeOAuthConfig(URL),
    )
  })

  it('leaves the Claude Code command untouched — it still takes a positional URL and a colon header', () => {
    expect(generateClaudeConfig(URL, KEY)).toBe(
      `claude mcp add --scope user --transport http giljo_hq ${URL}/mcp --header "Authorization: Bearer ${KEY}"`,
    )
    expect(generateClaudeOAuthConfig(URL)).toBe(
      `claude mcp add --transport http giljo_hq ${URL}/mcp --scope user`,
    )
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

  it('routes opencode oauth to the sign-in-plus-auth command (FE-9204)', () => {
    const result = generateConfigForTool('opencode', URL, KEY, { authMethod: 'oauth' })
    expect(result).toBe(`opencode mcp add giljo_hq --url ${URL}/mcp\nopencode mcp auth giljo_hq`)
    expect(result).not.toContain('Authorization')
    expect(result).not.toContain('Bearer')
  })

  it('routes opencode bearer to the header command (FE-9204)', () => {
    expect(generateConfigForTool('opencode', URL, KEY)).toBe(
      `opencode mcp add giljo_hq --url ${URL}/mcp --header "Authorization=Bearer ${KEY}"`,
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

  it('falls back to bearer for generic_mcp (no OAuth variant) even when oauth requested', () => {
    expect(generateConfigForTool('generic_mcp', URL, KEY, { authMethod: 'oauth' })).toBe(
      generateConfigForTool('generic_mcp', URL, KEY),
    )
  })

  it('still emits the bearer codex command unchanged', () => {
    expect(generateConfigForTool('codex', URL, KEY)).toBe(generateCodexConfig(URL))
  })

})

describe('AUTH_CAPABILITIES metadata (BE-6157)', () => {
  it('covers exactly the five connection tools (INF-9605a retired the Google CLIs)', () => {
    expect(Object.keys(AUTH_CAPABILITIES).sort()).toEqual(
      ['claude', 'claude_desktop', 'codex', 'generic_mcp', 'opencode'],
    )
  })

  it('matches the verified capability matrix (2026-06-20; opencode FE-9204)', () => {
    const matrix = {
      claude: ['Anthropic', true, true, 'oauth'],
      claude_desktop: ['Anthropic', true, true, 'oauth'],
      codex: ['OpenAI', true, true, 'oauth'],
      opencode: ['OpenCode', true, true, 'oauth'],
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
    expect(getAuthCapabilities('codex_cli')).toBe(AUTH_CAPABILITIES.codex)
  })

  it('getAuthCapabilities returns null for unknown tools', () => {
    expect(getAuthCapabilities('not_a_tool')).toBeNull()
  })
})

describe('makeKeyName', () => {
  it('returns the Codex prompt key for the codex_cli wizard id', () => {
    expect(makeKeyName('codex_cli')).toBe('Codex CLI prompt key')
  })

  it('falls back to a neutral key name for a retired tool id (INF-9605a)', () => {
    expect(makeKeyName('antigravity_cli')).toBe('AI Agent prompt key')
  })
})

describe('PS 5.1 safety: no generated command ever contains &&', () => {
  it('every tool config for both auth modes is &&-free', async () => {
    const mod = await import('./useMcpConfig')
    const url = 'https://x.example.com'
    for (const gen of Object.entries(mod)) {
      const [name, fn] = gen
      if (typeof fn !== 'function' || !name.startsWith('generate')) continue
      let out
      try {
        out = fn(url, 'gk_dummy_key', {})
      } catch {
        continue
      }
      if (typeof out !== 'string') continue
      expect(out.includes('&&'), `${name} output must not contain && (PS 5.1)`).toBe(false)
    }
  })
})
