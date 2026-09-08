/**
 * agentDisplay.spec.js — FE-9548
 *
 * Pure unit tests for the shared agent display helpers. isOrchestrator
 * predates this file's test coverage (only exercised indirectly via
 * AgentRow.spec.js); getPrimaryAgentLabel/getAgentRoleLabel are new
 * extractions this project introduces, so they get direct tests here.
 *
 * Edition scope: CE.
 */
import { describe, it, expect } from 'vitest'
import { isOrchestrator, getPrimaryAgentLabel, getAgentRoleLabel } from './agentDisplay'

describe('isOrchestrator', () => {
  it('is true when agent_name is orchestrator', () => {
    expect(isOrchestrator({ agent_name: 'orchestrator' })).toBe(true)
  })

  it('is true when agent_display_name is orchestrator', () => {
    expect(isOrchestrator({ agent_display_name: 'orchestrator' })).toBe(true)
  })

  it('is false for a specialist agent', () => {
    expect(isOrchestrator({ agent_display_name: 'implementer', agent_name: 'implementer-backend' })).toBe(false)
  })

  it('is false for null/undefined', () => {
    expect(isOrchestrator(null)).toBe(false)
    expect(isOrchestrator(undefined)).toBe(false)
  })
})

describe('getPrimaryAgentLabel', () => {
  it('returns "" for a null/undefined agent', () => {
    expect(getPrimaryAgentLabel(null)).toBe('')
    expect(getPrimaryAgentLabel(undefined)).toBe('')
  })

  it('prefers agent_name for the orchestrator, falling back to agent_display_name', () => {
    expect(getPrimaryAgentLabel({ agent_display_name: 'orchestrator', agent_name: 'Orchestrator' })).toBe(
      'Orchestrator',
    )
    expect(getPrimaryAgentLabel({ agent_display_name: 'orchestrator' })).toBe('orchestrator')
  })

  it('prefers agent_display_name for a specialist, falling back to agent_name', () => {
    expect(
      getPrimaryAgentLabel({ agent_display_name: 'implementer-backend', agent_name: 'CI2' }),
    ).toBe('implementer-backend')
    expect(getPrimaryAgentLabel({ agent_name: 'CI2' })).toBe('CI2')
  })
})

describe('getAgentRoleLabel', () => {
  it('returns "Fixed System Agent" for the orchestrator', () => {
    expect(getAgentRoleLabel({ agent_display_name: 'orchestrator' })).toBe('Fixed System Agent')
  })

  it('returns a title-cased role for each specialist template', () => {
    expect(getAgentRoleLabel({ agent_display_name: 'implementer-backend' })).toBe('Implementer')
    expect(getAgentRoleLabel({ agent_display_name: 'tester' })).toBe('Tester')
    expect(getAgentRoleLabel({ agent_display_name: 'reviewer' })).toBe('Reviewer')
    expect(getAgentRoleLabel({ agent_display_name: 'analyzer' })).toBe('Analyzer')
    expect(getAgentRoleLabel({ agent_display_name: 'documenter' })).toBe('Documenter')
  })

  it('resolves via agent_name when agent_display_name is a per-session suffix', () => {
    expect(getAgentRoleLabel({ role: 'implementer' })).toBe('Implementer')
  })
})
