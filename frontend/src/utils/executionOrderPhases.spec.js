import { describe, it, expect } from 'vitest'
import { buildExecutionOrderPhases } from './executionOrderPhases'

const orch = { agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'working' }
const impl = { agent_display_name: 'implementer', phase: 1 }
const tester = { agent_display_name: 'tester', phase: 2 }
const reviewer = { agent_display_name: 'reviewer', phase: 2 }

describe('buildExecutionOrderPhases', () => {
  it('is null in subagent mode (the orchestrator runs the crew in one session)', () => {
    expect(buildExecutionOrderPhases([orch, impl], 'subagent')).toBeNull()
  })

  it('is null when no agent carries a phase yet', () => {
    expect(buildExecutionOrderPhases([orch, { agent_display_name: 'implementer' }], 'multi_terminal')).toBeNull()
  })

  it('starts with the orchestrator, then one phase per number, parallel when several share one', () => {
    const phases = buildExecutionOrderPhases([impl, orch, reviewer, tester], 'multi_terminal')
    expect(phases.map((p) => p.label)).toEqual(['Start', 'Phase 1', 'Phase 2 Parallel Execution'])
    expect(phases[0].agents.map((a) => a.displayName)).toEqual(['Orchestrator'])
    expect(phases[1].agents.map((a) => a.displayName)).toEqual(['implementer'])
    expect(phases[2].agents.map((a) => a.displayName).sort()).toEqual(['reviewer', 'tester'])
  })

  it('gives every agent a colour and a tinted background from the shared agent palette', () => {
    const phases = buildExecutionOrderPhases([orch, impl], 'multi_terminal')
    for (const phase of phases) {
      for (const agent of phase.agents) {
        expect(agent.color).toMatch(/^#[0-9a-fA-F]{6}$/)
        expect(agent.tintedBg).toMatch(/^rgba\(/)
      }
    }
  })

  it('a worker with no phase lands in a "?" phase after the numbered ones', () => {
    const phases = buildExecutionOrderPhases([orch, impl, { agent_display_name: 'documenter' }], 'multi_terminal')
    expect(phases.map((p) => p.label)).toEqual(['Start', 'Phase 1', 'Phase ?'])
  })
})
