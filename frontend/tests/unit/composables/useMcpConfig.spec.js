import { describe, it, expect } from 'vitest'
import {
  normalizeToolId,
  detectPlatform,
  buildServerUrl,
  generateClaudeConfig,
  generateCodexConfig,
  generateGenericMcpConfig,
  generateConfigForTool,
  generateCodexEnvVar,
  makeKeyName,
} from '@/composables/useMcpConfig'

describe('useMcpConfig', () => {
  // ─── normalizeToolId ───────────────────────────────────────────────

  describe('normalizeToolId', () => {
    it('maps claude_code to claude', () => {
      expect(normalizeToolId('claude_code')).toBe('claude')
    })

    it('maps codex_cli to codex', () => {
      expect(normalizeToolId('codex_cli')).toBe('codex')
    })

    it('passes through unknown IDs unchanged', () => {
      expect(normalizeToolId('generic_mcp')).toBe('generic_mcp')
      expect(normalizeToolId('some_other_tool')).toBe('some_other_tool')
    })

    it('passes through legacy IDs unchanged', () => {
      expect(normalizeToolId('claude')).toBe('claude')
      expect(normalizeToolId('codex')).toBe('codex')
      expect(normalizeToolId('gemini')).toBe('gemini')
    })
  })

  // ─── detectPlatform ────────────────────────────────────────────────

  describe('detectPlatform', () => {
    it('returns windows when navigator.platform contains Win', () => {
      Object.defineProperty(global, 'navigator', {
        value: { platform: 'Win32' },
        writable: true,
        configurable: true,
      })
      expect(detectPlatform()).toBe('windows')
    })

    it('returns unix for non-Windows platforms', () => {
      Object.defineProperty(global, 'navigator', {
        value: { platform: 'Linux x86_64' },
        writable: true,
        configurable: true,
      })
      expect(detectPlatform()).toBe('unix')
    })

    it('returns unix for MacIntel platform', () => {
      Object.defineProperty(global, 'navigator', {
        value: { platform: 'MacIntel' },
        writable: true,
        configurable: true,
      })
      expect(detectPlatform()).toBe('unix')
    })
  })

  // ─── buildServerUrl ────────────────────────────────────────────────

  describe('buildServerUrl', () => {
    // INF-5012b — reverse-proxy/Cloudflare Tunnel deployments: backend returns
    // api.port=null when reached on the standard 443/80 port. The composed URL
    // must omit the ':port' segment.
    describe('backendConfig object signature (INF-5012b)', () => {
      it('omits port when cfg.port is null (mcp.example.com via Cloudflare)', () => {
        // Browser is on a different host so we hit the out-of-band branch,
        // not the window.location.origin shortcut.
        expect(
          buildServerUrl({ host: 'mcp.example.com', port: null, protocol: 'https' }),
        ).toBe('https://mcp.example.com')
      })

      it('omits port when cfg.port is undefined', () => {
        expect(
          buildServerUrl({ host: 'mcp.example.com', protocol: 'https' }),
        ).toBe('https://mcp.example.com')
      })

      it('omits port when cfg.port is the empty string', () => {
        expect(
          buildServerUrl({ host: 'mcp.example.com', port: '', protocol: 'https' }),
        ).toBe('https://mcp.example.com')
      })

      it('omits port when cfg.port is 0', () => {
        expect(
          buildServerUrl({ host: 'mcp.example.com', port: 0, protocol: 'https' }),
        ).toBe('https://mcp.example.com')
      })

      it('retains numeric port for CE localhost (port=7272)', () => {
        expect(
          buildServerUrl({ host: 'some-other-host.lan', port: 7272, protocol: 'http' }),
        ).toBe('http://some-other-host.lan:7272')
      })

      it('omits implicit https port 443', () => {
        expect(
          buildServerUrl({ host: 'mcp.example.com', port: 443, protocol: 'https' }),
        ).toBe('https://mcp.example.com')
      })

      it('omits implicit http port 80', () => {
        expect(
          buildServerUrl({ host: 'customer.lan', port: 80, protocol: 'http' }),
        ).toBe('http://customer.lan')
      })

      it('never renders :null or :undefined literal strings', () => {
        const nullCase = buildServerUrl({ host: 'mcp.example.com', port: null, protocol: 'https' })
        const undefCase = buildServerUrl({ host: 'mcp.example.com', port: undefined, protocol: 'https' })
        expect(nullCase).not.toContain(':null')
        expect(nullCase).not.toContain(':undefined')
        expect(undefCase).not.toContain(':null')
        expect(undefCase).not.toContain(':undefined')
      })

      it('returns window.location.origin when browser host matches cfg.host', () => {
        // jsdom default host is 'localhost' — force a match to verify the shortcut.
        const result = buildServerUrl({
          host: window.location.hostname,
          port: 7272,
          protocol: 'http',
        })
        expect(result).toBe(window.location.origin)
      })
    })

    // INF-5012b — downstream command generators must not inherit :null or
    // :undefined from a missing port.
    describe('composition with tool generators (INF-5012b)', () => {
      it('claude command on mcp.example.com has no :port', () => {
        const url = buildServerUrl({ host: 'mcp.example.com', port: null, protocol: 'https' })
        const cmd = generateClaudeConfig(url, 'giljo_abc')
        expect(cmd).toContain('https://mcp.example.com/mcp')
        expect(cmd).not.toContain(':null')
        expect(cmd).not.toContain(':undefined')
        expect(cmd).not.toContain(':7272')
      })

      it('codex command on mcp.example.com has no :port', () => {
        const url = buildServerUrl({ host: 'mcp.example.com', port: null, protocol: 'https' })
        const cmd = generateCodexConfig(url)
        expect(cmd).toContain('https://mcp.example.com/mcp')
        expect(cmd).not.toContain(':null')
        expect(cmd).not.toContain(':undefined')
      })

      it('claude command on CE localhost retains :7272', () => {
        const url = buildServerUrl({ host: 'some-other-host.lan', port: 7272, protocol: 'http' })
        const cmd = generateClaudeConfig(url, 'giljo_abc')
        expect(cmd).toContain('http://some-other-host.lan:7272/mcp')
      })
    })
  })

  // ─── generateClaudeConfig ──────────────────────────────────────────

  describe('generateClaudeConfig', () => {
    it('returns the correct claude mcp add command', () => {
      const result = generateClaudeConfig('https://localhost:8372', 'giljo_abc123')
      expect(result).toBe(
        'claude mcp add --scope user --transport http giljo_hq https://localhost:8372/mcp --header "Authorization: Bearer giljo_abc123"',
      )
    })
  })

  // ─── generateCodexConfig ───────────────────────────────────────────

  describe('generateCodexConfig', () => {
    it('returns the correct codex mcp add command', () => {
      const result = generateCodexConfig('https://localhost:8372')
      expect(result).toBe(
        'codex mcp add giljo_hq --url https://localhost:8372/mcp --bearer-token-env-var GILJO_API_KEY',
      )
    })
  })

  // ─── generateGenericMcpConfig ─────────────────────────────────────

  describe('generateGenericMcpConfig', () => {
    it('returns valid JSON with transport, url, and headers', () => {
      const result = generateGenericMcpConfig('https://localhost:8372', 'giljo_key456')
      const parsed = JSON.parse(result)
      const server = parsed['giljo_hq']
      expect(server).toBeDefined()
      expect(server).toHaveProperty('transport')
      expect(server).toHaveProperty('url', 'https://localhost:8372/mcp')
      expect(server).toHaveProperty('headers')
      expect(server.headers).toHaveProperty('Authorization', 'Bearer giljo_key456')
    })
  })

  // ─── generateConfigForTool ─────────────────────────────────────────

  describe('generateConfigForTool', () => {
    const serverUrl = 'https://localhost:8372'
    const apiKey = 'giljo_test'

    it('dispatches to claude generator for wizard ID claude_code', () => {
      expect(generateConfigForTool('claude_code', serverUrl, apiKey)).toContain('claude mcp add')
    })

    it('dispatches to claude generator for legacy ID claude', () => {
      expect(generateConfigForTool('claude', serverUrl, apiKey)).toContain('claude mcp add')
    })

    it('dispatches to codex generator for wizard ID codex_cli', () => {
      expect(generateConfigForTool('codex_cli', serverUrl, apiKey)).toContain('codex mcp add')
    })

    it('dispatches to codex generator for legacy ID codex', () => {
      expect(generateConfigForTool('codex', serverUrl, apiKey)).toContain('codex mcp add')
    })

    it('dispatches to generic MCP generator for generic_mcp', () => {
      const result = generateConfigForTool('generic_mcp', serverUrl, apiKey)
      const parsed = JSON.parse(result)
      expect(parsed['giljo_hq']).toHaveProperty('url', `${serverUrl}/mcp`)
    })
  })

  // ─── generateCodexEnvVar ───────────────────────────────────────────

  describe('generateCodexEnvVar', () => {
    it('returns Windows setx and $env commands for windows platform', () => {
      const result = generateCodexEnvVar('giljo_mykey', 'windows')
      expect(result).toContain('setx')
      expect(result).toContain('$env')
    })

    it('returns export command for unix platform', () => {
      const result = generateCodexEnvVar('giljo_mykey', 'unix')
      expect(result).toContain('export')
    })
  })

  // ─── makeKeyName ──────────────────────────────────────────────────

  describe('makeKeyName', () => {
    it('returns human-readable key name for claude_code', () => {
      expect(makeKeyName('claude_code')).toMatch(/prompt key/i)
    })

    it('returns human-readable key name for codex_cli', () => {
      expect(makeKeyName('codex_cli')).toMatch(/prompt key/i)
    })

    it('returns human-readable key name for gemini_cli', () => {
      expect(makeKeyName('gemini_cli')).toMatch(/prompt key/i)
    })

    it('includes a tool-specific portion in the name', () => {
      expect(makeKeyName('claude_code')).not.toBe(makeKeyName('codex_cli'))
    })
  })
})
