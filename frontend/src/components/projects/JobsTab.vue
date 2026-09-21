<template>
  <div class="implement-tab-wrapper">
    <div class="table-container smooth-border">
      <ExecutionOrderBar
        v-if="executionOrderPhases"
        :phases="executionOrderPhases"
      />

      <table class="agents-table" data-testid="agent-status-table">
        <thead>
          <tr>
            <th class="col-phase">Phase</th>
            <th class="col-play"></th>
            <th class="col-agent-name">Agent Name</th>
            <th class="col-center">Agent Status</th>
            <th class="col-center hide-mobile">Duration</th>
            <th class="col-center hide-mobile">Steps</th>
            <th class="col-center hide-mobile">Messages Waiting</th>
            <th class="col-actions"></th>
          </tr>
        </thead>
        <tbody>
          <AgentRow
            v-for="agent in phaseSortedAgents"
            :key="agent.job_id || agent.agent_id"
            :agent="agent"
            :now="now"
            :is-subagent-mode="isSubagentMode"
            :should-show-copy="shouldShowCopyButton(agent)"
            :play-faded="isPlayButtonFaded(agent)"
            :play-tooltip="playButtonTooltip(agent)"
            @play="handlePlay"
            @reactivate-play="reactivatePlay"
            @messages="(agent) => handleMessages(agent, projectId)"
            @steps="handleStepsClick"
            @agent-role="handleAgentRole"
            @agent-job="handleAgentJob"
            @handover="handleHandOver"
            @stop-project="handleStopProject(projectId, clipboardCopy)"
          />
        </tbody>
      </table>
    </div>

    <MessageComposer
      :project-id="projectId"
      :chain-mode="!!chainCtx"
      :conductor-agent-id="chainCtx?.conductor?.agentId || ''"
      :chain-run-id="chainCtx?.runId || ''"
      :orchestrator-agent-id="orchestratorAgentId"
    />

    <AgentDetailsModal
      v-model="showAgentDetailsModal"
      :agent="selectedAgent"
    />

    <AgentJobModal
      :show="showAgentJobModal"
      :agent="selectedAgent"
      :initial-tab="jobModalInitialTab"
      @close="showAgentJobModal = false"
    />

    <HandoverModal
      :show="showHandoverModal"
      :retirement-prompt="handoverData.retirement_prompt"
      :continuation-prompt="handoverData.continuation_prompt"
      @close="showHandoverModal = false"
    />

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useClipboard } from '@/composables/useClipboard'
import { useProjectStateStore } from '@/stores/projectStateStore'
import { useNotificationStore } from '@/stores/notifications'
import { notifyFailure } from '@/utils/notifyFailure'
import { useAgentJobs } from '@/composables/useAgentJobs'
import { useJobActions } from '@/composables/useJobActions'
import { usePlayButton } from '@/composables/usePlayButton'
import { isSubagentExecutionMode } from '@/composables/useExecutionMode'
import { getAgentColor as getAgentColorConfig, getAgentColorKey } from '@/config/agentColors'
import { hexToRgba } from '@/utils/colorUtils'
import { isOrchestrator } from '@/utils/agentDisplay'
import AgentRow from '@/components/projects/AgentRow.vue'
import AgentDetailsModal from '@/components/projects/AgentDetailsModal.vue'
import AgentJobModal from '@/components/projects/AgentJobModal.vue'
import HandoverModal from '@/components/projects/HandoverModal.vue'
import MessageComposer from '@/components/projects/MessageComposer.vue'
import ExecutionOrderBar from '@/components/projects/ExecutionOrderBar.vue'

const props = defineProps({
  project: {
    type: Object,
    required: true,
    validator: (value) => {
      return (
        value &&
        typeof value === 'object' &&
        ('project_id' in value || 'id' in value) &&
        'name' in value
      )
    },
  },
  chainCtx: {
    type: Object,
    default: null,
  },
})
const { copy: clipboardCopy } = useClipboard()
const projectStateStore = useProjectStateStore()
const notificationStore = useNotificationStore()
const { sortedJobs: sortedAgents, loadJobs, store: agentJobsStore } = useAgentJobs()

const projectId = computed(() => props.project?.project_id || props.project?.id)

const {
  showAgentDetailsModal,
  showAgentJobModal,
  showHandoverModal,
  handoverData,
  jobModalInitialTab,
  selectedAgent,
  handleMessages,
  handleStepsClick,
  handleAgentRole,
  handleAgentJob,
  handleHandOver,
  handleStopProject,
} = useJobActions((id) => agentJobsStore.getJob(id))

const {
  shouldShowCopyButton,
  isPlayButtonFaded,
  playButtonTooltip,
  reactivatePlay,
  handlePlay,
} = usePlayButton(
  computed(() => props.project),
  (pid) => projectStateStore.getProjectState(pid),
  clipboardCopy,
  computed(() => props.chainCtx)
)

const isSubagentMode = computed(() => {
  const state = projectStateStore.getProjectState(projectId.value)
  const executionMode = state?.execution_mode ?? props.project?.execution_mode
  return isSubagentExecutionMode(executionMode)
})

const executionOrderPhases = computed(() => {
  const state = projectStateStore.getProjectState(projectId.value)
  const executionMode = state?.execution_mode ?? props.project?.execution_mode
  if (isSubagentExecutionMode(executionMode)) return null

  const agentList = sortedAgents.value
  if (!agentList.some(a => a.phase != null)) return null

  const groups = {}
  for (const agent of agentList) {
    if (isOrchestrator(agent)) continue
    const phase = agent.phase ?? 999
    if (!groups[phase]) groups[phase] = []
    const agentColor = getAgentColorConfig(getAgentColorKey(agent)).hex
    groups[phase].push({
      displayName: agent.agent_display_name || agent.agent_name || 'unknown',
      color: agentColor,
      tintedBg: hexToRgba(agentColor, 0.15),
    })
  }

  const phases = [{
    label: 'Start',
    agents: [{
      displayName: 'Orchestrator',
      color: getAgentColorConfig('orchestrator').hex,
      tintedBg: hexToRgba(getAgentColorConfig('orchestrator').hex, 0.15),
    }],
  }]

  Object.keys(groups)
    .map(Number)
    .sort((a, b) => a - b)
    .forEach(phase => {
      const isParallel = groups[phase].length > 1
      const phaseNum = phase === 999 ? '?' : phase
      const label = isParallel ? `Phase ${phaseNum} Parallel Execution` : `Phase ${phaseNum}`
      phases.push({ label, agents: groups[phase] })
    })

  return phases
})

const phaseSortedAgents = computed(() => {
  const openProjectId = projectId.value
  const agents = sortedAgents.value.filter((a) => {
    if (a.chain_conductor === true) return false
    if (a.project_id == null || String(a.project_id) !== String(openProjectId)) return false
    return true
  })
  return agents.sort((a, b) => {
    const phaseA = isOrchestrator(a) ? -1 : (a.phase ?? 999)
    const phaseB = isOrchestrator(b) ? -1 : (b.phase ?? 999)
    if (phaseA !== phaseB) return phaseA - phaseB
    return 0
  })
})

const orchestratorAgentId = computed(() => phaseSortedAgents.value.find(isOrchestrator)?.agent_id || '')

const now = ref(Date.now())
let durationTickerId = null

const loadingJobs = ref(false)

async function refreshJobs() {
  if (!projectId.value) return
  if (loadingJobs.value) return

  loadingJobs.value = true
  try {
    await loadJobs(projectId.value)
  } catch (error) {
    console.warn('[JobsTab] Failed to load agent jobs:', error)
    notifyFailure(notificationStore, {
      operation: 'jobs.load',
      entityId: projectId.value || 'none',
      error,
      fallbackMessage: 'Failed to load agent jobs. Refresh the page or try again.',
      title: 'Agent jobs unavailable',
    })
  } finally {
    loadingJobs.value = false
  }
}

watch(projectId, () => { refreshJobs() }, { immediate: true })

onMounted(() => {
  durationTickerId = setInterval(() => { now.value = Date.now() }, 1000)
})

onUnmounted(() => {
  if (durationTickerId) { clearInterval(durationTickerId); durationTickerId = null }
})
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.implement-tab-wrapper {
  padding: 16px;

  .table-container {
    background: $elevation-raised;
    border-radius: $border-radius-rounded;
    margin-bottom: 16px;
    overflow: hidden;

    // 0873: transparent table bg so smooth-border inset shadow shows on all sides
    .agents-table,
    :deep(.v-table) {
      background: transparent;
    }

    .agents-table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;

      thead th {
        text-align: left;
        padding: 10px 14px;
        @include table-header-label;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        background: $elevation-raised;
        white-space: nowrap;

        &.col-phase {
          width: 56px;
          text-align: center;
        }

        &.col-play {
          width: 40px;
          padding: 0;
        }

        &.col-agent-name {
          width: 1%;
          white-space: nowrap;
        }

        &.col-center {
          text-align: center;
        }

        &.col-actions {
          width: 160px;
        }
      }

      tbody tr {
        transition: background $transition-fast;
        cursor: pointer;

        &:hover {
          background: rgba(255, 255, 255, 0.02);
        }
      }
    }
  }

  /* Responsive: tablet band and below — thead th.col-agent-name alignment.
     FE-9536: harmonized from a bespoke 840px onto the shared tablet token
     (ProjectsTable's compact-table step uses $breakpoint-compact = 1280px;
     this one is about a single header's text-align, not column hiding, so
     it stays on the narrower tablet band). */
  @media (max-width: $breakpoint-tablet) {
    .table-container .agents-table {
      thead th.col-agent-name {
        text-align: center;
      }
    }
  }

  /* Responsive: portrait / narrow screens — thead th.hide-mobile.
     FE-9536: harmonized from a bespoke 768px onto $breakpoint-mobile (600px),
     the SAME token ProjectsTable's .project-id-text hide already uses -- two
     conceptually similar "hide on a small screen" column drops now agree. */
  /* DUPLICATED in AgentRow for td.hide-mobile */
  @media (max-width: $breakpoint-mobile) {
    .table-container .agents-table {
      .hide-mobile {
        display: none;
      }
    }
  }
}
</style>
