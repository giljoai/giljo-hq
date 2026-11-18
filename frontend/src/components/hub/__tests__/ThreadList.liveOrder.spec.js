import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

const listMock = vi.fn(() => Promise.resolve({ data: { threads: [], count: 0 } }))
vi.mock('@/services/api', () => {
  const api = {
    threads: {
      list: (...a) => listMock(...a),
      search: vi.fn(),
      markRead: vi.fn(() => Promise.resolve({ data: {} })),
      participants: vi.fn(() => Promise.resolve({ data: { participants: [] } })),
      history: vi.fn(() => Promise.resolve({ data: { thread: null, messages: [] } })),
    },
    projects: { get: vi.fn(() => Promise.reject(new Error('not found'))) },
  }
  return { default: api, api }
})
vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn(), copied: { value: false } }),
}))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

import ThreadList from '@/components/hub/ThreadList.vue'
import ThreadCard from '@/components/hub/ThreadCard.vue'
import { useCommHubStore } from '@/stores/commHubStore'

const vuetify = createVuetify()
const ids = (w) => w.findAllComponents(ThreadCard).map((c) => c.props('thread').thread_id)

function listShaped(id, at) {
  return {
    thread_id: id,
    chat_id: `CHT-${id}`,
    subject: id,
    status: 'open',
    project_id: null,
    created_at: '2026-11-01T00:00:00Z',
    updated_at: at,
    last_message: { id: `m-${id}`, author: 'x', excerpt: 'hi', created_at: at },
  }
}

describe('ThreadList live order', () => {
  let pinia
  let store
  beforeEach(() => {
    window.localStorage.clear()
    pinia = createPinia()
    setActivePinia(pinia)
    store = useCommHubStore()
  })

  it('a live message for the older thread moves it to the top, no list reload', async () => {
    store._testSeedThread(listShaped('older', '2026-11-10T10:00:00Z'))
    store._testSeedThread(listShaped('newer', '2026-11-10T11:00:00Z'))
    const w = mount(ThreadList, { global: { plugins: [pinia, vuetify] } })
    await flushPromises()
    expect(ids(w)).toEqual(['newer', 'older'])
    listMock.mockClear()

    await store.handleThreadMessage({
      thread_id: 'older',
      message_id: 'live-1',
      content: 'hello',
      created_at: '2026-11-10T12:00:00Z',
    })
    await flushPromises()

    expect(ids(w)).toEqual(['older', 'newer'])
    expect(listMock).not.toHaveBeenCalled()
  })
})

describe('your-turn banner order uses the same live value', () => {
  it('Open next picks the thread that waited longest by live activity, not the list-time post', async () => {
    const { useYourTurnOpenNext } = await import('@/composables/useYourTurnThreads')
    const { ref } = await import('vue')
    setActivePinia(createPinia())
    const a = { ...listShaped('a', '2026-11-10T09:00:00Z'), last_activity_at: '2026-11-10T12:00:00Z' }
    const b = { ...listShaped('b', '2026-11-10T10:00:00Z'), last_activity_at: '2026-11-10T10:00:00Z' }
    const { openNextThreads } = useYourTurnOpenNext({
      router: { currentRoute: { value: { path: '/' } }, push: vi.fn() },
      threads: ref([a, b]),
    })
    expect(openNextThreads.value.map((t) => t.thread_id)).toEqual(['b', 'a'])
  })
})
