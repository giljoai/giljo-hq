import { describe, it, expect } from 'vitest'
import { harnessLabel } from '@/components/hub/rosterState'

describe('Hub harness label for chat apps', () => {
  it('names the Claude and ChatGPT apps instead of a generic harness', () => {
    expect(harnessLabel('claude')).toBe('Claude')
    expect(harnessLabel('chatgpt')).toBe('ChatGPT')
    expect(harnessLabel('hermes')).toBe('Hermes')
  })

  it('keeps every other label as it was', () => {
    expect(harnessLabel('generic')).toBe('Generic Harness')
    expect(harnessLabel('')).toBe('Generic Harness')
    expect(harnessLabel('OpenCode · Qwen')).toBe('OpenCode')
  })

  it('writes the CLI harnesses by their proper names', () => {
    expect(harnessLabel('claude-code')).toBe('Claude Code')
    expect(harnessLabel('codex')).toBe('Codex')
    expect(harnessLabel('opencode')).toBe('OpenCode')
    expect(harnessLabel('gemini')).toBe('Gemini CLI')
    expect(harnessLabel('antigravity')).toBe('Antigravity')
    expect(harnessLabel('OpenCode · Qwen')).toBe('OpenCode')
  })
})
