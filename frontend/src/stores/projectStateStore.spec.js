
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useProjectStateStore } from './projectStateStore'

describe('projectStateStore — staging_complete (pre-existing baseline)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('setStagingComplete sets stagingComplete=true and isStaging=false', () => {
    const store = useProjectStateStore()
    store.setStagingComplete('proj-1', true)
    const state = store.getProjectState('proj-1')
    expect(state.stagingComplete).toBe(true)
    expect(state.isStaging).toBe(false)
  })

  it('handleStagingComplete patches the store from a WS payload', () => {
    const store = useProjectStateStore()
    store.handleStagingComplete({ project_id: 'proj-1', staging_status: 'staging_complete' })
    expect(store.getProjectState('proj-1').stagingComplete).toBe(true)
  })
})

describe('projectStateStore — CE-0029 Item 3 implementation_launched', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('defaults implementationLaunched=false and implementationLaunchedAt=null', () => {
    const store = useProjectStateStore()
    store.setProject({ id: 'proj-1', name: 'p', staging_status: 'staging' })
    const state = store.getProjectState('proj-1')
    expect(state.implementationLaunched).toBe(false)
    expect(state.implementationLaunchedAt).toBeNull()
  })

  it('normalizeProjectState hydrates implementationLaunched from API field', () => {
    const store = useProjectStateStore()
    store.setProject({
      id: 'proj-1',
      name: 'p',
      staging_status: 'staging_complete',
      implementation_launched_at: '2026-05-17T12:00:00Z',
    })
    const state = store.getProjectState('proj-1')
    expect(state.implementationLaunched).toBe(true)
    expect(state.implementationLaunchedAt).toBe('2026-05-17T12:00:00Z')
  })

  it('setImplementationLaunched(projectId, timestamp) patches both fields', () => {
    const store = useProjectStateStore()
    store.setImplementationLaunched('proj-1', '2026-05-17T13:00:00Z')
    const state = store.getProjectState('proj-1')
    expect(state.implementationLaunched).toBe(true)
    expect(state.implementationLaunchedAt).toBe('2026-05-17T13:00:00Z')
  })

  it('setImplementationLaunched(projectId, null) clears both fields', () => {
    const store = useProjectStateStore()
    store.setImplementationLaunched('proj-1', '2026-05-17T13:00:00Z')
    store.setImplementationLaunched('proj-1', null)
    const state = store.getProjectState('proj-1')
    expect(state.implementationLaunched).toBe(false)
    expect(state.implementationLaunchedAt).toBeNull()
  })

  it('handleImplementationLaunched patches the store from a WS payload', () => {
    const store = useProjectStateStore()
    store.handleImplementationLaunched({
      project_id: 'proj-1',
      implementation_launched_at: '2026-05-17T14:00:00Z',
    })
    const state = store.getProjectState('proj-1')
    expect(state.implementationLaunched).toBe(true)
    expect(state.implementationLaunchedAt).toBe('2026-05-17T14:00:00Z')
  })

  it('handleImplementationLaunched ignores payloads without project_id', () => {
    const store = useProjectStateStore()
    store.handleImplementationLaunched({})
    expect(store.stateByProjectId.size).toBe(0)
  })

  it('handleImplementationLaunched preserves stagingComplete on the same project', () => {
    const store = useProjectStateStore()
    store.handleStagingComplete({ project_id: 'proj-1' })
    store.handleImplementationLaunched({
      project_id: 'proj-1',
      implementation_launched_at: '2026-05-17T14:00:00Z',
    })
    const state = store.getProjectState('proj-1')
    expect(state.stagingComplete).toBe(true)
    expect(state.implementationLaunched).toBe(true)
    expect(state.implementationLaunchedAt).toBe('2026-05-17T14:00:00Z')
  })
})

describe('projectStateStore — BE-6047 unstage/restage mission clearing (lock-release regression)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetModules()
  })

  it('unstageProject clears mission to empty string so isExecutionModeLocked releases', async () => {
    vi.doMock('@/services/api', () => ({
      default: { projects: { unstage: vi.fn().mockResolvedValue({}) } },
    }))
    const { useProjectStateStore: useStore } = await import('./projectStateStore')
    const store = useStore()
    store.setProject({ id: 'proj-1', mission: 'some orchestrator mission', staging_status: 'staged' })
    await store.unstageProject('proj-1')
    const state = store.getProjectState('proj-1')
    expect(state.mission).toBe('')
    expect(state.isStaged).toBe(false)
    expect(state.isStaging).toBe(false)
  })

  it('restageProject clears mission AND impl-launch fields so lock releases', async () => {
    vi.doMock('@/services/api', () => ({
      default: { projects: { restage: vi.fn().mockResolvedValue({}) } },
    }))
    const { useProjectStateStore: useStore } = await import('./projectStateStore')
    const store = useStore()
    store.setProject({ id: 'proj-1', mission: 'old mission', staging_status: 'staging_complete' })
    await store.restageProject('proj-1')
    const state = store.getProjectState('proj-1')
    expect(state.mission).toBe('')
    expect(state.isStaged).toBe(false)
    expect(state.isStaging).toBe(false)
    expect(state.stagingComplete).toBe(false)
    expect(state.implementationLaunched).toBe(false)
    expect(state.implementationLaunchedAt).toBeNull()
  })
})

describe('projectStateStore — $reset (TSK-9372)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('$reset clears stateByProjectId back to an empty Map', () => {
    const store = useProjectStateStore()
    store.setProject({ id: 'proj-1', mission: 'm', status: 'active', staging_status: 'staged' })
    store.setStagingComplete('proj-2', true)
    expect(store.stateByProjectId.size).toBe(2)

    store.$reset()

    expect(store.stateByProjectId.size).toBe(0)
    expect(store.getProjectState('proj-1')).toBeNull()
    expect(store.getProjectState('proj-2')).toBeNull()
  })
})

describe('projectStateStore — FE-9122 isLaunched monotonic guard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('setProject with a complete entity that carries no isLaunched field does not clobber a true isLaunched', () => {
    const store = useProjectStateStore()
    store.setProject({ id: 'proj-1', mission: 'm', staging_status: 'staging' })
    store.setLaunched('proj-1', true)
    expect(store.getProjectState('proj-1').isLaunched).toBe(true)

    store.setProject({ id: 'proj-1', mission: 'm', status: 'active', staging_status: 'staging' })

    expect(store.getProjectState('proj-1').isLaunched).toBe(true)
  })

  it('an explicit setLaunched(id, false) still clears isLaunched (bypasses the monotonic guard)', () => {
    const store = useProjectStateStore()
    store.setProject({ id: 'proj-1', mission: 'm' })
    store.setLaunched('proj-1', true)
    expect(store.getProjectState('proj-1').isLaunched).toBe(true)

    store.setLaunched('proj-1', false)

    expect(store.getProjectState('proj-1').isLaunched).toBe(false)
  })
})
