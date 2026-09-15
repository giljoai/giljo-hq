import { describe, expect, it } from 'vitest'
import { foldRetiredHarness, retiredHarnessLabel } from '@/config/retiredHarness'
import { SETUP_TOOLS, toolIdForHarness, harnessForToolId } from '@/config/setupTools'

describe('retiredHarness helpers (INF-9605a)', () => {
  it('labels every retired token as Generic (was <Name>)', () => {
    expect(retiredHarnessLabel('gemini')).toBe('Generic (was Gemini)')
    expect(retiredHarnessLabel('antigravity')).toBe('Generic (was Antigravity)')
    expect(retiredHarnessLabel('gemini_cli')).toBe('Generic (was Gemini CLI)')
    expect(retiredHarnessLabel('antigravity_cli')).toBe('Generic (was Antigravity CLI)')
  })

  it('returns null for live tokens and unknown values', () => {
    expect(retiredHarnessLabel('claude')).toBeNull()
    expect(retiredHarnessLabel('codex')).toBeNull()
    expect(retiredHarnessLabel('generic')).toBeNull()
    expect(retiredHarnessLabel(null)).toBeNull()
    expect(retiredHarnessLabel('something-else')).toBeNull()
  })

  it('folds retired tokens to generic and leaves everything else untouched', () => {
    expect(foldRetiredHarness('gemini')).toBe('generic')
    expect(foldRetiredHarness('antigravity')).toBe('generic')
    expect(foldRetiredHarness('claude')).toBe('claude')
    expect(foldRetiredHarness(undefined)).toBeUndefined()
  })
})

describe('setupTools after the retirement', () => {
  it('offers exactly the four surviving tools', () => {
    expect(SETUP_TOOLS.map((t) => t.id)).toEqual(['claude_code', 'codex_cli', 'opencode', 'generic'])
  })

  it('no longer maps the retired harness tokens to a card', () => {
    expect(toolIdForHarness('gemini')).toBeNull()
    expect(toolIdForHarness('antigravity')).toBeNull()
    expect(harnessForToolId('gemini_cli')).toBeNull()
    expect(harnessForToolId('antigravity_cli')).toBeNull()
  })
})
