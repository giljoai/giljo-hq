<template>
  <div class="launch-tab-wrapper">
    <!-- 3-column grid: Description | Mission | Agents -->
    <div class="content-grid">
      <!-- Description Card -->
      <div class="content-card smooth-border" data-testid="description-panel">
        <div class="section-label">
          <span>Project Description</span>
          <div class="header-actions">
            <v-btn
              icon="mdi-pencil"
              size="x-small"
              variant="text"
              class="header-edit-btn icon-interactive"
              title="Edit description"
              aria-label="Edit description"
              @click="editDescription"
            />
            <AgentTipsDialog />
          </div>
        </div>
        <div class="card-body scrollbar-standard">
          <p class="description-text">{{ project.description || 'No description available' }}</p>
        </div>
      </div>

      <!-- Mission Card -->
      <div class="content-card smooth-border" data-testid="mission-panel">
        <div class="section-label">
          <span>Mission</span>
        </div>
        <div class="card-body scrollbar-standard">
          <EmptyState
            v-if="!missionText"
            icon="mdi-file-document-outline"
            title="No mission generated"
          />
          <template v-else>
            <span class="orchestrator-tag">
              <v-icon size="14" class="mr-1">mdi-creation</v-icon>
              Orchestrator Generated
            </span>
            <div class="mission-content">
              {{ missionText }}
            </div>
          </template>
        </div>
      </div>

      <!-- Agents Column (bare, no card) -->
      <div class="agents-column" data-testid="agents-panel">
        <!-- Agents label + integration icons inline -->
        <div class="section-label section-label--standalone">
          <span>Agents</span>
          <div class="integrations-row">
            <v-tooltip location="bottom" max-width="300">
              <template #activator="{ props: tooltipProps }">
                <v-icon
                  v-bind="tooltipProps"
                  :class="{
                    'icon-disabled': integrationsResolved && !gitEnabled,
                    'icon-pending': !integrationsResolved,
                  }"
                  size="28"
                  color="white"
                  data-testid="git-status-icon"
                  class="cursor-pointer integration-icon"
                  aria-label="Git integration status"
                  @click="goToIntegrations"
                >mdi-git</v-icon>
              </template>
              <span v-if="!integrationsResolved">Checking Git integration status.</span>
              <span v-else-if="gitEnabled">Git integration enabled.</span>
              <span v-else>Git disabled. Click to enable.</span>
            </v-tooltip>
            <v-tooltip location="bottom" max-width="300">
              <template #activator="{ props: tooltipProps }">
                <v-img
                  v-bind="tooltipProps"
                  src="/Serena.png"
                  width="28"
                  height="28"
                  :class="{
                    'icon-disabled': integrationsResolved && !serenaEnabled,
                    'icon-pending': !integrationsResolved,
                  }"
                  data-testid="serena-status-icon"
                  class="cursor-pointer integration-icon"
                  alt="Serena MCP"
                  @click="goToIntegrations"
                />
              </template>
              <span v-if="!integrationsResolved">Checking Serena MCP status.</span>
              <span v-else-if="serenaEnabled">Serena MCP enabled.</span>
              <span v-else>Serena disabled. Click to enable.</span>
            </v-tooltip>
            <v-tooltip v-if="agenticTool" location="bottom" max-width="300">
              <template #activator="{ props: tooltipProps }">
                <v-icon
                  v-if="agenticTool.type === 'icon'"
                  v-bind="tooltipProps"
                  size="28"
                  color="primary"
                  data-testid="agentic-tool-icon"
                  class="cursor-pointer integration-icon"
                  :aria-label="agenticTool.alt"
                  @click="goToIntegrations"
                >{{ agenticTool.icon }}</v-icon>
                <v-img
                  v-else
                  v-bind="tooltipProps"
                  :src="agenticTool.src"
                  width="28"
                  height="28"
                  data-testid="agentic-tool-icon"
                  class="cursor-pointer integration-icon"
                  :alt="agenticTool.alt"
                  @click="goToIntegrations"
                />
              </template>
              <span>{{ agenticTool.label }} mode active.</span>
            </v-tooltip>
          </div>
        </div>

        <!-- Agents list (bare, no card wrapper) -->
        <div class="agents-list">
      <!-- All agents shown together -->
      <div
        v-for="agent in sortedJobs"
        :key="agent.job_id || agent.agent_id || agent.id"
        class="agent-slim-card"
        data-testid="agent-card"
        :data-agent-display-name="agent.agent_display_name"
        @click="handleAgentInfo(agent)"
      >
        <div class="agent-badge" :style="getAgentBadgeStyle(agent.agent_name || agent.agent_display_name)">
          {{ getAgentInitials(agent.agent_display_name) }}
        </div>
        <div class="agent-info">
          <span class="agent-name" data-testid="agent-name">{{ agent.agent_display_name?.toUpperCase() || '' }}</span>
          <div class="text-body-small agent-meta">
            <span v-if="agent.status && agent.status !== 'waiting' && agent.status !== 'pending'" class="status-text" :class="'status-' + agent.status">
              {{ agent.status }}
            </span>
            <v-tooltip v-if="agent.agent_id || agent.job_id" location="top">
              <template #activator="{ props: tooltipProps }">
                <span
                  v-bind="tooltipProps"
                  class="agent-id-link"
                  @click.stop
                >
                  • ID: {{ (agent.agent_id || agent.job_id || '').slice(0, 8) }}...
                </span>
              </template>
              <span>{{ agent.agent_id || agent.job_id }}</span>
            </v-tooltip>
          </div>
        </div>
        <span class="agent-type" data-testid="agent-display-name" style="display: none;">{{ agent.agent_display_name || '' }}</span>
        <span class="status-chip" data-testid="status-chip" style="display: none;">{{ agent.status || 'pending' }}</span>
        <v-icon
          v-if="agent.agent_display_name !== 'orchestrator'"
          size="small"
          class="icon-interactive mr-1"
          role="button"
          tabindex="0"
          title="Edit agent configuration"
          aria-label="Edit agent configuration"
          @click.stop="handleAgentEdit(agent)"
          @keydown.enter="handleAgentEdit(agent)"
        >mdi-pencil</v-icon>
        <v-icon
          size="small"
          class="icon-interactive"
          role="button"
          tabindex="0"
          title="View agent details"
          aria-label="View agent details"
          @click.stop="handleAgentInfo(agent)"
          @keydown.enter="handleAgentInfo(agent)"
        >mdi-eye</v-icon>
      </div>
      <!-- Empty state when no agents -->
      <div v-if="!sortedJobs || sortedJobs.length === 0" class="empty-agents">
        <v-icon size="48" class="empty-icon">mdi-account-group-outline</v-icon>
        <p class="text-body-small text-muted-a11y">No agents yet - click Stage Project to begin</p>
        </div>
      </div>
      </div>
    </div>

    <!-- Agent Details Modal -->
    <AgentDetailsModal
      v-model="showDetailsModal"
      :agent="selectedAgent"
    />

    <!-- Agent Mission Edit Modal -->
    <AgentMissionEditModal
      v-model="showMissionEditModal"
      :agent="selectedAgentForEdit"
      @mission-updated="handleMissionUpdated"
    />

  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import { useAgentJobs } from '@/composables/useAgentJobs'
import { useAgentJobsStore } from '@/stores/agentJobsStore'
import { useProjectStateStore } from '@/stores/projectStateStore'
import AgentDetailsModal from '@/components/projects/AgentDetailsModal.vue'
import AgentMissionEditModal from '@/components/projects/AgentMissionEditModal.vue'
import AgentTipsDialog from '@/components/common/AgentTipsDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { getAgentBadgeStyle } from '@/utils/colorUtils'

/**
 * LaunchTab Component - Complete Rewrite (Handover 0241)
 * Execution Mode Toggle moved to ProjectTabs (Handover 0428)
 * Flattened layout (Handover 0873): 2-col grid for cards, bare agents list
 */

const props = defineProps({
  project: {
    type: Object,
    required: true,
    validator: (value) => {
      return value && typeof value === 'object' && ('id' in value || 'project_id' in value)
    },
  },
  orchestrator: {
    type: Object,
    default: null,
  },
  isStaging: {
    type: Boolean,
    default: false,
  },
  gitEnabled: {
    type: Boolean,
    default: false,
  },
  serenaEnabled: {
    type: Boolean,
    default: false,
  },
  // TSK-9234: gitEnabled/serenaEnabled default to false, which means BOTH
  // "known to be off" and "not read yet". Without this flag the icons assert
  // "disabled -- click to enable" against a status nobody has read. Defaults to
  // false so a caller that omits it renders the honest unknown state rather
  // than a false negative.
  integrationsResolved: {
    type: Boolean,
    default: false,
  },
  agenticTool: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits([
  'edit-description',
])

const router = useRouter()

function goToIntegrations() {
  router.push({ path: '/tools', query: { tab: 'connect' } })
}

/**
 * Project ID from props
 */
const projectId = computed(() => {
  const id = props.project?.project_id || props.project?.id
  if (!id) {
    console.error('[LaunchTab] Project missing ID field')
    throw new Error('Invalid project: missing ID')
  }
  return id
})

/**
 * Get agent initials - uses word initials
 * Split by dash, space, or underscore and use first letter of each part
 * e.g., "Backend-Implementer" -> "BI", "Backend-Tester" -> "BT"
 */
const getAgentInitials = (displayName) => {
  if (!displayName) return '??'

  // Split by dash, space, or underscore
  const parts = displayName.split(/[-_\s]+/).filter(Boolean)

  if (parts.length >= 2) {
    // Use first letter of first two parts: "Backend-Implementer" -> "BI"
    return (parts[0][0] + parts[1][0]).toUpperCase()
  }

  // Single word fallback: use first two letters
  return displayName.substring(0, 2).toUpperCase()
}

const projectStateStore = useProjectStateStore()
const missionText = computed(
  () => projectStateStore.getProjectState(projectId.value)?.mission || '',
)

const { sortedJobs } = useAgentJobs()
const agentJobsStore = useAgentJobsStore()

/**
 * Component State
 */
const { showToast } = useToast()
const showDetailsModal = ref(false)
const selectedAgent = ref(null)
const showMissionEditModal = ref(false)
const selectedAgentForEdit = ref(null)

/**
 * Handle Edit Description button
 */
function editDescription() {
  emit('edit-description')
}

/**
 * Handle Info icon click for Agent Team members
 */
function handleAgentInfo(agent) {
  selectedAgent.value = {
    ...agent,
    id: agent.id || agent.job_id,
  }
  showDetailsModal.value = true
}

/**
 * Handle Edit icon click for Agent Team members
 */
function handleAgentEdit(agent) {
  if (agent.agent_display_name === 'orchestrator') {
    // Orchestrators don't have editable missions
    showToast({ message: 'Orchestrator configuration cannot be edited here', type: 'info' })
    return
  }

  selectedAgentForEdit.value = agent
  showMissionEditModal.value = true
}

/**
 * Handle mission updated event from modal
 */
function handleMissionUpdated({ jobId, mission }) {
  agentJobsStore.upsertJob?.({ job_id: jobId, mission })

  showToast({ message: 'Agent mission updated successfully', type: 'success' })
}

/**
 * Watchers
 */
watch(missionText, (next, previous) => {
  if (next && !previous) {
    showToast({ message: 'Agent mission generated', type: 'success' })
  }
})
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens.scss' as *;

.launch-tab-wrapper {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px;
  background: transparent;
}

/* Integration icons inline with Agents label */
.integrations-row {
  display: flex;
  align-items: center;
  gap: 8px;

  .integration-icon {
    opacity: 1;
    transition: opacity 0.25s ease;
    object-fit: contain;

    &.icon-disabled {
      opacity: 0.3;

      &:hover {
        opacity: 0.5;
      }
    }

    // TSK-9234: status not read yet. Deliberately BETWEEN enabled (1) and
    // disabled (0.3) so the icon claims neither -- rendering it at either
    // extreme would state a status nobody has read.
    &.icon-pending {
      opacity: 0.65;
    }
  }
}

/* Two-column grid for Description + Mission cards */
.content-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  grid-template-rows: 1fr;
  gap: 20px;
  flex: 1;
  min-height: 0;
}

/* Agents column (bare, no card frame — top padding matches content-card) */
.agents-column {
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding-top: 20px;
}

/* Individual content cards (Description, Mission) */
.content-card {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
  padding: 20px;

  .card-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    font-size: 0.8rem;
    line-height: 1.5;
    color: $color-text-primary;
    margin-top: 12px;

    .orchestrator-tag {
      display: inline-flex;
      align-items: center;
      background: rgba(212, 176, 138, 0.15);
      color: $color-agent-orchestrator;
      font-size: 0.65rem;
      font-weight: 600;
      padding: 3px 10px;
      border-radius: $border-radius-default;
      margin-bottom: 10px;
    }

    .mission-content {
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 0.78rem;
      line-height: 1.5;
      color: $color-text-secondary;
      font-style: italic;
    }

    .description-text {
      line-height: 1.5;
      white-space: pre-wrap;
      word-break: break-word;
    }
  }
}

/* Section label — IBM Plex Mono uppercase (matches integrations page) */
.section-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 26px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem;
  color: $color-text-muted;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: 600;

  .header-actions {
    display: flex;
    align-items: center;
    gap: 2px;
  }

  .header-edit-btn {
    width: 26px;
    height: 26px;
  }

  &--standalone {
    margin-bottom: 8px;
  }
}

/* Agents List — bare, no background/border/shadow */
.agents-list {
  display: flex;
  flex-direction: column;
  gap: 4px;

  .empty-agents {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 32px;
    text-align: center;

    .empty-icon {
      color: rgba(var(--v-theme-on-surface), 0.15);
      margin-bottom: 8px;
    }
  }
}

/* Agent card — tinted square badge pattern (0870j) */
.agent-slim-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: $border-radius-default;
  background: transparent;
  border: none;
  transition: background $transition-fast;
  cursor: pointer;

  &:hover {
    background: rgba(255, 255, 255, 0.03);
  }

  .agent-badge {
    width: 36px;
    height: 36px;
    border-radius: $border-radius-default;
    display: grid;
    place-items: center;
    font-size: 0.7rem;
    font-weight: 700;
    flex-shrink: 0;
  }

  .agent-info {
    flex: 1;
    min-width: 0;

    .agent-name {
      font-size: 0.78rem;
      font-weight: 500;
      color: $color-text-primary;
    }
  }

  // Meta line: status + id
  .agent-meta {
    font-size: 0.62rem;
    color: $color-text-muted;
    margin-top: 1px;
  }

  .status-text {
    text-transform: capitalize;
    font-size: 0.62rem;
    font-style: italic;

    &.status-waiting { color: $color-status-waiting; }
    &.status-working { color: $color-status-working; font-style: italic; }
    &.status-complete { color: $color-status-complete; }
    &.status-handed_over { color: $color-status-handed-over; }
    &.status-blocked { color: $color-status-blocked; }
    &.status-silent { color: $color-status-blocked; }
    &.status-pending { color: $color-status-waiting; }
  }

  .agent-id-link {
    cursor: pointer;
    font-family: 'IBM Plex Mono', monospace;
    background: rgba(255, 255, 255, 0.05);
    padding: 0 4px;
    border-radius: $border-radius-sharp;
    text-decoration: none;

    &:hover {
      color: $color-brand-yellow;
    }
  }

  .icon-interactive {
    flex-shrink: 0;
    width: 26px;
    height: 26px;
  }
}

@media (max-width: 1100px) {
  .content-grid {
    grid-template-columns: 1fr;
  }
}
</style>
