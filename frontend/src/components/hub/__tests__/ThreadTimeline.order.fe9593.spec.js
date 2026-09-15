import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

import ThreadTimeline from '@/components/hub/ThreadTimeline.vue'
import HubThreadToolbar from '@/components/hub/HubThreadToolbar.vue'
import {
  useHubMessageOrder,
  MESSAGE_ORDER_KEY,
  NEWEST_FIRST,
  OLDEST_FIRST,
  _resetHubMessageOrderForTests,
} from '@/components/hub/useHubMessageOrder'
import { useCommHubStore } from '@/stores/commHubStore'

const vuetify = createVuetify()
const THREAD_ID = 'thr-order'

const MESSAGES = [
  { message_id: 'm1', from_agent_id: 'a', from_kind: 'agent', from_display_name: 'A', content: 'first', message_type: 'broadcast', created_at: '2026-09-01T10:00:00Z' },
  { message_id: 'm2', from_agent_id: 'a', from_kind: 'agent', from_display_name: 'A', content: 'second, right after', message_type: 'broadcast', created_at: '2026-09-01T10:01:00Z' },
  { message_id: 'm3', from_agent_id: 'b', from_kind: 'agent', from_display_name: 'B', content: 'third', message_type: 'broadcast', created_at: '2026-09-01T13:00:00Z' },
].map((m) => ({ ...m, thread_id: THREAD_ID }))

function installFunctionalLocalStorage() {
  const store = new Map()
  Object.defineProperty(window, 'localStorage', {
    value: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
      clear: () => store.clear(),
    },
    writable: true,
  })
  return store
}

function renderedIds(wrapper) {
  return wrapper.findAll('.timeline-msg').map((row) => row.attributes('data-testid'))
}

function mountTimeline(pinia) {
  return mount(ThreadTimeline, { global: { plugins: [pinia, vuetify] } })
}

function mountToolbar(pinia) {
  return mount(HubThreadToolbar, {
    props: { modelValue: '' },
    global: { plugins: [pinia, vuetify], stubs: { MarkHandledToggle: true } },
  })
}

describe('message order (FE-9593)', () => {
  let pinia
  let storage

  beforeEach(() => {
    storage = installFunctionalLocalStorage()
    _resetHubMessageOrderForTests()
    pinia = createPinia()
    setActivePinia(pinia)
    const store = useCommHubStore()
    store.selectedThreadId = THREAD_ID
    MESSAGES.forEach((m) => store.handleThreadMessage(m))
  })

  it('defaults to oldest on top — the order the timeline always had', () => {
    const w = mountTimeline(pinia)
    expect(renderedIds(w)).toEqual(['timeline-message-m1', 'timeline-message-m2', 'timeline-message-m3'])

    const t = mountToolbar(pinia)
    expect(t.find('[data-testid="message-order-oldest"]').attributes('aria-pressed')).toBe('true')
    expect(t.find('[data-testid="message-order-newest"]').attributes('aria-pressed')).toBe('false')
  })

  it('the control flips the open thread to newest on top, and back', async () => {
    const timeline = mountTimeline(pinia)
    const toolbar = mountToolbar(pinia)

    await toolbar.find('[data-testid="message-order-newest"]').trigger('click')
    expect(renderedIds(timeline)).toEqual(['timeline-message-m3', 'timeline-message-m2', 'timeline-message-m1'])
    expect(toolbar.find('[data-testid="message-order-newest"]').attributes('aria-pressed')).toBe('true')

    await toolbar.find('[data-testid="message-order-oldest"]').trigger('click')
    expect(renderedIds(timeline)).toEqual(['timeline-message-m1', 'timeline-message-m2', 'timeline-message-m3'])
  })

  it('persists the choice per browser and reads it back on a fresh mount', async () => {
    const toolbar = mountToolbar(pinia)
    await toolbar.find('[data-testid="message-order-newest"]').trigger('click')
    expect(storage.get(MESSAGE_ORDER_KEY)).toBe(NEWEST_FIRST)

    _resetHubMessageOrderForTests()
    expect(useHubMessageOrder().order.value).toBe(NEWEST_FIRST)
    expect(renderedIds(mountTimeline(pinia))[0]).toBe('timeline-message-m3')
  })

  it('ignores a corrupt stored value rather than rendering nothing', () => {
    storage.set(MESSAGE_ORDER_KEY, 'sideways')
    _resetHubMessageOrderForTests()
    expect(useHubMessageOrder().order.value).toBe(OLDEST_FIRST)
  })

  it('keeps one author badge per run, at the TOP of the run, in either direction', async () => {
    const w = mountTimeline(pinia)
    const grouped = () =>
      w.findAll('.timeline-msg').map((row) => row.classes('timeline-msg--grouped'))

    expect(grouped()).toEqual([false, true, false])

    useHubMessageOrder().setOrder(NEWEST_FIRST)
    await w.vm.$nextTick()
    expect(renderedIds(w)).toEqual(['timeline-message-m3', 'timeline-message-m2', 'timeline-message-m1'])
    expect(grouped()).toEqual([false, false, true])
  })
})
