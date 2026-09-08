<template>
  <div class="step-connect" data-testid="step2-connect">
    <!-- Eyebrow + title (action-window header — one tool at a time) -->
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
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onUnmounted } from 'vue'
import { useWebSocketStore } from '@/stores/websocket'
import api from '@/services/api'
import { toolName, toolIdForHarness } from '@/config/setupTools'
import ConnectToolCard from './ConnectToolCard.vue'

const props = defineProps({
  selectedTools: {
    type: Array,
    required: true,
  },
})

const emit = defineEmits(['can-proceed', 'step-data', 'walk-state', 'advance-step'])

const wsStore = useWebSocketStore()

// Walk position + per-tool state (the mock state machine: toolIdx, conn{}, keyMode{}).
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

// Middot separators, never an em dash: FE-6259b locks "no em dash in step-2 copy".
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

// Advance the walk: next tool, or (on the last tool) advance the wizard step.
function handleAdvance() {
  if (!isLast.value) {
    toolIdx.value += 1
  } else {
    emit('advance-step')
  }
}

// "I already configured this" — marks the ACTIVE tool connected only (ratified
// behavior change from the old marks-ALL, proposal §6 / CODE_GUIDANCE event wiring:
// with the walk-one-tool-at-a-time model, manual confirmation is per-tool).
function markActiveConfigured() {
  connectionStatus[activeToolId.value] = 'connected'
}

// FE-9500: the event now NAMES the harness that connected (harness_resolver, from
// the initialize clientInfo) instead of the old hardcoded 'mcp_connected'. Flip the
// tool that actually attached. The previous contract flipped whichever tool the user
// happened to be looking at, so a client connecting from anywhere marked the wrong
// card -- including tools not installed on the machine.
//
// Two deliberate fallbacks, both honest:
//  - 'generic' (client self-identified with nothing) and any harness not in this
//    build's map flip the ACTIVE tool, the old behaviour: SOMETHING connected while
//    the user was walking this tool, which is the best available attribution.
//  - the legacy 'mcp_connected' literal is still accepted so a new frontend keeps
//    working against an older backend during a rolling deploy.
let wsUnsub = null
function handleToolConnected(payload) {
  const name = payload?.tool_name
  if (!name) return
  const mapped = name === 'mcp_connected' ? null : toolIdForHarness(name)
  const target = mapped && mapped !== 'generic' ? mapped : activeToolId.value
  if (target) connectionStatus[target] = 'connected'
}

// Gate: proceed once >= 1 tool is connected (footer Next; the hero drives the walk).
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

// Rail sub-rows: the overlay renders per-tool Connect sub-rows from this walk state
// (wizard progression, never event attribution).
const walkState = computed(() => ({
  order: order.value,
  activeId: activeToolId.value,
  conn: { ...connectionStatus },
}))
watch(walkState, (val) => emit('walk-state', val), { immediate: true, deep: true })

// FE-9569 detector 1: the card used to treat the WS event as the ONLY source
// of truth ("connected" flips only when a fresh setup:tool_connected fires
// while this step happens to be mounted). An already-authenticated tenant
// (connected in another TUI, or reconnecting after a reload) sends no
// `initialize` while the wizard is open, so nothing ever arrived and the dot
// stayed stuck on "Waiting..." forever. Read the durable truth instead —
// same idiom already shipped in ToolsConnectDirectory.vue's
// fetchCredentialStatus — and treat the WS event as a live delta on top of
// it, not the sole trigger.
//
// BE-9591 SUPERSEDES the earlier "no recency cutoff" ruling on this surface, and
// the reversal is deliberate rather than an oversight. That ruling made the dot
// flip whenever ANY connection had ever existed between this tenant and the
// harness, however old -- which the operator then hit from the other side: he
// connected on one machine, opened the wizard on a second, and Claude Code was
// already green there before that machine had ever connected. Once-connected read
// as forever-connected.
//
// So the ACTIVE flow now requires a FRESH connection: one whose timestamp is after
// this step was entered. The Connect page's passive per-tool status still reflects
// the durable record without a cutoff -- that is its job, and it is not this
// ruling's target.
//
// This is only safe BECAUSE BE-9590 landed. The earlier ruling existed to fix a
// dot stuck on "Waiting..." forever, since an already-authenticated client sent no
// `initialize` while the wizard was open and nothing announced. Modern clients
// attach with `server/discover`, which now announces too -- so connecting while the
// wizard is open produces a live event whichever handshake the tool speaks. Without
// BE-9590 this cutoff would re-create exactly the bug that ruling removed.
// When this step was entered. A durable connection older than this belongs to some
// other machine or some earlier day, and must not satisfy THIS flow.
const flowEnteredAt = new Date().toISOString()

/** True when a durable connect stamp is newer than the moment this flow started. */
function isFresh(stamp) {
  // A malformed or absent stamp is NOT fresh. The whole point is to stop history
  // satisfying the flow, and an unreadable timestamp is not evidence of anything.
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
  // Subscribe first so a connect event arriving WHILE the credential-status
  // fetch is in flight is never dropped.
  wsUnsub = wsStore.on('setup:tool_connected', handleToolConnected)
  await loadCredentialStatus()
  // Resume at the first not-yet-connected tool (now credential-status aware).
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
