<template>
  <div class="implement-tab-wrapper">
    <!-- Agent Table Container -->
    <div class="table-container smooth-border">
      <!-- Handover 0411a: Proposed execution order (multi-terminal mode) -->
      <ExecutionOrderBar
        v-if="executionOrderPhases"
        :phases="executionOrderPhases"
      />

      <!-- FE-9296b: the per-project auto check-in slider is retired. The cadence
           is an account-level Settings value now (Tools → Notifications); rows
           with slider-era auto_checkin_* values keep them as overrides. -->
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

    <!-- Message Composer (Bottom) — FE-6174b: in a chain the Orchestrator button
         reroutes to the conductor (master orchestrator); solo passes nothing.
         BE-9012d Part 1: sends via the Hub now (bus retired) — chain-run-id
         resolves the conductor's own coordination thread, orchestrator-agent-id
         addresses this project's own orchestrator. -->
    <MessageComposer
      :project-id="projectId"
      :chain-mode="!!chainCtx"
      :conductor-agent-id="chainCtx?.conductor?.agentId || ''"
      :chain-run-id="chainCtx?.runId || ''"
      :orchestrator-agent-id="orchestratorAgentId"
    />

    <!-- Agent Details Modal (GiljoAI face - shows role/template) -->
    <AgentDetailsModal
      v-model="showAgentDetailsModal"
      :agent="selectedAgent"
    />

    <!-- Agent Job Modal (Info button - shows assigned job/mission) - Handover 0423 -->
    <AgentJobModal
      :show="showAgentJobModal"
      :agent="selectedAgent"
      :initial-tab="jobModalInitialTab"
      @close="showAgentJobModal = false"
    />

    <!-- Handover Modal (Orchestrator session refresh) -->
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
import { useToast } from '@/composables/useToast'
import { useClipboard } from '@/composables/useClipboard'
import { useProjectStateStore } from '@/stores/projectStateStore'
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

/** JobsTab — Handover 0241 + 0243c + 0461d. Pure table layout with inline actions. */
const props = defineProps({
  /** Project object with project_id/id and name fields. */
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
  /** FE-6174b: chain context (null in solo). Drives the message-bar conductor
   *  reroute; everything else in the table is per-active-project, unchanged. */
  chainCtx: {
    type: Object,
    default: null,
  },
})

const { showToast } = useToast()
const { copy: clipboardCopy } = useClipboard()
const projectStateStore = useProjectStateStore()
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
  reactivatePlay,
  handlePlay,
} = usePlayButton(
  computed(() => props.project),
  (pid) => projectStateStore.getProjectState(pid),
  clipboardCopy
)

/** Subagent mode: all agents launched together by orchestrator (Handover 0875) */
const isSubagentMode = computed(() => {
  // FE-6019: WS-synced store is source of truth; prop is only the pre-hydration fallback.
  const state = projectStateStore.getProjectState(projectId.value)
  const executionMode = state?.execution_mode ?? props.project?.execution_mode
  // BE-9035c: fold rule lives once in useExecutionMode.js — anything that
  // isn't multi_terminal is subagent-style (covers 'subagent' + tolerated
  // legacy CLI tokens).
  return isSubagentExecutionMode(executionMode)
})

/** Handover 0411a: Proposed execution order phases for multi-terminal mode. */
const executionOrderPhases = computed(() => {
  // FE-6019: WS-synced store is source of truth; prop is only the pre-hydration fallback.
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

/**
 * CE-0029: phase sort only. The CE-0028b applyStagingHandoffStatusOverride
 * relabel is gone — CE-0029 Item 2 makes the backend pre-spawn an impl-phase
 * orchestrator execution at staging-end, so the latest orch exec is
 * genuinely `status='waiting'` immediately, with no UI fiction. The DB and
 * the displayed status now agree.
 */
const phaseSortedAgents = computed(() => {
  // BE-6200 (#6 follow-up): exclude the dedicated chain conductor from EVERY
  // project's agent lane. It gets its own ChainConductorCard. The filter keys
  // on the FLAT `chain_conductor` field the API now serializes — NOT on
  // job_metadata (never serialized + clobbered by the WS progress handler) and
  // NOT on project_id IS NULL (the conductor's pre-spawned impl-phase execution
  // carries a real project_id, which is exactly the row that leaked in).
  // Unconditional (not gated on chainCtx): a stale/mis-loaded chain context must
  // never let a conductor row render. Solo: no conductor exists → no-op.
  //
  // BE-6229 (belt-and-suspenders): the jobs store is GLOBAL (shared across
  // projects); only a project-scoped REST setJobs() reload self-cleans it. A
  // live WS event for a project-less conductor or a foreign project upserts into
  // that shared map and would render here. Drop any row whose project_id is null
  // or does not match the open project, so such a row can never leak into this
  // lane even if a future WS path forgets the chain_conductor flag.
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

/** BE-9012d Part 1: this project's own orchestrator agent_id, so the bottom
 *  composer can address a DIRECTED Hub post to it (the Hub addresses
 *  participants by agent_id, not by role — unlike the retired bus). */
const orchestratorAgentId = computed(() => phaseSortedAgents.value.find(isOrchestrator)?.agent_id || '')

// BE-5107: backend computes duration_seconds; FE ticks locally between WS events
// using working_started_at as the anchor so the cell doesn't freeze. For terminal
// statuses we trust the backend's frozen duration_seconds (completed_at-based).
// The single setInterval here drives all AgentRow duration cells via the :now prop.
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
    showToast({
      message: 'Failed to load agent jobs. Refresh the page or try again.',
      type: 'error',
      timeout: 5000,
    })
  } finally {
    loadingJobs.value = false
  }
}

watch(projectId, () => { refreshJobs() }, { immediate: true })

onMounted(() => {
  // FE-3007b: jobs are refetched on reconnect by the generalized resync
  // registry (useProjectTabsLifecycle registers the open-project resync, which
  // reloads agent jobs). JobsTab no longer needs its own onConnectionChange
  // listener — that was a redundant per-view reconnect path.
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

  /* Responsive: below 840px — thead th.col-agent-name alignment */
  @media (max-width: 840px) {
    .table-container .agents-table {
      thead th.col-agent-name {
        text-align: center;
      }
    }
  }

  /* Responsive: portrait / narrow screens — thead th.hide-mobile */
  /* DUPLICATED in AgentRow for td.hide-mobile */
  @media (max-width: 768px) {
    .table-container .agents-table {
      .hide-mobile {
        display: none;
      }
    }
  }
}
</style>
