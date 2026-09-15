import { computed } from 'vue'
import { useWebSocketStore } from '@/stores/websocket'

export function useNavConnectionStatus() {
  const wsStore = useWebSocketStore()

  const connectionIcon = computed(() => {
    switch (wsStore.connectionStatus) {
      case 'connected':
        return 'mdi-wifi'
      case 'connecting':
      case 'reconnecting':
        return 'mdi-wifi-sync'
      case 'disconnected':
        return 'mdi-wifi-off'
      default:
        return 'mdi-help-circle'
    }
  })

  const connectionColor = computed(() => {
    switch (wsStore.connectionStatus) {
      case 'connected':
        return 'success'
      case 'connecting':
      case 'reconnecting':
        return 'warning'
      case 'disconnected':
        return 'error'
      default:
        return 'grey'
    }
  })

  const connectionText = computed(() => {
    switch (wsStore.connectionStatus) {
      case 'connected':
        return 'Connected'
      case 'connecting':
        return 'Connecting...'
      case 'reconnecting':
        return `Reconnecting (${wsStore.reconnectAttempts}/${wsStore.maxReconnectAttempts})`
      case 'disconnected':
        return 'Disconnected'
      default:
        return 'Unknown'
    }
  })

  return {
    connectionIcon,
    connectionColor,
    connectionText,
  }
}
