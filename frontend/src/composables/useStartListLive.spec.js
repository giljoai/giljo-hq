import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent } from 'vue'

const h = vi.hoisted(() => ({ handlers: new Map(), reads: 0 }))
vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    on: (type, fn) => {
      if (!h.handlers.has(type)) h.handlers.set(type, new Set())
      h.handlers.get(type).add(fn)
      return () => h.handlers.get(type).delete(fn)
    },
  }),
}))
vi.mock('@/services/api', () => ({
  default: {
    onboarding: {
      startList: vi.fn(async () => {
        h.reads += 1
        return {
          data: {
            rows: {
              tool_connected: { done: false, live: false, tool_name: null },
              skills_installed: { done: false },
              product_exists: { done: false, product_name: null },
              project_staged: { done: false, has_project: false },
              project_built: { done: false },
            },
            done_count: 0,
          },
        }
      }),
    },
  },
}))
vi.mock('@/stores/user', () => ({ useUserStore: () => ({ currentUser: { id: 'u-1' } }) }))

import { useStartListLive, START_LIST_EVENTS } from '@/composables/useStartListLive'

const mounted = []
const mountHost = () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const w = mount(Host, { global: { plugins: [pinia] } })
  mounted.push(w)
  return w
}

const Host = defineComponent({
  setup() {
    useStartListLive()
    return () => null
  },
})

describe('useStartListLive', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    h.handlers.clear()
    h.reads = 0
  })
  afterEach(() => {
    mounted.splice(0).forEach((w) => w.unmount())
    vi.useRealTimers()
  })

  it('names the events of the card', () => {
    for (const e of [
      'setup:tool_connected',
      'setup:bootstrap_complete',
      'product:created',
      'project:created',
      'project:staging_complete',
      'project_update',
      'project:implementation_launched',
      'project:launched',
      'project:memory_updated',
    ]) {
      expect(START_LIST_EVENTS).toContain(e)
    }
  })

  it('reads once on mount', async () => {
    mountHost()
    await vi.advanceTimersByTimeAsync(0)
    expect(h.reads).toBe(1)
  })

  it.each([
    'setup:tool_connected',
    'setup:bootstrap_complete',
    'product:created',
    'project:created',
    'project:staging_complete',
    'project_update',
    'project:implementation_launched',
    'project:launched',
    'project:memory_updated',
  ])(
    '%s re-reads the facts',
    async (type) => {
      mountHost()
      await vi.advanceTimersByTimeAsync(0)
      h.reads = 0
      for (const fn of h.handlers.get(type)) fn({})
      await vi.advanceTimersByTimeAsync(1000)
      expect(h.reads).toBe(1)
    },
  )

  it('a burst of events collapses into one read', async () => {
    mountHost()
    await vi.advanceTimersByTimeAsync(0)
    h.reads = 0
    for (let i = 0; i < 5; i++) for (const fn of h.handlers.get('project_update')) fn({})
    await vi.advanceTimersByTimeAsync(1000)
    expect(h.reads).toBe(1)
  })

  it('window focus re-reads', async () => {
    mountHost()
    await vi.advanceTimersByTimeAsync(0)
    h.reads = 0
    window.dispatchEvent(new Event('focus'))
    await vi.advanceTimersByTimeAsync(1000)
    expect(h.reads).toBe(1)
  })

  it('unmount removes every listener, so nothing reads after it', async () => {
    const w = mountHost()
    await vi.advanceTimersByTimeAsync(0)
    w.unmount()
    h.reads = 0
    for (const set of h.handlers.values()) expect(set.size).toBe(0)
    window.dispatchEvent(new Event('focus'))
    await vi.advanceTimersByTimeAsync(5000)
    expect(h.reads).toBe(0)
  })

  it('does not poll', async () => {
    mountHost()
    await vi.advanceTimersByTimeAsync(0)
    h.reads = 0
    await vi.advanceTimersByTimeAsync(30 * 60 * 1000)
    expect(h.reads).toBe(0)
  })
})
