import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

import { api } from '@/services/api'
import MemoryBrowserView from './MemoryBrowserView.vue'
import { useProductStore } from '@/stores/products'
import { useMemoryStore } from '@/stores/memoryStore'

function entry(over = {}) {
  return {
    id: over.id || 'e1',
    sequence: 1,
    entry_type: 'project_completion',
    source: 'closeout_v1',
    timestamp: '2026-06-01T10:00:00Z',
    project_id: 'p1',
    project_name: 'Alpha',
    summary: 'Did a thing',
    key_outcomes: [],
    decisions_made: [],
    git_commits: [],
    tags: [],
    author_name: 'implementer',
    author_type: 'implementer',
    deleted_by_user: false,
    ...over,
  }
}

const SAMPLE = [
  entry({ id: 'a', summary: 'Refactored the **tenant** guard', tags: ['security'] }),
  entry({ id: 'b', summary: 'Tuned the slow query', tags: ['perf'] }),
]

let pinia

async function mountView() {
  const productStore = useProductStore()
  productStore.currentProductId = 'p1'
  const wrapper = mount(MemoryBrowserView, { global: { plugins: [pinia] } })
  await flushPromises()
  return wrapper
}

describe('MemoryBrowserView — FE-5042', () => {
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.clearAllMocks()
    api.products.getMemoryEntries.mockImplementation((_productId, opts = {}) => {
      const term = (opts.search || '').trim().toLowerCase()
      const entries = term
        ? SAMPLE.filter((e) =>
            [e.summary, e.project_name, ...(e.tags || [])].join(' ').toLowerCase().includes(term),
          )
        : SAMPLE
      return Promise.resolve({
        data: { entries, total_count: SAMPLE.length, filtered_count: entries.length },
      })
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows the no-product state when no product is active', async () => {
    const wrapper = mount(MemoryBrowserView, { global: { plugins: [pinia] } })
    await flushPromises()
    expect(wrapper.find('[data-test="memory-no-product"]').exists()).toBe(true)
  })

  it('fetches on mount via the existing endpoint and renders a row per entry', async () => {
    const wrapper = await mountView()
    expect(api.products.getMemoryEntries).toHaveBeenCalledWith('p1', { limit: 100 })
    expect(wrapper.find('[data-test="memory-row-a"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="memory-row-b"]').exists()).toBe(true)
  })

  it('client-side search narrows the rendered rows', async () => {
    const wrapper = await mountView()
    const memoryStore = useMemoryStore()
    memoryStore.searchText = 'tenant'
    await flushPromises()
    expect(wrapper.find('[data-test="memory-row-a"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="memory-row-b"]').exists()).toBe(false)
  })

  it('expand-on-click renders the summary as sanitized markdown', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('[data-test="memory-body-a"]').exists()).toBe(false)
    await wrapper.find('[data-test="memory-row-a"] .mem-row-head').trigger('click')
    const body = wrapper.find('[data-test="memory-body-a"]')
    expect(body.exists()).toBe(true)
    expect(body.find('.mem-markdown').html()).toContain('<strong>tenant</strong>')
  })

  it('shows the filtered-empty state when search matches nothing', async () => {
    const wrapper = await mountView()
    const memoryStore = useMemoryStore()
    vi.useFakeTimers()
    memoryStore.searchText = 'zzz-nope'
    await nextTick()
    await vi.advanceTimersByTimeAsync(300)
    vi.useRealTimers()
    await memoryStore.inFlightSearch
    await flushPromises()
    expect(wrapper.find('[data-test="memory-empty"]').exists()).toBe(true)
  })

  it('renders the tinted entry-type badge and tag chips, not the old .mem-chip', async () => {
    const wrapper = await mountView()
    const rowA = wrapper.find('[data-test="memory-row-a"]')
    const badge = rowA.find('.mem-badge')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain('project completion')
    expect(rowA.find('[data-test="memory-tag-security"]').classes()).toContain('mem-tag-chip')
    expect(wrapper.find('.mem-chip').exists()).toBe(false)
    expect(wrapper.find('[data-test="memory-list-card"]').exists()).toBe(true)
  })

  it('group-by-project toggle is a button that switches grouping', async () => {
    const wrapper = await mountView()
    const toggle = wrapper.find('[data-test="memory-group-toggle"]')
    expect(toggle.classes()).toContain('v-btn')
    expect(toggle.attributes('aria-checked')).toBe('false')
    expect(wrapper.find('[data-test="memory-group"]').exists()).toBe(false)
    await toggle.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="memory-group"]').exists()).toBe(true)
    expect(toggle.attributes('aria-checked')).toBe('true')
  })
})
