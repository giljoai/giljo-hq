/**
 * HubView.toolbar.fe9368.spec.js — FE-9368 (A, B, C, D wiring)
 *
 * DeletedCountButton has its own spec; this one covers the half that spec cannot see —
 * that the Hub actually WIRES the new chrome up. Two prior acceptance rounds on this
 * screen were failed by the operator's eyes on things every unit test passed through,
 * so the view-level assertions here are deliberately about what is on the page:
 *
 *  - the list view sits in ONE column, which is what makes the toolbar and the cards
 *    line up (A);
 *  - the toolbar is icon buttons and the deleted COUNT rides the trash icon (B);
 *  - the "What the indicators mean" trigger is gone from BOTH surfaces (C);
 *  - an open thread has its own search box, and it feeds the timeline (D).
 *
 * Edition scope: Both
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

// FE-9410: HubView now pushes routes as well as reading them (the attention strip
// navigates instead of selecting in place), so the mock has to answer useRouter too.
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/websocketEventRouter', () => ({ registerReconnectResync: () => () => {} }))

import HubView from '@/views/HubView.vue'
import { useCommHubStore } from '@/stores/commHubStore'

const THREAD_ID = 'thr-open'

const childStubs = {
  ThreadList: { template: '<div class="stub-thread-list" />' },
  ThreadTimeline: {
    props: ['search'],
    template: '<div class="stub-timeline" :data-search="search" />',
  },
  HubComposer: { template: '<div class="stub-composer" />' },
  AgentPill: { template: '<span class="stub-pill" />' },
  NewThreadDialog: { template: '<div />' },
  ThreadCreatedDialog: { template: '<div />' },
  ThreadDeletedDialog: { template: '<div />' },
  DeletedCountButton: {
    props: ['count', 'entity'],
    template: '<button class="stub-deleted" :data-count="count" :data-entity="entity" />',
  },
}

async function mountHub({ openThread = false } = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(HubView, { global: { plugins: [pinia], stubs: childStubs } })
  if (openThread) {
    const store = useCommHubStore()
    store._testSeedThread({ thread_id: THREAD_ID, chat_id: 'CHT-0001', subject: 'Test' })
    store.selectThread(THREAD_ID)
  }
  await flushPromises()
  return wrapper
}

describe('HubView toolbar and layout (FE-9368)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('wraps the list view in one column, so the bar and the cards share a width', async () => {
    const wrapper = await mountHub()
    const column = wrapper.find('.hub-view__column')
    expect(column.exists()).toBe(true)
    // The header, the toolbar and the cards all have to be INSIDE it; a bar left
    // outside would keep the exact misalignment this item exists to fix.
    expect(column.find('.filter-bar').exists()).toBe(true)
    expect(column.find('.stub-thread-list').exists()).toBe(true)
  })

  it('replaces the "New Thread" label with the [+] icon button', async () => {
    const wrapper = await mountHub()
    const newBtn = wrapper.find('[data-testid="new-thread-btn"]')
    expect(newBtn.exists()).toBe(true)
    expect(newBtn.text()).toBe('')
    expect(newBtn.attributes('title')).toBe('New thread')
  })

  it('hands the deleted COUNT to the trash button rather than a text label', async () => {
    const wrapper = await mountHub()
    const trash = wrapper.find('[data-testid="deleted-threads-btn"]')
    expect(trash.exists()).toBe(true)
    expect(trash.attributes('data-entity')).toBe('threads')
    // Zero here: the global api mock returns no deleted threads. The count is bound,
    // which is the wiring under test; the badge itself is DeletedCountButton's spec.
    expect(trash.attributes('data-count')).toBe('0')
    expect(wrapper.text()).not.toContain('Deleted (')
  })

  it('carries no indicator-legend trigger on the list view', async () => {
    const wrapper = await mountHub()
    expect(wrapper.find('[data-testid="hub-legend-btn"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('What the indicators mean')
  })

  it('carries no indicator-legend trigger inside a thread either', async () => {
    const wrapper = await mountHub({ openThread: true })
    expect(wrapper.find('[data-testid="hub-legend-btn-thread"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('What the indicators mean')
  })

  it('gives an open thread its own search box and feeds it to the timeline', async () => {
    const wrapper = await mountHub({ openThread: true })
    const search = wrapper.find('[data-testid="thread-message-search"]')
    expect(search.exists()).toBe(true)
    expect(wrapper.find('.stub-timeline').attributes('data-search')).toBe('')

    wrapper.vm.messageSearch = 'migration'
    await flushPromises()
    expect(wrapper.find('.stub-timeline').attributes('data-search')).toBe('migration')
  })

  it('drops the query when a different thread is opened', async () => {
    // A filter left over from the last conversation would silently hide messages in
    // the next one, and the operator would have no idea why.
    const wrapper = await mountHub({ openThread: true })
    wrapper.vm.messageSearch = 'migration'
    await flushPromises()

    const store = useCommHubStore()
    store._testSeedThread({ thread_id: 'thr-other', chat_id: 'CHT-0002', subject: 'Other' })
    store.selectThread('thr-other')
    await flushPromises()

    expect(wrapper.vm.messageSearch).toBe('')
  })
})
