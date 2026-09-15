import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref, computed, defineComponent } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'


const {
  mockSubscribeToProject,
  mockUnsubscribe,
  mockOnConnectionChange,
  mockWsOn,
  mockRegisterReconnectResync,
  mockUnregisterReconnectResync,
  resyncState,
} = vi.hoisted(() => {
  const resyncState = { callback: null }
  const mockUnregisterReconnectResync = vi.fn()
  return {
    mockSubscribeToProject: vi.fn(),
    mockUnsubscribe: vi.fn(),
    mockOnConnectionChange: vi.fn().mockReturnValue(vi.fn()),
    mockWsOn: vi.fn().mockImplementation(() => vi.fn()),
    mockUnregisterReconnectResync,
    mockRegisterReconnectResync: vi.fn((cb) => {
      resyncState.callback = cb
      return mockUnregisterReconnectResync
    }),
    resyncState,
  }
})

vi.mock('@/stores/websocketEventRouter', () => ({
  registerReconnectResync: mockRegisterReconnectResync,
}))

const mockLoadJobs = vi.fn().mockResolvedValue([])
const mockApiProjectsGet = vi.fn()
const mockSetProject = vi.fn()
const mockSetStagingComplete = vi.fn()

vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    subscribeToProject: mockSubscribeToProject,
    unsubscribe: mockUnsubscribe,
    onConnectionChange: mockOnConnectionChange,
    on: mockWsOn,
  }),
}))

vi.mock('@/composables/useAgentJobs', () => ({
  useAgentJobs: () => ({ loadJobs: mockLoadJobs }),
}))

vi.mock('@/services/api', () => {
  const apiMock = {
    projects: { get: (...args) => mockApiProjectsGet(...args) },
  }
  return { api: apiMock, default: apiMock }
})

vi.mock('@/stores/projectStateStore', () => ({
  useProjectStateStore: () => ({
    setProject: mockSetProject,
    setStagingComplete: mockSetStagingComplete,
    setLaunched: vi.fn(),
    getProjectState: () => null,
  }),
}))

vi.mock('@/stores/projectTabs', () => ({
  useProjectTabsStore: () => ({ currentProject: null }),
}))


async function mountHost({
  projectId = ref('proj-1'),
  executionMode = ref('multi_terminal'),
  executionPlatform = ref(null),
  missionText = computed(() => ''),
  isProjectStaged = computed(() => false),
  isProjectStaging = computed(() => false),
  memoryWritten = ref(false),
  resetCloseout = vi.fn(),
  cleanupCloseout = vi.fn(),
  getProject = () => ({ id: 'proj-1', project_id: 'proj-1', name: 'Test', execution_mode: 'multi_terminal' }),
} = {}) {
  const { useProjectTabsLifecycle } = await import('./useProjectTabsLifecycle')

  const Host = defineComponent({
    name: 'LifecycleHost',
    setup() {
      const result = useProjectTabsLifecycle({
        projectId,
        executionMode,
        executionPlatform,
        missionText,
        isProjectStaged,
        isProjectStaging,
        memoryWritten,
        resetCloseout,
        cleanupCloseout,
        getProject,
      })
      return result
    },
    template: '<div />',
  })

  return mount(Host)
}


describe('useProjectTabsLifecycle', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()

    mockApiProjectsGet.mockResolvedValue({
      data: { id: 'proj-1', project_id: 'proj-1', name: 'Test', execution_mode: 'multi_terminal' },
    })
  })


  describe('onMounted WS subscriptions', () => {
    it('registers a product:memory:updated handler on mount', async () => {
      await mountHost()
      await flushPromises()

      const eventTypes = mockWsOn.mock.calls.map(([evt]) => evt)
      expect(eventTypes).toContain('product:memory:updated')
    })

    it('registers a project:staging_complete handler on mount', async () => {
      await mountHost()
      await flushPromises()

      const eventTypes = mockWsOn.mock.calls.map(([evt]) => evt)
      expect(eventTypes).toContain('project:staging_complete')
    })

    it('registers a project:implementation_launched handler on mount', async () => {
      await mountHost()
      await flushPromises()

      const eventTypes = mockWsOn.mock.calls.map(([evt]) => evt)
      expect(eventTypes).toContain('project:implementation_launched')
    })

    it('registers a reconnect resync on mount (generalized registry)', async () => {
      await mountHost()
      await flushPromises()

      expect(mockRegisterReconnectResync).toHaveBeenCalledTimes(1)
      expect(mockOnConnectionChange).not.toHaveBeenCalled()
    })
  })


  describe('onBeforeUnmount cleanup', () => {
    it('calls wsStore.unsubscribe on unmount', async () => {
      const wrapper = await mountHost()
      await flushPromises()

      wrapper.unmount()

      expect(mockUnsubscribe).toHaveBeenCalledWith('project', 'proj-1')
    })

    it('calls cleanupCloseout on unmount', async () => {
      const cleanupCloseout = vi.fn()
      const wrapper = await mountHost({ cleanupCloseout })
      await flushPromises()

      wrapper.unmount()

      expect(cleanupCloseout).toHaveBeenCalledTimes(1)
    })

    it('calls the reconnect-resync unregister fn on unmount', async () => {
      const wrapper = await mountHost()
      await flushPromises()

      wrapper.unmount()

      expect(mockUnregisterReconnectResync).toHaveBeenCalledTimes(1)
    })

    it('calls the WS event handler unsub fns on unmount', async () => {
      const unsubFns = { memory: vi.fn(), staging: vi.fn(), impl: vi.fn() }
      let callIdx = 0
      const unsubArr = [unsubFns.memory, unsubFns.staging, unsubFns.impl]
      mockWsOn.mockImplementation(() => unsubArr[callIdx++] ?? vi.fn())

      const wrapper = await mountHost()
      await flushPromises()
      wrapper.unmount()

      expect(unsubFns.memory).toHaveBeenCalledTimes(1)
      expect(unsubFns.staging).toHaveBeenCalledTimes(1)
      expect(unsubFns.impl).toHaveBeenCalledTimes(1)
    })
  })


  describe('loadProjectData (called via projectId watch immediate)', () => {
    it('calls wsStore.subscribeToProject with the project id', async () => {
      await mountHost()
      await flushPromises()

      expect(mockSubscribeToProject).toHaveBeenCalledWith('proj-1')
    })

    it('does NOT re-fetch the project on initial mount (kills the double-fetch)', async () => {
      await mountHost()
      await flushPromises()

      expect(mockApiProjectsGet).not.toHaveBeenCalled()
    })

    it('refetches the project on a real project switch', async () => {
      const projectId = ref('proj-1')
      await mountHost({ projectId })
      await flushPromises()
      expect(mockApiProjectsGet).not.toHaveBeenCalled()

      projectId.value = 'proj-2'
      await flushPromises()
      expect(mockApiProjectsGet).toHaveBeenCalledWith('proj-2')
    })

    it('calls loadJobs with the project id', async () => {
      await mountHost()
      await flushPromises()

      expect(mockLoadJobs).toHaveBeenCalledWith('proj-1')
    })
  })


  describe('refetchProject via project:staging_complete', () => {
    it('calls api.projects.get when matching project:staging_complete fires', async () => {
      await mountHost()
      await flushPromises()

      const call = mockWsOn.mock.calls.find(([evt]) => evt === 'project:staging_complete')
      expect(call).toBeTruthy()
      const handler = call[1]

      mockApiProjectsGet.mockClear()
      mockApiProjectsGet.mockResolvedValue({
        data: { id: 'proj-1', project_id: 'proj-1', name: 'Updated', execution_mode: 'multi_terminal' },
      })

      await handler({ project_id: 'proj-1', staging_status: 'staging_complete' })
      await flushPromises()

      expect(mockApiProjectsGet).toHaveBeenCalledWith('proj-1')
    })

    it('does NOT call api.projects.get for a different project id', async () => {
      await mountHost()
      await flushPromises()

      const call = mockWsOn.mock.calls.find(([evt]) => evt === 'project:staging_complete')
      const handler = call[1]

      mockApiProjectsGet.mockClear()
      await handler({ project_id: 'other-project', staging_status: 'staging_complete' })
      await flushPromises()

      expect(mockApiProjectsGet).not.toHaveBeenCalled()
    })
  })

  describe('refetchProject via project:implementation_launched', () => {
    it('calls api.projects.get when matching project:implementation_launched fires', async () => {
      await mountHost()
      await flushPromises()

      const call = mockWsOn.mock.calls.find(([evt]) => evt === 'project:implementation_launched')
      expect(call).toBeTruthy()
      const handler = call[1]

      mockApiProjectsGet.mockClear()
      mockApiProjectsGet.mockResolvedValue({
        data: { id: 'proj-1', project_id: 'proj-1', name: 'Test', execution_mode: 'multi_terminal', implementation_launched_at: '2026-06-01T10:00:00Z' },
      })

      await handler({ project_id: 'proj-1' })
      await flushPromises()

      expect(mockApiProjectsGet).toHaveBeenCalledWith('proj-1')
    })
  })


  describe('product:memory:updated WS handler', () => {
    it('sets memoryWritten to true when entry.project_id matches', async () => {
      const memoryWritten = ref(false)
      await mountHost({ memoryWritten })
      await flushPromises()

      const call = mockWsOn.mock.calls.find(([evt]) => evt === 'product:memory:updated')
      const handler = call[1]

      handler({ entry: { project_id: 'proj-1' } })
      await flushPromises()

      expect(memoryWritten.value).toBe(true)
    })

    it('does NOT set memoryWritten for a different project id', async () => {
      const memoryWritten = ref(false)
      await mountHost({ memoryWritten })
      await flushPromises()

      const call = mockWsOn.mock.calls.find(([evt]) => evt === 'product:memory:updated')
      const handler = call[1]

      handler({ entry: { project_id: 'different-project' } })
      await flushPromises()

      expect(memoryWritten.value).toBe(false)
    })
  })


  describe('reconnect resync (registry-driven)', () => {
    it('reloads open-project data when its registered resync fires', async () => {
      await mountHost()
      await flushPromises()

      expect(resyncState.callback).toBeTypeOf('function')

      mockApiProjectsGet.mockClear()
      mockApiProjectsGet.mockResolvedValue({
        data: { id: 'proj-1', project_id: 'proj-1', name: 'Test', execution_mode: 'multi_terminal' },
      })

      await resyncState.callback()
      await flushPromises()

      expect(mockApiProjectsGet).toHaveBeenCalledWith('proj-1')
      expect(mockLoadJobs).toHaveBeenCalledWith('proj-1')
    })
  })
})
