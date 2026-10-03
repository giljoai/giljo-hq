import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ hash: '' }) }))
vi.mock('@/services/api', () => ({
  default: {
    stats: {
      getDashboard: vi.fn().mockResolvedValue({ data: { project_status_dist: {}, total_commits: 0 } }),
      getCallCounts: vi.fn().mockResolvedValue({ data: { total_api_calls: 0, total_mcp_calls: 0 } }),
    },
  },
}))

import DashboardView from '@/views/DashboardView.vue'
import { useProductStore } from '@/stores/products'

describe('dashboard filter chevrons follow the product list', () => {
  let widthSpy
  beforeEach(() => {
    setActivePinia(createPinia())
    widthSpy = vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(900)
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(300)
  })
  afterEach(() => vi.restoreAllMocks())

  it('products that arrive after mount still light the right chevron', async () => {
    const wrapper = mount(DashboardView, {
      global: { stubs: { RecentProjectsList: true, RecentMemoriesList: true, ProjectReviewModal: true, RouterLink: true } },
    })
    await flushPromises()
    await new Promise((r) => setTimeout(r, 150))

    useProductStore().products = [
      { id: 'a', name: 'A' },
      { id: 'b', name: 'B' },
      { id: 'c', name: 'C' },
    ]
    await flushPromises()

    expect(widthSpy).toHaveBeenCalled()
    expect(wrapper.vm.canScrollRight).toBe(true)
    wrapper.unmount()
  })
})

describe('guide anchor scroll', () => {
  it('scrolls once the page has rendered, with no fixed delay (source-level: the view imports docs/ and cannot mount under test)', async () => {
    const { readFileSync } = await import('node:fs')
    const { resolve } = await import('node:path')
    const src = readFileSync(resolve(__dirname, 'UserGuideView.vue'), 'utf8')
    const fn = src.slice(src.indexOf('function handleUrlAnchor'), src.indexOf('onMounted('))
    expect(fn).toContain('scrollToAnchor(hash)')
    expect(fn).not.toContain('setTimeout')
  })
})
