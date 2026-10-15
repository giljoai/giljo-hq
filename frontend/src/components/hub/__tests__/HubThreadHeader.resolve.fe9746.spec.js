import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

const showToast = vi.fn()
const updateMock = vi.fn()
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast }) }))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: vi.fn() }) }))
vi.mock('@/services/api', () => {
  const api = { threads: { update: (...a) => updateMock(...a), list: vi.fn(), markRead: vi.fn() } }
  return { default: api, api }
})

import HubThreadHeader from '@/components/hub/HubThreadHeader.vue'
import { useCommHubStore } from '@/stores/commHubStore'

const vuetify = createVuetify()
const THREAD = { thread_id: 't1', chat_id: 'CHT-0042', subject: 'General chat', status: 'open', product_id: null, project_id: null, participants: [] }

describe('HubThreadHeader resolve / reopen control (FE-9746)', () => {
  let pinia
  let store

  beforeEach(() => {
    showToast.mockReset()
    updateMock.mockReset()
    pinia = createPinia()
    setActivePinia(pinia)
    store = useCommHubStore()
  })

  function open(thread) {
    store._testSeedThread(thread)
    store.selectedThreadId = thread.thread_id
    return mount(HubThreadHeader, { global: { plugins: [pinia, vuetify], stubs: { AgentPill: true } } })
  }

  it('sits right after the copy icon in row 1 and reads Mark resolved on a live thread', () => {
    const w = open(THREAD)
    const row1 = w.get('[data-testid="thread-header-row1"]')
    const btn = row1.get('[data-testid="thread-header-resolve"]')
    expect(btn.attributes('aria-label')).toBe('Mark resolved')
    expect(btn.attributes('title')).toBe('Mark resolved')
    expect(btn.html()).toContain('mdi-check-circle-outline')
    const html = row1.html()
    expect(html.indexOf('data-testid="thread-header-copy"')).toBeLessThan(html.indexOf('data-testid="thread-header-resolve"'))
  })

  it.each(['resolved', 'closed'])('reads Reopen with the undo icon on a %s thread', (status) => {
    const w = open({ ...THREAD, status })
    const btn = w.get('[data-testid="thread-header-resolve"]')
    expect(btn.attributes('aria-label')).toBe('Reopen')
    expect(btn.html()).toContain('mdi-undo')
  })

  it('resolves with one click, no dialog, and toasts with an Undo that restores the previous status', async () => {
    updateMock.mockResolvedValue({ data: { thread_id: 't1', status: 'resolved' } })
    const w = open(THREAD)
    await w.get('[data-testid="thread-header-resolve"]').trigger('click')
    await flushPromises()
    expect(updateMock).toHaveBeenCalledWith('t1', { status: 'resolved' })
    expect(store.selectedThread.status).toBe('resolved')
    const toast = showToast.mock.calls.at(-1)[0]
    expect(toast.type).toBe('success')
    expect(toast.action.label).toBe('Undo')

    updateMock.mockResolvedValue({ data: { thread_id: 't1', status: 'open' } })
    await toast.action.callback()
    await flushPromises()
    expect(updateMock).toHaveBeenLastCalledWith('t1', { status: 'open' })
    expect(store.selectedThread.status).toBe('open')
  })

  it('reopens a closed thread and Undo puts it back to closed', async () => {
    updateMock.mockResolvedValue({ data: { thread_id: 't1', status: 'open' } })
    const w = open({ ...THREAD, status: 'closed' })
    await w.get('[data-testid="thread-header-resolve"]').trigger('click')
    await flushPromises()
    expect(updateMock).toHaveBeenCalledWith('t1', { status: 'open' })
    const toast = showToast.mock.calls.at(-1)[0]

    updateMock.mockResolvedValue({ data: { thread_id: 't1', status: 'closed' } })
    await toast.action.callback()
    await flushPromises()
    expect(updateMock).toHaveBeenLastCalledWith('t1', { status: 'closed' })
    expect(store.selectedThread.status).toBe('closed')
  })

  it('shows an error toast and leaves the status alone when the server refuses', async () => {
    updateMock.mockRejectedValue(new Error('boom'))
    const w = open(THREAD)
    await w.get('[data-testid="thread-header-resolve"]').trigger('click')
    await flushPromises()
    expect(store.selectedThread.status).toBe('open')
    expect(showToast.mock.calls.at(-1)[0].type).toBe('error')
  })
})
