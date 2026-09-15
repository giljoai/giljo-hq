import { describe, expect, it } from 'vitest'
import { SETUP_TOOLS, TOOL_META, toolName, methodTag } from '@/config/setupTools'

describe('setupTools registry (FE-9204)', () => {
  it('lists exactly the four connectable tools, in order (INF-9605a)', () => {
    expect(SETUP_TOOLS.map((t) => t.id)).toEqual(['claude_code', 'codex_cli', 'opencode', 'generic'])
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
