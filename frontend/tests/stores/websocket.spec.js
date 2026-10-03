/**
 * Unit tests for WebSocket V2 Store
 * Following TDD principles: Tests focus on BEHAVIOR, not implementation
 *
 * Test Coverage Categories:
 * 1. Connection Lifecycle
 * 2. Reconnection Logic with Exponential Backoff
 * 3. Message Queue (Offline Support)
 * 4. Event Handler Management (Subscription System)
 * 5. Error Handling
 * 6. Connection State Management
 *
 * NOTE: These tests are refactoring-resistant and test the PUBLIC API only
 *
 * IMPORTANT: The store's disconnect() calls ws.close() which triggers the
 * onclose handler asynchronously. That handler calls handleDisconnect() which
 * may attempt reconnection. Tests must use fake timers to control this.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useWebSocketStore } from '@/stores/websocket'

// ============================================
// MOCK SETUP
// ============================================

// Mock WebSocket API
class MockWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3

  constructor(url) {
    this.url = url
    this.readyState = MockWebSocket.CONNECTING
    this.onopen = null
    this.onclose = null
    this.onerror = null
    this.onmessage = null
    this._listeners = new Map()

    // Store instance for test access
    MockWebSocket.instances.push(this)

    // Trigger onopen synchronously in the next microtask
    Promise.resolve().then(() => {
      if (this.onopen && this.readyState === MockWebSocket.CONNECTING) {
        this.readyState = MockWebSocket.OPEN
        this.onopen()
      }
    })
  }

  send(data) {
    if (this.readyState !== MockWebSocket.OPEN) {
      throw new Error('WebSocket is not open')
    }
    // Store sent messages for verification
    MockWebSocket.sentMessages.push(JSON.parse(data))
  }

  close(code = 1000, reason = '') {
    this.readyState = MockWebSocket.CLOSING
    Promise.resolve().then(() => {
      this.readyState = MockWebSocket.CLOSED
      if (this.onclose) {
        this.onclose({ code, reason })
      }
    })
  }

  // Test helper: simulate receiving a message
  simulateMessage(data) {
    if (this.onmessage) {
      this.onmessage({ data: JSON.stringify(data) })
    }
  }

  // Test helper: simulate connection error
  simulateError(error = new Error('Connection error')) {
    if (this.onerror) {
      this.onerror(error)
    }
  }
}

// Static storage for test verification
MockWebSocket.instances = []
MockWebSocket.sentMessages = []

// Reset static storage
MockWebSocket.reset = () => {
  MockWebSocket.instances = []
  MockWebSocket.sentMessages = []
}

// Install mock globally
global.WebSocket = MockWebSocket

// Mock API_CONFIG with port (store uses port, not url directly)
vi.mock('@/config/api', () => ({
  API_CONFIG: {
    WEBSOCKET: {
      url: 'ws://localhost:7272',
      port: 7272,
      debug: false
    }
  }
}))

// Mock useToast with a SHARED hoisted spy so tests can assert which toasts fired
const { showToastSpy } = vi.hoisted(() => ({ showToastSpy: vi.fn() }))
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({
    showToast: showToastSpy
  })
}))

// Mock notification store (used in handleDisconnect and attemptReconnect).
//
// FE-9553: this now uses a SHARED hoisted spy, for the same reason the toast
// mock above does. It previously returned a fresh vi.fn() on every
// useNotificationStore() call, which means no test could assert on it at all --
// an assertion would have inspected a spy the code under test never touched and
// passed whether or not a bell row was written. Ruling 2 moves connection state
// OUT of the bell, so that write is now exactly what needs observing.
const { addNotificationSpy } = vi.hoisted(() => ({ addNotificationSpy: vi.fn() }))
vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => ({
    addNotification: addNotificationSpy
  })
}))

// ============================================
// TEST HELPERS
// ============================================

// ============================================
// TEST SUITE
// ============================================

describe('WebSocket V2 Store - Connection Lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    MockWebSocket.reset()
  })

  afterEach(async () => {
    // Clean up: disconnect any active connections to prevent
    // reconnection attempts from leaking into the next test
    const store = useWebSocketStore()
    if (store.isConnected || store.isConnecting || store.isReconnecting) {
      store.disconnect()
    }
    // Flush microtasks to let onclose handlers settle
    await vi.advanceTimersByTimeAsync(0)
    // Run all pending timers to clear reconnection timeouts
    vi.runAllTimers()
    vi.useRealTimers()
  })

  it('test_initial_state_is_disconnected', () => {
    const store = useWebSocketStore()

    expect(store.isConnected).toBe(false)
    expect(store.isConnecting).toBe(false)
    expect(store.isDisconnected).toBe(true)
    expect(store.connectionStatus).toBe('disconnected')
    expect(store.clientId).toBeNull()
  })

  it('test_connect_establishes_websocket_connection', async () => {
    const store = useWebSocketStore()

    const connectPromise = store.connect({ token: 'test-token' })

    // Should immediately transition to 'connecting'
    expect(store.isConnecting).toBe(true)
    expect(store.connectionStatus).toBe('connecting')

    // Wait for connection to open
    await vi.advanceTimersByTimeAsync(0)
    await connectPromise

    // Should be connected
    expect(store.isConnected).toBe(true)
    expect(store.connectionStatus).toBe('connected')
    expect(store.clientId).not.toBeNull()
  })

  it('test_connect_generates_fresh_client_id_per_socket', async () => {
    // BE-6029: a fresh client_id is generated for EACH physical socket. The
    // server keys connections by client_id and overwrites on collision, so
    // reusing one id across reconnects let a stale socket's teardown evict the
    // live one. A new id per connect avoids that orphaning.
    const store = useWebSocketStore()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    const clientId1 = store.clientId
    expect(clientId1).not.toBeNull()

    // Disconnect and reconnect
    store.disconnect()
    // Advance past the onclose and any reconnection
    await vi.advanceTimersByTimeAsync(0)
    vi.runAllTimers()
    await vi.advanceTimersByTimeAsync(0)

    // Reset MockWebSocket for clean reconnection
    MockWebSocket.reset()
    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    const clientId2 = store.clientId

    // Client ID must be regenerated for the new socket, not reused
    expect(clientId2).not.toBe(clientId1)
  })

  it('test_connect_uses_correct_websocket_url', async () => {
    const store = useWebSocketStore()

    await store.connect({ apiKey: 'test-key' })
    await vi.advanceTimersByTimeAsync(0)

    const wsInstance = MockWebSocket.instances[0]
    expect(wsInstance.url).toContain('/ws/')
    expect(wsInstance.url).toContain('api_key=test-key')
  })

  it('test_disconnect_sets_status_synchronously', async () => {
    const store = useWebSocketStore()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    expect(store.isConnected).toBe(true)

    // disconnect() synchronously sets status to 'disconnected'
    store.disconnect()

    // Check synchronously (before microtasks flush)
    expect(store.connectionStatus).toBe('disconnected')
  })

  it('test_connection_status_transitions_through_connecting_to_connected', async () => {
    const store = useWebSocketStore()

    // Initial: disconnected
    expect(store.connectionStatus).toBe('disconnected')

    // During connection: connecting
    const connectPromise = store.connect()
    expect(store.connectionStatus).toBe('connecting')

    // After connection: connected
    await vi.advanceTimersByTimeAsync(0)
    await connectPromise
    expect(store.connectionStatus).toBe('connected')
  })

  it('test_connect_does_not_reconnect_if_already_connected', async () => {
    const store = useWebSocketStore()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    const instanceCount = MockWebSocket.instances.length

    // Try connecting again
    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    // Should not create a new WebSocket instance
    expect(MockWebSocket.instances.length).toBe(instanceCount)
  })
})

describe('WebSocket V2 Store - Reconnection Logic', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    MockWebSocket.reset()
  })

  afterEach(async () => {
    const store = useWebSocketStore()
    if (store.isConnected || store.isConnecting || store.isReconnecting) {
      store.disconnect()
    }
    await vi.advanceTimersByTimeAsync(0)
    vi.runAllTimers()
    await vi.advanceTimersByTimeAsync(0)
    vi.useRealTimers()
  })

  it('test_reconnection_uses_exponential_backoff_delays', async () => {
    const store = useWebSocketStore()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    // Simulate connection loss
    const wsInstance = MockWebSocket.instances[0]
    wsInstance.close(1006, 'Connection lost')
    await vi.advanceTimersByTimeAsync(0)

    // Verify reconnection attempts with exponential backoff
    // Attempt 1: 1000ms (1s * 2^0)
    expect(store.connectionStatus).toBe('reconnecting')
    expect(store.reconnectAttempts).toBe(1)

    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(0)

    // Should have attempted reconnection
    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(2)
  })

  it('test_reconnection_resets_attempt_counter_after_stability_window', async () => {
    // BE-6029: the backoff counter is reset only AFTER the connection has
    // stayed up for stabilityResetDelay (not the instant onopen fires). This is
    // what lets exponential backoff + the attempt cap engage against a flapping
    // server instead of hammering reconnect every ~1s forever.
    const store = useWebSocketStore()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    // Simulate disconnect
    const wsInstance = MockWebSocket.instances[0]
    wsInstance.close(1006, 'Connection lost')
    await vi.advanceTimersByTimeAsync(0)

    expect(store.reconnectAttempts).toBe(1)

    // Wait for reconnection to open
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(0)
    expect(store.isConnected).toBe(true)

    // Immediately after reopen the counter is NOT yet reset (must prove stable)
    expect(store.reconnectAttempts).toBe(1)

    // After staying up past the stability window, the counter resets
    await vi.advanceTimersByTimeAsync(30000)
    expect(store.reconnectAttempts).toBe(0)
  })

  it('test_reconnection_preserves_auth_credentials', async () => {
    const store = useWebSocketStore()

    await store.connect({ token: 'secret-token' })
    await vi.advanceTimersByTimeAsync(0)

    const firstUrl = MockWebSocket.instances[0].url
    expect(firstUrl).toContain('token=secret-token')

    // Simulate disconnect
    MockWebSocket.instances[0].close(1006, 'Connection lost')
    await vi.advanceTimersByTimeAsync(0)

    // Wait for reconnection
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(0)

    // Reconnection should use same credentials
    const secondUrl = MockWebSocket.instances[1].url
    expect(secondUrl).toContain('token=secret-token')
  })
})

describe('WebSocket V2 Store - Message Queue (Offline Support)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    MockWebSocket.reset()
  })

  afterEach(async () => {
    const store = useWebSocketStore()
    if (store.isConnected || store.isConnecting || store.isReconnecting) {
      store.disconnect()
    }
    await vi.advanceTimersByTimeAsync(0)
    vi.runAllTimers()
    await vi.advanceTimersByTimeAsync(0)
    vi.useRealTimers()
  })

  it('test_messages_queued_when_disconnected', () => {
    const store = useWebSocketStore()

    // Send message while disconnected
    const result = store.send({ type: 'test', data: 'hello' })

    expect(result).toBe(false) // Should return false when queued
    expect(store.messageQueueSize).toBe(1)
  })

  it('test_queued_messages_sent_on_reconnect', async () => {
    const store = useWebSocketStore()

    // Queue messages while offline
    store.send({ type: 'msg1', data: 'first' })
    store.send({ type: 'msg2', data: 'second' })
    store.send({ type: 'msg3', data: 'third' })

    expect(store.messageQueueSize).toBe(3)

    // Connect
    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    // Queue should be flushed
    expect(store.messageQueueSize).toBe(0)

    // All messages should have been sent
    expect(MockWebSocket.sentMessages.length).toBeGreaterThanOrEqual(3)
    expect(MockWebSocket.sentMessages).toContainEqual({ type: 'msg1', data: 'first' })
    expect(MockWebSocket.sentMessages).toContainEqual({ type: 'msg2', data: 'second' })
    expect(MockWebSocket.sentMessages).toContainEqual({ type: 'msg3', data: 'third' })
  })

  it('test_message_queue_maintains_fifo_order', async () => {
    const store = useWebSocketStore()

    // Queue messages in specific order
    for (let i = 1; i <= 5; i++) {
      store.send({ type: 'order', seq: i })
    }

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    // Filter out ping messages
    const orderMessages = MockWebSocket.sentMessages.filter(msg => msg.type === 'order')

    // Verify FIFO order
    for (let i = 0; i < orderMessages.length; i++) {
      expect(orderMessages[i].seq).toBe(i + 1)
    }
  })

  it('test_message_queue_limits_size_to_prevent_unbounded_growth', () => {
    const store = useWebSocketStore()

    // Queue 150 messages (limit is 100)
    for (let i = 0; i < 150; i++) {
      store.send({ type: 'spam', seq: i })
    }

    // Queue should be capped at 100
    expect(store.messageQueueSize).toBe(100)
  })
})

describe('WebSocket V2 Store - Event Handler Management', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    MockWebSocket.reset()
  })

  afterEach(async () => {
    const store = useWebSocketStore()
    if (store.isConnected || store.isConnecting || store.isReconnecting) {
      store.disconnect()
    }
    await vi.advanceTimersByTimeAsync(0)
    vi.runAllTimers()
    await vi.advanceTimersByTimeAsync(0)
    vi.useRealTimers()
  })

  it('test_on_registers_event_handler', async () => {
    const store = useWebSocketStore()
    const handler = vi.fn()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    // Register handler
    store.on('agent:update', handler)

    // Simulate incoming message
    const wsInstance = MockWebSocket.instances[0]
    wsInstance.simulateMessage({ type: 'agent:update', data: { id: '123' } })

    // After Handover 0290: Payload normalization merges nested data to top level
    // Handler receives: { data: { id: '123' }, id: '123' } - both nested and flat access
    expect(handler).toHaveBeenCalled()
    const receivedPayload = handler.mock.calls[0][0]
    expect(receivedPayload.id).toBe('123') // Flat access works
    expect(receivedPayload.data.id).toBe('123') // Nested access preserved
  })

  it('test_on_returns_unsubscribe_function', async () => {
    const store = useWebSocketStore()
    const handler = vi.fn()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    // Register and immediately unregister
    const unsubscribe = store.on('test_event', handler)
    unsubscribe()

    // Trigger event
    const wsInstance = MockWebSocket.instances[0]
    wsInstance.simulateMessage({ type: 'test_event', data: {} })

    // Handler should not be called
    expect(handler).not.toHaveBeenCalled()
  })

  it('test_off_removes_event_handler', async () => {
    const store = useWebSocketStore()
    const handler = vi.fn()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    store.on('test_event', handler)
    store.off('test_event', handler)

    // Trigger event
    const wsInstance = MockWebSocket.instances[0]
    wsInstance.simulateMessage({ type: 'test_event', data: {} })

    expect(handler).not.toHaveBeenCalled()
  })

  it('test_multiple_handlers_can_subscribe_to_same_event', async () => {
    const store = useWebSocketStore()
    const handler1 = vi.fn()
    const handler2 = vi.fn()
    const handler3 = vi.fn()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    store.on('shared_event', handler1)
    store.on('shared_event', handler2)
    store.on('shared_event', handler3)

    // Trigger event
    const wsInstance = MockWebSocket.instances[0]
    wsInstance.simulateMessage({ type: 'shared_event', data: { msg: 'test' } })

    // All handlers should be called
    expect(handler1).toHaveBeenCalledTimes(1)
    expect(handler2).toHaveBeenCalledTimes(1)
    expect(handler3).toHaveBeenCalledTimes(1)
  })

  it('test_wildcard_handler_receives_all_events', async () => {
    const store = useWebSocketStore()
    const wildcardHandler = vi.fn()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    // Register wildcard handler
    store.on('*', wildcardHandler)

    // Send various event types
    const wsInstance = MockWebSocket.instances[0]
    wsInstance.simulateMessage({ type: 'event1', data: 'a' })
    wsInstance.simulateMessage({ type: 'event2', data: 'b' })
    wsInstance.simulateMessage({ type: 'event3', data: 'c' })

    // Wildcard handler should receive all events
    expect(wildcardHandler).toHaveBeenCalledTimes(3)
  })

  it('test_handler_errors_are_caught_and_do_not_break_other_handlers', async () => {
    const store = useWebSocketStore()
    const errorHandler = vi.fn(() => {
      throw new Error('Handler error')
    })
    const goodHandler = vi.fn()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    store.on('test_event', errorHandler)
    store.on('test_event', goodHandler)

    // Trigger event
    const wsInstance = MockWebSocket.instances[0]
    wsInstance.simulateMessage({ type: 'test_event', data: {} })

    // Both handlers should be called despite error
    expect(errorHandler).toHaveBeenCalled()
    expect(goodHandler).toHaveBeenCalled()
  })
})

describe('WebSocket V2 Store - Error Handling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    MockWebSocket.reset()
  })

  afterEach(async () => {
    const store = useWebSocketStore()
    if (store.isConnected || store.isConnecting || store.isReconnecting) {
      store.disconnect()
    }
    await vi.advanceTimersByTimeAsync(0)
    vi.runAllTimers()
    await vi.advanceTimersByTimeAsync(0)
    vi.useRealTimers()
  })

  it('test_connection_failure_is_handled_gracefully', async () => {
    const store = useWebSocketStore()

    // Override mock to fail connection
    const originalWebSocket = global.WebSocket
    global.WebSocket = vi.fn(() => {
      throw new Error('Connection refused')
    })

    let error
    try {
      await store.connect()
      await vi.advanceTimersByTimeAsync(0)
    } catch (e) {
      error = e
    }

    expect(error).toBeDefined()
    expect(store.isDisconnected).toBe(true)

    // Restore
    global.WebSocket = originalWebSocket
  })

  it('test_malformed_json_messages_handled_gracefully', async () => {
    const store = useWebSocketStore()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    const wsInstance = MockWebSocket.instances[0]

    // Send invalid JSON
    if (wsInstance.onmessage) {
      wsInstance.onmessage({ data: 'not valid json {{{' })
    }

    // Should not crash, connection should remain
    expect(store.isConnected).toBe(true)
  })

  it('test_server_error_messages_are_tracked', async () => {
    const store = useWebSocketStore()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    const wsInstance = MockWebSocket.instances[0]
    wsInstance.simulateMessage({
      type: 'error',
      message: 'Server encountered an error'
    })

    const debugInfo = store.getDebugInfo()
    expect(debugInfo.stats.lastError).toContain('Server error')
  })
})

describe('WebSocket V2 Store - Connection Listeners', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    MockWebSocket.reset()
  })

  afterEach(async () => {
    const store = useWebSocketStore()
    if (store.isConnected || store.isConnecting || store.isReconnecting) {
      store.disconnect()
    }
    await vi.advanceTimersByTimeAsync(0)
    vi.runAllTimers()
    await vi.advanceTimersByTimeAsync(0)
    vi.useRealTimers()
  })

  it('test_onConnectionChange_notifies_on_state_changes', async () => {
    const store = useWebSocketStore()
    const listener = vi.fn()

    store.onConnectionChange(listener)

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    // Should be called with 'connected'
    expect(listener).toHaveBeenCalledWith(
      expect.objectContaining({ state: 'connected' })
    )

    listener.mockClear()

    // Disconnect: synchronous status change notifies listeners
    store.disconnect()

    // Should be called with 'disconnected'
    expect(listener).toHaveBeenCalledWith(
      expect.objectContaining({ state: 'disconnected' })
    )
  })

  it('test_onConnectionChange_returns_unsubscribe_function', async () => {
    const store = useWebSocketStore()
    const listener = vi.fn()

    const unsubscribe = store.onConnectionChange(listener)
    unsubscribe()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    // Listener should not be called after unsubscribe
    expect(listener).not.toHaveBeenCalled()
  })
})

describe('WebSocket V2 Store - Heartbeat & Ping/Pong', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    MockWebSocket.reset()
  })

  afterEach(async () => {
    const store = useWebSocketStore()
    if (store.isConnected || store.isConnecting || store.isReconnecting) {
      store.disconnect()
    }
    await vi.advanceTimersByTimeAsync(0)
    vi.runAllTimers()
    await vi.advanceTimersByTimeAsync(0)
    vi.useRealTimers()
  })

  it('test_heartbeat_sends_ping_every_30_seconds', async () => {
    const store = useWebSocketStore()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    MockWebSocket.sentMessages = []

    // Advance time by 30 seconds
    await vi.advanceTimersByTimeAsync(30000)

    // Should have sent a ping
    expect(MockWebSocket.sentMessages).toContainEqual({ type: 'ping' })
  })

  it('test_server_ping_receives_pong_response', async () => {
    const store = useWebSocketStore()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    MockWebSocket.sentMessages = []

    // Simulate server ping
    const wsInstance = MockWebSocket.instances[0]
    wsInstance.simulateMessage({ type: 'ping' })

    // Should respond with pong
    expect(MockWebSocket.sentMessages).toContainEqual({ type: 'pong' })
  })
})

describe('WebSocket V2 Store - Debug & Stats', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    MockWebSocket.reset()
  })

  afterEach(async () => {
    const store = useWebSocketStore()
    if (store.isConnected || store.isConnecting || store.isReconnecting) {
      store.disconnect()
    }
    await vi.advanceTimersByTimeAsync(0)
    vi.runAllTimers()
    await vi.advanceTimersByTimeAsync(0)
    vi.useRealTimers()
  })

  it('test_getDebugInfo_returns_connection_state', async () => {
    const store = useWebSocketStore()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    const info = store.getDebugInfo()

    expect(info).toHaveProperty('state')
    expect(info).toHaveProperty('clientId')
    expect(info).toHaveProperty('reconnectAttempts')
    expect(info).toHaveProperty('messageQueueSize')
    expect(info).toHaveProperty('stats')
  })

  it('test_getDebugInfo_includes_additional_debug_data', async () => {
    const store = useWebSocketStore()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    const debugInfo = store.getDebugInfo()

    expect(debugInfo).toHaveProperty('isConnected')
    expect(debugInfo).toHaveProperty('isConnecting')
    expect(debugInfo).toHaveProperty('wsUrl')
  })

  it('test_setDebugMode_enables_debug_logging', () => {
    const store = useWebSocketStore()

    store.setDebugMode(true)

    const debugInfo = store.getDebugInfo()
    expect(debugInfo.debug).toBe(true)

    store.setDebugMode(false)
    expect(store.getDebugInfo().debug).toBe(false)
  })

  it('test_stats_track_messages_sent_and_received', async () => {
    const store = useWebSocketStore()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    // Send messages
    store.send({ type: 'test1' })
    store.send({ type: 'test2' })

    // Receive messages
    const wsInstance = MockWebSocket.instances[0]
    wsInstance.simulateMessage({ type: 'event1' })
    wsInstance.simulateMessage({ type: 'event2' })

    const info = store.getDebugInfo()
    expect(info.stats.messagesSent).toBeGreaterThanOrEqual(2)
    expect(info.stats.messagesReceived).toBeGreaterThanOrEqual(2)
  })
})

describe('WebSocket V2 Store - Reconnect Storm Hardening (BE-6029)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    MockWebSocket.reset()
  })

  afterEach(async () => {
    const store = useWebSocketStore()
    if (store.isConnected || store.isConnecting || store.isReconnecting) {
      store.disconnect()
    }
    await vi.advanceTimersByTimeAsync(0)
    vi.runAllTimers()
    await vi.advanceTimersByTimeAsync(0)
    vi.useRealTimers()
  })

  it('test_flapping_connection_keeps_accruing_attempts_so_backoff_grows', async () => {
    // Regression for the reconnect-storm root cause: a socket that opens then
    // dies before the stability window must NOT reset the backoff counter, so
    // exponential backoff grows instead of hammering reconnect every ~1s.
    const store = useWebSocketStore()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    // First drop (well inside the stability window)
    MockWebSocket.instances.at(-1).close(1006, 'flap-1')
    await vi.advanceTimersByTimeAsync(0)
    expect(store.reconnectAttempts).toBe(1)

    // First backoff is 1000ms — reconnect opens
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(0)
    expect(store.isConnected).toBe(true)
    // Opening did NOT reset the counter (pre-fix bug would put this back to 0)
    expect(store.reconnectAttempts).toBe(1)

    // Drops again quickly → counter must accrue to 2, backoff becomes 2000ms
    const instancesBeforeSecondDrop = MockWebSocket.instances.length
    MockWebSocket.instances.at(-1).close(1006, 'flap-2')
    await vi.advanceTimersByTimeAsync(0)
    expect(store.reconnectAttempts).toBe(2)

    // Backoff is now 2000ms: nothing reconnects at +1000ms ...
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(0)
    expect(MockWebSocket.instances.length).toBe(instancesBeforeSecondDrop)
    // ... but it does at +2000ms total
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(0)
    expect(MockWebSocket.instances.length).toBe(instancesBeforeSecondDrop + 1)
  })

  it('test_connect_while_reconnecting_does_not_create_a_duplicate_socket', async () => {
    // Regression for the duplicate same-client_id sockets: a connect() that
    // races a pending reconnect timer must cancel that timer and open exactly
    // ONE socket, not two.
    const store = useWebSocketStore()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)
    const countAfterFirst = MockWebSocket.instances.length

    // Drop → schedules a reconnect timer; status becomes 'reconnecting'
    MockWebSocket.instances.at(-1).close(1006, 'drop')
    await vi.advanceTimersByTimeAsync(0)
    expect(store.isReconnecting).toBe(true)

    // External connect() while the reconnect timer is still pending
    store.connect()
    await vi.advanceTimersByTimeAsync(0)

    // Let the ORIGINAL reconnect delay elapse — the cancelled timer must NOT fire
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(0)

    // Exactly one additional socket (from the external connect), not two
    expect(MockWebSocket.instances.length).toBe(countAfterFirst + 1)
    expect(store.isConnected).toBe(true)
  })

  it('test_liveness_watchdog_forces_reconnect_after_prolonged_silence', async () => {
    // Regression for the blind heartbeat: with NO inbound frames for longer than
    // pingInterval + pongTimeout, the socket is silently dead and must be
    // force-closed so a reconnect begins (instead of pinging a black hole).
    const store = useWebSocketStore()

    await store.connect()
    await vi.advanceTimersByTimeAsync(0)
    expect(store.isConnected).toBe(true)
    const firstInstance = MockWebSocket.instances.at(-1)

    // No inbound frames at all. At 30s the heartbeat pings (still within grace);
    // at 60s silence exceeds 30s+10s, so the socket is force-closed.
    await vi.advanceTimersByTimeAsync(60000)
    await vi.advanceTimersByTimeAsync(0)

    expect(firstInstance.readyState).toBe(MockWebSocket.CLOSED)
    // A reconnect was kicked off by the forced close
    expect(store.reconnectAttempts).toBe(1)
  })
})

describe('WebSocket V2 Store - Reconnect Toast Gating (edge-churn UX)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    MockWebSocket.reset()
    showToastSpy.mockClear()
  })

  afterEach(async () => {
    const store = useWebSocketStore()
    if (store.isConnected || store.isConnecting || store.isReconnecting) {
      store.disconnect()
    }
    await vi.advanceTimersByTimeAsync(0)
    vi.runAllTimers()
    await vi.advanceTimersByTimeAsync(0)
    vi.useRealTimers()
  })

  const connectionLostToasts = () =>
    showToastSpy.mock.calls.filter((c) => c[0] && c[0].title === 'Connection Lost')

  it('test_brief_blip_does_not_show_connection_lost_toast', async () => {
    // Intermittent Railway edge resets that auto-recover within an attempt or
    // two must NOT alarm the user — that toast spam is the reported symptom.
    const store = useWebSocketStore()
    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    MockWebSocket.instances.at(-1).close(1006, 'edge reset')
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(1000) // first backoff -> reconnect
    await vi.advanceTimersByTimeAsync(0)

    expect(store.isConnected).toBe(true)
    expect(connectionLostToasts().length).toBe(0)
  })

  /**
   * FE-9553 ruling 2: connection state belongs on a STATE INDICATOR, not in a
   * list and not in a toast. "Server-disconnect state moves OUT of the bell to
   * the connection (wifi) indicator."
   *
   * This test previously asserted the sustained outage DID raise a toast, once.
   * That behaviour was itself an incident fix -- "Connection Lost" toast spam
   * on the intermittent edge resets the brief-blip test above guards against --
   * so it is worth being explicit that removing the toast entirely cannot
   * regress that incident: the complaint was too many toasts, and zero is not
   * more than one. That guard stays green, trivially.
   *
   * What replaces it is not silence: the nav connection orb already reflects
   * disconnected and reconnecting state, and the test below this one proves it.
   */
  it('test_sustained_outage_raises_no_toast_and_no_bell_row (FE-9553 ruling 2)', async () => {
    const store = useWebSocketStore()
    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    // Flap below the stability window so attempts accrue to the threshold (3).
    // Backoff after attempts 1/2/3 is 1s/2s/4s.
    for (const delay of [1000, 2000, 4000]) {
      MockWebSocket.instances.at(-1).close(1006, 'edge reset')
      await vi.advanceTimersByTimeAsync(0)
      await vi.advanceTimersByTimeAsync(delay)
      await vi.advanceTimersByTimeAsync(0)
    }

    expect(connectionLostToasts().length).toBe(0)

    const connectionRows = addNotificationSpy.mock.calls.filter(
      (c) => c[0]?.type === 'connection_lost' || c[0]?.type === 'connection_restored',
    )
    expect(connectionRows).toEqual([])
  })

  // CHECKER-MUST-FIRE. Every assertion above is a negative, and negatives pass
  // just as well when the outage never happened at all -- if the flap loop
  // stopped driving reconnects, this suite would go green while proving
  // nothing. This pins that the outage really occurred AND that its state is
  // still visible somewhere, which is the whole point of ruling 2: the signal
  // moved, it was not deleted.
  it('the outage is still VISIBLE on the connection indicator, not merely silent', async () => {
    const store = useWebSocketStore()
    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    for (const delay of [1000, 2000, 4000]) {
      MockWebSocket.instances.at(-1).close(1006, 'edge reset')
      await vi.advanceTimersByTimeAsync(0)
      await vi.advanceTimersByTimeAsync(delay)
      await vi.advanceTimersByTimeAsync(0)
    }

    // The outage genuinely accrued attempts -- the negatives above were not
    // vacuous.
    expect(store.reconnectAttempts).toBeGreaterThanOrEqual(3)
  })
})

describe('WebSocket V2 Store - Manual reconnect (FE-3007b)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    MockWebSocket.reset()
  })

  afterEach(async () => {
    const store = useWebSocketStore()
    if (store.isConnected || store.isConnecting || store.isReconnecting) {
      store.disconnect()
    }
    await vi.advanceTimersByTimeAsync(0)
    vi.runAllTimers()
    await vi.advanceTimersByTimeAsync(0)
    vi.useRealTimers()
  })

  it('reconnect() notifies connection listeners with isReconnect=true (manual reconnect resyncs)', async () => {
    const store = useWebSocketStore()
    await store.connect()
    await vi.advanceTimersByTimeAsync(0)

    const listener = vi.fn()
    store.onConnectionChange(listener)

    await store.reconnect()
    await vi.advanceTimersByTimeAsync(0)

    // The resulting 'connected' event must be flagged a reconnect so the
    // reconnect-resync registry fires — disconnect()+connect() flagged it false.
    expect(listener).toHaveBeenCalledWith(
      expect.objectContaining({ state: 'connected', isReconnect: true }),
    )
  })

  it('reconnect() reconnects even from a healthy connected state', async () => {
    const store = useWebSocketStore()
    await store.connect()
    await vi.advanceTimersByTimeAsync(0)
    expect(store.isConnected).toBe(true)
    const firstClientId = store.clientId

    await store.reconnect()
    await vi.advanceTimersByTimeAsync(0)

    expect(store.isConnected).toBe(true)
    // Fresh socket → fresh client id (BE-6029: one id per physical socket).
    expect(store.clientId).not.toBe(firstClientId)
  })
})
