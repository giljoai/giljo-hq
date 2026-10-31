import { describe, it, expect } from 'vitest'
import { contrastRatio, compositeOver, getAgentBadgeStyle } from '@/utils/colorUtils'
import { AGENT_COLORS, getAgentColor, getAgentColorKey } from '@/config/agentColors'

const SURFACES = ['#12202e', '#1e3147', '#243b53', '#283c51']
const withPill = (s) => compositeOver('#ffffff', s, 0.03)

describe('role badge helper at a 20% tint', () => {
  for (const role of Object.keys(AGENT_COLORS)) {
    it(`${role} reaches 4.5:1 at alpha 0.2 on every surface (and the Hub pill's 3% layer)`, () => {
      const { hex } = AGENT_COLORS[role]
      const { color, backgroundColor } = getAgentBadgeStyle(role, 0.2)
      expect(backgroundColor).toContain(', 0.2)')
      for (const s of SURFACES) {
        for (const base of [s, withPill(s)]) {
          expect(contrastRatio(color, compositeOver(hex, base, 0.2)), `${role} on ${base}`).toBeGreaterThanOrEqual(4.5)
        }
      }
    })
  }
})

describe('Hub participant to role colour', () => {
  const cases = [
    ['analyzer', 'Analyzer'],
    ['implementer', 'Implementer Frontend'],
    ['documenter', 'documenter'],
    ['tester', 'Tester'],
  ]
  for (const [role, display] of cases) {
    for (const membership of ['creator', 'auto-enrolled', 'member']) {
      it(`${display} enrolled as "${membership}" gets the ${role} colour`, () => {
        const key = getAgentColorKey({ role: membership, display_name: display })
        expect(getAgentColor(key).hex).toBe(AGENT_COLORS[role].hex)
      })
    }
  }
  it('a participant role that IS an agent role still wins over the display name', () => {
    expect(getAgentColor(getAgentColorKey({ role: 'reviewer', display_name: 'Orchestrator' })).hex).toBe(AGENT_COLORS.reviewer.hex)
  })
  it('nothing resolves: falls back to the first non-empty value as before', () => {
    expect(getAgentColorKey({ role: 'creator', display_name: 'Patrik' })).toBe('creator')
  })
})
