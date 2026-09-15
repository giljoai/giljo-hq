import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { useDashboardRealtime } from './useDashboardRealtime'

const handlersByType = new Map()
const unsub = vi.fn()

vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    on: (type, handler) => {
      handlersByType.set(type, handler)
      return unsub
    },
  }),
}))

function mountHost(refetch) {
  const Host = defineComponent({
    setup() {
      useDashboardRealtime(refetch, { debounceMs: 20 })
      return () => null
    },
  })
  return mount(Host)
}

function fire(type) {
  handlersByType.get(type)?.()
}

describe('useDashboardRealtime — FE-9501c (D7)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    handlersByType.clear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('subscribes to project_update, agent:created, and task:updated on mount', () => {
    mountHost(vi.fn())
    expect(handlersByType.has('project_update')).toBe(true)
    expect(handlersByType.has('agent:created')).toBe(true)
    expect(handlersByType.has('task:updated')).toBe(true)
  })

  it('calls refetch after a single event, once the debounce window elapses', () => {
    const refetch = vi.fn()
    mountHost(refetch)

    fire('project_update')
    expect(refetch).not.toHaveBeenCalled()

    vi.advanceTimersByTime(20)
    expect(refetch).toHaveBeenCalledTimes(1)
  })

  it('collapses a burst across all three event types into ONE refetch', () => {
    const refetch = vi.fn()
    mountHost(refetch)

    fire('project_update')
    fire('agent:created')
    fire('task:updated')
    vi.advanceTimersByTime(20)

    expect(refetch).toHaveBeenCalledTimes(1)
  })

  it('unsubscribes every handler on unmount', () => {
    const wrapper = mountHost(vi.fn())
    wrapper.unmount()
    expect(unsub).toHaveBeenCalledTimes(3)
  })
})
