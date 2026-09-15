import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createReconnectPolicy } from '@/stores/websocketReconnectPolicy'

vi.mock('@/composables/useApiUrl', () => ({
  getApiBaseUrl: () => 'http://localhost:8000',
  getWsBaseUrl: () => 'ws://localhost:8000',
}))

import { useWebSocketStore } from '@/stores/websocket'

describe('createReconnectPolicy (FE-9056)', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('arm: slow-retry interval fires the reconnect callback repeatedly', () => {
    const cb = vi.fn()
    const policy = createReconnectPolicy({ onReconnectNeeded: cb, slowRetryDelay: 60000 })
    policy.arm()
    expect(cb).not.toHaveBeenCalled()
    vi.advanceTimersByTime(60000)
    expect(cb).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(60000)
    expect(cb).toHaveBeenCalledTimes(2)
    policy.disarm()
  })

  it('online event triggers an immediate reconnect', () => {
    const cb = vi.fn()
    const policy = createReconnectPolicy({ onReconnectNeeded: cb })
    policy.arm()
    window.dispatchEvent(new Event('online'))
    expect(cb).toHaveBeenCalledWith('online')
    policy.disarm()
  })

  it('visibilitychange re-arms only when the tab becomes visible', () => {
    const cb = vi.fn()
    const policy = createReconnectPolicy({ onReconnectNeeded: cb })
    policy.arm()

    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
    expect(cb).not.toHaveBeenCalled()

    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
    document.dispatchEvent(new Event('visibilitychange'))
    expect(cb).toHaveBeenCalledWith('visibility')
    policy.disarm()
  })

  it('disarm stops the timer and removes listeners (no leak)', () => {
    const cb = vi.fn()
    const policy = createReconnectPolicy({ onReconnectNeeded: cb, slowRetryDelay: 60000 })
    policy.arm()
    policy.disarm()
    vi.advanceTimersByTime(120000)
    window.dispatchEvent(new Event('online'))
    expect(cb).not.toHaveBeenCalled()
    expect(policy.isArmed()).toBe(false)
  })

  it('arm is idempotent: double-arm keeps a single interval + listener set', () => {
    const cb = vi.fn()
    const policy = createReconnectPolicy({ onReconnectNeeded: cb, slowRetryDelay: 60000 })
    policy.arm()
    policy.arm()
    vi.advanceTimersByTime(60000)
    expect(cb).toHaveBeenCalledTimes(1)
    window.dispatchEvent(new Event('online'))
    expect(cb).toHaveBeenCalledTimes(2)
    policy.disarm()
  })
})

describe('websocket store post-cap reconnect (FE-9056)', () => {
  let sockets
  let RealWebSocket

  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    sockets = []
    RealWebSocket = global.WebSocket
    global.WebSocket = class {
      constructor(url) {
        this.url = url
        this.readyState = 0
        this.onopen = null
        this.onmessage = null
        this.onclose = null
        this.onerror = null
        sockets.push(this)
      }
      send() {}
      close() {
        this.readyState = 3
      }
    }
  })

  afterEach(() => {
    global.WebSocket = RealWebSocket
    vi.useRealTimers()
  })

  const failLatest = () => {
    const s = sockets[sockets.length - 1]
    if (s && s.onclose) {
      s.onclose({ code: 1006, reason: 'test drop' })
    }
  }

  it('arms slow-retry + online re-arm after the cap, and disarms on a successful open', async () => {
    const store = useWebSocketStore()
    store.connect({}).catch(() => {})

    let guard = 0
    while (store.reconnectAttempts < 10 && guard++ < 50) {
      failLatest()
      await vi.advanceTimersByTimeAsync(30000)
    }
    expect(store.reconnectAttempts).toBe(10)

    failLatest()
    const countAfterArm = sockets.length

    window.dispatchEvent(new Event('online'))
    expect(sockets.length).toBe(countAfterArm + 1)

    failLatest()
    const countBeforeSlow = sockets.length
    await vi.advanceTimersByTimeAsync(60000)
    expect(sockets.length).toBe(countBeforeSlow + 1)

    sockets[sockets.length - 1].onopen()
    expect(store.isConnected).toBe(true)
    const countAfterOpen = sockets.length
    await vi.advanceTimersByTimeAsync(65000)
    expect(sockets.length).toBe(countAfterOpen)
  })
})
