<template>
  <v-dialog v-model="model" max-width="560" scrollable>
    <v-card v-draggable class="smooth-border">
      <div class="dlg-header">
        <v-icon class="mr-2" :color="chipColor">{{ icon }}</v-icon>
        Connection Health
        <v-spacer />
        <v-btn icon size="small" variant="text" class="dlg-close" @click="model = false">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </div>

      <v-card-text>
        <v-expansion-panels v-model="panels" variant="accordion">
          <v-expansion-panel value="status">
            <v-expansion-panel-title>
              <v-icon start :color="chipColor">{{ icon }}</v-icon>
              Connection Status
            </v-expansion-panel-title>
            <v-expansion-panel-text>
              <v-list density="compact">
                <v-list-item>
                  <v-list-item-title>State</v-list-item-title>
                  <v-list-item-subtitle>{{ connectionState }}</v-list-item-subtitle>
                </v-list-item>
                <v-list-item v-if="clientId">
                  <v-list-item-title>Client ID</v-list-item-title>
                  <v-list-item-subtitle>{{ clientId }}</v-list-item-subtitle>
                </v-list-item>
                <v-list-item>
                  <v-list-item-title>WebSocket URL</v-list-item-title>
                  <v-list-item-subtitle>{{ wsUrl }}</v-list-item-subtitle>
                </v-list-item>
                <v-list-item v-if="debugInfo?.stats?.connectedAt">
                  <v-list-item-title>Connected At</v-list-item-title>
                  <v-list-item-subtitle>{{ formatTime(debugInfo.stats.connectedAt) }}</v-list-item-subtitle>
                </v-list-item>
                <v-list-item v-if="debugInfo?.stats?.disconnectedAt">
                  <v-list-item-title>Disconnected At</v-list-item-title>
                  <v-list-item-subtitle>{{ formatTime(debugInfo.stats.disconnectedAt) }}</v-list-item-subtitle>
                </v-list-item>
                <v-list-item v-if="messageQueueSize > 0">
                  <v-list-item-title>Queued Messages</v-list-item-title>
                  <v-list-item-subtitle>{{ messageQueueSize }}</v-list-item-subtitle>
                </v-list-item>
              </v-list>
            </v-expansion-panel-text>
          </v-expansion-panel>

          <v-expansion-panel value="events">
            <v-expansion-panel-title>
              <v-icon start>mdi-history</v-icon>
              Recent Events
            </v-expansion-panel-title>
            <v-expansion-panel-text>
              <v-list density="compact" class="event-list">
                <v-list-item
                  v-for="(event, index) in recentEvents"
                  :key="index"
                  :class="`event-${event.type}`"
                >
                  <template #prepend>
                    <v-icon size="small" :color="getEventColor(event.type)">
                      {{ getEventIcon(event.type) }}
                    </v-icon>
                  </template>
                  <v-list-item-title>{{ event.message }}</v-list-item-title>
                  <v-list-item-subtitle>{{ formatTime(event.timestamp) }}</v-list-item-subtitle>
                </v-list-item>
                <v-list-item v-if="!recentEvents?.length">
                  <v-list-item-title class="text-grey">No events recorded</v-list-item-title>
                </v-list-item>
              </v-list>
            </v-expansion-panel-text>
          </v-expansion-panel>

          <v-expansion-panel v-if="debugInfo?.stats?.lastError" value="error">
            <v-expansion-panel-title color="error">
              <v-icon start color="error">mdi-alert-circle</v-icon>
              Last Error
            </v-expansion-panel-title>
            <v-expansion-panel-text>
              <v-alert type="error" variant="tonal">
                {{ debugInfo.stats.lastError }}
              </v-alert>
            </v-expansion-panel-text>
          </v-expansion-panel>
        </v-expansion-panels>
      </v-card-text>

      <div class="dlg-footer">
        <v-btn
          color="primary"
          variant="flat"
          :disabled="isConnecting"
          prepend-icon="mdi-refresh"
          @click="forceReconnect"
        >
          Reconnect
        </v-btn>
        <v-spacer />
        <v-btn variant="text" @click="model = false">Close</v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useWebSocketStore } from '@/stores/websocket'
import { getWsBaseUrl } from '@/composables/useApiUrl'

const model = defineModel({ type: Boolean, default: false })

const wsStore = useWebSocketStore()

const panels = ref(['status'])
const debugInfo = ref({})
const refreshInterval = ref(null)

const chipColor = computed(() => {
  switch (wsStore.connectionStatus) {
    case 'connected': return 'success'
    case 'connecting':
    case 'reconnecting': return 'warning'
    case 'disconnected': return 'error'
    default: return 'grey'
  }
})

const icon = computed(() => {
  switch (wsStore.connectionStatus) {
    case 'connected': return 'mdi-wifi'
    case 'connecting':
    case 'reconnecting': return 'mdi-wifi-sync'
    case 'disconnected': return 'mdi-wifi-off'
    default: return 'mdi-help-circle'
  }
})

const isConnecting = computed(() => wsStore.isConnecting)
const messageQueueSize = computed(() => wsStore.messageQueueSize)
const clientId = computed(() => wsStore.clientId)
const connectionState = computed(() => wsStore.connectionStatus)

const wsUrl = computed(() => {
  const baseUrl =
    import.meta.env.VITE_WS_URL ||
    getWsBaseUrl() ||
    `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
  return `${baseUrl}/ws/${clientId.value || '{client_id}'}`
})

const recentEvents = computed(() => debugInfo.value?.eventHistory?.slice(0, 10) || [])

const updateDebugInfo = () => {
  debugInfo.value = wsStore.getDebugInfo()
}

const forceReconnect = async () => {
  await wsStore.reconnect()
  updateDebugInfo()
}

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  return new Date(timestamp).toLocaleTimeString()
}

const getEventIcon = (type) => {
  const icons = {
    connection: 'mdi-connection',
    error: 'mdi-alert-circle',
    subscription: 'mdi-broadcast',
    log: 'mdi-text',
    test: 'mdi-test-tube',
  }
  return icons[type] || 'mdi-circle'
}

const getEventColor = (type) => {
  const colors = {
    connection: 'success',
    error: 'error',
    subscription: 'info',
    log: 'grey',
    test: 'warning',
  }
  return colors[type] || 'grey'
}

onMounted(() => {
  updateDebugInfo()
  refreshInterval.value = setInterval(() => {
    if (model.value) {
      updateDebugInfo()
    }
  }, 1000)
})

onUnmounted(() => {
  if (refreshInterval.value) {
    clearInterval(refreshInterval.value)
  }
})
</script>

<style lang="scss" scoped>
@use '../../styles/design-tokens' as *;

.event-list {
  max-height: 300px;
  overflow-y: auto;
}

.event-connection { border-left: 2px solid rgb(var(--v-theme-success)); }
.event-error { border-left: 2px solid rgb(var(--v-theme-error)); }
.event-subscription { border-left: 2px solid rgb(var(--v-theme-info)); }
.event-test { border-left: 2px solid rgb(var(--v-theme-warning)); }
</style>
