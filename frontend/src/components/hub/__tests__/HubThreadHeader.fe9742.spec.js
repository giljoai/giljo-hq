import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

const copySpy = vi.fn().mockResolvedValue(true)
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))
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
  project_name: 'Sprint ledger project',
}

describe('HubThreadHeader main frame (FE-9742)', () => {
  let pinia
  let store

  beforeEach(() => {
    copySpy.mockClear()
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

  it('1: row 1 holds serial, title, lock icon and one Copy join id control that copies the UUID', async () => {
    const w = open(PROJECT_THREAD)
    const row1 = w.get('[data-testid="thread-header-row1"]')
    expect(row1.get('[data-testid="thread-header-serial"]').text()).toBe('CHT-0043')
    expect(row1.get('[data-testid="thread-header-title"]').text()).toBe('Sprint ledger')
    expect(row1.get('[data-testid="thread-header-rename"]').html()).toContain('mdi-lock-outline')
    const copy = row1.get('[data-testid="thread-header-copy"]')
    expect(copy.attributes('aria-label')).toBe('Copy join id')
    await copy.trigger('click')
    expect(copySpy).toHaveBeenCalledWith('t-project')
  })

  it('1: a standalone thread shows the rename pencil', () => {
    const w = open(GENERAL)
    expect(w.get('[data-testid="thread-header-rename"]').html()).toContain('mdi-pencil-outline')
  })

  it('1: the second copy icon and the join_thread line are gone from the frame', () => {
    const w = open(GENERAL)
    const header = w.get('[data-testid="thread-header"]')
    expect(header.html().match(/mdi-content-copy/g)).toHaveLength(1)
    expect(header.find('[data-testid="thread-header-id"]').exists()).toBe(false)
    expect(header.text()).not.toContain('join_thread')
    expect(header.text()).not.toContain('t-general')
  })

  it('1: row 2 of a project thread is badge, project title, product, with no label words', () => {
    const w = open(PROJECT_THREAD)
    const row2 = w.get('[data-testid="thread-header-row2"]')
    expect(row2.text()).not.toContain('Project:')
    expect(row2.text()).not.toContain('Product:')
    expect(row2.get('[data-testid="thread-header-project-badge"]').text()).toBe('BE-0017')
    expect(row2.get('[data-testid="thread-header-project"]').text()).toContain('Sprint ledger')
    expect(row2.get('[data-testid="thread-header-product"]').text()).toBe('GiljoAI MCP SaaS edition')
    expect(row2.get('[data-testid="thread-header-product"]').classes()).toContain('hub-thread-header__muted')
    const html = row2.html()
    const at = (id) => html.indexOf(`data-testid="${id}"`)
    expect(at('thread-header-project')).toBeLessThan(at('thread-header-project-badge'))
    expect(at('thread-header-project-badge')).toBeLessThan(at('thread-header-product'))
    expect(at('thread-header-product')).toBeLessThan(at('thread-header-dates'))
  })

  it('1: a standalone thread shows a muted General instead of a project, then the product', () => {
    const w = open(GENERAL)
    const row2 = w.get('[data-testid="thread-header-row2"]')
    const general = row2.get('[data-testid="thread-header-general"]')
    expect(general.text()).toBe('General')
    expect(general.classes()).toContain('hub-thread-header__muted')
    expect(row2.find('[data-testid="thread-header-project"]').exists()).toBe(false)
    expect(row2.get('[data-testid="thread-header-product"]').text()).toBe('GiljoAI MCP SaaS edition')
  })

  it('1: a product-less standalone thread shows General and no product text', () => {
    const w = open({ ...GENERAL, product_id: null })
    const row2 = w.get('[data-testid="thread-header-row2"]')
    expect(row2.get('[data-testid="thread-header-general"]').text()).toBe('General')
    expect(row2.find('[data-testid="thread-header-product"]').exists()).toBe(false)
  })

  it('1: Created and Last msg stay tinted and live in row 2', () => {
    const w = open(GENERAL)
    const dates = w.get('[data-testid="thread-header-row2"] [data-testid="thread-header-dates"]')
    expect(dates.classes()).toContain('thread-dates--tinted')
    expect(dates.text()).toContain('Created')
    expect(dates.text()).toContain('Last msg')
  })

  it('1: no agent pills and no scope note in the main frame; the roster frame follows it', () => {
    store.participantsByThreadId = new Map([
      ['t-general', [{ participant_id: 'a1', participant_type: 'agent', display_name: 'x', harness: 'claude-code' }]],
    ])
    const w = open(GENERAL)
    const header = w.get('[data-testid="thread-header"]')
    expect(header.find('[data-testid="thread-header-pills"]').exists()).toBe(false)
    expect(header.find('[data-testid="thread-header-scope"]').exists()).toBe(false)
    expect(header.find('[data-testid="thread-roster-scope"]').exists()).toBe(false)
    const html = w.html()
    expect(html.indexOf('data-testid="thread-header"')).toBeLessThan(html.indexOf('data-testid="thread-roster"'))
  })
})
