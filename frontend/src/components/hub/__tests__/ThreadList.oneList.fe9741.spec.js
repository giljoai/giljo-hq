import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

const searchThreadsMock = vi.fn()
const projectGetMock = vi.fn()

vi.mock('@/services/api', () => {
  const api = {
    threads: {
      list: vi.fn(() => Promise.resolve({ data: { threads: [], count: 0 } })),
      search: (...args) => searchThreadsMock(...args),
      markRead: vi.fn(() => Promise.resolve({ data: {} })),
    },
    projects: { get: (...args) => projectGetMock(...args) },
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
function memoryStorage() {
  const data = new Map()
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
    clear: () => data.clear(),
  }
}

const SHOW_ALL_KEY = 'giljo.hub.threadList.showAll'
const RESOLVED_KEY = 'giljo.hub.threadList.resolvedOpen'

function seedOpen(store, n, { projectEvery = 0 } = {}) {
  for (let i = 1; i <= n; i += 1) {
    store._testSeedThread({
      thread_id: `open-${i}`,
      chat_id: `CHT-${String(i).padStart(4, '0')}`,
      subject: `Open ${i}`,
      status: 'open',
      project_id: projectEvery && i % projectEvery === 0 ? `proj-${i}` : null,
      created_at: `2026-10-01T00:00:${String(i).padStart(2, '0')}Z`,
      updated_at: `2026-10-01T00:00:${String(i).padStart(2, '0')}Z`,
    })
  }
}

function seedResolved(store, n) {
  for (let i = 1; i <= n; i += 1) {
    store._testSeedThread({
      thread_id: `done-${i}`,
      chat_id: `CHT-9${String(i).padStart(3, '0')}`,
      subject: `Done ${i}`,
      status: i % 2 ? 'resolved' : 'closed',
      project_id: null,
      created_at: `2026-09-01T00:00:${String(i).padStart(2, '0')}Z`,
      updated_at: `2026-09-01T00:00:${String(i).padStart(2, '0')}Z`,
    })
  }
}

const ids = (w) => w.findAllComponents(ThreadCard).map((c) => c.props('thread').thread_id)

describe('ThreadList one list (FE-9741)', () => {
  let pinia
  let store

  beforeEach(() => {
    window.localStorage = memoryStorage()
    pinia = createPinia()
    setActivePinia(pinia)
    store = useCommHubStore()
    searchThreadsMock.mockReset()
    projectGetMock.mockReset().mockRejectedValue(new Error('not found'))
  })

  const mountList = (props = {}) => mount(ThreadList, { props, global: { plugins: [pinia, vuetify] } })

  it('shows project-bound and standalone threads together in one list', async () => {
    store._testSeedThread({ thread_id: 'g', chat_id: 'CHT-0001', subject: 'General one', status: 'open', project_id: null, updated_at: '2026-10-01T00:00:01Z' })
    store._testSeedThread({ thread_id: 'p', chat_id: 'CHT-0002', subject: 'Project one', status: 'open', project_id: 'proj-1', updated_at: '2026-10-01T00:00:02Z' })
    const w = mountList()
    await flushPromises()
    expect(ids(w)).toEqual(['p', 'g'])
  })

  it('shows only the newest five open threads, with Show all (N) for the rest', async () => {
    seedOpen(store, 8)
    const w = mountList()
    await flushPromises()
    expect(ids(w)).toEqual(['open-8', 'open-7', 'open-6', 'open-5', 'open-4'])
    const btn = w.find('[data-testid="thread-list-show-all"]')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toBe('Show all (8)')
  })

  it('has no Show all control when five or fewer threads are open', async () => {
    seedOpen(store, 5)
    const w = mountList()
    await flushPromises()
    expect(ids(w)).toHaveLength(5)
    expect(w.find('[data-testid="thread-list-show-all"]').exists()).toBe(false)
  })

  it('expands to every open thread on Show all and remembers it per browser', async () => {
    seedOpen(store, 8)
    const w = mountList()
    await flushPromises()
    await w.find('[data-testid="thread-list-show-all"]').trigger('click')
    expect(ids(w)).toHaveLength(8)
    expect(localStorage.getItem(SHOW_ALL_KEY)).toBe('1')
    expect(w.find('[data-testid="thread-list-show-all"]').text()).toBe('Show fewer')

    const again = mountList()
    await flushPromises()
    expect(ids(again)).toHaveLength(8)

    await again.find('[data-testid="thread-list-show-all"]').trigger('click')
    expect(ids(again)).toHaveLength(5)
    expect(localStorage.getItem(SHOW_ALL_KEY)).toBe('0')
  })

  it('folds resolved and closed threads under a collapsed Resolved (N) section', async () => {
    seedOpen(store, 2)
    seedResolved(store, 3)
    const w = mountList()
    await flushPromises()
    expect(ids(w)).toEqual(['open-2', 'open-1'])
    const toggle = w.find('[data-testid="thread-list-resolved-toggle"]')
    expect(toggle.text()).toContain('Resolved (3)')
    expect(toggle.attributes('aria-expanded')).toBe('false')
  })

  it('opens the Resolved section on click and remembers it per browser', async () => {
    seedOpen(store, 1)
    seedResolved(store, 3)
    const w = mountList()
    await flushPromises()
    await w.find('[data-testid="thread-list-resolved-toggle"]').trigger('click')
    expect(ids(w)).toHaveLength(4)
    expect(w.find('[data-testid="thread-list-resolved-toggle"]').attributes('aria-expanded')).toBe('true')
    expect(localStorage.getItem(RESOLVED_KEY)).toBe('1')

    const again = mountList()
    await flushPromises()
    expect(ids(again)).toHaveLength(4)
  })

  it('does not count resolved threads against the five-thread cap', async () => {
    seedOpen(store, 5)
    seedResolved(store, 4)
    const w = mountList()
    await flushPromises()
    expect(ids(w)).toHaveLength(5)
    expect(w.find('[data-testid="thread-list-show-all"]').exists()).toBe(false)
  })

  it('says so when nothing is open but resolved threads exist', async () => {
    seedResolved(store, 2)
    const w = mountList()
    await flushPromises()
    expect(w.find('[data-testid="thread-list-empty"]').exists()).toBe(false)
    expect(w.find('[data-testid="thread-list-no-open"]').exists()).toBe(true)
    expect(w.find('[data-testid="thread-list-resolved-toggle"]').exists()).toBe(true)
  })

  it('shows every search hit: no cap, resolved hits visible, nothing persisted', async () => {
    vi.useFakeTimers()
    try {
      seedOpen(store, 8)
      seedResolved(store, 2)
      searchThreadsMock.mockResolvedValue({ data: { threads: [...store.threadList] } })
      const w = mountList({ search: '' })
      await flushPromises()
      await w.setProps({ search: 'thread' })
      vi.advanceTimersByTime(400)
      await flushPromises()
      expect(ids(w)).toHaveLength(10)
      expect(w.find('[data-testid="thread-list-show-all"]').exists()).toBe(false)
      expect(localStorage.getItem(SHOW_ALL_KEY)).toBe(null)
      expect(localStorage.getItem(RESOLVED_KEY)).toBe(null)
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps an opened thread visible when it sits beyond the cap', async () => {
    seedOpen(store, 8)
    store.selectThread('open-1')
    const w = mountList()
    await flushPromises()
    expect(ids(w)).toContain('open-1')
    expect(w.findAllComponents(ThreadCard).find((c) => c.props('thread').thread_id === 'open-1').props('selected')).toBe(true)
    expect(localStorage.getItem(SHOW_ALL_KEY)).toBe(null)
  })

  it('keeps an opened thread visible when it sits in the resolved fold', async () => {
    seedOpen(store, 1)
    seedResolved(store, 3)
    store.selectThread('done-2')
    const w = mountList()
    await flushPromises()
    expect(ids(w)).toContain('done-2')
    expect(w.find('[data-testid="thread-list-resolved-toggle"]').attributes('aria-expanded')).toBe('true')
    expect(localStorage.getItem(RESOLVED_KEY)).toBe(null)
  })

  it('folds back to the cap once the selection moves off a hidden thread', async () => {
    seedOpen(store, 8)
    store.selectThread('open-1')
    const w = mountList()
    await flushPromises()
    store.selectThread(null)
    await flushPromises()
    expect(ids(w)).toHaveLength(5)
  })

  it('badges project threads with their project alias, fetching only the visible ones', async () => {
    for (let i = 1; i <= 8; i += 1) {
      store._testSeedThread({
        thread_id: `p-${i}`,
        chat_id: `CHT-000${i}`,
        subject: '(project comms)',
        status: 'open',
        project_id: `proj-${i}`,
        updated_at: `2026-10-01T00:00:0${i}Z`,
      })
    }
    projectGetMock.mockImplementation((id) =>
      Promise.resolve({
        data: { id, taxonomy_alias: `FE-${id.split('-')[1]}`, project_type: { abbreviation: 'FE', color: '#6DB3E4' } },
      }),
    )
    const w = mountList()
    await flushPromises()
    expect(projectGetMock).toHaveBeenCalledTimes(5)
    const top = w.findAllComponents(ThreadCard)[0]
    expect(top.props('thread')._projectAlias).toBe('FE-8')
    expect(top.find('[data-testid="thread-card-project-badge"]').text()).toBe('FE-8')

    await w.find('[data-testid="thread-list-show-all"]').trigger('click')
    await flushPromises()
    expect(projectGetMock).toHaveBeenCalledTimes(8)
  })

  it('keeps a plain Project label, and asks once, when the project cannot be read', async () => {
    store._testSeedThread({ thread_id: 'p-1', chat_id: 'CHT-0001', subject: '(project comms)', status: 'open', project_id: 'gone', project_name: 'Gone', title: 'Gone' })
    const w = mountList()
    await flushPromises()
    await w.setProps({ sort: 'created' })
    await flushPromises()
    expect(projectGetMock).toHaveBeenCalledTimes(1)
    expect(w.find('[data-testid="thread-card-project-label"]').text()).toBe('Project')
  })
})
