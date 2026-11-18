import { describe, expect, it } from 'vitest'
import {
  SETUP_TOOLS,
  TOOL_META,
  toolName,
  methodTag,
  setupToolsFor,
  toolIdForSurface,
} from '@/config/setupTools'

describe('setupTools registry (FE-9204)', () => {
  it('lists the two directory tools first, then the four terminal/generic tools in order (FE-0034b)', () => {
    expect(SETUP_TOOLS.map((t) => t.id)).toEqual([
      'claude',
      'chatgpt',
      'claude_code',
      'codex_cli',
      'opencode',
      'generic',
    ])
  })

  it('every tool has a name and either a logo or an mdi icon', () => {
    for (const t of SETUP_TOOLS) {
      expect(t.name).toBeTruthy()
      expect(Boolean(t.logo) || Boolean(t.icon)).toBe(true)
    }
  })

  it('TOOL_META is keyed by id and toolName resolves it', () => {
    expect(TOOL_META.opencode.name).toBe('OpenCode')
    expect(toolName('generic')).toBe('Generic MCP client')
    expect(toolName('unknown_tool')).toBe('your tool')
  })
})

describe('methodTag — per-edition (proposal §3/§4)', () => {
  it('SaaS: sign-in-capable tools read SIGN-IN OR KEY', () => {
    for (const id of ['claude_code', 'codex_cli', 'opencode']) {
      expect(methodTag(id, false)).toBe('SIGN-IN OR KEY')
    }
  })

  it('generic client is always MANUAL CONFIG, both editions', () => {
    expect(methodTag('generic', false)).toBe('MANUAL CONFIG')
    expect(methodTag('generic', true)).toBe('MANUAL CONFIG')
  })

  it('CE: every non-generic tool reads API KEY', () => {
    for (const id of ['claude_code', 'codex_cli', 'opencode']) {
      expect(methodTag(id, true)).toBe('API KEY')
    }
  })
})

describe('directory tools (FE-0034b)', () => {
  it('claude and chatgpt carry method directory, an https directoryUrl and three desktop steps', () => {
    expect(TOOL_META.claude.name).toBe('Claude')
    expect(TOOL_META.chatgpt.name).toBe('ChatGPT')
    for (const id of ['claude', 'chatgpt']) {
      const t = TOOL_META[id]
      expect(t.method).toBe('directory')
      expect(t.directoryUrl).toMatch(/^https:\/\//)
      expect(t.desktopSteps).toHaveLength(3)
      expect(t.logo).toBeTruthy()
    }
    expect(TOOL_META.claude.directoryUrl).toBe('https://claude.ai/directory/giljo-hq')
    expect(TOOL_META.chatgpt.directoryUrl).toBe(
      'https://chatgpt.com/plugins/plugin_asdk_app_6ad81df7a0608191a87c20051d37ffdf',
    )
  })

  it('the four existing tools have no directory method', () => {
    for (const id of ['claude_code', 'codex_cli', 'opencode', 'generic']) {
      expect(TOOL_META[id].method).toBeUndefined()
    }
  })

  it('methodTag reads ONE CLICK for directory tools in both editions', () => {
    expect(methodTag('claude', false)).toBe('ONE CLICK')
    expect(methodTag('chatgpt', false)).toBe('ONE CLICK')
    expect(methodTag('claude', true)).toBe('ONE CLICK')
  })

  it('CE hides the two directory tiles; SaaS shows all six', () => {
    expect(setupToolsFor(true).map((t) => t.id)).toEqual(['claude_code', 'codex_cli', 'opencode', 'generic'])
    expect(setupToolsFor(false).map((t) => t.id)).toHaveLength(6)
  })

  it('hosted surfaces map to tiles; Codex-hosted and unknown surfaces map to nothing', () => {
    expect(toolIdForSurface('claude')).toBe('claude')
    expect(toolIdForSurface('chatgpt')).toBe('chatgpt')
    expect(toolIdForSurface('codex_hosted')).toBeNull()
    expect(toolIdForSurface(null)).toBeNull()
    expect(toolIdForSurface(undefined)).toBeNull()
  })
})
