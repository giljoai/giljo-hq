import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({
  removeMember: vi.fn().mockResolvedValue({}),
  hydrate: vi.fn().mockResolvedValue(undefined),
  isProjectInActiveChain: vi.fn().mockReturnValue(false),
  runForProject: vi.fn().mockReturnValue({ id: 'run-1' }),
  isProjectRunLocked: vi.fn().mockReturnValue(false),
  showToast: vi.fn(),
  fetchProjects: vi.fn().mockResolvedValue(undefined),
  fetchActiveProject: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('pinia', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, storeToRefs: (s) => ({ statuses: s.statuses }) }
})

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/sequenceRunStore', () => ({
  useSequenceRunStore: () => ({
    activeChainProjectIds: [],
    isProjectInActiveChain: h.isProjectInActiveChain,
    isProjectRunLocked: h.isProjectRunLocked,
    runForProject: h.runForProject,
    hydrate: h.hydrate,
  }),
}))
vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({
    projects: [],
    projectsTotal: 0,
    loading: false,
    deletedProjects: [],
    hiddenProjects: [],
    activeProjectMeta: null,
    fetchProjects: h.fetchProjects,
    fetchActiveProject: h.fetchActiveProject,
    fetchHiddenProjects: vi.fn().mockResolvedValue(undefined),
    fetchDeletedProjects: vi.fn().mockResolvedValue(undefined),
    fetchProject: vi.fn().mockResolvedValue(null),
    activateProject: vi.fn().mockResolvedValue(undefined),
    clearListQuery: vi.fn(),
  }),
}))
vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    currentProduct: { id: 'prod-1' },
    activeProduct: { id: 'prod-1' },
    fetchProducts: vi.fn().mockResolvedValue(undefined),
    fetchActiveProduct: vi.fn().mockResolvedValue(undefined),
  }),
}))
vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => ({ clearForProject: vi.fn() }),
}))
vi.mock('@/stores/projectStatusesStore', () => ({
  useProjectStatusesStore: () => ({
    statuses: ref([]),
    ensureLoaded: vi.fn().mockResolvedValue(undefined),
  }),
}))
vi.mock('@/stores/websocketEventRouter', () => ({
  registerReconnectResync: vi.fn(() => vi.fn()),
}))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: h.showToast }) }))
vi.mock('@/services/api', () => ({
  default: {
    sequenceRuns: { removeMember: h.removeMember },
    taxonomyTypes: { list: vi.fn().mockResolvedValue({ data: [] }) },
  },
}))

import ProjectsView from './ProjectsView.vue'

async function mountView() {
  const wrapper = mount(ProjectsView, {
    shallow: true,
    global: { renderStubDefaultSlot: true },
  })
  await flushPromises()
  h.hydrate.mockClear()
  h.removeMember.mockClear()
  h.showToast.mockClear()
  return wrapper
}

describe('ProjectsView handleProjectToggle (FE-6175 RC1)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    h.isProjectInActiveChain.mockReturnValue(false)
    h.runForProject.mockReturnValue({ id: 'run-1' })
  })

  it('non-chain row -> raw toggle, NOT removeMember', async () => {
    h.isProjectInActiveChain.mockReturnValue(false)
    const wrapper = await mountView()
    const toggle = vi.fn()

    await wrapper.vm.handleProjectToggle({ id: 'p1' }, toggle)
    await flushPromises()

    expect(toggle).toHaveBeenCalledWith({ id: 'p1' })
    expect(h.removeMember).not.toHaveBeenCalled()
    expect(h.hydrate).not.toHaveBeenCalled()
  })

  it('in-chain row -> NO-OP (no toggle, no chain write, silent)', async () => {
    h.isProjectInActiveChain.mockReturnValue(true)
    const wrapper = await mountView()
    const toggle = vi.fn()

    await wrapper.vm.handleProjectToggle({ id: 'p2' }, toggle)
    await flushPromises()

    expect(toggle).not.toHaveBeenCalled()
    expect(h.removeMember).not.toHaveBeenCalled()
    expect(h.hydrate).not.toHaveBeenCalled()
    expect(h.showToast).not.toHaveBeenCalled()
  })
})
