import { describe, it, expect } from 'vitest'
import { hexToRgba, getAgentBadgeStyle } from '@/utils/colorUtils'

describe('colorUtils', () => {
  describe('hexToRgba', () => {
    it('converts hex to rgba', () => {
      expect(hexToRgba('#D4B08A', 0.15)).toBe('rgba(212, 176, 138, 0.15)')
    })

    it('handles full opacity', () => {
      expect(hexToRgba('#FF0000', 1)).toBe('rgba(255, 0, 0, 1)')
    })
  })

  describe('getAgentBadgeStyle', () => {
    it('returns style object for known agent', () => {
      const style = getAgentBadgeStyle('orchestrator')
      expect(style.backgroundColor).toContain('rgba(212, 176, 138, 0.15)')
      expect(style.color).toBe('#D4B08A')
    })

    it('returns style for synonym agent name', () => {
      const style = getAgentBadgeStyle('implementor')
      expect(style.color).toBe('#6DB3E4')
    })

    it('falls back to orchestrator for unknown agent', () => {
      const style = getAgentBadgeStyle('unknown-agent')
      expect(style.color).toBe('#D4B08A')
    })

    it('handles null/undefined gracefully', () => {
      const style = getAgentBadgeStyle(null)
      expect(style).toHaveProperty('backgroundColor')
      expect(style).toHaveProperty('color')
    })

    it('never returns borderRadius: the badge class owns the shape', () => {
      const style = getAgentBadgeStyle('orchestrator')
      expect(style).not.toHaveProperty('borderRadius')
    })
  })
})
