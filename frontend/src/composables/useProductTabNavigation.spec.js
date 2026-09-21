import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  push: vi.fn(),
  route: { name: 'Projects', params: {}, query: {} },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: h.push }),
  useRoute: () => h.route,
}))

import { useProductTabNavigation } from './useProductTabNavigation'
import { useProductStore } from '@/stores/products'
import { useProjectStore } from '@/stores/projects'
import { useProductActivityStore } from '@/stores/productActivityStore'

let pinia
let switchTabCalls

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  h.route = { name: 'Projects', params: {}, query: {} }
  switchTabCalls = []
})

function setup({ projects = [] } = {}) {
  const productStore = useProductStore()
  const projectStore = useProjectStore()
  const activityStore = useProductActivityStore()
  projectStore.projects = projects
  productStore.switchTab = vi.fn(async (id) => {
    switchTabCalls.push(id)
    projectStore.projects = []
  })
  activityStore.clearActivity = vi.fn()
  return { productStore, projectStore, activityStore }
}

describe('useProductTabNavigation — a tab click leaves another product’s detail page', () => {
  it('pushes to Projects when the open project belongs to a different product', async () => {
    h.route = { name: 'ProjectLaunch', params: { projectId: 'proj-a' }, query: {} }
    setup({ projects: [{ id: 'proj-a', product_id: 'prod-a', status: 'active' }] })

    const { selectTab } = useProductTabNavigation()
    await selectTab('prod-b')

    expect(switchTabCalls).toEqual(['prod-b'])
    expect(h.push).toHaveBeenCalledWith({ name: 'Projects' })
  })

  it('pushes to Projects from a chain-run view of another product', async () => {
    h.route = { name: 'ProjectLaunch', params: { projectId: 'proj-a' }, query: { run: 'run-1' } }
    setup({ projects: [{ id: 'proj-a', product_id: 'prod-a', status: 'active' }] })

    const { selectTab } = useProductTabNavigation()
    await selectTab('prod-b')

    expect(h.push).toHaveBeenCalledWith({ name: 'Projects' })
  })

  it('does not navigate when the open project belongs to the product being switched to', async () => {
    h.route = { name: 'ProjectLaunch', params: { projectId: 'proj-b' }, query: {} }
    setup({ projects: [{ id: 'proj-b', product_id: 'prod-b', status: 'active' }] })

    const { selectTab } = useProductTabNavigation()
    await selectTab('prod-b')

    expect(switchTabCalls).toEqual(['prod-b'])
    expect(h.push).not.toHaveBeenCalled()
  })

  it('does not navigate from a product-agnostic route', async () => {
    h.route = { name: 'Projects', params: {}, query: {} }
    setup({ projects: [{ id: 'proj-a', product_id: 'prod-a', status: 'active' }] })

    const { selectTab } = useProductTabNavigation()
    await selectTab('prod-b')

    expect(h.push).not.toHaveBeenCalled()
  })

  it('does not navigate when the open project’s owner is unknown (cannot prove it is foreign)', async () => {
    h.route = { name: 'ProjectLaunch', params: { projectId: 'proj-unknown' }, query: {} }
    setup({ projects: [] })

    const { selectTab } = useProductTabNavigation()
    await selectTab('prod-b')

    expect(h.push).not.toHaveBeenCalled()
  })

  it('still clears the activity badge for the tab being viewed', async () => {
    const { activityStore } = setup()

    const { selectTab } = useProductTabNavigation()
    await selectTab('prod-b')

    expect(activityStore.clearActivity).toHaveBeenCalledWith('prod-b')
  })
})
