/**
 * ProjectsView.fe9502c.spec.js — FE-9502c
 *
 * Regression test for a cross-tab data-leak bug found while building the
 * tabbed product shell: ProjectsView scoped project creation/browsing by
 * `productStore.activeProduct` (the server's SINGLE "active" product), not
 * by the viewed tab. With two tabs open — Product A viewed, Product B
 * server-active — creating a "new project" while looking at A's tab would
 * silently have created it under B. Fixed to scope by
 * `productStore.currentProduct` (the viewed tab), matching how
 * useProductTaxonomy/effectiveProductId already prioritize it elsewhere.
 *
 * This is the "create/edit/browse each without touching the other" DoD
 * proof for PR1: two REAL, DIFFERENT products (viewed vs. server-active),
 * and the view must resolve to the viewed one.
 *
 * Edition scope: CE.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

const VIEWED_PRODUCT = { id: 'prod-viewed-A', name: 'Product A (viewed tab)' }
const SERVER_ACTIVE_PRODUCT = { id: 'prod-active-B', name: 'Product B (server-active)' }

const h = vi.hoisted(() => ({
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
    isProjectInActiveChain: vi.fn().mockReturnValue(false),
    isProjectRunLocked: vi.fn().mockReturnValue(false),
    runForProject: vi.fn().mockReturnValue(null),
    hydrate: vi.fn().mockResolvedValue(undefined),
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
    clearListQuery: vi.fn(),
  }),
}))
// Deliberately DIFFERENT products for currentProduct vs activeProduct -- the
// bug only shows up when they diverge, which is exactly the two-tab case.
vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    currentProduct: VIEWED_PRODUCT,
    activeProduct: SERVER_ACTIVE_PRODUCT,
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
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))
vi.mock('@/services/api', () => ({
  default: {
    taxonomyTypes: { list: vi.fn().mockResolvedValue({ data: [] }) },
  },
}))

import ProjectsView from './ProjectsView.vue'

describe('ProjectsView — FE-9502c scopes by the viewed tab, not the server-active product', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('resolves activeProduct (create/filter scope) to the VIEWED tab when it differs from server-active', async () => {
    const wrapper = mount(ProjectsView, {
      shallow: true,
      global: { renderStubDefaultSlot: true },
    })
    await flushPromises()

    expect(wrapper.vm.activeProduct).toMatchObject({ id: VIEWED_PRODUCT.id })
    expect(wrapper.vm.activeProduct?.id).not.toBe(SERVER_ACTIVE_PRODUCT.id)
  })

  it('passes the viewed product to the create/edit dialog, not the server-active one', async () => {
    const wrapper = mount(ProjectsView, {
      global: { renderStubDefaultSlot: true, stubs: { ProjectCreateEditDialog: true } },
    })
    await flushPromises()

    const dialog = wrapper.findComponent({ name: 'ProjectCreateEditDialog' })
    expect(dialog.exists()).toBe(true)
    expect(dialog.props('activeProduct')).toMatchObject({ id: VIEWED_PRODUCT.id })
  })
})
