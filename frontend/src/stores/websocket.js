/**
 * Consolidated WebSocket Store V2
 * Merges websocket.js (507 lines) + flowWebSocket.js (377 lines) + stores/websocket.js (318 lines)
 * into single, clean Pinia store (~500 lines)
 *
 * PRODUCTION-GRADE:
 * - Auto-reconnection with exponential backoff
 * - Message queue for offline support
 * - Centralized subscription tracking
 * - Integration with all Pinia stores
 * - Memory leak prevention
 * - Zero breaking changes
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { API_CONFIG } from '@/config/api'
import { getWsBaseUrl } from '@/composables/useApiUrl'
import { normalizeWebsocketPayload } from '@/utils/normalizeWebsocketPayload'
import { createReconnectPolicy } from '@/stores/websocketReconnectPolicy'

export const useWebSocketStore = defineStore('websocket', () => {
  // ============================================
  // STATE
  // ============================================

  // WebSocket instance
  const ws = ref(null)

  // Connection state
  const clientId = ref(null)
  const connectionStatus = ref('disconnected') // 'disconnected' | 'connecting' | 'connected' | 'reconnecting'
  const connectionError = ref(null)
  const reconnectAttempts = ref(0)
  const authCredentials = ref(null)

  // Configuration
  const config = {
    maxReconnectAttempts: 10,
    reconnectDelay: 1000,
    maxReconnectDelay: 30000,
    slowRetryDelay: 60000, // FE-9056: after the fast-retry cap, keep trying this slowly (never give up)
    pingInterval: 30000, // 30 seconds
    pongTimeout: 10000, // grace after a ping cycle before a silent socket is declared dead
    stabilityResetDelay: 5000, // a connection up this long is "healthy" -> reset backoff. Short so normal Railway edge churn recovers promptly instead of accruing toward the attempt cap.
    messageQueueSize: 100,
    maxEventHistory: 50,
    debug: API_CONFIG.WEBSOCKET?.debug || false,
  }

  // Message queue
  const messageQueue = ref([])

  // Subscriptions tracking (refcounted)
  // key: 'entity_type:entity_id' -> value: number (subscriber count)
  const subscriptions = ref(new Map())

  // Event handlers tracking
  const eventHandlers = ref(new Map()) // key: event type -> value: Set<handler>

  // Connection listeners
  const connectionListeners = ref(new Set())

  // Reconnection mutex
  const reconnectTimer = ref(null)

  // Heartbeat
  const pingInterval = ref(null)

  // Liveness: timestamp (ms) of the last inbound frame, for dead-socket detection
  const lastActivityAt = ref(0)

  // Stability gate: only reset the reconnect backoff counter once a connection
  // has stayed up long enough to be considered healthy (prevents flap loops).
  const stableTimer = ref(null)

  // FE-9056: after the fast-retry ladder is exhausted, this policy keeps a slow
  // heartbeat retry alive and re-arms an immediate reconnect on network return
  // ('online') or tab refocus (visibilitychange). Armed in handleDisconnect when
  // the cap is hit, disarmed the moment a connection opens or on manual disconnect.
  const reconnectPolicy = createReconnectPolicy({
    onReconnectNeeded: () => triggerReconnect(),
    slowRetryDelay: config.slowRetryDelay,
    log,
  })

  // Stats and debug
  const stats = ref({
    messagesSent: 0,
    messagesReceived: 0,
    connectionAttempts: 0,
    lastError: null,
    connectedAt: null,
    disconnectedAt: null,
  })

  const eventHistory = ref([])

  // ============================================
  // COMPUTED
  // ============================================

  const isConnected = computed(() => connectionStatus.value === 'connected')
  const isConnecting = computed(() => connectionStatus.value === 'connecting')
  const isReconnecting = computed(() => connectionStatus.value === 'reconnecting')
  const isDisconnected = computed(() => connectionStatus.value === 'disconnected')

  // ============================================
  // CONNECTION MANAGEMENT
  // ============================================

  /**
   * Generate unique client ID
   */
  function generateClientId() {
    return `client_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }

  /**
   * Connect to WebSocket server
   * @param {Object} options - Connection options
   * @param {string} options.apiKey - API key for authentication
   * @param {string} options.token - Bearer token for authentication
   */
  async function connect(options = {}) {
    if (isConnected.value || isConnecting.value) {
      log('Already connected or connecting')
      return Promise.resolve()
    }

    // Cancel any pending reconnect timer so it cannot fire a second, racing
    // connect() after this one — the source of duplicate sockets under one id.
    if (reconnectTimer.value) {
      clearTimeout(reconnectTimer.value)
      reconnectTimer.value = null
    }

    // Tear down any lingering (half-open / closing) socket before opening a new
    // one. Detach its handlers first so its delayed onclose cannot trigger a
    // second reconnect for a connection we are deliberately replacing.
    if (ws.value) {
      try {
        ws.value.onopen = null
        ws.value.onmessage = null
        ws.value.onclose = null
        ws.value.onerror = null
        ws.value.close(1000, 'Replacing connection')
      } catch {
        /* already closed */
      }
      ws.value = null
    }

    const isReconnectAttempt = connectionStatus.value === 'reconnecting'
    connectionStatus.value = 'connecting'
    authCredentials.value = options
    stats.value.connectionAttempts++

    // Fresh client ID per physical socket: the server keys connections by
    // client_id and overwrites on collision, so reusing one id across reconnects
    // lets a stale socket's teardown evict the live one. A new id avoids that.
    clientId.value = generateClientId()

    return new Promise((resolve, reject) => {
      try {
        // Build WebSocket URL with authentication
        // Option 3: Use relative WebSocket URLs - derive from current location
        // This ensures WebSocket connects to the same host the user is accessing
        // Security note: Auth is enforced server-side via JWT, not by hostname
        // Use the central resolver so demo (Cloudflare Tunnel), CE prod
        // (same-origin FastAPI) and dev (Vite proxy) all build the right URL
        // without ever concatenating hostname + VITE_API_PORT.
        const baseUrl = getWsBaseUrl() || `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
        const wsUrl = new URL(`${baseUrl}/ws/${clientId.value}`)

        // Add auth parameters if provided
        if (options.apiKey) {
          wsUrl.searchParams.append('api_key', options.apiKey)
        } else if (options.token) {
          wsUrl.searchParams.append('token', options.token)
        }

        log(`Connecting to ${wsUrl.origin}${wsUrl.pathname}`)

        ws.value = new WebSocket(wsUrl.toString())

        // Connection opened
        ws.value.onopen = () => {
          log('Connection established')
          connectionStatus.value = 'connected'
          connectionError.value = null

          // We're back: stop the slow-retry heartbeat and drop the online/
          // visibility re-arm listeners (idempotent no-op if never armed).
          reconnectPolicy.disarm()
          stats.value.connectedAt = new Date().toISOString()
          stats.value.lastError = null
          addEvent('connection', 'Connected')

          // Do NOT reset the backoff counter immediately. A socket that opens
          // then dies seconds later (flapping server / cold-start loop stall)
          // must keep accruing attempts so exponential backoff and the attempt
          // cap engage. Only declare the connection healthy — and reset the
          // counter — after it has stayed up for stabilityResetDelay.
          if (stableTimer.value) {
            clearTimeout(stableTimer.value)
          }
          stableTimer.value = setTimeout(() => {
            reconnectAttempts.value = 0
            stableTimer.value = null
          }, config.stabilityResetDelay)

          // Start heartbeat
          startHeartbeat()

          // Process queued messages
          processMessageQueue()

          // Notify connection listeners
          notifyConnectionListeners('connected', { isReconnect: isReconnectAttempt })

          // Re-subscribe to all previous subscriptions
          resubscribeAll()

          resolve()
        }

        // Message received
        ws.value.onmessage = (event) => {
          try {
            // Any inbound frame proves the socket is alive — feeds the
            // liveness watchdog in startHeartbeat().
            lastActivityAt.value = Date.now()
            const data = JSON.parse(event.data)
            stats.value.messagesReceived++
            log('Message received', data)
            handleMessage(data)
          } catch (error) {
            log('Failed to parse message', error)
            stats.value.lastError = `Parse error: ${error.message}`
          }
        }

        // Connection closed
        ws.value.onclose = (event) => {
          log(`Connection closed (code: ${event.code}, reason: ${event.reason})`)
          stats.value.disconnectedAt = new Date().toISOString()
          addEvent('connection', `Closed (${event.code}: ${event.reason})`)
          handleDisconnect(event)

          if (connectionStatus.value === 'connecting') {
            reject(new Error(`Connection failed: ${event.reason || 'Unknown error'}`))
          }
        }

        // Connection error
        ws.value.onerror = (error) => {
          log('Connection error', error)
          stats.value.lastError = `Connection error: ${error.message || 'Unknown'}`
          addEvent('error', 'Connection error', error)

          if (connectionStatus.value === 'connecting') {
            connectionStatus.value = 'disconnected'
            reject(error)
          }
        }
      } catch (error) {
        log('Failed to create connection', error)
        stats.value.lastError = `Connection failed: ${error.message}`
        connectionStatus.value = 'disconnected'
        reject(error)
      }
    })
  }

  /**
   * Manually reconnect (e.g. the Connection Health dialog's Reconnect button).
   *
   * FE-3007b: a manual reconnect must trigger the same store-resync path as an
   * automatic one. We mark the status 'reconnecting' BEFORE calling connect()
   * so that (a) connect()'s "already connected" guard lets it proceed even from
   * a healthy connection, and (b) connect() sees connectionStatus==='reconnecting'
   * and flags the resulting 'connected' notification isReconnect=true — which is
   * what the reconnect-resync registry listens for. connect() also clears the
   * reconnect-timer mutex and detaches the old socket's handlers before replacing
   * it, so this does NOT race with auto-reconnect or change backoff policy
   * (BE-6029 / BE-3008 untouched).
   */
  async function reconnect() {
    log('Manual reconnect requested')
    connectionStatus.value = 'reconnecting'
    return connect(authCredentials.value || {})
  }

  /**
   * FE-9056: single reconnect attempt driven by the post-cap reconnect policy
   * (slow-retry tick, or an 'online'/visibility re-arm). Mirrors manual
   * reconnect(): marks 'reconnecting' first so a successful open is treated as a
   * reconnect (isReconnect=true) and the store-resync path fires. No-op while a
   * connection is already open or in progress. Failures fall through onclose ->
   * handleDisconnect, which keeps the policy armed for the next slow tick.
   */
  function triggerReconnect() {
    if (isConnected.value || isConnecting.value) {
      return
    }
    connectionStatus.value = 'reconnecting'
    connect(authCredentials.value || {}).catch(() => {
      /* onclose drives the next attempt; policy stays armed */
    })
  }

  /**
   * Disconnect from WebSocket server
   */
  function disconnect() {
    log('Disconnecting')

    // Cancel pending reconnect
    if (reconnectTimer.value) {
      clearTimeout(reconnectTimer.value)
      reconnectTimer.value = null
    }

    // Cancel the stability gate
    if (stableTimer.value) {
      clearTimeout(stableTimer.value)
      stableTimer.value = null
    }

    // Manual disconnect stops the post-cap slow-retry policy (we are
    // disconnecting on purpose).
    reconnectPolicy.disarm()

    // Stop heartbeat
    if (pingInterval.value) {
      clearInterval(pingInterval.value)
      pingInterval.value = null
    }

    // Close WebSocket
    if (ws.value) {
      ws.value.close(1000, 'Client disconnect')
      ws.value = null
    }

    connectionStatus.value = 'disconnected'
    notifyConnectionListeners('disconnected')
  }

  /**
   * Handle disconnection and attempt reconnect
   */
  function handleDisconnect(_event) {
    connectionStatus.value = 'disconnected'

    // Cancel the stability gate: the connection did not survive long enough to
    // be deemed healthy, so the backoff counter must keep accruing.
    if (stableTimer.value) {
      clearTimeout(stableTimer.value)
      stableTimer.value = null
    }

    // Stop heartbeat
    if (pingInterval.value) {
      clearInterval(pingInterval.value)
      pingInterval.value = null
    }

    // Notify listeners
    notifyConnectionListeners('disconnected')

    // NOTE: no toast here, and since FE-9553 none anywhere in this store.
    // Connection state is carried by the nav connection orb, which reports the
    // CURRENT state rather than announcing a past one.

    // Attempt reconnect if we haven't exceeded max attempts. FE-9056: once the
    // fast-retry cap is hit, DON'T give up — arm the slow-retry policy so a long
    // deploy/outage still recovers (on the next slow tick, or immediately when
    // the network returns / the tab is refocused) instead of freezing the tab.
    if (reconnectAttempts.value < config.maxReconnectAttempts) {
      attemptReconnect()
    } else {
      reconnectPolicy.arm()
    }
  }

  /**
   * Attempt to reconnect with exponential backoff
   */
  async function attemptReconnect() {
    // Clear any existing reconnect timer to prevent overlapping attempts
    if (reconnectTimer.value) {
      clearTimeout(reconnectTimer.value)
      reconnectTimer.value = null
    }

    reconnectAttempts.value++
    connectionStatus.value = 'reconnecting'

    // Calculate delay with exponential backoff
    const delay = Math.min(
      config.reconnectDelay * Math.pow(2, reconnectAttempts.value - 1),
      config.maxReconnectDelay,
    )

    log(
      `Reconnecting in ${delay}ms (attempt ${reconnectAttempts.value}/${config.maxReconnectAttempts})`,
    )

    // Notify listeners
    notifyConnectionListeners('reconnecting', {
      attempt: reconnectAttempts.value,
      maxAttempts: config.maxReconnectAttempts,
      delay,
    })

    // FE-9553 ruling 2: connection state belongs on a STATE INDICATOR, not in a
    // list and not in a toast. A sustained outage used to raise both a
    // "Connection Lost" toast and an unread bell row; both are gone, and the nav
    // connection orb (useNavConnectionStatus -> NavigationDrawer) is now the sole
    // carrier. It already reports disconnected and reconnecting, with the attempt
    // count in its tooltip, which is strictly more current than a one-shot toast
    // announcing a state that may have changed since.
    //
    // The toast this replaces was itself an incident fix -- "Connection Lost"
    // spam on intermittent edge resets -- so it is worth being explicit that
    // removing it cannot regress that incident: the complaint was too many
    // toasts, and zero is not more than one. The brief-blip guard above it stays
    // green trivially.

    reconnectTimer.value = setTimeout(async () => {
      reconnectTimer.value = null
      try {
        await connect(authCredentials.value)

        // FE-9553 ruling 2: no "Connection Restored" toast and no bell row
        // either. A restore is a state CHANGE, and the orb shows the new state
        // the instant it happens -- announcing "we are connected again" in a
        // list the operator reads later is the least useful place for it. The
        // symmetry matters too: if the loss is not announced, celebrating the
        // recovery would report half a story.
      } catch (error) {
        console.error('WebSocket: Reconnection failed', error)
        // Will trigger handleDisconnect again if needed
      }
    }, delay)
  }

  /**
   * Start heartbeat mechanism
   */
  function startHeartbeat() {
    if (pingInterval.value) {
      clearInterval(pingInterval.value)
    }

    // Treat the connection as fresh-alive the moment the heartbeat starts.
    lastActivityAt.value = Date.now()

    // Send ping every 30 seconds, and verify the socket is actually alive.
    pingInterval.value = setInterval(() => {
      if (!isConnected.value) {
        return
      }

      // Liveness check: if NO inbound frame has arrived for a full ping cycle
      // plus a grace window, the socket is silently dead (half-open) — close it
      // so onclose drives a reconnect, instead of pinging a black hole forever.
      const silentForMs = Date.now() - lastActivityAt.value
      if (silentForMs > config.pingInterval + config.pongTimeout) {
        log(`No server activity for ${silentForMs}ms — forcing reconnect`)
        stats.value.lastError = 'Liveness timeout'
        try {
          ws.value && ws.value.close(4000, 'Liveness timeout')
        } catch {
          /* already closing */
        }
        return
      }

      send({ type: 'ping' })
    }, config.pingInterval)
  }

  // ============================================
  // MESSAGE HANDLING
  // ============================================

  /**
   * Send message to server
   */
  function send(data) {
    if (!isConnected.value) {
      log('Not connected, queuing message', data)
      messageQueue.value.push(data)

      // Limit queue size
      if (messageQueue.value.length > config.messageQueueSize) {
        messageQueue.value.shift() // Remove oldest
      }

      return false
    }

    try {
      ws.value.send(JSON.stringify(data))
      stats.value.messagesSent++
      log('Message sent', data)
      return true
    } catch (error) {
      log('Failed to send message', error)
      stats.value.lastError = `Send error: ${error.message}`
      messageQueue.value.push(data)
      return false
    }
  }

  /**
   * Process queued messages
   */
  function processMessageQueue() {
    while (messageQueue.value.length > 0 && isConnected.value) {
      const message = messageQueue.value.shift()
      send(message)
    }
  }

  /**
   * Handle incoming message
   *
   * Normalizes payload structure for backward compatibility:
   * - HTTP bridge sends flat: { type, project_id, tenant_key, ... }
   * - Direct broadcast sends nested: { type, data: { project_id, tenant_key, ... } }
   *
   * After normalization, handlers always receive flat payloads with data accessible
   * at the top level (e.g., payload.tenant_key works for both formats).
   *
   * @see Handover 0290 - WebSocket Payload Normalization
   */
  function handleMessage(data) {
    // Normalize nested payloads (Handover 0290)
    // Uses shared utility for consistent normalization with event router
    const { type, payload } = normalizeWebsocketPayload(data)

    // Handle system messages
    switch (type) {
      case 'pong':
        // Heartbeat response
        break

      case 'ping':
        // Server heartbeat - respond with pong
        send({ type: 'pong' })
        break

      case 'subscribed':
      case 'unsubscribed':
        log(`${type} to ${payload.entity_type}:${payload.entity_id}`)
        addEvent('subscription', `${type} ${payload.entity_type}:${payload.entity_id}`)
        break

      case 'error':
        log('Server error', payload)
        stats.value.lastError = `Server error: ${payload.message || payload.error}`
        addEvent('error', 'Server error', payload)
        break

      default:
        // Route to registered handlers
        notifyMessageHandlers(type, payload)
    }
  }

  /**
   * Notify message handlers
   */
  function notifyMessageHandlers(type, payload) {
    // Call specific handlers for this type
    const handlers = eventHandlers.value.get(type)
    if (handlers) {
      handlers.forEach((handler) => {
        try {
          handler(payload)
        } catch (error) {
          console.error(`Error in message handler for ${type}:`, error)
        }
      })
    }

    // Call wildcard handlers
    const wildcardHandlers = eventHandlers.value.get('*')
    if (wildcardHandlers) {
      wildcardHandlers.forEach((handler) => {
        try {
          handler({ type, ...payload })
        } catch (error) {
          console.error('Error in wildcard handler:', error)
        }
      })
    }
  }

  // ============================================
  // EVENT HANDLER MANAGEMENT
  // ============================================

  /**
   * Register message handler
   * @param {string} type - Message type (or '*' for all)
   * @param {Function} handler - Handler function
   * @returns {Function} Unsubscribe function
   */
  function on(type, handler) {
    if (!eventHandlers.value.has(type)) {
      eventHandlers.value.set(type, new Set())
    }

    eventHandlers.value.get(type).add(handler)
    log(`Registered handler for ${type}`)

    // Return unsubscribe function
    return () => off(type, handler)
  }

  /**
   * Remove message handler
   */
  function off(type, handler) {
    const handlers = eventHandlers.value.get(type)
    if (handlers) {
      handlers.delete(handler)
      if (handlers.size === 0) {
        eventHandlers.value.delete(type)
      }
      log(`Removed handler for ${type}`)
    }
  }

  // ============================================
  // CONNECTION LISTENER MANAGEMENT
  // ============================================

  /**
   * Register connection state listener
   */
  function onConnectionChange(callback) {
    connectionListeners.value.add(callback)

    // Return unsubscribe function
    return () => {
      connectionListeners.value.delete(callback)
    }
  }

  /**
   * Notify connection listeners
   */
  function notifyConnectionListeners(state, data = {}) {
    connectionListeners.value.forEach((listener) => {
      try {
        listener({ state, ...data })
      } catch (error) {
        console.error('Error in connection listener:', error)
      }
    })
  }

  // ============================================
  // SUBSCRIPTION MANAGEMENT
  // ============================================

  /**
   * Subscribe to entity updates
   */
  function subscribe(entityType, entityId) {
    const key = `${entityType}:${entityId}`

    const currentCount = subscriptions.value.get(key) || 0
    const nextCount = currentCount + 1
    subscriptions.value.set(key, nextCount)

    if (currentCount > 0) {
      log(`Subscription refcount incremented for ${key} (${nextCount})`)
      return key
    }

    const success = send({
      type: 'subscribe',
      entity_type: entityType,
      entity_id: entityId,
    })

    if (success || !isConnected.value) {
      // Subscription is tracked even if queued (will be sent on reconnect)
      log(`Subscribed to ${key}`)
    }

    return key
  }

  /**
   * Unsubscribe from entity updates
   */
  function unsubscribe(entityType, entityId) {
    const key = `${entityType}:${entityId}`

    const currentCount = subscriptions.value.get(key) || 0

    if (currentCount <= 0) {
      log(`Not subscribed to ${key}`)
      return false
    }

    if (currentCount > 1) {
      const nextCount = currentCount - 1
      subscriptions.value.set(key, nextCount)
      log(`Subscription refcount decremented for ${key} (${nextCount})`)
      return true
    }

    // Last subscriber: actually unsubscribe on the wire.
    send({ type: 'unsubscribe', entity_type: entityType, entity_id: entityId })

    subscriptions.value.delete(key)
    log(`Unsubscribed from ${key}`)
    return true
  }

  /**
   * Re-subscribe to all previous subscriptions (on reconnect)
   */
  function resubscribeAll() {
    log(`Re-subscribing to ${subscriptions.value.size} subscriptions`)

    subscriptions.value.forEach((count, key) => {
      if (!count || count <= 0) {
        return
      }
      const [entityType, entityId] = key.split(':')
      send({
        type: 'subscribe',
        entity_type: entityType,
        entity_id: entityId,
      })
    })
  }

  /**
   * Convenience: Subscribe to project updates
   */
  function subscribeToProject(projectId) {
    return subscribe('project', projectId)
  }

  /**
   * Convenience: Subscribe to agent updates
   */
  function subscribeToAgent(agentId) {
    return subscribe('agent', agentId)
  }

  // ============================================
  // DEBUG & LOGGING
  // ============================================

  /**
   * Debug logging
   */
  function log(message, data = null) {
    if (config.debug) {
      const safeMsg = String(message).replace(/[\n\r\t]/g, ' ')
      console.warn(`[WebSocketV2] ${safeMsg}`, data || '')
    }

    // Add to event history
    addEvent('log', message, data)
  }

  /**
   * Add event to history
   */
  function addEvent(type, message, data = null) {
    const event = {
      type,
      message,
      data,
      timestamp: new Date().toISOString(),
    }

    eventHistory.value.unshift(event)

    // Limit history size
    if (eventHistory.value.length > config.maxEventHistory) {
      eventHistory.value.pop()
    }
  }

  /**
   * Get connection info
   */
  function getConnectionInfo() {
    return {
      state: connectionStatus.value,
      clientId: clientId.value,
      reconnectAttempts: reconnectAttempts.value,
      maxReconnectAttempts: config.maxReconnectAttempts,
      messageQueueSize: messageQueue.value.length,
      subscriptionsCount: subscriptions.value.size,
      stats: stats.value,
      eventHistory: eventHistory.value.slice(0, 10),
    }
  }

  /**
   * Get debug info
   */
  function getDebugInfo() {
    return {
      state: connectionStatus.value,
      isConnected: isConnected.value,
      isConnecting: isConnecting.value,
      isReconnecting: isReconnecting.value,
      clientId: clientId.value,
      reconnectAttempts: reconnectAttempts.value,
      maxReconnectAttempts: config.maxReconnectAttempts,
      messageQueueSize: messageQueue.value.length,
      subscriptions: Array.from(subscriptions.value.keys()),
      stats: stats.value,
      eventHistory: eventHistory.value.slice(0, 10),
      debug: config.debug,
      wsUrl: ws.value?.url || 'Not connected',
    }
  }

  /**
   * Enable/disable debug mode
   */
  function setDebugMode(enabled) {
    config.debug = enabled
    log(`Debug mode ${enabled ? 'enabled' : 'disabled'}`)
  }

  // ============================================
  // RETURN STORE API
  // ============================================

  return {
    // State
    connectionStatus,
    connectionError,
    reconnectAttempts,
    clientId,
    messageQueueSize: computed(() => messageQueue.value.length),
    subscriptions: computed(() => Array.from(subscriptions.value.keys())),

    // Computed
    isConnected,
    isConnecting,
    isReconnecting,
    isDisconnected,

    // Connection
    connect,
    reconnect,
    disconnect,

    // Messaging
    send,
    on,
    off,
    onConnectionChange,

    // Subscriptions
    subscribe,
    unsubscribe,
    subscribeToProject,
    subscribeToAgent,

    // Debug
    getConnectionInfo,
    getDebugInfo,
    setDebugMode,
  }
})
