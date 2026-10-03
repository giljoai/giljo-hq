import { describe, expect, it } from 'vitest'
import {
  generateClaudeDesktopConfig,
  generateConfigForTool,
  normalizeToolId,
  makeKeyName,
} from '../useMcpConfig'

const SERVER_PROXIED = 'https://giljo.example.com'
const SERVER_HTTP = 'http://localhost:7272'
const API_KEY = 'fake-key-for-test'

describe('generateClaudeDesktopConfig', () => {
  it('writes the mcp-remote bridge entry with the bearer in AUTH_HEADER only', () => {
    const cfg = JSON.parse(generateClaudeDesktopConfig(SERVER_PROXIED, API_KEY))

    expect(cfg).toHaveProperty('mcpServers.giljo_hq')
    const entry = cfg.mcpServers.giljo_hq
    expect(entry.command).toBe('npx')
    expect(entry.args).toEqual([
      'mcp-remote',
      `${SERVER_PROXIED}/mcp`,
      '--header',
      'Authorization:${AUTH_HEADER}',
    ])
    expect(entry.env).toEqual({ AUTH_HEADER: `Bearer ${API_KEY}` })
  })

  it('never touches TLS verification (plain HTTP or proxied HTTPS)', () => {
    for (const url of [SERVER_HTTP, SERVER_PROXIED]) {
      const entry = JSON.parse(generateClaudeDesktopConfig(url, API_KEY)).mcpServers.giljo_hq
      expect(entry.env.NODE_TLS_REJECT_UNAUTHORIZED).toBeUndefined()
    }
  })

  it('output is pretty-printed JSON with 2-space indent (matches backend byte-for-byte)', () => {
    const raw = generateClaudeDesktopConfig(SERVER_PROXIED, API_KEY)
    const expected = JSON.stringify(
      {
        mcpServers: {
          giljo_hq: {
            command: 'npx',
            args: [
              'mcp-remote',
              `${SERVER_PROXIED}/mcp`,
              '--header',
              'Authorization:${AUTH_HEADER}',
            ],
            env: { AUTH_HEADER: `Bearer ${API_KEY}` },
          },
        },
      },
      null,
      2,
    )
    expect(raw).toBe(expected)
  })
})

describe('generateConfigForTool dispatch', () => {
  it('routes claude_desktop to JSON generator', () => {
    const cfg = JSON.parse(generateConfigForTool('claude_desktop', SERVER_HTTP, API_KEY))
    expect(cfg.mcpServers.giljo_hq.command).toBe('npx')
    expect(cfg.mcpServers.giljo_hq.env.NODE_TLS_REJECT_UNAUTHORIZED).toBeUndefined()
  })
})

describe('normalizeToolId / makeKeyName for claude_desktop', () => {
  it('normalizeToolId returns claude_desktop unchanged', () => {
    expect(normalizeToolId('claude_desktop')).toBe('claude_desktop')
  })

  it('makeKeyName produces a recognizable Claude Desktop key name', () => {
    expect(makeKeyName('claude_desktop')).toBe('Claude Desktop prompt key')
  })

  it('makeKeyName for legacy claude id reflects renamed display ("Claude Code CLI")', () => {
    expect(makeKeyName('claude')).toBe('Claude Code CLI prompt key')
  })
})
