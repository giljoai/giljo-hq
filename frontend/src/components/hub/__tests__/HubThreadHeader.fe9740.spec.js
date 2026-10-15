import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: vi.fn().mockResolvedValue(true) }) }))

import HubThreadHeader from '@/components/hub/HubThreadHeader.vue'
import ThreadTimeline from '@/components/hub/ThreadTimeline.vue'
import { formatHubDateTime } from '@/components/hub/hubDateTime'
import { useCommHubStore } from '@/stores/commHubStore'
import { useProductStore } from '@/stores/products'
import { useProjectStore } from '@/stores/projects'

const vuetify = createVuetify()

const GENERAL = {
  thread_id: 't-general',
  chat_id: 'CHT-0042',
  subject: 'General chat',
  status: 'open',
  product_id: 'prod-1',
  project_id: null,
  participants: [],
  created_at: '2026-10-04T21:46:00Z',
  last_activity_at: '2026-10-05T11:59:00Z',
  last_message: { id: 'm9', created_at: '2026-10-05T11:59:00Z' },
}

const PROJECT_THREAD = {
  ...GENERAL,
  thread_id: 't-project',
  chat_id: 'CHT-0043',
  title: 'Sprint ledger',
  project_id: 'proj-1',
  project_name: 'Sprint ledger project',
}

function mountHeader(pinia) {
  return mount(HubThreadHeader, { global: { plugins: [pinia, vuetify], stubs: { AgentPill: true } } })
}

describe('HubThreadHeader (FE-9740)', () => {
  let pinia
  let store

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useCommHubStore()
    useProductStore().products = [{ id: 'prod-1', name: 'GiljoAI MCP SaaS edition' }]
    useProjectStore().projects = [
      {
        id: 'proj-1',
        name: 'Sprint ledger',
        taxonomy_alias: 'BE-0017',
        project_type: { abbreviation: 'BE', color: '#6DB3E4' },
      },
    ]
  })

  function open(thread) {
    store._testSeedThread(thread)
    store.selectedThreadId = thread.thread_id
  }

  it('2: Created is the primary-text item and Last msg the accent item', () => {
    open(GENERAL)
    const w = mountHeader(pinia)
    const dates = w.get('[data-testid="thread-header-dates"]')
    expect(dates.classes()).toContain('thread-dates--tinted')
    expect(w.get('[data-testid="thread-dates-created"]').classes()).toContain('thread-dates__item--created')
    expect(w.get('[data-testid="thread-dates-last-message"]').classes()).toContain('thread-dates__item--last')
  })

  it('3: a general thread shows General and its product name, no Project line (FE-9742 wording)', () => {
    open(GENERAL)
    const w = mountHeader(pinia)
    expect(w.get('[data-testid="thread-header-product"]').text()).toBe('GiljoAI MCP SaaS edition')
    expect(w.get('[data-testid="thread-header-general"]').text()).toBe('General')
    expect(w.find('[data-testid="thread-header-project"]').exists()).toBe(false)
  })

  it('3: a product-less thread shows no product text', () => {
    open({ ...GENERAL, product_id: null })
    expect(mountHeader(pinia).find('[data-testid="thread-header-product"]').exists()).toBe(false)
  })

  it('3: a project thread shows the taxonomy badge and the project title, without the Project word', () => {
    open(PROJECT_THREAD)
    const w = mountHeader(pinia)
    const line = w.get('[data-testid="thread-header-project"]')
    expect(line.text()).not.toContain('Project:')
    expect(line.get('[data-testid="thread-header-project-badge"]').text()).toBe('BE-0017')
    expect(line.text()).toContain('Sprint ledger')
  })

  it('3: the project and product sit directly under the title row, with the dates after them', () => {
    open(PROJECT_THREAD)
    const html = mountHeader(pinia).html()
    const at = (id) => html.indexOf(`data-testid="${id}"`)
    expect(at('thread-header-title')).toBeLessThan(at('thread-header-project'))
    expect(at('thread-header-project')).toBeLessThan(at('thread-header-product'))
    expect(at('thread-header-product')).toBeLessThan(at('thread-header-dates'))
  })

  it('4: no retag menu and no product pill in the header', () => {
    open(GENERAL)
    const w = mountHeader(pinia)
    expect(w.find('[data-testid="thread-header-retag"]').exists()).toBe(false)
    expect(w.find('[data-testid="thread-header-retag-menu"]').exists()).toBe(false)
    expect(w.find('.thread-retag-menu__trigger').exists()).toBe(false)
  })

  it('5: the scope note lives in the roster frame, after the agent tiles', () => {
    open(GENERAL)
    store.participantsByThreadId = new Map([
      [GENERAL.thread_id, [{ participant_id: 'a1', participant_type: 'agent', display_name: 'x' }]],
    ])
    const w = mountHeader(pinia)
    const html = w.html()
    const at = (id) => html.indexOf(`data-testid="${id}"`)
    expect(at('thread-roster-tile')).toBeGreaterThan(-1)
    expect(at('thread-roster-tile')).toBeLessThan(at('thread-roster-scope'))
    expect(w.find('[data-testid="thread-header-scope"]').exists()).toBe(false)
    expect(w.get('[data-testid="thread-roster-scope"]').text()).toContain('next poll')
  })
})

describe('ThreadTimeline message date (FE-9740)', () => {
  it('1: a message shows its date and time in the header format', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useCommHubStore()
    store.selectedThreadId = 't-time'
    store.handleThreadMessage({
      thread_id: 't-time',
      message_id: 'm-time',
      from_agent_id: 'implementer',
      from_kind: 'agent',
      from_display_name: 'implementer',
      content: 'hello',
      message_type: 'broadcast',
      created_at: '2026-10-05T11:59:00Z',
    })
    const w = mount(ThreadTimeline, { global: { plugins: [pinia, vuetify] } })
    const text = w.get('[data-testid="message-time"]').text()
    expect(text).toBe(formatHubDateTime('2026-10-05T11:59:00Z'))
    expect(text).toMatch(/2026/)
  })
})
