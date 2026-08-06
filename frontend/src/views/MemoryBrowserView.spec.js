/**
 * MemoryBrowserView.spec.js — FE-5042
 *
 * Component spec for the 360 Memory browser view. Proves:
 *   - no-product empty state when no product is active;
 *   - entries fetched on mount (via the existing read endpoint) render as rows;
 *   - the client-side search computed drives which rows show;
 *   - expand-on-click renders the summary as sanitized markdown (v-html).
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

// Use the global api mock from tests/setup.js, but control getMemoryEntries.
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

// setup.js installs a GLOBAL pinia via config.global.plugins. We create our
// own pinia per test, make it active (so out-of-component useStore() calls hit
// it) AND pass it to mount so the mounted component resolves the SAME stores.
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
    // Search-aware mock: mirror the real ?search= server path, which returns
    // ONLY the matching entries. The old mock returned the full SAMPLE for every
    // call, so when the view's 250ms search debounce fired it repopulated the
    // list and flipped serverSearch=true — racing the filtered/empty assertions
    // under slow CI timing (BE-6162). With a faithful mock the pre-debounce
    // client filter and the post-debounce server result agree, so the search
    // assertions are deterministic regardless of when the debounce fires.
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
    // Defensive: a test that enabled fake timers must not leak them to the next.
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
    // Body hidden until expanded.
    expect(wrapper.find('[data-test="memory-body-a"]').exists()).toBe(false)
    await wrapper.find('[data-test="memory-row-a"] .mem-row-head').trigger('click')
    const body = wrapper.find('[data-test="memory-body-a"]')
    expect(body.exists()).toBe(true)
    // marked turned **tenant** into a <strong>, DOMPurify kept it.
    expect(body.find('.mem-markdown').html()).toContain('<strong>tenant</strong>')
  })

  it('shows the filtered-empty state when search matches nothing', async () => {
    const wrapper = await mountView()
    const memoryStore = useMemoryStore()
    // The search box is debounced (250ms) and the view fires the resulting
    // server ?search= call fire-and-forget (BE-6082), so the settle is not
    // observable from the DOM alone. Asserting after a fixed flush guesses at
    // when that lands and loses the race (BE-6162, TSK-9219); polling the DOM
    // instead only moved the guess into a wall-clock window, which then had to
    // be widened twice and still expired under a starved CI event loop
    // (TSK-9232, TSK-9237). So wait on the promise itself, not on the clock:
    // nextTick() guarantees the watcher has registered its debounce while fake
    // timers are still installed, advancing them fires it, and awaiting the
    // store's inFlightSearch waits for THIS search to settle. (It says nothing
    // about the store reaching a final state — _runSearch does not sequence
    // requests — but this test fires exactly one search, so that is enough.)
    vi.useFakeTimers()
    memoryStore.searchText = 'zzz-nope'
    await nextTick()
    await vi.advanceTimersByTimeAsync(300) // fire the 250ms debounce
    vi.useRealTimers()
    await memoryStore.inFlightSearch
    await flushPromises() // let Vue render the settled state
    expect(wrapper.find('[data-test="memory-empty"]').exists()).toBe(true)
  })

  // FE-6125 design-system harmonization: rows render the canonical tinted
  // badge (entry-type) + tinted pill chips (tags), not the retired .mem-chip,
  // and the list lives inside the smooth-border surface card.
  it('renders the tinted entry-type badge and tag chips, not the old .mem-chip', async () => {
    const wrapper = await mountView()
    const rowA = wrapper.find('[data-test="memory-row-a"]')
    // Canonical square tinted badge for the entry type.
    const badge = rowA.find('.mem-badge')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain('project completion')
    // Canonical tinted pill chip for the tag.
    expect(rowA.find('[data-test="memory-tag-security"]').classes()).toContain('mem-tag-chip')
    // The retired bespoke chip is gone everywhere.
    expect(wrapper.find('.mem-chip').exists()).toBe(false)
    // List sits inside the design-system surface card.
    expect(wrapper.find('[data-test="memory-list-card"]').exists()).toBe(true)
  })

  // The group toggle is now a real button (matches the Projects filter-bar
  // buttons): outlined when off, flat (brand-primary) when on.
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
