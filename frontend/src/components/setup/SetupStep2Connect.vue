<template>
  <div class="step-connect" data-testid="step2-connect">
    <div class="connect-eyebrow">{{ eyebrow }}</div>
    <h2 class="connect-title">{{ title }}</h2>

    <ConnectToolCard
      :key="activeToolId"
      :tool-id="activeToolId"
      :connected="activeConnected"
      :key-mode="!!keyMode[activeToolId]"
      :connected-next="connectedNext"
      :advance-label="advanceLabel"
      @advance="handleAdvance"
      @toggle-key-mode="toggleKeyMode"
      @mark-configured="markActiveConfigured"
    />
    <ConnectAgentLink />
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onUnmounted } from 'vue'
import { useWebSocketStore } from '@/stores/websocket'
import api from '@/services/api'
import { toolName, toolIdForHarness } from '@/config/setupTools'
import ConnectToolCard from './ConnectToolCard.vue'
import ConnectAgentLink from './ConnectAgentLink.vue'

const props = defineProps({
  selectedTools: {
    type: Array,
    required: true,
  },
})

const emit = defineEmits(['can-proceed', 'step-data', 'walk-state', 'advance-step'])

const wsStore = useWebSocketStore()

const toolIdx = ref(0)
const connectionStatus = reactive(
  Object.fromEntries(props.selectedTools.map((id) => [id, 'waiting'])),
)
const keyMode = reactive({})

const order = computed(() => props.selectedTools)
const activeToolId = computed(
  () => order.value[Math.min(toolIdx.value, Math.max(0, order.value.length - 1))] || order.value[0],
)
const activeToolName = computed(() => toolName(activeToolId.value))
const activeConnected = computed(() => connectionStatus[activeToolId.value] === 'connected')

const isLast = computed(() => toolIdx.value >= order.value.length - 1)

const eyebrow = computed(
  () => `02 · CONNECT · TOOL ${toolIdx.value + 1} OF ${order.value.length}`,
)
const title = computed(() =>
  activeToolId.value === 'generic' ? 'Connect your MCP client.' : `Connect ${activeToolName.value}.`,
)
const connectedNext = computed(() => {
  if (isLast.value) return 'All tools connected. Agents and skills are next.'
  return `${toolName(order.value[toolIdx.value + 1])} is next. Same move.`
})
const advanceLabel = computed(() => (isLast.value ? 'Install agents & skills' : 'Next tool'))

function toggleKeyMode() {
  keyMode[activeToolId.value] = !keyMode[activeToolId.value]
}

function handleAdvance() {
  if (!isLast.value) {
    toolIdx.value += 1
  } else {
    emit('advance-step')
  }
}

function markActiveConfigured() {
  connectionStatus[activeToolId.value] = 'connected'
}

let wsUnsub = null
function handleToolConnected(payload) {
  const name = payload?.tool_name
  if (!name) return
  const mapped = toolIdForHarness(name)
  const target = mapped && mapped !== 'generic' ? mapped : activeToolId.value
  if (target) connectionStatus[target] = 'connected'
}

const hasConnectedTool = computed(() =>
  Object.values(connectionStatus).some((s) => s === 'connected'),
)
watch(hasConnectedTool, (val) => emit('can-proceed', val), { immediate: true })

const connectedTools = computed(() =>
  Object.entries(connectionStatus)
    .filter(([, status]) => status === 'connected')
    .map(([id]) => id),
)
watch(connectedTools, (val) => emit('step-data', { connectedTools: val }), { deep: true, immediate: true })

const walkState = computed(() => ({
  order: order.value,
  activeId: activeToolId.value,
  conn: { ...connectionStatus },
}))
watch(walkState, (val) => emit('walk-state', val), { immediate: true, deep: true })

const flowEnteredAt = new Date().toISOString()

function isFresh(stamp) {
  return typeof stamp === 'string' && stamp > flowEnteredAt
}

async function loadCredentialStatus() {
  try {
    const { data } = await api.connect.credentialStatus()
    const connectedHarnesses = data?.connected_harnesses || {}
    for (const [harness, stamp] of Object.entries(connectedHarnesses)) {
      const id = toolIdForHarness(harness)
      if (id && Object.prototype.hasOwnProperty.call(connectionStatus, id) && isFresh(stamp)) {
        connectionStatus[id] = 'connected'
      }
    }
  } catch (e) {
    console.warn('[SetupStep2Connect] Failed to fetch credential status:', e)
  }
}

onMounted(async () => {
  wsUnsub = wsStore.on('setup:tool_connected', handleToolConnected)
  await loadCredentialStatus()
  const firstUnconnected = order.value.findIndex((id) => connectionStatus[id] !== 'connected')
  toolIdx.value = firstUnconnected === -1 ? 0 : firstUnconnected
})

onUnmounted(() => {
  if (wsUnsub) wsUnsub()
})
</script>

<style scoped lang="scss">
@use '../../styles/variables' as *;
@use '../../styles/design-tokens' as *;

.step-connect {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.connect-eyebrow {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: $color-brand-yellow;
  margin-bottom: 8px;
}

.connect-title {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 700;
  font-size: 1.4rem;
  letter-spacing: -0.02em;
  color: $color-text-primary;
  margin: 0 0 16px;
}
</style>
