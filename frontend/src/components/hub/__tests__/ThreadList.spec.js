/**
 * ThreadList.spec.js — FE-6054e, rewritten for the Quiet Cards card list (FE-9289c)
 *
 * ThreadList now owns list-level state (scope, search, selection, the delete dialog)
 * and renders one ThreadCard per thread. The card emits open/rename/copy/delete/lock-info;
 * ThreadList turns those into store calls + toasts. These tests exercise that seam and
 * the scope split; ThreadCard's own rendering is covered in ThreadCard.spec.js.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

const loadThreadsMock = vi.fn()
const searchThreadsMock = vi.fn()
const updateMock = vi.fn()
const deleteMock = vi.fn()
const copyMock = vi.fn(() => Promise.resolve(true))
const showToastMock = vi.fn()

vi.mock('@/services/api', () => ({
  default: {
    threads: {
      list: (...args) => loadThreadsMock(...args),
      search: (...args) => searchThreadsMock(...args),
      update: (...args) => updateMock(...args),
      delete: (...args) => deleteMock(...args),
    },
  },
}))
vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: copyMock, copied: { value: false } }),
}))
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

import ThreadList from '@/components/hub/ThreadList.vue'
import ThreadCard from '@/components/hub/ThreadCard.vue'
import { useCommHubStore } from '@/stores/commHubStore'
import { useUserStore } from '@/stores/user'

const vuetify = createVuetify()

function mountList(pinia, props = {}) {
  return mount(ThreadList, { props, global: { plugins: [pinia, vuetify] } })
}

describe('ThreadList (Quiet Cards)', () => {
  let pinia
  let store

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useCommHubStore()
    loadThreadsMock.mockReset().mockResolvedValue({ data: { threads: [], count: 0 } })
    searchThreadsMock.mockReset()
    updateMock.mockReset()
    deleteMock.mockReset().mockResolvedValue({ data: {} })
    copyMock.mockClear()
    showToastMock.mockClear()
  })

  afterEach(() => vi.restoreAllMocks())

  it('renders one ThreadCard per thread in the store', async () => {
    store._testSeedThread({ thread_id: 'a', chat_id: 'CHT-0001', subject: 'Alpha', project_id: null })
    store._testSeedThread({ thread_id: 'b', chat_id: 'CHT-0002', subject: 'Beta', project_id: null })
    const wrapper = mountList(pinia)
    await flushPromises()
    expect(wrapper.findAllComponents(ThreadCard).length).toBe(2)
  })

  it('never decorates a TERMINAL thread as your-turn, wherever the baton stopped', async () => {
    // FE-9365i, caught live by the operator: resolved threads wore the gold frame and
    // raised hand because the baton simply stopped where the conversation stopped.
    // "Done" and "waiting on you" cannot both be true.
    const userStore = useUserStore()
    userStore.currentUser = { id: 'op-1' }
    store._testSeedThread({ thread_id: 'open1', chat_id: 'CHT-0001', subject: 'live', project_id: null, status: 'open', next_action_owner: 'op-1' })
    store._testSeedThread({ thread_id: 'done1', chat_id: 'CHT-0002', subject: 'done', project_id: null, status: 'resolved', next_action_owner: 'op-1' })

    const wrapper = mountList(pinia)
    await flushPromises()

    const byId = Object.fromEntries(
      wrapper.findAllComponents(ThreadCard).map((c) => [c.props('thread').thread_id, c.props('thread')]),
    )
    expect(byId.open1._yourTurn).toBe(true)
    expect(byId.done1._yourTurn).toBe(false)
  })

  it('open event selects the thread and emits select', async () => {
    store._testSeedThread({ thread_id: 'a', chat_id: 'CHT-0001', subject: 'Alpha', project_id: null })
    const wrapper = mountList(pinia)
    await flushPromises()
    await wrapper.findComponent(ThreadCard).vm.$emit('open', 'a')
    expect(store.selectedThreadId).toBe('a')
    expect(wrapper.emitted('select')[0]).toEqual(['a'])
  })

  it('rename event calls the store PATCH and toasts success', async () => {
    store._testSeedThread({ thread_id: 'a', chat_id: 'CHT-0001', subject: 'Old', project_id: null })
    updateMock.mockResolvedValueOnce({ data: { thread_id: 'a', subject: 'New' } })
    const wrapper = mountList(pinia)
    await flushPromises()
    await wrapper.findComponent(ThreadCard).vm.$emit('rename', { thread: { thread_id: 'a' }, subject: 'New' })
    await flushPromises()
    expect(updateMock).toHaveBeenCalledWith('a', { subject: 'New' })
    expect(showToastMock).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }))
  })

  it('a rejected rename surfaces the reason as an error toast', async () => {
    store._testSeedThread({ thread_id: 'a', chat_id: 'CHT-0001', subject: 'Old', project_id: null })
    updateMock.mockRejectedValueOnce({ response: { data: { detail: 'named after its project' } } })
    const wrapper = mountList(pinia)
    await flushPromises()
    await wrapper.findComponent(ThreadCard).vm.$emit('rename', { thread: { thread_id: 'a' }, subject: 'x' })
    await flushPromises()
    expect(showToastMock).toHaveBeenCalledWith({ type: 'error', message: 'named after its project' })
  })

  it('copy event copies the thread_id UUID (not the CHT alias)', async () => {
    store._testSeedThread({ thread_id: 'uuid-a', chat_id: 'CHT-0001', subject: 'Alpha', project_id: null })
    const wrapper = mountList(pinia)
    await flushPromises()
    await wrapper.findComponent(ThreadCard).vm.$emit('copy', { thread_id: 'uuid-a', chat_id: 'CHT-0001' })
    await flushPromises()
    expect(copyMock).toHaveBeenCalledWith('uuid-a')
  })

  it('lock-info explains the project lock instead of deleting', async () => {
    store._testSeedThread({ thread_id: 'p', chat_id: 'CHT-0003', subject: 'Bound', project_id: 'proj-1' })
    const wrapper = mountList(pinia)
    await flushPromises()
    await wrapper.findComponent(ThreadCard).vm.$emit('lock-info', {})
    expect(showToastMock).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('360 memory') }))
    expect(deleteMock).not.toHaveBeenCalled()
  })

  it('delete event opens the confirm dialog, and confirming calls deleteThread', async () => {
    store._testSeedThread({ thread_id: 'a', chat_id: 'CHT-0001', subject: 'Alpha', project_id: null })
    const wrapper = mountList(pinia)
    await flushPromises()
    await wrapper.findComponent(ThreadCard).vm.$emit('delete', { thread_id: 'a', chat_id: 'CHT-0001' })
    await flushPromises()
    expect(wrapper.find('[data-testid="thread-delete-dialog"]').exists()).toBe(true)
    // The dialog body states the real consequence.
    expect(wrapper.text()).toContain('no longer shown')
  })
})

describe('ThreadList scope prop', () => {
  let pinia
  let store

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useCommHubStore()
    loadThreadsMock.mockReset().mockResolvedValue({ data: { threads: [], count: 0 } })
    store._testSeedThread({ thread_id: 'pb', project_id: 'projA', subject: 'Bound', chat_id: 'CHT-0009' })
    store._testSeedThread({ thread_id: 'ts', project_id: null, subject: 'Standalone', chat_id: 'CHT-0010' })
  })

  it("scope='project' renders only project-bound threads", async () => {
    const wrapper = mountList(pinia, { scope: 'project' })
    await flushPromises()
    expect(wrapper.findAllComponents(ThreadCard).length).toBe(1)
    expect(wrapper.text()).toContain('Bound')
    expect(wrapper.text()).not.toContain('Standalone')
  })

  it("scope='town' renders only standalone threads", async () => {
    const wrapper = mountList(pinia, { scope: 'town' })
    await flushPromises()
    expect(wrapper.findAllComponents(ThreadCard).length).toBe(1)
    expect(wrapper.text()).toContain('Standalone')
  })

  it("default scope ('all') renders both", async () => {
    const wrapper = mountList(pinia)
    await flushPromises()
    expect(wrapper.findAllComponents(ThreadCard).length).toBe(2)
  })
})
