import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

import ThreadAgentRoster from '@/components/hub/ThreadAgentRoster.vue'
import { useCommHubStore } from '@/stores/commHubStore'
import { useUserStore } from '@/stores/user'

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
const COLLAPSED_KEY = 'giljo.hub.threadRoster.collapsed'
const ME = 'user-me'
const T = 'thr-roster'

const NOW = new Date().toISOString()

const agent = (id, over = {}) => ({
  participant_id: id,
  participant_type: 'agent',
  display_name: `name-${id}`,
  role: 'implementer',
  harness: 'claude-code',
  status: 'working',
  last_seen_at: NOW,
  ...over,
})

function setup({ thread = {}, participants = [], messages = [] } = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useUserStore().currentUser = { id: ME }
  const store = useCommHubStore()
  store._testSeedThread({
    thread_id: T,
    chat_id: 'CHT-0001',
    subject: 'A thread',
    status: 'open',
    project_id: null,
    next_action_owner: null,
    ...thread,
  })
  store.selectedThreadId = T
  store.participantsByThreadId = new Map([[T, participants]])
  store.messagesByThreadId = new Map([[T, messages]])
  return { pinia, store }
}

const mountRoster = (pinia) => mount(ThreadAgentRoster, { global: { plugins: [pinia, vuetify] } })

const msg = (id, from, over = {}) => ({
  message_id: id,
  thread_id: T,
  from_agent_id: from,
  from_kind: 'agent',
  content: 'x',
  message_type: 'broadcast',
  requires_action: false,
  created_at: '2026-10-05T11:59:00Z',
  ...over,
})

describe('ThreadAgentRoster (FE-9742)', () => {
  beforeEach(() => {
    window.localStorage = memoryStorage()
  })

  it('2: header line counts agents on the thread and the active ones; the user is not an agent', () => {
    const { pinia } = setup({
      participants: [
        agent('a1'),
        agent('a2', { status: 'complete' }),
        agent('a3', { status: null, last_seen_at: null }),
        { participant_id: ME, participant_type: 'user', display_name: 'Patrik' },
      ],
    })
    const head = mountRoster(pinia).get('[data-testid="thread-roster-head"]').text()
    expect(head).toContain('Agents')
    expect(head).toContain('3 on this thread')
    expect(head).toContain('1 active')
  })

  it('2: defaults to expanded, Collapse hides the tiles and persists, a fresh mount stays collapsed', async () => {
    const { pinia } = setup({ participants: [agent('a1')] })
    const w = mountRoster(pinia)
    expect(w.findAll('[data-testid="thread-roster-tile"]')).toHaveLength(1)
    expect(w.get('[data-testid="thread-roster-toggle"]').text()).toContain('Collapse')

    await w.get('[data-testid="thread-roster-toggle"]').trigger('click')
    expect(w.find('[data-testid="thread-roster-tile"]').exists()).toBe(false)
    expect(w.find('[data-testid="thread-roster-scope"]').exists()).toBe(false)
    expect(w.get('[data-testid="thread-roster-toggle"]').text()).toContain('Expand')
    expect(localStorage.getItem(COLLAPSED_KEY)).toBe('1')

    const again = mountRoster(pinia)
    expect(again.find('[data-testid="thread-roster-tile"]').exists()).toBe(false)

    await again.get('[data-testid="thread-roster-toggle"]').trigger('click')
    expect(mountRoster(pinia).findAll('[data-testid="thread-roster-tile"]')).toHaveLength(1)
  })

  it('2: collapsed, the header says how many need you, only when more than none', async () => {
    const { pinia } = setup({
      thread: { next_action_owner: ME },
      participants: [agent('a1'), agent('a2'), agent('a3')],
      messages: [
        msg('m1', 'a2', { requires_action: true }),
        msg('m2', 'a1'),
      ],
    })
    const w = mountRoster(pinia)
    await w.get('[data-testid="thread-roster-toggle"]').trigger('click')
    expect(w.get('[data-testid="thread-roster-head"]').text()).toContain('2 need you')

    window.localStorage = memoryStorage()
    const calm = setup({ participants: [agent('a1')], messages: [msg('m1', 'a1')] })
    const w2 = mountRoster(calm.pinia)
    await w2.get('[data-testid="thread-roster-toggle"]').trigger('click')
    expect(w2.get('[data-testid="thread-roster-head"]').text()).not.toContain('need you')
  })

  it('2: an agent waiting on a user-approval status needs you; a resolved thread needs nobody', async () => {
    const live = setup({ participants: [agent('a1', { status: 'awaiting_user' })] })
    const w = mountRoster(live.pinia)
    await w.get('[data-testid="thread-roster-toggle"]').trigger('click')
    expect(w.get('[data-testid="thread-roster-head"]').text()).toContain('1 need you')

    const done = setup({
      thread: { status: 'resolved', next_action_owner: ME },
      participants: [agent('a1', { status: 'awaiting_user' })],
      messages: [msg('m1', 'a1', { requires_action: true })],
    })
    expect(mountRoster(done.pinia).get('[data-testid="thread-roster-head"]').text()).not.toContain('need you')
  })

  it('3: a tile carries initials, name, harness and a plain-word state', () => {
    const { pinia } = setup({
      participants: [agent('a1', { display_name: 'implementer-working', status: 'working' })],
    })
    const tile = mountRoster(pinia).get('[data-testid="thread-roster-tile"]')
    expect(tile.get('[data-testid="thread-roster-avatar"]').text()).toBe('IW')
    expect(tile.get('[data-testid="thread-roster-name"]').text()).toBe('implementer-working')
    expect(tile.get('[data-testid="thread-roster-sub"]').text()).toBe('claude-code · working')
  })

  it('3: states read holds baton, blocked, working, unknown; a generic harness is labelled', () => {
    const { pinia } = setup({
      thread: { next_action_owner: 'b1' },
      participants: [
        agent('b1'),
        agent('b2', { status: 'blocked' }),
        agent('b3', { status: 'working', harness: 'generic' }),
        agent('b4', { status: null, last_seen_at: null, harness: null }),
      ],
    })
    const subs = mountRoster(pinia)
      .findAll('[data-testid="thread-roster-sub"]')
      .map((s) => s.text())
    expect(subs).toEqual([
      'claude-code · holds baton',
      'claude-code · blocked',
      'Generic Harness · working',
      'Generic Harness · unknown',
    ])
  })

  it('3: a participant who has been seen but has no status is not called unknown', () => {
    const { pinia } = setup({ participants: [agent('a1', { status: null })] })
    const sub = mountRoster(pinia).get('[data-testid="thread-roster-sub"]').text()
    expect(sub).not.toContain('unknown')
  })

  it('4: the scope note is the last line of the expanded frame, worded per thread kind', () => {
    const general = setup({ participants: [agent('a1')] })
    const w = mountRoster(general.pinia)
    const html = w.html()
    expect(html.indexOf('thread-roster-tile')).toBeLessThan(html.indexOf('thread-roster-scope'))
    expect(w.get('[data-testid="thread-roster-scope"]').text()).toContain('next poll')

    const project = setup({ thread: { project_id: 'p-1' }, participants: [agent('a1')] })
    expect(mountRoster(project.pinia).get('[data-testid="thread-roster-scope"]').text()).toContain(
      "not part of an agent's working context",
    )
  })

  it('3: an empty thread still shows the frame, with a zero count and the scope note', () => {
    const { pinia } = setup({ participants: [] })
    const w = mountRoster(pinia)
    expect(w.get('[data-testid="thread-roster-head"]').text()).toContain('0 on this thread')
    expect(w.find('[data-testid="thread-roster-tile"]').exists()).toBe(false)
    expect(w.find('[data-testid="thread-roster-scope"]').exists()).toBe(true)
  })

  it('2: storage that refuses reads and writes still renders expanded and still toggles', async () => {
    window.localStorage = {
      getItem: vi.fn(() => {
        throw new Error('denied')
      }),
      setItem: vi.fn(() => {
        throw new Error('denied')
      }),
    }
    const { pinia } = setup({ participants: [agent('a1')] })
    const w = mountRoster(pinia)
    expect(w.findAll('[data-testid="thread-roster-tile"]')).toHaveLength(1)
    await w.get('[data-testid="thread-roster-toggle"]').trigger('click')
    expect(w.find('[data-testid="thread-roster-tile"]').exists()).toBe(false)
  })
})
