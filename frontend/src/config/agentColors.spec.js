/**
 * agentColors.spec.js — FE-9490
 *
 * Regression coverage for the shared badge helpers introduced to consolidate
 * six copy-pasted initials-derivation sites and three drifting colour-key
 * priorities:
 *
 * Bug 1 — initials swallowed punctuation. Every copy split a display name on
 * `/[-_\s]+/` (or an equivalent) WITHOUT stripping other punctuation first, so
 * a parenthetical suffix like "Reviewer (Phase 5)" rendered as "R(" — a
 * literal bracket leaking into the badge.
 *
 * Bug 2 — the same agent could resolve to a different colour in different
 * views, because callers picked their own key priority (`role || display_name`
 * in the Hub composer/pill, `display_name` alone in the timeline,
 * `agent_name || agent_display_name` in the project agent rows).
 *
 * getAgentInitials() and getAgentColorKey() are the single source of truth
 * both bugs now route through.
 */

import { describe, it, expect } from 'vitest'
import { getAgentColor, getAgentColorKey, getAgentInitials } from './agentColors'

describe('getAgentInitials', () => {
  it('does not leak a bracket for a parenthetical name (the reported bug)', () => {
    expect(getAgentInitials('Reviewer (Phase 5)')).toBe('RP')
    expect(getAgentInitials('Reviewer (Phase 5)')).toMatch(/^[A-Z]{1,2}$/)
  })

  it('rejects other punctuation the same way', () => {
    expect(getAgentInitials('Reviewer: Phase 5')).toBe('RP')
    expect(getAgentInitials('Reviewer/Phase5')).not.toContain('/')
    expect(getAgentInitials('R(')).not.toContain('(')
  })

  it('returns first-letter-of-first-two-words for an ordinary multi-word name', () => {
    expect(getAgentInitials('Backend Implementer')).toBe('BI')
    expect(getAgentInitials('Backend-Implementer')).toBe('BI')
    expect(getAgentInitials('backend_implementer')).toBe('BI')
  })

  it('returns the first two characters for a single-word name', () => {
    expect(getAgentInitials('orchestrator')).toBe('OR')
  })

  it('falls back to ?? for empty, whitespace-only, or all-punctuation names', () => {
    expect(getAgentInitials('')).toBe('??')
    expect(getAgentInitials(null)).toBe('??')
    expect(getAgentInitials(undefined)).toBe('??')
    expect(getAgentInitials('   ')).toBe('??')
    expect(getAgentInitials('(())')).toBe('??')
  })

  it('handles a numeric word segment (e.g. "GPT-4") like the legacy split did', () => {
    expect(getAgentInitials('GPT-4')).toBe('G4')
  })
})

describe('getAgentColorKey', () => {
  it('prefers role over display_name for a Hub participant shape', () => {
    expect(getAgentColorKey({ role: 'reviewer', display_name: 'Reviewer (Phase 5)' })).toBe(
      'reviewer'
    )
  })

  it('prefers agent_name over agent_display_name for a job/agent-record shape', () => {
    expect(
      getAgentColorKey({ agent_name: 'implementer', agent_display_name: 'Backend Dev (contract)' })
    ).toBe('implementer')
  })

  it('falls back to display_name when no stable key is present', () => {
    expect(getAgentColorKey({ display_name: 'Reviewer (Phase 5)' })).toBe('Reviewer (Phase 5)')
  })

  it('falls back to agent_display_name when agent_name is absent', () => {
    expect(getAgentColorKey({ agent_display_name: 'Reviewer (Phase 5)' })).toBe(
      'Reviewer (Phase 5)'
    )
  })

  it('passes a plain string straight through', () => {
    expect(getAgentColorKey('orchestrator')).toBe('orchestrator')
  })

  it('returns an empty string for null/undefined (getAgentColor then floors to the default)', () => {
    expect(getAgentColorKey(null)).toBe('')
    expect(getAgentColorKey(undefined)).toBe('')
  })
})

describe('FE-9490 DoD: "Reviewer (Phase 5)" and "Reviewer" render identically', () => {
  it('yield the same colour', () => {
    const punctuated = getAgentColor(getAgentColorKey({ role: 'reviewer', display_name: 'Reviewer (Phase 5)' }))
    const plain = getAgentColor('Reviewer')
    expect(punctuated.hex).toBe(plain.hex)
  })

  it('yield alphabetic-only initials for the punctuated form', () => {
    expect(getAgentInitials('Reviewer (Phase 5)')).toMatch(/^[A-Z]+$/)
  })
})
