import { describe, it, expect } from 'vitest'
import { buildChainScreenControls, buildStopChainEffects } from './chainScreenVisibility.js'

const preRunCtx = {
  run: { id: 'r1', status: 'pending', execution_mode: 'subagent' },
  locked: true,
}
const runningCtx = {
  run: { id: 'r1', status: 'running', execution_mode: 'subagent' },
  locked: true,
}

describe('buildChainScreenControls — solo (no chain)', () => {
  it('is inert outside a chain: nothing shown, nothing hidden', () => {
    const c = buildChainScreenControls(null, false)
    expect(c.showStopChain).toBe(false)
    expect(c.showModeLabel).toBe(false)
  })
})

describe('buildChainScreenControls — pre-run (byte-identical to today)', () => {
  it('shows the Execution Mode selector', () => {
    expect(buildChainScreenControls(preRunCtx, false).showModeSelector).toBe(true)
  })

  it('shows the Stage/Unstage Chain button', () => {
    expect(buildChainScreenControls(preRunCtx, false).showStageButton).toBe(true)
  })

  it('shows the Implement button', () => {
    expect(buildChainScreenControls(preRunCtx, false).showImplementButton).toBe(true)
  })

  it('does NOT show Stop chain before the run starts', () => {
    expect(buildChainScreenControls(preRunCtx, false).showStopChain).toBe(false)
  })

  it('does NOT show the read-only mode label (the selector is still there)', () => {
    expect(buildChainScreenControls(preRunCtx, false).showModeLabel).toBe(false)
  })
})

describe('buildChainScreenControls — running', () => {
  it('HIDES the Execution Mode selector', () => {
    expect(buildChainScreenControls(runningCtx, true).showModeSelector).toBe(false)
  })

  it('HIDES Unstage Chain (it is server-refused while running anyway)', () => {
    expect(buildChainScreenControls(runningCtx, true).showStageButton).toBe(false)
  })

  it('HIDES Implement rather than merely disabling it', () => {
    expect(buildChainScreenControls(runningCtx, true).showImplementButton).toBe(false)
  })

  it('shows Stop chain', () => {
    expect(buildChainScreenControls(runningCtx, true).showStopChain).toBe(true)
  })

  it('shows the read-only mode label with the run mode', () => {
    const c = buildChainScreenControls(runningCtx, true)
    expect(c.showModeLabel).toBe(true)
    expect(c.modeLabel).toBe('subagent')
  })

  it('omits the mode label when execution_mode is null (decision #12, old runs)', () => {
    const ctx = { run: { id: 'r1', status: 'running', execution_mode: null }, locked: true }
    expect(buildChainScreenControls(ctx, true).showModeLabel).toBe(false)
  })

  it('omits the mode label when execution_mode is an empty string', () => {
    const ctx = { run: { id: 'r1', status: 'running', execution_mode: '' }, locked: true }
    expect(buildChainScreenControls(ctx, true).showModeLabel).toBe(false)
  })
})

describe('buildStopChainEffects — what the confirm modal narrates', () => {
  const run = {
    resolved_order: ['p1', 'p2', 'p3', 'p4', 'p5'],
    project_statuses: {
      p1: 'completed',
      p2: 'implementing',
      p3: 'pending',
      p4: 'pending',
      p5: 'pending',
    },
  }

  it('buckets the operator example exactly: 1 completed, 2 underway, 3-5 unstarted', () => {
    const e = buildStopChainEffects(run)
    expect(e.completed).toEqual([1])
    expect(e.underway).toEqual([2])
    expect(e.unstarted).toEqual([3, 4, 5])
  })

  it('numbers members by their position in resolved_order, 1-based', () => {
    const e = buildStopChainEffects({
      resolved_order: ['pX', 'pY'],
      project_statuses: { pX: 'completed', pY: 'implementing' },
    })
    expect(e.completed).toEqual([1])
    expect(e.underway).toEqual([2])
  })

  it('treats every terminal status as finished, not merely "completed"', () => {
    const e = buildStopChainEffects({
      resolved_order: ['p1', 'p2', 'p3'],
      project_statuses: { p1: 'failed', p2: 'terminated', p3: 'implementing' },
    })
    expect(e.completed).toEqual([1, 2])
    expect(e.underway).toEqual([3])
  })

  it('treats a member with no recorded status as unstarted', () => {
    const e = buildStopChainEffects({ resolved_order: ['p1', 'p2'], project_statuses: { p1: 'implementing' } })
    expect(e.unstarted).toEqual([2])
  })

  it("treats 'staged' as unstarted -- staged work has not begun", () => {
    const e = buildStopChainEffects({
      resolved_order: ['p1', 'p2'],
      project_statuses: { p1: 'implementing', p2: 'staged' },
    })
    expect(e.unstarted).toEqual([2])
  })

  it('handles a chain with nothing finished yet (no completed sentence to render)', () => {
    const e = buildStopChainEffects({
      resolved_order: ['p1', 'p2'],
      project_statuses: { p1: 'planning', p2: 'pending' },
    })
    expect(e.completed).toEqual([])
    expect(e.underway).toEqual([1])
    expect(e.unstarted).toEqual([2])
  })

  it('handles a missing run without throwing', () => {
    const e = buildStopChainEffects(null)
    expect(e).toEqual({ completed: [], underway: [], unstarted: [] })
  })

  it('falls back to project_ids when resolved_order is absent', () => {
    const e = buildStopChainEffects({
      project_ids: ['p1', 'p2'],
      project_statuses: { p1: 'completed', p2: 'implementing' },
    })
    expect(e.completed).toEqual([1])
    expect(e.underway).toEqual([2])
  })
})
