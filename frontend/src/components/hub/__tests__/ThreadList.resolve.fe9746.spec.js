import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

const showToast = vi.fn()
const updateMock = vi.fn()
vi.mock('@/services/api', () => {
  const api = {
    threads: {
      list: vi.fn(() => Promise.resolve({ data: { threads: [], count: 0 } })),
      search: vi.fn(),
      markRead: vi.fn(() => Promise.resolve({ data: {} })),
      update: (...a) => updateMock(...a),
    },
    projects: { get: vi.fn(() => Promise.reject(new Error('nf'))) },
  }
  return { default: api, api }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: vi.fn(), copied: { value: false } }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast }) }))

import ThreadList from '@/components/hub/ThreadList.vue'
import ThreadCard from '@/components/hub/ThreadCard.vue'
import { useCommHubStore } from '@/stores/commHubStore'

const vuetify = createVuetify()
function memoryStorage() {
  const data = new Map()
  return { getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)), removeItem: (k) => data.delete(k), clear: () => data.clear() }
}
const ids = (w) => w.findAllComponents(ThreadCard).map((c) => c.props('thread').thread_id)

describe('ThreadList resolve / reopen (FE-9746)', () => {
  let pinia
  let store

  beforeEach(() => {
    window.localStorage = memoryStorage()
    window.localStorage.setItem('giljo.hub.threadList.resolvedOpen', '1')
    showToast.mockReset()
    updateMock.mockReset()
    pinia = createPinia()
    setActivePinia(pinia)
    store = useCommHubStore()
    store._testSeedThread({ thread_id: 'a', chat_id: 'CHT-0001', subject: 'A', status: 'open', updated_at: '2026-10-01T00:00:02Z' })
    store._testSeedThread({ thread_id: 'b', chat_id: 'CHT-0002', subject: 'B', status: 'resolved', updated_at: '2026-10-01T00:00:01Z' })
  })

  const mountList = () => mount(ThreadList, { global: { plugins: [pinia, vuetify] } })
  const resolveBtn = (w, id) => w.findAllComponents(ThreadCard).find((c) => c.props('thread').thread_id === id).get('[data-testid="thread-card-resolve"]')

  it('moves a resolved card into the Resolved fold and Undo moves it back', async () => {
    updateMock.mockResolvedValue({ data: { thread_id: 'a', status: 'resolved' } })
    const w = mountList()
    await flushPromises()
    expect(w.get('[data-testid="thread-list-resolved-toggle"]').text()).toContain('Resolved (1)')

    await resolveBtn(w, 'a').trigger('click')
    await flushPromises()
    expect(updateMock).toHaveBeenCalledWith('a', { status: 'resolved' })
    expect(w.get('[data-testid="thread-list-resolved-toggle"]').text()).toContain('Resolved (2)')
    expect(w.find('[data-testid="thread-list-no-open"]').exists()).toBe(true)

    const toast = showToast.mock.calls.at(-1)[0]
    expect(toast.action.label).toBe('Undo')
    updateMock.mockResolvedValue({ data: { thread_id: 'a', status: 'open' } })
    await toast.action.callback()
    await flushPromises()
    expect(updateMock).toHaveBeenLastCalledWith('a', { status: 'open' })
    expect(w.get('[data-testid="thread-list-resolved-toggle"]').text()).toContain('Resolved (1)')
    expect(ids(w)).toContain('a')
  })

  it('Reopen on a card in the fold brings it back to the open list', async () => {
    updateMock.mockResolvedValue({ data: { thread_id: 'b', status: 'open' } })
    const w = mountList()
    await flushPromises()
    expect(resolveBtn(w, 'b').attributes('aria-label')).toBe('Reopen')
    await resolveBtn(w, 'b').trigger('click')
    await flushPromises()
    expect(updateMock).toHaveBeenCalledWith('b', { status: 'open' })
    expect(w.find('[data-testid="thread-list-resolved-toggle"]').exists()).toBe(false)
    expect(ids(w).sort()).toEqual(['a', 'b'])
  })
})
