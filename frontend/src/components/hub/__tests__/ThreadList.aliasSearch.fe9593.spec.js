import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

const searchThreadsMock = vi.fn()

vi.mock('@/services/api', () => ({
  default: {
    threads: {
      list: vi.fn(() => Promise.resolve({ data: { threads: [], count: 0 } })),
      search: (...args) => searchThreadsMock(...args),
      markRead: vi.fn(() => Promise.resolve({ data: {} })),
    },
  },
}))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: vi.fn(), copied: { value: false } }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

import ThreadList from '@/components/hub/ThreadList.vue'
import ThreadCard from '@/components/hub/ThreadCard.vue'

const vuetify = createVuetify()

const EXACT = { thread_id: 'exact', chat_id: 'CHT-0400', subject: 'The one', project_id: null, created_at: '2026-01-01T00:00:00Z', last_activity_at: '2026-01-02T00:00:00Z' }
const QUOTER_A = { thread_id: 'qa', chat_id: 'CHT-0511', subject: 'Mentions CHT-0400', project_id: null, created_at: '2026-06-01T00:00:00Z', last_activity_at: '2026-09-01T00:00:00Z' }
const QUOTER_B = { thread_id: 'qb', chat_id: 'CHT-0512', subject: 'Also CHT-0400', project_id: null, created_at: '2026-07-01T00:00:00Z', last_activity_at: '2026-09-02T00:00:00Z' }

function renderedChatIds(wrapper) {
  return wrapper.findAllComponents(ThreadCard).map((c) => c.props('thread').chat_id)
}

async function mountAndSearch(pinia, query, sort = 'activity') {
  const wrapper = mount(ThreadList, { props: { search: '', sort }, global: { plugins: [pinia, vuetify] } })
  await flushPromises()
  await wrapper.setProps({ search: query })
  await vi.advanceTimersByTimeAsync(400)
  await flushPromises()
  return wrapper
}

describe('ThreadList alias search ranks the exact thread first (FE-9593)', () => {
  let pinia

  beforeEach(() => {
    vi.useFakeTimers()
    pinia = createPinia()
    setActivePinia(pinia)
    searchThreadsMock.mockReset().mockResolvedValue({ data: { threads: [EXACT, QUOTER_B, QUOTER_A] } })
  })

  it('pins CHT-0400 above threads that merely quote it, whatever the list sort says', async () => {
    const w = await mountAndSearch(pinia, 'CHT-0400')
    expect(searchThreadsMock).toHaveBeenCalledWith({ query: 'CHT-0400' })
    expect(renderedChatIds(w)).toEqual(['CHT-0400', 'CHT-0512', 'CHT-0511'])
    vi.useRealTimers()
  })

  it('accepts the alias in any casing, without the dash, or as the bare number', async () => {
    for (const q of ['cht-400', 'CHT0400', '400']) {
      const w = await mountAndSearch(pinia, q)
      expect(renderedChatIds(w)[0]).toBe('CHT-0400')
      w.unmount()
    }
    vi.useRealTimers()
  })

  it('leaves the list sort alone for a query that is not an alias', async () => {
    const w = await mountAndSearch(pinia, 'The one')
    expect(renderedChatIds(w)).toEqual(['CHT-0512', 'CHT-0511', 'CHT-0400'])
    vi.useRealTimers()
  })

  it('still pins under the Serial sort, and a 5-digit alias pins the same way', async () => {
    const BIG = { ...EXACT, thread_id: 'big', chat_id: 'CHT-10000', subject: 'Past 9999' }
    searchThreadsMock.mockResolvedValue({ data: { threads: [BIG, QUOTER_B, QUOTER_A] } })
    const w = await mountAndSearch(pinia, 'CHT-10000', 'serial')
    expect(renderedChatIds(w)[0]).toBe('CHT-10000')
    vi.useRealTimers()
  })
})
