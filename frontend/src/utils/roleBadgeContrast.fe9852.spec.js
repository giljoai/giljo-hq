import { describe, it, expect } from 'vitest'
import { contrastRatio, compositeOver, getAgentBadgeStyle } from '@/utils/colorUtils'
import { AGENT_COLORS } from '@/config/agentColors'

const SURFACES = ['#12202e', '#1e3147', '#243b53', '#283c51']

describe('role badge text contrast', () => {
  for (const role of Object.keys(AGENT_COLORS)) {
    it(`${role} reaches 4.5:1 on every surface`, () => {
      const { hex } = AGENT_COLORS[role]
      const { color } = getAgentBadgeStyle(role)
      for (const s of SURFACES) {
        expect(contrastRatio(color, compositeOver(hex, s, 0.15)), `${role} on ${s}`).toBeGreaterThanOrEqual(4.5)
      }
    })
  }
  it('keeps the tint background unchanged', () => {
    expect(getAgentBadgeStyle('orchestrator').backgroundColor).toBe('rgba(212, 176, 138, 0.15)')
  })
})
