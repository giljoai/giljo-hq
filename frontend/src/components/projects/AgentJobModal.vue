<template>
  <v-dialog v-model="isVisible" max-width="700" persistent scrollable>
    <v-card v-draggable class="smooth-border">
      <!-- Header -->
      <div class="dlg-header">
        <div
          class="agent-badge-sq"
          :style="getAgentBadgeStyle(displayAgent?.agent_name || displayAgent?.agent_display_name)"
        >{{ getAgentAbbr(displayAgent?.agent_name || displayAgent?.agent_display_name) }}</div>
        <span class="dlg-title"><span class="agent-name-label">{{ displayAgent?.agent_name || displayAgent?.agent_display_name }}</span>&nbsp;- Assigned Job</span>
        <v-btn icon variant="text" size="small" class="dlg-close" @click="handleClose">
          <v-icon icon="mdi-close" size="18" />
        </v-btn>
      </div>

      <v-divider />

      <!-- Agent Info -->
      <v-card-text v-if="displayAgent" class="pa-4 pb-0">
        <div class="text-body-small text-muted-a11y">
          <div><strong>Agent ID:</strong> {{ displayAgent.agent_id }}</div>
          <div><strong>Job ID:</strong> {{ displayAgent.job_id }}</div>
          <div v-if="formattedCreatedAt"><strong>Created:</strong> {{ formattedCreatedAt }}</div>
        </div>
      </v-card-text>

      <!-- Tabs -->
      <div class="tab-pills px-4 py-2">
        <button
          class="pill-btn"
          :class="{ active: activeTab === 'mission' }"
          data-test="job-tab-mission"
          @click="activeTab = 'mission'"
        >
          <v-icon size="18">mdi-text-box-outline</v-icon>
          Mission
        </button>
        <button
          class="pill-btn"
          :class="{ active: activeTab === 'plan' }"
          data-test="job-tab-plan"
          @click="activeTab = 'plan'"
        >
          <v-icon size="18">mdi-checkbox-marked-outline</v-icon>
          Plan ({{ todoItemsCount }})
        </button>
      </div>

      <v-divider />

      <!-- Tab Content -->
      <v-card-text class="pa-4">
        <v-window v-model="activeTab">
          <!-- Mission Tab -->
          <v-window-item value="mission">
            <div v-if="displayAgent" class="mission-section">
              <v-card variant="flat" class="pa-3 smooth-border">
                <pre class="mission-text">{{ displayAgent.mission || 'No mission assigned yet.' }}</pre>
              </v-card>
            </div>
            <div v-else class="text-center py-4 text-muted-a11y">
              No agent selected
            </div>
          </v-window-item>

          <!-- Plan Tab -->
          <v-window-item value="plan">
            <div v-if="todoItems.length === 0" class="empty-state pa-4 text-center">
              <v-icon icon="mdi-checkbox-blank-outline" size="32" class="mb-2" />
              <div class="text-body-medium text-muted-a11y">
                No tasks reported yet
              </div>
            </div>

            <div v-else class="todo-items-list">
              <div
                v-for="(item, index) in todoItems"
                :key="`todo-${index}`"
                class="todo-item-row"
                data-test="todo-item-row"
              >
                <v-icon
                  :icon="getStatusIcon(item.status)"
                  :color="getStatusColor(item.status)"
                  :class="{ 'pulse-animation': item.status === 'in_progress' }"
                  class="mr-2"
                  size="20"
                />
                <span class="todo-item-content">{{ item.content }}</span>
              </div>
            </div>
          </v-window-item>
        </v-window>
      </v-card-text>

      <v-divider />

      <!-- Footer -->
      <div class="dlg-footer">
        <v-spacer />
        <v-btn color="primary" @click="handleClose">Close</v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed, ref, toRaw, watch } from 'vue'
import { getAgentBadgeStyle } from '@/utils/colorUtils'

// Props
const props = defineProps({
  show: {
    type: Boolean,
    required: true,
  },
  agent: {
    type: Object,
    default: null,
  },
  initialTab: {
    type: String,
    default: 'mission',
    validator: (value) => ['mission', 'plan'].includes(value),
  },
})

// Emits
const emit = defineEmits(['close'])

// State
const activeTab = ref(props.initialTab)

// Snapshot: freeze agent data when modal opens to decouple from live WebSocket reactivity
const agentSnapshot = ref(null)

// Computed
const isVisible = computed({
  get: () => props.show,
  set: (value) => {
    if (!value) emit('close')
  },
})

// Prefer snapshot data while modal is open; fall back to live prop
const displayAgent = computed(() => agentSnapshot.value || props.agent)

const todoItems = computed(() =>
  displayAgent.value?.todo_items && Array.isArray(displayAgent.value.todo_items)
    ? displayAgent.value.todo_items
    : [],
)

const formattedCreatedAt = computed(() => {
  if (!displayAgent.value?.created_at) return null
  const date = new Date(displayAgent.value.created_at)
  return date.toLocaleString()
})

const todoItemsCount = computed(() => todoItems.value.length)

// Watch initialTab to update activeTab when modal opens
watch(
  () => props.initialTab,
  (newTab) => {
    activeTab.value = newTab
  },
  { immediate: true },
)

// Snapshot agent data on open -- disconnect from live WebSocket reactivity
watch(
  () => props.show,
  (visible) => {
    if (visible) {
      agentSnapshot.value = props.agent ? { ...toRaw(props.agent) } : null
    } else {
      agentSnapshot.value = null
    }
  },
)

// BE-9416: the snapshot above is deliberate -- it disconnects the open modal from
// live WS churn. But a mission arriving over agent:created / agent:mission_updated
// is now BOUNDED (it has to clear the cross-worker broker's byte cap), so a modal
// opened in the window before the store's top-up lands would freeze an EXCERPT and
// render it as the whole mission, with nothing to say otherwise.
//
// Narrowest possible fix: adopt the full text when it arrives, and ONLY then --
// this watch fires only on the truncated -> whole transition, so ordinary status
// churn still cannot reach the snapshot and the disconnect keeps doing its job.
watch(
  () => props.agent?.mission_truncated,
  (isTruncated, wasTruncated) => {
    if (wasTruncated && !isTruncated && agentSnapshot.value && props.agent?.mission) {
      agentSnapshot.value = { ...agentSnapshot.value, mission: props.agent.mission, mission_truncated: false }
    }
  },
)

// Methods
function handleClose() {
  emit('close')
}

function getStatusIcon(status) {
  switch (status) {
    case 'completed':
      return 'mdi-checkbox-marked'
    case 'in_progress':
      return 'mdi-progress-clock'
    case 'pending':
    default:
      return 'mdi-checkbox-blank-outline'
  }
}

function getStatusColor(status) {
  switch (status) {
    case 'completed':
      return 'success'
    case 'in_progress':
      return 'warning'
    case 'pending':
    default:
      return 'grey'
  }
}


function getAgentAbbr(agentName) {
  if (!agentName) return '?'
  return agentName
    .split(/[\s_-]+/)
    .map(word => word[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)
}
</script>

<style lang="scss" scoped>
@use '../../styles/design-tokens' as *;
.tab-pills {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mission-section {
  max-height: 400px;
  overflow-y: auto;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 200px;
}

.todo-items-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 400px;
  overflow-y: auto;
  padding: 8px 0;
}

.todo-item-row {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-radius: $border-radius-sharp;
  transition: background-color $transition-normal ease;
}

.todo-item-row:hover {
  background-color: rgba(0, 0, 0, 0.02);
}

.todo-item-content {
  font-size: 0.875rem;
  line-height: 1.4;
}

/* Pulse animation for in_progress items */
@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

.pulse-animation {
  animation: pulse 2s ease-in-out infinite;
}

.agent-name-label {
  text-transform: capitalize;
}
</style>
