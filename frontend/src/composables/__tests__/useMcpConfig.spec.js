import { describe, expect, it } from 'vitest'
import {
  generateClaudeDesktopConfig,
  generateConfigForTool,
  normalizeToolId,
  makeKeyName,
} from '../useMcpConfig'

const SERVER_HTTPS = 'https://192.0.2.10:7272'
const SERVER_PROXIED = 'https://giljo.example.com'
const SERVER_HTTP = 'http://localhost:7272'
const API_KEY = 'fake-key-for-test'

describe('generateClaudeDesktopConfig', () => {
  it('injects NODE_TLS_REJECT_UNAUTHORIZED when selfSigned=true (mkcert/LAN HTTPS)', () => {
    const raw = generateClaudeDesktopConfig(SERVER_HTTPS, API_KEY, { selfSigned: true })
    const cfg = JSON.parse(raw)

    expect(cfg).toHaveProperty('mcpServers.giljo_hq')
    const entry = cfg.mcpServers.giljo_hq
    expect(entry.command).toBe('npx')
    expect(entry.args).toEqual([
      'mcp-remote',
      `${SERVER_HTTPS}/mcp`,
      '--header',
      'Authorization:${AUTH_HEADER}',
    ])
    expect(entry.env.AUTH_HEADER).toBe(`Bearer ${API_KEY}`)
    expect(entry.env.NODE_TLS_REJECT_UNAUTHORIZED).toBe('0')
  })

  it('omits NODE_TLS_REJECT_UNAUTHORIZED for proxied HTTPS (selfSigned=false)', () => {
    const raw = generateClaudeDesktopConfig(SERVER_PROXIED, API_KEY, { selfSigned: false })
    const cfg = JSON.parse(raw)

    const entry = cfg.mcpServers.giljo_hq
    expect(entry.args[1]).toBe(`${SERVER_PROXIED}/mcp`)
    expect(entry.env.AUTH_HEADER).toBe(`Bearer ${API_KEY}`)
    expect(entry.env.NODE_TLS_REJECT_UNAUTHORIZED).toBeUndefined()
  })

  it('omits NODE_TLS_REJECT_UNAUTHORIZED for plain HTTP', () => {
    const raw = generateClaudeDesktopConfig(SERVER_HTTP, API_KEY, { selfSigned: false })
    const cfg = JSON.parse(raw)

    const entry = cfg.mcpServers.giljo_hq
    expect(entry.args[1]).toBe(`${SERVER_HTTP}/mcp`)
    expect(entry.env.AUTH_HEADER).toBe(`Bearer ${API_KEY}`)
    expect(entry.env.NODE_TLS_REJECT_UNAUTHORIZED).toBeUndefined()
  })

  it('omits NODE_TLS_REJECT_UNAUTHORIZED when no options object is passed', () => {
    const raw = generateClaudeDesktopConfig(SERVER_HTTP, API_KEY)
    const cfg = JSON.parse(raw)
    expect(cfg.mcpServers.giljo_hq.env.NODE_TLS_REJECT_UNAUTHORIZED).toBeUndefined()
  })

  it('output is pretty-printed JSON with 2-space indent (matches backend byte-for-byte)', () => {
    const raw = generateClaudeDesktopConfig(SERVER_HTTPS, API_KEY, { selfSigned: true })
    const expected = JSON.stringify(
      {
        mcpServers: {
          giljo_hq: {
            command: 'npx',
            args: [
              'mcp-remote',
              `${SERVER_HTTPS}/mcp`,
              '--header',
              'Authorization:${AUTH_HEADER}',
            ],
            env: {
              AUTH_HEADER: `Bearer ${API_KEY}`,
              NODE_TLS_REJECT_UNAUTHORIZED: '0',
            },
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
    const out = generateConfigForTool('claude_desktop', SERVER_HTTPS, API_KEY, { selfSigned: true })
    const cfg = JSON.parse(out)
    expect(cfg.mcpServers.giljo_hq.command).toBe('npx')
    expect(cfg.mcpServers.giljo_hq.env.NODE_TLS_REJECT_UNAUTHORIZED).toBe('0')
  })

  it('routes claude_desktop without options (no self-signed) correctly', () => {
    const out = generateConfigForTool('claude_desktop', SERVER_HTTP, API_KEY)
    const cfg = JSON.parse(out)
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
