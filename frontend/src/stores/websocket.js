
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { API_CONFIG } from '@/config/api'
import { getWsBaseUrl } from '@/composables/useApiUrl'
import { normalizeWebsocketPayload } from '@/utils/normalizeWebsocketPayload'
import { createReconnectPolicy } from '@/stores/websocketReconnectPolicy'

export const useWebSocketStore = defineStore('websocket', () => {

  const ws = ref(null)

  const clientId = ref(null)
  const connectionStatus = ref('disconnected')
  const connectionError = ref(null)
  const reconnectAttempts = ref(0)
  const authCredentials = ref(null)

  const config = {
    maxReconnectAttempts: 10,
    reconnectDelay: 1000,
    maxReconnectDelay: 30000,
    slowRetryDelay: 60000,
    pingInterval: 30000,
    pongTimeout: 10000,
    stabilityResetDelay: 5000,
    messageQueueSize: 100,
    maxEventHistory: 50,
    debug: API_CONFIG.WEBSOCKET?.debug || false,
  }

  const messageQueue = ref([])

  const subscriptions = ref(new Map())

  const eventHandlers = ref(new Map())

  const connectionListeners = ref(new Set())

  const reconnectTimer = ref(null)

  const pingInterval = ref(null)

  const lastActivityAt = ref(0)

  const stableTimer = ref(null)

  const reconnectPolicy = createReconnectPolicy({
    onReconnectNeeded: () => triggerReconnect(),
    slowRetryDelay: config.slowRetryDelay,
    log,
  })

  const stats = ref({
    messagesSent: 0,
    messagesReceived: 0,
    connectionAttempts: 0,
    lastError: null,
    connectedAt: null,
    disconnectedAt: null,
  })

  const eventHistory = ref([])


  const isConnected = computed(() => connectionStatus.value === 'connected')
  const isConnecting = computed(() => connectionStatus.value === 'connecting')
  const isReconnecting = computed(() => connectionStatus.value === 'reconnecting')
  const isDisconnected = computed(() => connectionStatus.value === 'disconnected')


  function generateClientId() {
    return `client_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }

  async function connect(options = {}) {
    if (isConnected.value || isConnecting.value) {
      log('Already connected or connecting')
      return Promise.resolve()
    }

    if (reconnectTimer.value) {
      clearTimeout(reconnectTimer.value)
      reconnectTimer.value = null
    }

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

    clientId.value = generateClientId()

    return new Promise((resolve, reject) => {
      try {
        const baseUrl = getWsBaseUrl() || `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
        const wsUrl = new URL(`${baseUrl}/ws/${clientId.value}`)

        if (options.apiKey) {
          wsUrl.searchParams.append('api_key', options.apiKey)
        } else if (options.token) {
          wsUrl.searchParams.append('token', options.token)
        }

        log(`Connecting to ${wsUrl.origin}${wsUrl.pathname}`)

        ws.value = new WebSocket(wsUrl.toString())

        ws.value.onopen = () => {
          log('Connection established')
          connectionStatus.value = 'connected'
          connectionError.value = null

          reconnectPolicy.disarm()
          stats.value.connectedAt = new Date().toISOString()
          stats.value.lastError = null
          addEvent('connection', 'Connected')

          if (stableTimer.value) {
            clearTimeout(stableTimer.value)
          }
          stableTimer.value = setTimeout(() => {
            reconnectAttempts.value = 0
            stableTimer.value = null
          }, config.stabilityResetDelay)

          startHeartbeat()

          processMessageQueue()

          notifyConnectionListeners('connected', { isReconnect: isReconnectAttempt })

          resubscribeAll()

          resolve()
        }

        ws.value.onmessage = (event) => {
          try {
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

        ws.value.onclose = (event) => {
          log(`Connection closed (code: ${event.code}, reason: ${event.reason})`)
          stats.value.disconnectedAt = new Date().toISOString()
          addEvent('connection', `Closed (${event.code}: ${event.reason})`)
          handleDisconnect(event)

          if (connectionStatus.value === 'connecting') {
            reject(new Error(`Connection failed: ${event.reason || 'Unknown error'}`))
          }
        }

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

  async function reconnect() {
    log('Manual reconnect requested')
    connectionStatus.value = 'reconnecting'
    return connect(authCredentials.value || {})
  }

  function triggerReconnect() {
    if (isConnected.value || isConnecting.value) {
      return
    }
    connectionStatus.value = 'reconnecting'
    connect(authCredentials.value || {}).catch(() => {
      /* onclose drives the next attempt; policy stays armed */
    })
  }

  function disconnect() {
    log('Disconnecting')

    if (reconnectTimer.value) {
      clearTimeout(reconnectTimer.value)
      reconnectTimer.value = null
    }

    if (stableTimer.value) {
      clearTimeout(stableTimer.value)
      stableTimer.value = null
    }

    reconnectPolicy.disarm()

    if (pingInterval.value) {
      clearInterval(pingInterval.value)
      pingInterval.value = null
    }

    if (ws.value) {
      ws.value.close(1000, 'Client disconnect')
      ws.value = null
    }

    connectionStatus.value = 'disconnected'
    notifyConnectionListeners('disconnected')
  }

  function handleDisconnect(_event) {
    connectionStatus.value = 'disconnected'

    if (stableTimer.value) {
      clearTimeout(stableTimer.value)
      stableTimer.value = null
    }

    if (pingInterval.value) {
      clearInterval(pingInterval.value)
      pingInterval.value = null
    }

    notifyConnectionListeners('disconnected')


    if (reconnectAttempts.value < config.maxReconnectAttempts) {
      attemptReconnect()
    } else {
      reconnectPolicy.arm()
    }
  }

  async function attemptReconnect() {
    if (reconnectTimer.value) {
      clearTimeout(reconnectTimer.value)
      reconnectTimer.value = null
    }

    reconnectAttempts.value++
    connectionStatus.value = 'reconnecting'

    const delay = Math.min(
      config.reconnectDelay * Math.pow(2, reconnectAttempts.value - 1),
      config.maxReconnectDelay,
    )

    log(
      `Reconnecting in ${delay}ms (attempt ${reconnectAttempts.value}/${config.maxReconnectAttempts})`,
    )

    notifyConnectionListeners('reconnecting', {
      attempt: reconnectAttempts.value,
      maxAttempts: config.maxReconnectAttempts,
      delay,
    })


    reconnectTimer.value = setTimeout(async () => {
      reconnectTimer.value = null
      try {
        await connect(authCredentials.value)

      } catch (error) {
        console.error('WebSocket: Reconnection failed', error)
      }
    }, delay)
  }

  function startHeartbeat() {
    if (pingInterval.value) {
      clearInterval(pingInterval.value)
    }

    lastActivityAt.value = Date.now()

    pingInterval.value = setInterval(() => {
      if (!isConnected.value) {
        return
      }

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


  function send(data) {
    if (!isConnected.value) {
      log('Not connected, queuing message', data)
      messageQueue.value.push(data)

      if (messageQueue.value.length > config.messageQueueSize) {
        messageQueue.value.shift()
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

  function processMessageQueue() {
    while (messageQueue.value.length > 0 && isConnected.value) {
      const message = messageQueue.value.shift()
      send(message)
    }
  }

  function handleMessage(data) {
    const { type, payload } = normalizeWebsocketPayload(data)

    switch (type) {
      case 'pong':
        break

      case 'ping':
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
        notifyMessageHandlers(type, payload)
    }
  }

  function notifyMessageHandlers(type, payload) {
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


  function on(type, handler) {
    if (!eventHandlers.value.has(type)) {
      eventHandlers.value.set(type, new Set())
    }

    eventHandlers.value.get(type).add(handler)
    log(`Registered handler for ${type}`)

    return () => off(type, handler)
  }

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


  function onConnectionChange(callback) {
    connectionListeners.value.add(callback)

    return () => {
      connectionListeners.value.delete(callback)
    }
  }

  function notifyConnectionListeners(state, data = {}) {
    connectionListeners.value.forEach((listener) => {
      try {
        listener({ state, ...data })
      } catch (error) {
        console.error('Error in connection listener:', error)
      }
    })
  }


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
      log(`Subscribed to ${key}`)
    }

    return key
  }

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

    send({ type: 'unsubscribe', entity_type: entityType, entity_id: entityId })

    subscriptions.value.delete(key)
    log(`Unsubscribed from ${key}`)
    return true
  }

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

  function subscribeToProject(projectId) {
    return subscribe('project', projectId)
  }

  function subscribeToAgent(agentId) {
    return subscribe('agent', agentId)
  }


  function log(message, data = null) {
    if (config.debug) {
      const safeMsg = String(message).replace(/[\n\r\t]/g, ' ')
      console.warn(`[WebSocketV2] ${safeMsg}`, data || '')
    }

    addEvent('log', message, data)
  }

  function addEvent(type, message, data = null) {
    const event = {
      type,
      message,
      data,
      timestamp: new Date().toISOString(),
    }

    eventHistory.value.unshift(event)

    if (eventHistory.value.length > config.maxEventHistory) {
      eventHistory.value.pop()
    }
  }

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

  function setDebugMode(enabled) {
    config.debug = enabled
    log(`Debug mode ${enabled ? 'enabled' : 'disabled'}`)
  }


  return {
    connectionStatus,
    connectionError,
    reconnectAttempts,
    clientId,
    messageQueueSize: computed(() => messageQueue.value.length),
    subscriptions: computed(() => Array.from(subscriptions.value.keys())),

    isConnected,
    isConnecting,
    isReconnecting,
    isDisconnected,

    connect,
    reconnect,
    disconnect,

    send,
    on,
    off,
    onConnectionChange,

    subscribe,
    unsubscribe,
    subscribeToProject,
    subscribeToAgent,

    getConnectionInfo,
    getDebugInfo,
    setDebugMode,
  }
})
