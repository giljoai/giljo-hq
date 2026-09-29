import { describe, it, expect } from 'vitest'
import { orderAgentsForDisplay } from './agentDisplayOrder'

const orch = { agent_id: 'a-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator' }
const impl = { agent_id: 'a-im', agent_display_name: 'implementer', phase: 2 }
const tester = { agent_id: 'a-te', agent_display_name: 'tester', phase: 1 }
const noPhase = { agent_id: 'a-np', agent_display_name: 'documenter' }

describe('orderAgentsForDisplay', () => {
  it('puts the orchestrator first whatever position the store handed it', () => {
    expect(orderAgentsForDisplay([impl, orch]).map((a) => a.agent_id)).toEqual(['a-or', 'a-im'])
    expect(orderAgentsForDisplay([impl, tester, orch]).map((a) => a.agent_id)).toEqual(['a-or', 'a-te', 'a-im'])
  })

  it('orders workers by phase, and a worker with no phase last', () => {
    expect(orderAgentsForDisplay([noPhase, impl, tester]).map((a) => a.agent_id)).toEqual(['a-te', 'a-im', 'a-np'])
  })

  it('is stable for equal phases and does not mutate its input', () => {
    const a = { agent_id: 'a', phase: 1 }
    const b = { agent_id: 'b', phase: 1 }
    const input = [b, a]
    expect(orderAgentsForDisplay(input).map((x) => x.agent_id)).toEqual(['b', 'a'])
    expect(input.map((x) => x.agent_id)).toEqual(['b', 'a'])
  })

  it('tolerates an empty or missing list', () => {
    expect(orderAgentsForDisplay([])).toEqual([])
    expect(orderAgentsForDisplay(undefined)).toEqual([])
  })
})
