<template>
  <div class="tools-directory smooth-border" data-testid="tools-connect-directory">
    <!-- Fleet rail — the user's tools with live status + "+ Add a tool" -->
    <aside class="dir-rail">
      <div class="dir-rail-top">
        <img src="/icons/Giljo_YW_Face.svg" alt="" class="dir-rail-logo" />
        <span class="dir-rail-kicker">YOUR TOOLS</span>
      </div>

      <div class="dir-rail-list">
        <button
          v-for="tool in fleet"
          :key="tool.id"
          :class="['dir-rail-row', { 'dir-rail-row--active': mode === 'card' && selectedId === tool.id }]"
          :data-testid="`dir-tool-${tool.id}`"
          @click="selectTool(tool.id)"
        >
          <span :class="['dir-rail-dot', `dir-rail-dot--${statusFor(tool.id)}`]" />
          <span class="dir-rail-label">{{ tool.name }}</span>
          <span class="dir-rail-status">{{ statusLabel(statusFor(tool.id)) }}</span>
        </button>

        <button
          :class="['dir-rail-row', 'dir-rail-row--add', { 'dir-rail-row--active': mode === 'picker' }]"
          data-testid="dir-add-tool"
          @click="openPicker"
        >
          <span class="dir-rail-add-icon"><v-icon size="14">mdi-plus</v-icon></span>
          <span class="dir-rail-label">Add a tool</span>
        </button>
      </div>
    </aside>

    <!-- Action window -->
    <div class="dir-window">
      <!-- Tool picker (from "+ Add a tool") -->
      <template v-if="mode === 'picker'">
        <div class="dir-eyebrow">TOOLS · ADD A TOOL</div>
        <h2 class="dir-title">Pick a tool to connect.</h2>
        <div class="dir-picker-grid">
          <div
            v-for="tool in SETUP_TOOLS"
            :key="tool.id"
            class="dir-picker-card smooth-border"
            :data-testid="`dir-pick-${tool.id}`"
            role="button"
            tabindex="0"
            @click="addTool(tool.id)"
            @keydown.enter.prevent="addTool(tool.id)"
            @keydown.space.prevent="addTool(tool.id)"
          >
            <span class="dir-picker-well">
              <img v-if="tool.logo" :src="tool.logo" :alt="tool.name" class="dir-picker-logo" />
              <v-icon v-else size="20">{{ tool.icon }}</v-icon>
            </span>
            <span class="dir-picker-name">{{ tool.name }}</span>
          </div>
        </div>
      </template>

      <!-- Selected tool's connect card -->
      <template v-else-if="selectedId">
        <div class="dir-eyebrow">TOOLS · {{ selectedName }}</div>
        <h2 class="dir-title">{{ selectedName }}.</h2>
        <ConnectToolCard
          :key="selectedId"
          :tool-id="selectedId"
          :connected="isConfigured"
          :key-mode="!!keyMode[selectedId]"
          connected-next="This tool is live. Manage or remove it here anytime."
          :advance-label="''"
          :show-already-configured="true"
          @toggle-key-mode="toggleKeyMode"
          @mark-configured="markConfigured"
        />
        <div class="dir-window-foot">
          <span class="dir-remove-link" role="button" tabindex="0" data-testid="dir-remove-tool" @click="removeTool(selectedId)">
            Remove tool
          </span>
        </div>
      </template>

      <!-- Empty fleet -->
      <template v-else>
        <div class="dir-empty" data-testid="dir-empty">
          <p>No tools yet. Add your first with <strong>+ Add a tool</strong>.</p>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useUserStore } from '@/stores/user'
import { useWebSocketStore } from '@/stores/websocket'
import api from '@/services/api'
import { SETUP_TOOLS, TOOL_META, toolName, toolIdForHarness, harnessForToolId } from '@/config/setupTools'
import ConnectToolCard from '@/components/setup/ConnectToolCard.vue'

const userStore = useUserStore()
const wsStore = useWebSocketStore()

// Fleet = the user's chosen tools (persisted via setup_selected_tools). "+ Add a tool"
// appends here. Connection status is WORKSPACE-LEVEL, backed by the durable
// GET /api/connect/credential-status endpoint (FE-9274) — the server emits a
// GENERIC connect event (it cannot tell which CLI connected, proposal §6: no
// per-tool attribution), so every row reflects the same tenant-wide credential
// truth. This also fixes the core bug where an in-memory-only status reverted to
// "Waiting" on every remount: the durable fetch survives navigation.
const fleetIds = ref([...(userStore.currentUser?.setup_selected_tools ?? [])])
const fleet = computed(() =>
  fleetIds.value.filter((id) => TOOL_META[id]).map((id) => ({ id, name: toolName(id) })),
)

const credStatus = reactive({
  has_valid_api_key: false,
  has_valid_oauth: false,
  has_expired_oauth: false,
  connected_harnesses: {},
})
// "I already configured this" optimistic flip — bridges the gap until the NEXT
// completed fetchCredentialStatus() call, which is always authoritative and always
// clears this flag (whatever it finds). It must never persist past that fetch: an
// un-reset optimistic flag would let a stale "Configured" survive an authoritative
// fetch that found no valid credential (e.g. after a revoke) — a false-positive
// worse than the stale-red bug this component was built to fix.
const optimisticConfigured = ref(false)
// In-session-only message after a revoke drops the workspace to no valid credential
// (no persistence flag, honors the no-tracking-per-tool rule: a fresh reload settles
// back to the plain "Not set up" idle state).
const justDeleted = ref(false)

const keyMode = reactive({})
const selectedId = ref(fleetIds.value[0] || null)
const mode = ref(selectedId.value ? 'card' : 'picker')

const selectedName = computed(() => toolName(selectedId.value))

// FE-9500: WORKSPACE-level -- "this account holds a live credential". True the
// moment ANY tool connects, so it must never be rendered as one tool's status.
const hasWorkspaceCredential = computed(
  () => credStatus.has_valid_api_key || credStatus.has_valid_oauth || optimisticConfigured.value,
)

// PER-TOOL truth: this tool completed an MCP handshake (mcp_sessions clientInfo,
// via credential-status.connected_harnesses). Previously every card was bound to
// the workspace flag above, so connecting ONE tool lit Claude, Antigravity and
// every other card green -- including tools not installed on the machine.
const connectedToolIds = computed(() => {
  const ids = new Set()
  for (const harness of Object.keys(credStatus.connected_harnesses || {})) {
    const id = toolIdForHarness(harness)
    if (id) ids.add(id)
  }
  return ids
})

// BE-9591 (c): PICKING A TOOL ALWAYS STARTS A FRESH FLOW.
//
// The operator's second-device case: he connected on his PC, opened this UI on a
// laptop, and the card was already green -- a connection inherited from a machine
// that was not the one in front of him. The server cannot tell machines apart, so
// the card verifies the connect he is performing NOW rather than reporting that
// SOMETHING, SOMEWHERE once connected.
//
// Deliberate UI theatre, and strictly view state: entering the flow WRITES NOTHING.
// Back out without connecting and the passive surfaces show the remembered state
// again immediately, because nothing was erased -- only "Remove tool" erases, and
// only a connection landing after entry upgrades the card.
//
// The RAIL (statusFor / connectedToolIds) is untouched and still shows the durable
// record: that passive label is not this ruling's target.
const cardEnteredAt = ref(new Date().toISOString())

/** Connect stamps newer than the moment this card was opened. */
const freshlyConnectedToolIds = computed(() => {
  const ids = new Set()
  for (const [harness, stamp] of Object.entries(credStatus.connected_harnesses || {})) {
    // A malformed or absent stamp is not fresh: the point is to stop history
    // satisfying the flow, and an unreadable timestamp is not evidence of anything.
    if (typeof stamp !== 'string' || stamp <= cardEnteredAt.value) continue
    const id = toolIdForHarness(harness)
    if (id) ids.add(id)
  }
  return ids
})

// The optimistic flip stays per-tool ("I already configured this" on THIS card) and
// is deliberately NOT subject to the freshness cutoff: it is the user asserting about
// the machine in front of them, which is the very thing the cutoff exists to require.
// Inherited history is what gets filtered, not an explicit statement.
const isConfigured = computed(
  () => freshlyConnectedToolIds.value.has(selectedId.value) || optimisticConfigured.value,
)
const isReauth = computed(
  () => !isConfigured.value && credStatus.has_expired_oauth && !credStatus.has_valid_api_key,
)

async function fetchCredentialStatus() {
  try {
    const { data } = await api.connect.credentialStatus()
    credStatus.has_valid_api_key = !!data?.has_valid_api_key
    credStatus.has_valid_oauth = !!data?.has_valid_oauth
  credStatus.has_expired_oauth = !!data?.has_expired_oauth
    credStatus.connected_harnesses = data?.connected_harnesses || {}
    // The completed fetch is authoritative — clear the optimistic flag atomically
    // with the new credStatus so a stale "already configured" click can never
    // outlive a real fetch that found nothing valid.
    optimisticConfigured.value = false
  } catch (e) {
    console.warn('[ToolsConnectDirectory] Failed to fetch credential status:', e)
  }
}

async function handleKeyRevoked() {
  await fetchCredentialStatus()
  // Revoking a key is a WORKSPACE event, so the "just deleted" notice keys off the
  // workspace flag -- not the selected tool's per-tool status (FE-9500).
  if (!hasWorkspaceCredential.value) {
    justDeleted.value = true
  }
}

// FE-9500: this takes an `id` and must ANSWER FOR THAT id. It previously returned
// the SELECTED tool's status for every row, so opening one tool's card painted the
// whole sidebar with that tool's state -- the visible half of "every harness reports
// connected". Only the transient states below are allowed to be selection-scoped.
function statusFor(id) {
  if (connectedToolIds.value.has(id)) return 'configured'
  if (selectedId.value === id && optimisticConfigured.value) return 'configured'
  if (selectedId.value === id && isReauth.value) return 'reauth'
  if (selectedId.value === id && justDeleted.value) return 'deleted'
  if (mode.value === 'card' && selectedId.value === id) return 'waiting'
  return 'idle'
}
function statusLabel(state) {
  switch (state) {
    case 'configured':
      return 'Configured'
    case 'reauth':
      return 'Requires re-authentication'
    case 'deleted':
      return 'API key deleted'
    case 'waiting':
      return 'Waiting'
    default:
      return 'Not set up'
  }
}

function selectTool(id) {
  // Each pick is a NEW flow, so the freshness anchor moves with it.
  cardEnteredAt.value = new Date().toISOString()
  selectedId.value = id
  mode.value = 'card'
}

function openPicker() {
  mode.value = 'picker'
}

async function addTool(id) {
  if (!fleetIds.value.includes(id)) {
    fleetIds.value = [...fleetIds.value, id]
    try {
      await userStore.updateSetupState({ setup_selected_tools: [...fleetIds.value] })
    } catch (e) {
      console.warn('[ToolsConnectDirectory] Failed to persist tool selection:', e)
    }
  }
  selectTool(id)
}

async function removeTool(id) {
  fleetIds.value = fleetIds.value.filter((t) => t !== id)
  try {
    await userStore.updateSetupState({ setup_selected_tools: [...fleetIds.value] })
  } catch (e) {
    console.warn('[ToolsConnectDirectory] Failed to persist tool removal:', e)
  }
  // BE-9591: forget the DURABLE connection too. Dropping the card from the local
  // fleet list was the whole of "Remove tool", and the card's green comes from
  // connected_harnesses (mcp_sessions rows) -- so re-adding the tool showed it
  // connected again from history, with nothing the user could do about it.
  //
  // Failure is warned, not surfaced: the card is already gone from the fleet list
  // and the user asked for that. A stale row means the status is wrong on the next
  // fetch, which is the same place they would go to try again.
  const harness = harnessForToolId(id)
  if (harness) {
    try {
      await api.connect.removeConnection(harness)
      await fetchCredentialStatus()
    } catch (e) {
      console.warn('[ToolsConnectDirectory] Failed to clear stored connection:', e)
    }
  }
  if (selectedId.value === id) {
    selectedId.value = fleetIds.value[0] || null
    mode.value = selectedId.value ? 'card' : 'picker'
  }
}

function toggleKeyMode() {
  keyMode[selectedId.value] = !keyMode[selectedId.value]
}

// "I already configured this" — optimistic workspace-level flip; the next durable
// fetch (mount, WS event, or key-created/-revoked) reconciles it against the truth.
function markConfigured() {
  optimisticConfigured.value = true
}

// FE-9500 changed the backend to emit the RESOLVED harness token (e.g.
// 'claude-code', 'opencode') instead of the hardcoded 'mcp_connected'
// placeholder this used to gate on -- so that check was permanently false in
// production and a real connect never refreshed this directory (it survived
// only on its own mount-time fetch, plus the api-key-created/-revoked window
// events). Re-fetch on ANY connect event: the durable GET recomputes full
// per-tool truth from connected_harnesses regardless of which token arrived,
// same as the credential-status idiom everywhere else on this surface. The
// legacy 'mcp_connected' literal still triggers it too (falls through the
// same truthy check) so an older backend during a rolling deploy keeps working.
let wsUnsub = null
async function handleToolConnected(payload) {
  if (payload?.tool_name) {
    await fetchCredentialStatus()
  }
}

onMounted(() => {
  wsUnsub = wsStore.on('setup:tool_connected', handleToolConnected)
  window.addEventListener('api-key-created', fetchCredentialStatus)
  window.addEventListener('api-key-revoked', handleKeyRevoked)
  fetchCredentialStatus()
})
onUnmounted(() => {
  if (wsUnsub) wsUnsub()
  window.removeEventListener('api-key-created', fetchCredentialStatus)
  window.removeEventListener('api-key-revoked', handleKeyRevoked)
})
</script>

<style scoped lang="scss">
@use '../../styles/variables' as *;
@use '../../styles/design-tokens' as *;

.tools-directory {
  display: grid;
  grid-template-columns: 240px 1fr;
  min-height: 460px;
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
  overflow: hidden;
  /* Must match .connect-grid's max-width in ToolsView.vue — the directory and the
     stacked integration cards below it are siblings on the Connect tab and have to
     align on the same right edge. */
  max-width: 1100px;
}

/* Fleet rail */
.dir-rail {
  background: $color-background-tertiary;
  box-shadow: inset -1px 0 0 rgba(255, 255, 255, 0.08);
  padding: 22px 16px;
  display: flex;
  flex-direction: column;
}

.dir-rail-top {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 20px;
}

.dir-rail-logo {
  height: 20px;
}

.dir-rail-kicker {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem;
  letter-spacing: 0.16em;
  color: var(--text-muted);
}

.dir-rail-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.dir-rail-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: 9px;
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  width: 100%;
}

.dir-rail-row:hover {
  background: rgba(255, 255, 255, 0.04);
}

.dir-rail-row--active {
  background: rgba($color-brand-yellow, 0.08);
}

.dir-rail-dot {
  width: 8px;
  height: 8px;
  flex-shrink: 0;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.15);
}

.dir-rail-dot--configured {
  background: $color-status-success;
}

.dir-rail-dot--reauth {
  background: $color-status-warning;
}

.dir-rail-dot--deleted {
  background: $color-indicator-disconnected;
}

/* FE-9569: unified onto the authoritative Waiting token (design-system-
   sample-v2.html "Status & Brand Colors" -- Waiting #ffd700, its own
   distinct status, not the disconnected/error red used above for --deleted). */
.dir-rail-dot--waiting {
  background: $color-status-waiting;
  animation: dir-wait 1.6s ease infinite;
}

@keyframes dir-wait {
  0%, 100% { opacity: 0.35; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.1); }
}

@media (prefers-reduced-motion: reduce) {
  .dir-rail-dot--waiting {
    animation: none;
  }
}

.dir-rail-label {
  flex: 1;
  font-size: 0.8rem;
  font-weight: 500;
  color: $lightest-blue;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dir-rail-row--active .dir-rail-label {
  color: $color-text-primary;
}

.dir-rail-status {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.52rem;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}

.dir-rail-row--add {
  margin-top: 6px;
  color: var(--text-muted);
}

.dir-rail-add-icon {
  width: 8px;
  height: 8px;
  display: grid;
  place-items: center;
  color: var(--text-muted);
}

/* Action window */
.dir-window {
  padding: 26px 30px;
  min-width: 0;
}

.dir-eyebrow {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.66rem;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: $color-brand-yellow;
  margin-bottom: 8px;
}

.dir-title {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 700;
  font-size: 1.35rem;
  letter-spacing: -0.02em;
  color: $color-text-primary;
  margin: 0 0 16px;
}

.dir-picker-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.dir-picker-card {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 13px 15px;
  border-radius: $border-radius-md;
  background: $elevation-elevated;
  cursor: pointer;
  transition: transform 0.15s;
}

.dir-picker-card:hover {
  transform: translateY(-1px);
  --smooth-border-color: #{rgba($color-brand-yellow, 0.4)};
}

.dir-picker-card:focus-visible {
  outline: 2px solid $color-brand-yellow;
  outline-offset: 2px;
}

.dir-picker-well {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: $border-radius-default;
  background: rgba(255, 255, 255, 0.05);
  display: grid;
  place-items: center;
  color: $lightest-blue;
}

.dir-picker-logo {
  width: 20px;
  height: 20px;
  object-fit: contain;
}

.dir-picker-name {
  font-family: 'Outfit', $typography-font-primary;
  font-size: 0.86rem;
  font-weight: 600;
  color: $color-text-primary;
}

.dir-window-foot {
  margin-top: 14px;
}

.dir-remove-link {
  font-size: 0.74rem;
  color: var(--text-muted);
  cursor: pointer;
}

.dir-remove-link:hover,
.dir-remove-link:focus-visible {
  color: $color-status-error;
}

.dir-empty {
  color: var(--text-secondary);
  font-size: 0.88rem;
  padding: 40px 0;
  text-align: center;
}

@media (max-width: 720px) {
  .tools-directory {
    grid-template-columns: 1fr;
  }

  .dir-rail {
    box-shadow: inset 0 -1px 0 rgba(255, 255, 255, 0.08);
  }

  .dir-picker-grid {
    grid-template-columns: 1fr;
  }
}
</style>
