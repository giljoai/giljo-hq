import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'
import headerSource from '@/components/hub/HubThreadHeader.vue?raw'
import datesSource from '@/components/hub/ThreadDates.vue?raw'

const copySpy = vi.fn().mockResolvedValue(true)
const toasts = []
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: (t) => toasts.push(t) }) }))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: copySpy }) }))

import HubThreadHeader from '@/components/hub/HubThreadHeader.vue'
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
  project_name: 'Sprint ledger',
}

describe('HubThreadHeader left-grouped (FE-9743)', () => {
  let pinia
  let store

  beforeEach(() => {
    copySpy.mockClear()
    toasts.length = 0
    pinia = createPinia()
    setActivePinia(pinia)
    store = useCommHubStore()
    useProductStore().products = [{ id: 'prod-1', name: 'GiljoAI MCP SaaS edition' }]
    useProjectStore().projects = [
      { id: 'proj-1', name: 'Sprint ledger', taxonomy_alias: 'BE-0017', project_type: { abbreviation: 'BE', color: '#6DB3E4' } },
    ]
  })

  function open(thread) {
    store._testSeedThread(thread)
    store.selectedThreadId = thread.thread_id
    return mount(HubThreadHeader, { global: { plugins: [pinia, vuetify], stubs: { AgentPill: true } } })
  }

  it('1: the copy control is an icon button right after the lock, with a tooltip and an aria-label', async () => {
    const w = open(PROJECT_THREAD)
    const row1 = w.get('[data-testid="thread-header-row1"]')
    const copy = row1.get('[data-testid="thread-header-copy"]')
    expect(copy.attributes('aria-label')).toBe('Copy join id')
    expect(copy.attributes('title')).toBeTruthy()
    expect(copy.text()).not.toContain('Copy join id')
    expect(copy.html()).toContain('mdi-content-copy')
    const html = row1.html()
    const at = (id) => html.indexOf(`data-testid="${id}"`)
    expect(at('thread-header-serial')).toBeLessThan(at('thread-header-title'))
    expect(at('thread-header-title')).toBeLessThan(at('thread-header-rename'))
    expect(at('thread-header-rename')).toBeLessThan(at('thread-header-copy'))
    await copy.trigger('click')
    expect(copySpy).toHaveBeenCalledWith('t-project')
    expect(toasts[0].type).toBe('success')
  })

  it('1: nothing in the header or the dates is pinned to the right edge', () => {
    expect(headerSource).not.toMatch(/margin-left:\s*auto/)
    expect(datesSource).not.toMatch(/margin-left:\s*auto/)
  })

  it('1: Created and Last msg flow with the other row 2 items, dot separated', () => {
    const w = open(GENERAL)
    const dates = w.get('[data-testid="thread-header-row2"] [data-testid="thread-header-dates"]')
    expect(dates.classes()).toContain('thread-dates--dotted')
    expect(dates.classes()).toContain('thread-dates--tinted')
    expect(headerSource).toMatch(/row2 > \* \+ \*::before/)
  })

  it('2: a project thread whose project title equals the thread title shows the badge only', () => {
    const w = open(PROJECT_THREAD)
    const line = w.get('[data-testid="thread-header-project"]')
    expect(line.get('[data-testid="thread-header-project-badge"]').text()).toBe('BE-0017')
    expect(line.find('.hub-thread-header__project-name').exists()).toBe(false)
    expect(w.get('[data-testid="thread-header-row2"]').text()).not.toContain('Sprint ledger')
  })

  it('2: the comparison ignores case and surrounding whitespace', () => {
    const w = open({ ...PROJECT_THREAD, project_name: '  sprint LEDGER ' })
    expect(w.find('.hub-thread-header__project-name').exists()).toBe(false)
  })

  it('2: a project title that differs from the thread title is still shown', () => {
    const w = open({ ...PROJECT_THREAD, title: 'Sprint ledger chat' })
    const name = w.get('.hub-thread-header__project-name')
    expect(name.text()).toBe('Sprint ledger')
  })

  it('2: a standalone thread keeps the muted General', () => {
    const w = open(GENERAL)
    expect(w.get('[data-testid="thread-header-general"]').text()).toBe('General')
  })

  it('2: a project thread with no alias loaded and a duplicate title leaves no empty project line', () => {
    useProjectStore().projects = []
    const w = open(PROJECT_THREAD)
    expect(w.find('[data-testid="thread-header-project"]').exists()).toBe(false)
    expect(w.get('[data-testid="thread-header-product"]').text()).toBe('GiljoAI MCP SaaS edition')
  })
})
