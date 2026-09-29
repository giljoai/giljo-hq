import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const { getProjectMock } = vi.hoisted(() => ({ getProjectMock: vi.fn() }))

vi.mock('@/services/api', () => {
  const api = { projects: { get: (...a) => getProjectMock(...a) } }
  return { default: api, api }
})

import { useChainContext } from '@/composables/useChainContext'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'

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
    conductor_label: 'Conductor A',
    locked: false,
    ...overrides,
  }
}

function makeProject(id, overrides = {}) {
  return { id, name: `Project ${id}`, taxonomy_alias: `FE-${id}`, product_id: 'prod-1', ...overrides }
}

let store

async function contextFor(opts) {
  const ctx = useChainContext(opts)
  await flushPromises()
  return ctx
}

beforeEach(() => {
  setActivePinia(createPinia())
  store = useSequenceRunStore()
  vi.clearAllMocks()
  getProjectMock.mockImplementation(async (id) => ({ data: makeProject(id) }))
})

describe('useChainContext — null contract', () => {
  it('is null with neither a run id nor a project id', async () => {
    store._testSeedRuns([makeRun()])
    const { chainCtx } = await contextFor()
    expect(chainCtx.value).toBeNull()
  })

  it('is null for a run the viewed product does not have', async () => {
    store._testSeedRuns([makeRun()])
    const { chainCtx } = await contextFor({ runId: () => 'run-other' })
    expect(chainCtx.value).toBeNull()
  })

  it('is null for a project in no chain (the solo page)', async () => {
    store._testSeedRuns([makeRun()])
    const { chainCtx } = await contextFor({ projectId: () => 'p-solo' })
    expect(chainCtx.value).toBeNull()
  })
})

describe('useChainContext — finding the run', () => {
  it('finds the run by id (board group)', async () => {
    store._testSeedRuns([makeRun()])
    const { chainCtx } = await contextFor({ runId: () => 'run-1' })
    expect(chainCtx.value.runId).toBe('run-1')
  })

  it('finds the run by member project (member page)', async () => {
    store._testSeedRuns([makeRun()])
    const { chainCtx } = await contextFor({ projectId: () => 'p2' })
    expect(chainCtx.value.runId).toBe('run-1')
  })

  it('also finds a finished run whose members still wait for review', async () => {
    store._testSeedReviewPending([makeRun({ status: 'completed' })])
    const { chainCtx } = await contextFor({ projectId: () => 'p3' })
    expect(chainCtx.value.runId).toBe('run-1')
  })

  it('follows the store live: a sequence:updated re-hydrate moves the counter', async () => {
    store._testSeedRuns([makeRun()])
    const { chainCtx } = await contextFor({ runId: () => 'run-1' })
    expect(chainCtx.value.counter).toEqual({ n: 1, m: 3 })
    store._testSeedRuns([makeRun({ current_index: 1 })])
    expect(chainCtx.value.counter).toEqual({ n: 2, m: 3 })
  })
})

describe('useChainContext — chain bundle', () => {
  it('warms the project store for each member and lists them in run order', async () => {
    store._testSeedRuns([makeRun({ resolved_order: ['p3', 'p1', 'p2'] })])
    const { chainCtx } = await contextFor({ runId: () => 'run-1' })
    expect(getProjectMock).toHaveBeenCalledTimes(3)
    expect(chainCtx.value.projects.map((p) => p.id)).toEqual(['p3', 'p1', 'p2'])
    expect(chainCtx.value.tabs.map((t) => t.projectId)).toEqual(['p3', 'p1', 'p2'])
  })

  it('skips a member that no longer resolves and keeps the rest', async () => {
    getProjectMock.mockImplementation(async (id) => {
      if (id === 'p2') throw new Error('404')
      return { data: makeProject(id) }
    })
    store._testSeedRuns([makeRun()])
    const { chainCtx } = await contextFor({ runId: () => 'run-1' })
    expect(chainCtx.value.projects.map((p) => p.id)).toEqual(['p1', 'p3'])
  })

  it('exposes chainMission, locked and the conductor from the run', async () => {
    store._testSeedRuns([makeRun({ chain_mission: 'Ship it', locked: true })])
    const { chainCtx } = await contextFor({ runId: () => 'run-1' })
    expect(chainCtx.value.chainMission).toBe('Ship it')
    expect(chainCtx.value.locked).toBe(true)
    expect(chainCtx.value.conductor.agentId).toBe('cond-agent')
  })

  it('names the chain from the goal heading, else from the member aliases', async () => {
    store._testSeedRuns([makeRun({ chain_mission: '# Chain mission: One Jobs board\nbody' })])
    const named = await contextFor({ runId: () => 'run-1' })
    expect(named.chainCtx.value.name).toBe('One Jobs board')

    setActivePinia(createPinia())
    store = useSequenceRunStore()
    store._testSeedRuns([makeRun({ chain_mission: 'plain goal, no heading' })])
    const unnamed = await contextFor({ runId: () => 'run-1' })
    expect(unnamed.chainCtx.value.name).toBe('FE-p1 → FE-p2 → FE-p3')
  })
})

describe('useChainContext — member states', () => {
  it('derives completed / current / needsReview from the run', async () => {
    store._testSeedRuns([
      makeRun({ current_index: 1, project_statuses: { p1: 'completed', p2: 'implementing', p3: 'pending' } }),
    ])
    const { chainCtx } = await contextFor({ runId: () => 'run-1' })
    const [t1, t2, t3] = chainCtx.value.tabs
    expect([t1.isCompleted, t1.needsReview, t1.isCurrent]).toEqual([true, true, false])
    expect([t2.isWorking, t2.isCurrent]).toEqual([true, true])
    expect([t3.isStarted, t3.isCurrent]).toEqual([false, false])
  })

  it('a reviewed member no longer needs review', async () => {
    store._testSeedRuns([makeRun({ project_statuses: { p1: 'completed' }, reviewed_project_ids: ['p1'] })])
    store.markReviewed('run-1', 'p1')
    const { chainCtx } = await contextFor({ runId: () => 'run-1' })
    expect(chainCtx.value.tabs[0].needsReview).toBe(false)
  })

  it("isPlanning reads only the run's own 'planning' status (FE-9493)", async () => {
    store._testSeedRuns([
      makeRun({ project_statuses: { p1: 'implementing', p2: 'planning', p3: 'staged' } }),
    ])
    const { chainCtx } = await contextFor({ runId: () => 'run-1' })
    const [t1, t2, t3] = chainCtx.value.tabs
    expect(t1.isPlanning).toBe(false)
    expect(t2.isPlanning).toBe(true)
    expect(t3.isPlanning).toBe(false)
  })
})
