import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { ref, computed, nextTick } from 'vue'
import { setActivePinia, createPinia } from 'pinia'
import { useProjectCloseout } from './useProjectCloseout'

vi.mock('@/services/api', () => {
  const apiObj = {
    products: {
      getMemoryEntries: vi.fn(() => Promise.resolve({ data: { entries: [] } })),
    },
  }
  return { default: apiObj, api: apiObj }
})

vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => ({
    clearForProject: vi.fn(),
  }),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({
    showToast: vi.fn(),
  }),
}))

function makeProject(overrides = {}) {
  return ref({
    id: 'proj-1',
    project_id: 'proj-1',
    product_id: 'prod-1',
    status: 'active',
    ...overrides,
  })
}

function makeJobs(overrides = []) {
  return computed(() => overrides)
}

describe('useProjectCloseout', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('initial state', () => {
    it('exposes showCloseoutModal as false initially', () => {
      const project = makeProject()
      const sortedJobs = makeJobs([])
      const { showCloseoutModal } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs })
      expect(showCloseoutModal.value).toBe(false)
    })

    it('exposes memoryWritten as false initially', () => {
      const project = makeProject()
      const sortedJobs = makeJobs([])
      const { memoryWritten } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs })
      expect(memoryWritten.value).toBe(false)
    })

  })

  describe('projectDoneStatus', () => {
    it('returns "completed" for a completed project', () => {
      const project = makeProject({ status: 'completed' })
      const { projectDoneStatus } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs([]) })
      expect(projectDoneStatus.value).toBe('completed')
    })

    it('returns "terminated" for a terminated project', () => {
      const project = makeProject({ status: 'terminated' })
      const { projectDoneStatus } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs([]) })
      expect(projectDoneStatus.value).toBe('terminated')
    })

    it('returns "cancelled" for a cancelled project', () => {
      const project = makeProject({ status: 'cancelled' })
      const { projectDoneStatus } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs([]) })
      expect(projectDoneStatus.value).toBe('cancelled')
    })

    it('returns null for an active project', () => {
      const project = makeProject({ status: 'active' })
      const { projectDoneStatus } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs([]) })
      expect(projectDoneStatus.value).toBeNull()
    })
  })

  describe('allJobsTerminal', () => {
    it('returns false when jobs array is empty', () => {
      const project = makeProject()
      const { allJobsTerminal } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs([]) })
      expect(allJobsTerminal.value).toBe(false)
    })

    it('returns false when project is already in a terminal status', () => {
      const project = makeProject({ status: 'completed' })
      const jobs = [
        { agent_display_name: 'orchestrator', status: 'complete' },
        { agent_display_name: 'implementer', status: 'complete' },
      ]
      const { allJobsTerminal } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs(jobs) })
      expect(allJobsTerminal.value).toBe(false)
    })

    it('returns false when not all jobs are terminal', () => {
      const project = makeProject()
      const jobs = [
        { agent_display_name: 'orchestrator', status: 'complete' },
        { agent_display_name: 'implementer', status: 'working' },
      ]
      const { allJobsTerminal } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs(jobs) })
      expect(allJobsTerminal.value).toBe(false)
    })

    it('returns false when all jobs are terminal but orchestrator is missing', () => {
      const project = makeProject()
      const jobs = [
        { agent_display_name: 'implementer', status: 'complete' },
        { agent_display_name: 'tester', status: 'decommissioned' },
      ]
      const { allJobsTerminal } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs(jobs) })
      expect(allJobsTerminal.value).toBe(false)
    })

    it('returns true when all jobs are terminal and orchestrator is complete', () => {
      const project = makeProject()
      const jobs = [
        { agent_display_name: 'orchestrator', status: 'complete' },
        { agent_display_name: 'implementer', status: 'decommissioned' },
      ]
      const { allJobsTerminal } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs(jobs) })
      expect(allJobsTerminal.value).toBe(true)
    })

    it('treats "completed" status (alternate spelling) as terminal', () => {
      const project = makeProject()
      const jobs = [
        { agent_display_name: 'orchestrator', status: 'completed' },
        { agent_display_name: 'implementer', status: 'complete' },
      ]
      const { allJobsTerminal } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs(jobs) })
      expect(allJobsTerminal.value).toBe(true)
    })

    it('returns false when staging_complete and implementation has not launched (CE-0028)', () => {
      const project = makeProject({
        staging_status: 'staging_complete',
        implementation_launched_at: null,
      })
      const jobs = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      const { allJobsTerminal } = useProjectCloseout({
        project,
        projectId: computed(() => 'proj-1'),
        sortedJobs: makeJobs(jobs),
      })
      expect(allJobsTerminal.value).toBe(false)
    })

    it('returns true when staging_complete AND implementation_launched_at is set (CE-0028)', () => {
      const project = makeProject({
        staging_status: 'staging_complete',
        implementation_launched_at: '2026-05-17T10:00:00Z',
      })
      const jobs = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      const { allJobsTerminal } = useProjectCloseout({
        project,
        projectId: computed(() => 'proj-1'),
        sortedJobs: makeJobs(jobs),
      })
      expect(allJobsTerminal.value).toBe(true)
    })
  })

  describe('CE-0028 staging→implementation handoff', () => {
    it('does not surface closeout button while staging_complete + implementation not launched', () => {
      const project = makeProject({
        product_id: 'prod-1',
        staging_status: 'staging_complete',
        implementation_launched_at: null,
      })
      const jobs = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      const { showCloseoutButton, showMemoryPending } = useProjectCloseout({
        project,
        projectId: computed(() => 'proj-1'),
        sortedJobs: makeJobs(jobs),
      })
      expect(showCloseoutButton.value).toBe(false)
      expect(showMemoryPending.value).toBe(false)
    })

    it('does not start memory polling at staging_complete pre-Implement', async () => {
      const api = (await import('@/services/api')).default
      api.products.getMemoryEntries.mockClear()

      const project = makeProject({
        product_id: 'prod-1',
        staging_status: 'staging_complete',
        implementation_launched_at: null,
      })
      const jobsRef = ref([{ agent_display_name: 'orchestrator', status: 'working' }])
      const sortedJobs = computed(() => jobsRef.value)
      useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs })

      jobsRef.value = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      await nextTick()
      await nextTick()

      expect(api.products.getMemoryEntries).not.toHaveBeenCalled()
    })
  })

  describe('CE-0029 Item 1 reactive-project regression', () => {
    it('updates allJobsTerminal when the project ref mutates from staging to staging_complete', async () => {
      const project = makeProject({
        product_id: 'prod-1',
        staging_status: 'staging',
        implementation_launched_at: null,
      })
      const jobs = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      const { allJobsTerminal } = useProjectCloseout({
        project,
        projectId: computed(() => 'proj-1'),
        sortedJobs: makeJobs(jobs),
      })

      expect(allJobsTerminal.value).toBe(true)

      project.value = { ...project.value, staging_status: 'staging_complete' }
      await nextTick()
      expect(allJobsTerminal.value).toBe(false)
    })

    it('resumes closeout when implementation_launched_at appears on the reactive ref', async () => {
      const project = makeProject({
        product_id: 'prod-1',
        staging_status: 'staging_complete',
        implementation_launched_at: null,
      })
      const jobs = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      const { allJobsTerminal } = useProjectCloseout({
        project,
        projectId: computed(() => 'proj-1'),
        sortedJobs: makeJobs(jobs),
      })

      expect(allJobsTerminal.value).toBe(false)

      project.value = {
        ...project.value,
        implementation_launched_at: '2026-05-17T10:00:00Z',
      }
      await nextTick()
      expect(allJobsTerminal.value).toBe(true)
    })
  })

  describe('showCloseoutButton', () => {
    it('returns false when jobs are not all terminal', () => {
      const project = makeProject()
      const jobs = [
        { agent_display_name: 'orchestrator', status: 'working' },
      ]
      const { showCloseoutButton } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs(jobs) })
      expect(showCloseoutButton.value).toBe(false)
    })

    it('returns true when all jobs terminal and no product_id (no memory gate)', () => {
      const project = makeProject({ product_id: null })
      const jobs = [
        { agent_display_name: 'orchestrator', status: 'complete' },
      ]
      const { showCloseoutButton } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs(jobs) })
      expect(showCloseoutButton.value).toBe(true)
    })

    it('returns false when all jobs terminal but memory not yet written (has product_id)', () => {
      const project = makeProject({ product_id: 'prod-1' })
      const jobs = [
        { agent_display_name: 'orchestrator', status: 'complete' },
      ]
      const { showCloseoutButton } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs(jobs) })
      expect(showCloseoutButton.value).toBe(false)
    })

    it('returns true when all jobs terminal and memory is written', () => {
      const project = makeProject({ product_id: 'prod-1' })
      const jobs = [
        { agent_display_name: 'orchestrator', status: 'complete' },
      ]
      const { showCloseoutButton, memoryWritten } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs(jobs) })
      memoryWritten.value = true
      expect(showCloseoutButton.value).toBe(true)
    })
  })

  describe('showMemoryPending', () => {
    it('returns false when jobs are not terminal', () => {
      const project = makeProject({ product_id: 'prod-1' })
      const jobs = [{ agent_display_name: 'orchestrator', status: 'working' }]
      const { showMemoryPending } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs(jobs) })
      expect(showMemoryPending.value).toBe(false)
    })

    it('returns false when no product_id', () => {
      const project = makeProject({ product_id: null })
      const jobs = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      const { showMemoryPending } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs(jobs) })
      expect(showMemoryPending.value).toBe(false)
    })

    it('returns true when jobs terminal, has product_id, memory not written', () => {
      const project = makeProject({ product_id: 'prod-1' })
      const jobs = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      const { showMemoryPending } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs(jobs) })
      expect(showMemoryPending.value).toBe(true)
    })

    it('returns false when memory is written', () => {
      const project = makeProject({ product_id: 'prod-1' })
      const jobs = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      const { showMemoryPending, memoryWritten } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs(jobs) })
      memoryWritten.value = true
      expect(showMemoryPending.value).toBe(false)
    })
  })

  describe('openCloseoutModal', () => {
    it('sets showCloseoutModal to true', () => {
      const project = makeProject()
      const { showCloseoutModal, openCloseoutModal } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs([]) })
      expect(showCloseoutModal.value).toBe(false)
      openCloseoutModal()
      expect(showCloseoutModal.value).toBe(true)
    })
  })

  describe('handleCloseoutComplete', () => {
    it('closes the modal and calls the onComplete callback', async () => {
      const project = makeProject()
      const onComplete = vi.fn()
      const { showCloseoutModal, handleCloseoutComplete } = useProjectCloseout({
        project,
        projectId: computed(() => 'proj-1'),
        sortedJobs: makeJobs([]),
        onComplete,
      })
      showCloseoutModal.value = true
      await handleCloseoutComplete()
      expect(showCloseoutModal.value).toBe(false)
      expect(onComplete).toHaveBeenCalledOnce()
    })
  })

  describe('showContinueGuidance removed', () => {
    it('does not expose showContinueGuidance (Continue Working gate deleted)', () => {
      const project = makeProject()
      const result = useProjectCloseout({
        project,
        projectId: computed(() => 'proj-1'),
        sortedJobs: makeJobs([]),
      })
      expect(result.showContinueGuidance).toBeUndefined()
      expect(result.handleContinueWorking).toBeUndefined()
    })
  })

  describe('memory polling watcher', () => {
    it('sets memoryWritten when API returns existing entries', async () => {
      const api = (await import('@/services/api')).default
      api.products.getMemoryEntries.mockResolvedValue({ data: { entries: [{ id: 1 }] } })

      const project = makeProject({ product_id: 'prod-1' })
      const jobsRef = ref([{ agent_display_name: 'orchestrator', status: 'working' }])
      const sortedJobs = computed(() => jobsRef.value)
      const { memoryWritten } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs })

      jobsRef.value = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      await nextTick()
      await nextTick()

      expect(memoryWritten.value).toBe(true)
    })

    it('sets memoryPollTimedOut after 30s when API returns no entries', async () => {
      const api = (await import('@/services/api')).default
      api.products.getMemoryEntries.mockResolvedValue({ data: { entries: [] } })

      const project = makeProject({ product_id: 'prod-1' })
      const jobs = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      const { memoryWritten, memoryPollTimedOut } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs(jobs) })

      await nextTick()
      await nextTick()
      expect(memoryWritten.value).toBe(false)
      expect(memoryPollTimedOut.value).toBe(false)

      vi.advanceTimersByTime(30_000)
      await nextTick()
      await nextTick()

      expect(memoryPollTimedOut.value).toBe(true)
      expect(memoryWritten.value).toBe(false)
    })

    it('does NOT set memoryWritten on timeout (no fail-open)', async () => {
      const api = (await import('@/services/api')).default
      api.products.getMemoryEntries.mockResolvedValue({ data: { entries: [] } })

      const project = makeProject({ product_id: 'prod-1' })
      const jobs = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      const { memoryWritten, memoryPollTimedOut } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs: makeJobs(jobs) })

      await nextTick()
      await nextTick()

      vi.advanceTimersByTime(30_000)
      await nextTick()
      await nextTick()

      expect(memoryPollTimedOut.value).toBe(true)
      expect(memoryWritten.value).toBe(false)
    })
  })

  describe('memoryPollTimedOut state', () => {
    it('exposes memoryPollTimedOut as false initially', () => {
      const project = makeProject()
      const sortedJobs = makeJobs([])
      const { memoryPollTimedOut } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs })
      expect(memoryPollTimedOut.value).toBe(false)
    })

    it('exposes memoryPollError as false initially', () => {
      const project = makeProject()
      const sortedJobs = makeJobs([])
      const { memoryPollError } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs })
      expect(memoryPollError.value).toBe(false)
    })

    it('sets memoryPollError when initial API call throws', async () => {
      const api = (await import('@/services/api')).default
      api.products.getMemoryEntries.mockRejectedValue(new Error('Network error'))

      const project = makeProject({ product_id: 'prod-1' })
      const jobsRef = ref([{ agent_display_name: 'orchestrator', status: 'working' }])
      const sortedJobs = computed(() => jobsRef.value)
      const { memoryPollError } = useProjectCloseout({ project, projectId: computed(() => 'proj-1'), sortedJobs })

      jobsRef.value = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      await nextTick()
      await nextTick()

      expect(memoryPollError.value).toBe(true)
    })
  })

  describe('retryMemoryPoll', () => {
    it('resets timeout and error state and restarts polling', async () => {
      const api = (await import('@/services/api')).default
      api.products.getMemoryEntries.mockResolvedValue({ data: { entries: [] } })

      const project = makeProject({ product_id: 'prod-1' })
      const jobs = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      const { memoryPollTimedOut, memoryPollError, retryMemoryPoll } = useProjectCloseout({
        project,
        projectId: computed(() => 'proj-1'),
        sortedJobs: makeJobs(jobs),
      })

      await nextTick()
      await nextTick()

      vi.advanceTimersByTime(30_000)
      await nextTick()
      expect(memoryPollTimedOut.value).toBe(true)

      api.products.getMemoryEntries.mockResolvedValue({ data: { entries: [{ id: 1 }] } })

      retryMemoryPoll()
      expect(memoryPollTimedOut.value).toBe(false)
      expect(memoryPollError.value).toBe(false)
    })

    it('auto-transitions to success if entry appears after timeout was dismissed', async () => {
      const api = (await import('@/services/api')).default
      api.products.getMemoryEntries.mockResolvedValue({ data: { entries: [] } })

      const project = makeProject({ product_id: 'prod-1' })
      const jobs = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      const { memoryWritten, memoryPollTimedOut, retryMemoryPoll } = useProjectCloseout({
        project,
        projectId: computed(() => 'proj-1'),
        sortedJobs: makeJobs(jobs),
      })

      await nextTick()
      await nextTick()

      vi.advanceTimersByTime(30_000)
      await nextTick()
      expect(memoryPollTimedOut.value).toBe(true)

      api.products.getMemoryEntries.mockResolvedValue({ data: { entries: [{ id: 1 }] } })
      retryMemoryPoll()
      await nextTick()
      await nextTick()

      expect(memoryWritten.value).toBe(true)
      expect(memoryPollTimedOut.value).toBe(false)
    })
  })

  describe('dismissMemoryPollError', () => {
    it('clears timed-out state when dismissed', async () => {
      const api = (await import('@/services/api')).default
      api.products.getMemoryEntries.mockResolvedValue({ data: { entries: [] } })

      const project = makeProject({ product_id: 'prod-1' })
      const jobs = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      const { memoryPollTimedOut, dismissMemoryPollError } = useProjectCloseout({
        project,
        projectId: computed(() => 'proj-1'),
        sortedJobs: makeJobs(jobs),
      })

      await nextTick()
      await nextTick()

      vi.advanceTimersByTime(30_000)
      await nextTick()
      expect(memoryPollTimedOut.value).toBe(true)

      dismissMemoryPollError()
      expect(memoryPollTimedOut.value).toBe(false)
    })
  })

  describe('showMemoryPending with error states', () => {
    it('stays true when memoryPollTimedOut is true (spinner kept visible by design)', () => {
      const project = makeProject({ product_id: 'prod-1' })
      const jobs = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      const { showMemoryPending, memoryPollTimedOut } = useProjectCloseout({
        project,
        projectId: computed(() => 'proj-1'),
        sortedJobs: makeJobs(jobs),
      })
      memoryPollTimedOut.value = true
      expect(showMemoryPending.value).toBe(true)
    })

    it('stays true when memoryPollError is true (spinner kept visible by design)', () => {
      const project = makeProject({ product_id: 'prod-1' })
      const jobs = [{ agent_display_name: 'orchestrator', status: 'complete' }]
      const { showMemoryPending, memoryPollError } = useProjectCloseout({
        project,
        projectId: computed(() => 'proj-1'),
        sortedJobs: makeJobs(jobs),
      })
      memoryPollError.value = true
      expect(showMemoryPending.value).toBe(true)
    })
  })
})
