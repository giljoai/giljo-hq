/**
 * useChainContext.spec.js — FE-6174b
 *
 * Unit tests for the harvested conditional-chain-layer data source. All external
 * dependencies are mocked; the composable is driven via loadRun() directly
 * (mirrors useChainCockpit.spec.js — bypasses the route watcher).
 *
 * Edition scope: CE.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'

const {
  routeMock,
  fetchRunMock,
  fetchProjectMock,
  projectByIdMock,
  getProjectStateMock,
  registerResyncMock,
  isReviewedMock,
} = vi.hoisted(() => ({
  routeMock: { query: {} },
  fetchRunMock: vi.fn(),
  fetchProjectMock: vi.fn(),
  projectByIdMock: vi.fn(),
  getProjectStateMock: vi.fn(() => null),
  registerResyncMock: vi.fn(() => vi.fn()),
  // Defaults to "not reviewed" so completed members show needsReview=true by default.
  isReviewedMock: vi.fn(() => false),
}))

vi.mock('vue-router', () => ({
  useRoute: () => routeMock,
}))

vi.mock('@/stores/sequenceRunStore', () => ({
  useSequenceRunStore: () => ({
    fetchRun: fetchRunMock,
    activeRun: ref(null),
    isReviewed: isReviewedMock,
    markReviewed: vi.fn(),
  }),
}))

vi.mock('@/stores/projectStateStore', () => ({
  useProjectStateStore: () => ({
    getProjectState: getProjectStateMock,
  }),
}))

vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({
    fetchProject: fetchProjectMock,
    projectById: projectByIdMock,
  }),
}))

vi.mock('@/stores/websocketEventRouter', () => ({
  registerReconnectResync: registerResyncMock,
}))

vi.mock('@/composables/useAgentJobs', () => ({
  useAgentJobs: () => ({ sortedJobs: { value: [] } }),
}))

// Import AFTER mocks
import { useChainContext } from '@/composables/useChainContext'

function makeRun(overrides = {}) {
  return {
    id: 'run-1',
    project_ids: ['p1', 'p2', 'p3'],
    resolved_order: ['p1', 'p2', 'p3'],
    current_index: 0,
    status: 'pending',
    execution_mode: 'multi_terminal',
    project_statuses: {},
    conductor_agent_id: 'cond-agent',
    conductor_project_id: 'p1',
    conductor_label: 'Conductor A',
    locked: false,
    ...overrides,
  }
}

function makeProject(id, overrides = {}) {
  return {
    id,
    name: `Project ${id}`,
    taxonomy_alias: `FE-${id}`,
    product_id: 'prod-1',
    mission: '',
    ...overrides,
  }
}

let ctx
function setup() {
  setActivePinia(createPinia())
  ctx = useChainContext()
}

beforeEach(() => {
  vi.clearAllMocks()
  routeMock.query = {}
  fetchRunMock.mockResolvedValue(makeRun())
  // resolveProjects warms the store via fetchProject then reads back via projectById.
  fetchProjectMock.mockResolvedValue(undefined)
  projectByIdMock.mockImplementation((id) => makeProject(id))
  getProjectStateMock.mockReturnValue(null)
  registerResyncMock.mockReturnValue(vi.fn())
  isReviewedMock.mockReturnValue(false) // default: not reviewed
})

describe('useChainContext — null contract (deletion test)', () => {
  it('chainCtx is null when no run is loaded', () => {
    setup()
    expect(ctx.chainCtx.value).toBeNull()
  })

  it('chainCtx stays null after loadRun(null)', async () => {
    setup()
    await ctx.loadRun(null)
    await flushPromises()
    expect(ctx.chainCtx.value).toBeNull()
    expect(ctx.projects.value).toHaveLength(0)
  })

  it('falls back to null when fetchRun throws (unknown/foreign run)', async () => {
    fetchRunMock.mockRejectedValue(new Error('not found'))
    setup()
    await ctx.loadRun('bad')
    await flushPromises()
    expect(ctx.chainCtx.value).toBeNull()
  })

  it('degrades to solo when ALL members 404 (orphaned run — FE-6175 RC2)', async () => {
    // Every member fetch rejects (hard-deleted) -> zero resolvable projects.
    fetchProjectMock.mockRejectedValue(new Error('404'))
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    expect(ctx.chainCtx.value).toBeNull()
    expect(ctx.run.value).toBeNull()
    expect(ctx.projects.value).toHaveLength(0)
  })

  it('keeps the run + skips only the dead member when SOME members resolve (partial orphan)', async () => {
    // p2 is hard-deleted; p1 + p3 resolve. The run stays, p2 is dropped.
    fetchProjectMock.mockImplementation((id) =>
      id === 'p2' ? Promise.reject(new Error('404')) : Promise.resolve(undefined),
    )
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    expect(ctx.run.value).not.toBeNull()
    expect(ctx.projects.value.map((p) => p.id)).toEqual(['p1', 'p3'])
  })
})

describe('useChainContext — chain bundle', () => {
  it('warms the project store for each chain project (no cold tab-switch refetch)', async () => {
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    // resolveProjects must warm projectStore (NOT a raw axios GET) so a sibling
    // tab switch finds the project already resident — the FE-6174b fix for the
    // spinner unmount/remount + double-fetch regression.
    expect(fetchProjectMock).toHaveBeenCalledWith('p1')
    expect(fetchProjectMock).toHaveBeenCalledWith('p2')
    expect(fetchProjectMock).toHaveBeenCalledWith('p3')
  })

  it('builds the bundle + ordered projects on loadRun', async () => {
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    expect(fetchRunMock).toHaveBeenCalledWith('run-1')
    expect(ctx.chainCtx.value).not.toBeNull()
    expect(ctx.chainCtx.value.tabs.map((t) => t.projectId)).toEqual(['p1', 'p2', 'p3'])
    expect(ctx.chainCtx.value.conductor).toEqual({
      agentId: 'cond-agent',
      projectId: 'p1',
      label: 'Conductor A',
    })
  })

  it('counter starts at 1/M and reflects current_index', async () => {
    fetchRunMock.mockResolvedValue(makeRun({ current_index: 0 }))
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    expect(ctx.chainCtx.value.counter).toEqual({ n: 1, m: 3 })
  })

  it('counter advances with current_index (2/3)', async () => {
    fetchRunMock.mockResolvedValue(makeRun({ current_index: 1 }))
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    expect(ctx.chainCtx.value.counter).toEqual({ n: 2, m: 3 })
    expect(ctx.chainCtx.value.currentPid).toBe('p2')
  })

  it('locked reflects run.locked', async () => {
    fetchRunMock.mockResolvedValue(makeRun({ locked: true }))
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    expect(ctx.chainCtx.value.locked).toBe(true)
  })
})

describe('useChainContext — tab states', () => {
  it('derives isCompleted / isCurrent flags from project_statuses', async () => {
    fetchRunMock.mockResolvedValue(
      makeRun({
        current_index: 1,
        project_statuses: { p1: 'completed', p2: 'running', p3: 'pending' },
      }),
    )
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    const [t1, t2] = ctx.chainCtx.value.tabs
    expect(t1.isCompleted).toBe(true)
    expect(t2.isCurrent).toBe(true)
  })

  it('needsReview is true for a completed + unreviewed member (chain review fix)', async () => {
    fetchRunMock.mockResolvedValue(
      makeRun({
        project_statuses: { p1: 'completed', p2: 'pending', p3: 'pending' },
      }),
    )
    isReviewedMock.mockReturnValue(false) // not reviewed
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    const [t1, t2] = ctx.chainCtx.value.tabs
    expect(t1.needsReview).toBe(true)  // completed + not reviewed
    expect(t2.needsReview).toBe(false) // pending — not completed
  })

  it('needsReview is false when isReviewed returns true (already confirmed)', async () => {
    fetchRunMock.mockResolvedValue(
      makeRun({ project_statuses: { p1: 'completed', p2: 'pending', p3: 'pending' } }),
    )
    isReviewedMock.mockReturnValue(true) // already reviewed
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    const [t1] = ctx.chainCtx.value.tabs
    expect(t1.isCompleted).toBe(true)
    expect(t1.needsReview).toBe(false) // completed but reviewed
  })

  it('needsReview is false for awaiting_review status (dead state — BE never writes it)', async () => {
    fetchRunMock.mockResolvedValue(
      makeRun({
        current_index: 1,
        project_statuses: { p1: 'completed', p2: 'running', p3: 'awaiting_review' },
      }),
    )
    isReviewedMock.mockReturnValue(false)
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    const [t1, , t3] = ctx.chainCtx.value.tabs
    expect(t1.needsReview).toBe(true)  // completed + not reviewed
    expect(t3.needsReview).toBe(false) // awaiting_review ≠ 'completed' → dead state
  })
})

describe('useChainContext — headMission', () => {
  it('prefers the live projectState mission', async () => {
    getProjectStateMock.mockImplementation((id) =>
      id === 'p1' ? { mission: 'Live WS mission' } : null,
    )
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    expect(ctx.chainCtx.value.headMission).toBe('Live WS mission')
  })

  it('falls back to the head project record mission', async () => {
    projectByIdMock.mockImplementation((id) =>
      makeProject(id, { mission: id === 'p1' ? 'Record mission' : '' }),
    )
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    expect(ctx.chainCtx.value.headMission).toBe('Record mission')
  })
})

describe('useChainContext — resync', () => {
  it('registers a reconnect resync callback', () => {
    setup()
    expect(registerResyncMock).toHaveBeenCalled()
  })
})

describe('useChainContext — tab isWorking derivation (bug fix: position != activity)', () => {
  it('staging-head bug repro: current-head with pending status has isWorking===false', async () => {
    // Bug repro: current_index=0 but p1 is still pending (sub-orchestrator not started).
    // Old code keyed on isCurrent, so this would have driven a WORKING badge prematurely.
    fetchRunMock.mockResolvedValue(
      makeRun({
        current_index: 0,
        project_statuses: { p1: 'pending', p2: 'implementing', p3: 'staged' },
      }),
    )
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    const [t1, t2, t3] = ctx.chainCtx.value.tabs
    // The current-position tab is NOT working — still pending
    expect(t1.isCurrent).toBe(true)
    expect(t1.isWorking).toBe(false)
    // Only the implementing member is working
    expect(t2.isWorking).toBe(true)
    // staged is not a recognized working status
    expect(t3.isWorking).toBe(false)
  })

  it('isWorking is true only for implementing (and synonym) statuses', async () => {
    fetchRunMock.mockResolvedValue(
      makeRun({
        project_statuses: { p1: 'implementing', p2: 'pending', p3: 'completed' },
      }),
    )
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    const [t1, t2, t3] = ctx.chainCtx.value.tabs
    expect(t1.isWorking).toBe(true)
    expect(t2.isWorking).toBe(false)
    expect(t3.isWorking).toBe(false)
  })

  it('isWorking is false when status is empty (not yet seeded)', async () => {
    fetchRunMock.mockResolvedValue(makeRun({ project_statuses: {} }))
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    const [t1] = ctx.chainCtx.value.tabs
    expect(t1.isWorking).toBe(false)
  })
})

describe('useChainContext — tab isPlanning derivation (FE-9239)', () => {
  it('isPlanning is true when staging_status is "staging" (record fallback, no live state)', async () => {
    projectByIdMock.mockImplementation((id) =>
      makeProject(id, { staging_status: id === 'p1' ? 'staging' : '' }),
    )
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    const [t1, t2] = ctx.chainCtx.value.tabs
    expect(t1.isPlanning).toBe(true)
    expect(t2.isPlanning).toBe(false)
  })

  it('isPlanning is true when staging_status is "staged"', async () => {
    projectByIdMock.mockImplementation((id) =>
      makeProject(id, { staging_status: id === 'p1' ? 'staged' : '' }),
    )
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    const [t1] = ctx.chainCtx.value.tabs
    expect(t1.isPlanning).toBe(true)
  })

  it('isPlanning is false for staging_complete (default: falls through to WAITING, not PLANNING)', async () => {
    projectByIdMock.mockImplementation((id) =>
      makeProject(id, { staging_status: id === 'p1' ? 'staging_complete' : '' }),
    )
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    const [t1] = ctx.chainCtx.value.tabs
    expect(t1.isPlanning).toBe(false)
  })

  it('isPlanning is false for a completed member even if staging_status is stale "staging"', async () => {
    fetchRunMock.mockResolvedValue(
      makeRun({ project_statuses: { p1: 'completed', p2: 'pending', p3: 'pending' } }),
    )
    projectByIdMock.mockImplementation((id) =>
      makeProject(id, { staging_status: id === 'p1' ? 'staging' : '' }),
    )
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    const [t1] = ctx.chainCtx.value.tabs
    expect(t1.isCompleted).toBe(true)
    expect(t1.isPlanning).toBe(false)
  })

  it('isPlanning is false for a working (implementing) member even if staging_status is stale "staged"', async () => {
    fetchRunMock.mockResolvedValue(
      makeRun({ project_statuses: { p1: 'implementing', p2: 'pending', p3: 'pending' } }),
    )
    projectByIdMock.mockImplementation((id) =>
      makeProject(id, { staging_status: id === 'p1' ? 'staged' : '' }),
    )
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    const [t1] = ctx.chainCtx.value.tabs
    expect(t1.isWorking).toBe(true)
    expect(t1.isPlanning).toBe(false)
  })

  it('prefers the live projectStateStore flags over the record staging_status fallback (live says staging)', async () => {
    getProjectStateMock.mockImplementation((id) =>
      id === 'p1' ? { isStaging: true, isStaged: false } : null,
    )
    projectByIdMock.mockImplementation((id) => makeProject(id, { staging_status: '' }))
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    const [t1] = ctx.chainCtx.value.tabs
    expect(t1.isPlanning).toBe(true)
  })

  it('live store flags override a stale record staging_status (record says staging, live says settled)', async () => {
    getProjectStateMock.mockImplementation((id) =>
      id === 'p1' ? { isStaging: false, isStaged: false } : null,
    )
    projectByIdMock.mockImplementation((id) =>
      makeProject(id, { staging_status: id === 'p1' ? 'staging' : '' }),
    )
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    const [t1] = ctx.chainCtx.value.tabs
    expect(t1.isPlanning).toBe(false)
  })
})

describe('useChainContext — chainMission (FE-6199 B2)', () => {
  it('exposes chainMission from run.chain_mission (not headMission)', async () => {
    fetchRunMock.mockResolvedValue(makeRun({ chain_mission: 'Ship the whole product' }))
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    expect(ctx.chainCtx.value.chainMission).toBe('Ship the whole product')
  })

  it('chainMission is empty string when run has no chain_mission', async () => {
    fetchRunMock.mockResolvedValue(makeRun({ chain_mission: null }))
    setup()
    await ctx.loadRun('run-1')
    await flushPromises()
    expect(ctx.chainCtx.value.chainMission).toBe('')
  })

  it('chainCtx is null when no run is loaded (solo invariant)', () => {
    setup()
    expect(ctx.chainCtx.value).toBeNull()
  })
})
