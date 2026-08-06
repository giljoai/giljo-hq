<template>
  <v-container class="project-tabs-container">
    <!-- Project Header (static, no scroll) -->
    <div class="project-header">
      <h1 class="text-headline-large project-title-row">
        Project:
        <!-- Series Chip (Handover 0440c) -->
        <v-chip
          v-if="localProject?.project_type_id || localProject?.series_number"
          :color="resolveTaxonomyColor({
            abbreviation: localProject?.project_type?.abbreviation,
            alias: localProject?.taxonomy_alias,
            color: localProject?.project_type?.color,
          })"
          size="small"
          variant="flat"
          class="project-badge mx-2"
          :title="isReservedTaskAlias(localProject?.taxonomy_alias)
            ? 'Converted from task'
            : (localProject?.project_type?.label || 'Untyped')"
        >
          {{ localProject.taxonomy_alias }}
        </v-chip>
        <v-tooltip v-if="localProject?.name && localProject.name.length > 40" location="bottom">
          <template #activator="{ props: tooltipProps }">
            <span v-bind="tooltipProps" class="project-name-text project-name-text--truncated" tabindex="0">
              {{ localProject.name.slice(0, 40) + '...' }}
            </span>
          </template>
          <span>{{ localProject.name }}</span>
        </v-tooltip>
        <span v-else class="project-name-text">{{ localProject?.name || 'Loading...' }}</span>
      </h1>
      <!-- FE-6174b: chain mode replaces the project-id line with the N/M counter +
           "Multi project mode" indicator (no project id in the title). Solo keeps
           the project-id line unchanged. -->
      <ChainModeBar v-if="chainCtx" :counter="chainCtx.counter" class="mb-0" />
      <p v-else class="text-body-medium project-id mb-0">
        Project ID: {{ localProject?.project_id || localProject?.id || 'N/A' }}
      </p>
    </div>

    <!-- FE-6174b: chain project tab strip (one active project at a time). Shown in
         both Staging + Implementation. Conditional layer only. -->
    <ProjectTabStrip
      v-if="chainCtx"
      :tabs="chainCtx.tabs"
      :active-pid="projectId"
      @select="handleTabSelect"
    />

    <!-- Tab Pills -->
    <div class="tab-pills">
      <button
        class="pill-btn smooth-border"
        :class="{ active: activeTab === 'launch' }"
        data-testid="launch-tab"
        @click="setActiveTab('launch')"
      >
        <v-icon size="18">mdi-rocket-launch-outline</v-icon>
        Staging
      </button>
      <button
        class="pill-btn smooth-border"
        :class="{ active: activeTab === 'jobs' }"
        data-testid="jobs-tab"
        @click="setActiveTab('jobs')"
      >
        <v-icon size="18">mdi-code-braces</v-icon>
        Implementation
      </button>
    </div>

    <!-- Execution Mode + Action Buttons (Launch tab only) -->
    <div v-if="activeTab === 'launch'" class="execution-mode-row">
      <!-- FE-6174b: in a chain the selector reflects the run's mode and locks from
           run.locked; onModeChange dispatches to the run instead of the project.
           Solo bindings are unchanged (byte-identical). -->
      <ExecutionModeSelector
        :execution-platform="chainCtx ? (chainCtx.run.execution_mode || null) : executionPlatform"
        :is-execution-mode-locked="chainCtx ? chainCtx.locked : isExecutionModeLocked"
        @change="onModeChange"
      />
      <!-- TSK-9038: read-only "detected: <harness>" chip, solo only -- chain runs
           have no per-project MCP session to read a resolved_harness from. -->
      <HarnessChip v-if="!chainCtx" :harness="orchestrator?.detected_harness" />
    </div>

    <div v-if="activeTab === 'launch'" class="action-buttons-row">
      <!-- FE-6174b: chain Stage Chain / Implement, styled exactly like solo. -->
      <template v-if="chainCtx">
        <v-btn
          class="stage-button"
          variant="outlined"
          :color="chainStageColor"
          :loading="chainStaging"
          :disabled="chainStageDisabled"
          :title="chainStageTitle"
          data-testid="stage-chain-btn"
          @click="handleChainStage"
        >
          {{ chainStageText }}
        </v-btn>

        <v-btn
          class="launch-button"
          :disabled="!chainImplementReady"
          :color="chainImplementReady ? 'yellow-darken-2' : undefined"
          :variant="chainImplementReady ? 'flat' : 'outlined'"
          data-testid="implement-chain-btn"
          @click="handleChainImplement"
        >
          Implement
        </v-btn>
      </template>

      <template v-else>
        <v-btn
          class="stage-button"
          variant="outlined"
          :color="stageButtonColor"
          :loading="loadingStageProject"
          :disabled="stageButtonDisabled"
          :title="stageButtonTitle"
          data-testid="stage-project-btn"
          @click="handleStageOrRestage"
        >
          {{ stageButtonText }}
        </v-btn>

        <v-btn
          class="launch-button"
          :disabled="!executionModeSelected || !readyToLaunch"
          :color="executionModeSelected && readyToLaunch ? 'yellow-darken-2' : undefined"
          :variant="executionModeSelected && readyToLaunch ? 'flat' : 'outlined'"
          data-testid="launch-jobs-btn"
          @click="handleLaunchJobs"
        >
          Implement
        </v-btn>
      </template>
    </div>

    <!-- Project Status Area (Jobs tab only) — all banner states via child -->
    <ProjectStatusBanner
      v-if="activeTab === 'jobs'"
      :project-done-status="chainAwareProjectDoneStatus"
      :orchestrator-closeout-blocked="orchestratorCloseoutBlocked"
      :show-orch-unlocked-banner="showOrchUnlockedBanner"
      :show-closeout-button="chainAwareShowCloseoutButton"
      :show-memory-pending="showMemoryPending"
      :all-jobs-terminal="allJobsTerminal"
      :memory-poll-timed-out="memoryPollTimedOut"
      :memory-poll-error="memoryPollError"
      :is-chain-member="Boolean(chainCtx)"
      @open-decision-modal="openDecisionModal"
      @dismiss-orch-unlocked="showOrchUnlockedBanner = false"
      @open-closeout-modal="onReviewProjectClick"
      @retry-memory-poll="retryMemoryPoll"
      @dismiss-memory-poll-error="dismissMemoryPollError"
    />

    <!-- FE-6174b/6199: overarching mission window + conductor card (staging only). -->
    <ChainStagingHeader v-if="chainCtx && activeTab === 'launch'" :chain-ctx="chainCtx" />

    <!-- Tab Content (flat, no v-window wrapper — Handover 0875) -->
    <LaunchTab
      v-if="activeTab === 'launch'"
      :project="projectWithUpdatedMode"
      :orchestrator="orchestrator"
      :is-staging="loadingStageProject"
      :git-enabled="gitEnabled"
      :serena-enabled="serenaEnabled"
      :integrations-resolved="integrationsResolved"
      :agentic-tool="agenticTool"
      @edit-description="emit('edit-description')"
    />

    <JobsTab
      v-else-if="activeTab === 'jobs'"
      :project="projectWithUpdatedMode"
      :chain-ctx="chainCtx"
    />

    <!-- Project Closeout Modal (Handover 0361) -->
    <CloseoutModal
      :show="showCloseoutModal"
      :project-id="localProject.project_id || localProject.id"
      :project-name="localProject.name"
      :product-id="localProject.product_id"
      :project-status="localProject.status"
      :orchestrator-closeout-blocked="orchestratorCloseoutBlocked"
      :orchestrator-job-id="orchestratorJobId"
      @close="showCloseoutModal = false"
      @closeout="handleCloseoutComplete"
    />

    <!-- HITL Decision Modal — pre-decision only. Hosts ApprovalCard. -->
    <DecisionModal
      :show="showDecisionModal"
      :orchestrator-job-id="orchestratorJobId"
      @close="showDecisionModal = false"
      @approval-decided="handleApprovalDecided"
    />

    <!-- FE-6174b: per-tab chain Review reuses the existing CloseoutModal (async;
         does NOT pause the chain). Pass the member's real chain status so the modal
         can skip the archive call when the conductor already completed it (#7 fix). -->
    <CloseoutModal
      v-if="chainCtx && chainReviewTab"
      :show="showChainReview"
      :project-id="chainReviewTab.projectId"
      :project-name="chainReviewTab.name"
      :product-id="chainReviewTab.productId || localProject.product_id"
      :project-status="chainReviewTab.status || 'active'"
      suppress-navigation
      @close="showChainReview = false"
      @closeout="handleChainReviewComplete"
    />
  </v-container>
</template>

<script setup>
import { ref, computed, watch, watchEffect, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAgentJobs } from '@/composables/useAgentJobs'
import { useProjectStore } from '@/stores/projects'
import { useProjectStateStore } from '@/stores/projectStateStore'
import { useIntegrationStatus } from '@/composables/useIntegrationStatus'
import { isAwaitingUser } from '@/utils/statusConfig'
import { useProjectCloseout } from '@/composables/useProjectCloseout'
import { useExecutionMode } from '@/composables/useExecutionMode'
import { useProjectStaging } from '@/composables/useProjectStaging'
import { useProjectTabsLifecycle } from '@/composables/useProjectTabsLifecycle'
import { useChainTabControls } from '@/composables/useChainTabControls'
import { useChainAutoNav } from '@/composables/useChainAutoNav'
import LaunchTab from './LaunchTab.vue'
import JobsTab from './JobsTab.vue'
import CloseoutModal from '@/components/orchestration/CloseoutModal.vue'
import DecisionModal from '@/components/orchestration/DecisionModal.vue'
import ExecutionModeSelector from './project-tabs/ExecutionModeSelector.vue'
import HarnessChip from './project-tabs/HarnessChip.vue'
import ProjectStatusBanner from './project-tabs/ProjectStatusBanner.vue'
import ChainModeBar from './chain/ChainModeBar.vue'
import ProjectTabStrip from './chain/ProjectTabStrip.vue'
import ChainStagingHeader from './chain/ChainStagingHeader.vue'
import { resolveTaxonomyColor, isReservedTaskAlias } from '@/utils/taxonomyBadge'
import { buildChainAwareShowCloseout, buildReviewDispatcher, buildChainAwareProjectDoneStatus } from './reviewDispatch.js'

/**
 * Props
 */
const props = defineProps({
  project: {
    type: Object,
    required: true,
  },
  orchestrator: {
    type: Object,
    default: null,
  },
  /**
   * FE-6174b: chain context bundle (from useChainContext), or null in solo. When
   * null EVERY chain affordance is v-if'd out and the view renders the
   * byte-identical solo path (the deletion test). Never mutate it here — writes
   * flow through useChainLifecycle / sequenceRunStore and sync back via the store.
   */
  chainCtx: {
    type: Object,
    default: null,
  },
})

/**
 * Emits
 */
const emit = defineEmits([
  'edit-description',
  'project-updated',
])

/**
 * Store and Router
 */
const route = useRoute()
const router = useRouter()

const projectStore = useProjectStore()
const projectStateStore = useProjectStateStore()
const { sortedJobs } = useAgentJobs()

// Integration status for LaunchTab (Handover 0427)
// TSK-9234: `resolved` is load-bearing, do not drop it. gitEnabled/serenaEnabled
// default to false, so without it LaunchTab renders both integration icons in
// their disabled treatment -- tooltip "click to enable" -- before anything has
// been read. `resolved` also stays false when the fetch ERRORED, which keeps a
// fully-configured box from being told its integrations are off during a
// transient outage. Same class as the FE-9233 nudge, milder surface.
const {
  gitEnabled,
  serenaEnabled,
  resolved: integrationsResolved,
} = useIntegrationStatus()

// FE-3007a: store-backed computed — single source of truth via projectStore, falls back to prop while first fetch is in-flight.
const projectId = computed(() => props.project?.project_id || props.project?.id || null)

const currentChainTab = computed(() => (props.chainCtx?.tabs || []).find((t) => t.projectId === projectId.value) || null)

const localProject = computed(
  () => (projectId.value && projectStore.projectById(projectId.value)) || props.project || {},
)

// Mission text from project state store (needed for execution-mode lock check)
const missionText = computed(
  () => projectStateStore.getProjectState(projectId.value)?.mission || '',
)

// Computed: project is in 'staged' state
const isProjectStaged = computed(() => {
  const state = projectStateStore.getProjectState(projectId.value)
  return Boolean(state?.isStaged)
})

// Computed: project is in 'staging' state
const isProjectStaging = computed(() => {
  const state = projectStateStore.getProjectState(projectId.value)
  return Boolean(state?.isStaging)
})

// Execution mode management via composable (Handover 0428 / FE-6006)
const {
  executionPlatform,
  executionMode,
  executionModeSelected,
  isExecutionModeLocked,
  agenticTool,
  handleExecutionModeChange,
} = useExecutionMode({
  projectId,
  missionText,
  isProjectStaged,
  isProjectStaging,
  initialMode: props.project?.execution_mode || null,
})

/**
 * Local state - Tab activation (Handover 0243e)
 */
const activeTab = ref('launch')

// Initialize from URL query param if present
if (route.query.tab && ['launch', 'jobs'].includes(route.query.tab)) {
  activeTab.value = route.query.tab
}

// Auto-select Implementation tab for active staged projects arriving via jobs link
if (route.query.via === 'jobs' && !route.query.tab) {
  const stop = watchEffect(() => {
    const state = projectStateStore.getProjectState(projectId.value)
    if (props.project?.status === 'active' && state?.stagingComplete) {
      activeTab.value = 'jobs'
      nextTick(() => stop())
    }
  })
}

/**
 * Sync URL when tab changes
 */
watch(activeTab, (newTab) => {
  if (route.query.tab !== newTab) {
    router.replace({
      query: { ...route.query, tab: newTab },
      hash: route.hash
    })
  }
})

/**
 * Computed: Project is ready to launch (staging complete, not still staging)
 */
const readyToLaunch = computed(() => {
  const state = projectStateStore.getProjectState(projectId.value)
  return Boolean(state?.stagingComplete && !state?.isStaging)
})

/**
 * BE-6047: Recovery affordance — staging_complete but implementation NOT yet launched.
 * When true, the stage button should offer "Re-Stage" (restage verb) instead of Stage/Unstage.
 */
const canRestage = computed(() => {
  const state = projectStateStore.getProjectState(projectId.value)
  return Boolean(state?.stagingComplete && !state?.implementationLaunched && !state?.isStaging)
})

/**
 * Staging + launch logic via composable (FE-6006)
 * BE-6047: canRestage threads the recovery affordance into the composable
 */
const {
  loadingStageProject,
  handleStageOrRestage,
  handleLaunchJobs: _handleLaunchJobsBase,
  onLaunchSuccess,
} = useProjectStaging({
  projectId,
  executionMode,
  isProjectStaged,
  readyToLaunch,
  canRestage,
})

// Wire up the post-launch tab switch + route update
onLaunchSuccess(() => {
  activeTab.value = 'jobs'
  if (route.query.via !== 'jobs') {
    router.replace({ query: { ...route.query, via: 'jobs' } })
  }
})

function handleLaunchJobs() {
  return _handleLaunchJobsBase(props.project)
}

// FE-6174b: chain controls (extracted to useChainTabControls, 800-line guardrail).
// All inert in solo. Reuses chain lifecycle + sequenceRunStore; no new writers.
const chainCtxRef = computed(() => props.chainCtx)

// FE-6218: live-follow auto-nav for a HEADLESS chain drive. Adds an event-driven
// pane flip OVER the existing user-click flips (handleChainImplement / onLaunchSuccess),
// never replacing them. markUserAction() feeds its anti-hijack guard from the
// user-action seams below (tab pills + chain tab-select + Implement). Inert in solo.
const { markUserAction } = useChainAutoNav({ chainCtx: chainCtxRef, projectId, activeTab, router, route })

// User tab-switch seam (anti-hijack): a manual tab pick opens the suppression
// window so the WS echo of the user's own drive does not yank the pane back.
function setActiveTab(tab) {
  markUserAction()
  activeTab.value = tab
}

const {
  chainStaging,
  showChainReview,
  chainReviewTab,
  chainStageText,
  chainStageDisabled,
  chainStageColor,
  chainStageTitle,
  chainImplementReady,
  patchRunMode,
  handleChainStage,
  handleChainImplement,
  handleTabSelect,
  handleTabReview,
  handleChainReviewComplete,
} = useChainTabControls({ chainCtx: chainCtxRef, projectId, router, route, activeTab, onUserNav: markUserAction })

// Dispatch execution-mode changes: chain → patch the run; solo → existing path.
function onModeChange(mode) {
  if (props.chainCtx) {
    patchRunMode(mode)
    return
  }
  handleExecutionModeChange(mode)
}

/**
 * Local state
 */
const showDecisionModal = ref(false)
const showOrchUnlockedBanner = ref(false)

function openDecisionModal() {
  showDecisionModal.value = true
}

function handleApprovalDecided() {
  showDecisionModal.value = false
  showOrchUnlockedBanner.value = true
}

// FE-6174c: chain → handleTabReview (suppress-nav path); solo → openCloseoutModal.
function onReviewProjectClick() {
  buildReviewDispatcher(props.chainCtx, currentChainTab.value, handleTabReview, openCloseoutModal)()
}

/**
 * Computed: Project with updated execution_mode (Handover 0404)
 */
const projectWithUpdatedMode = computed(() => ({
  ...localProject.value,
  execution_mode: executionMode.value,
}))

const {
  showCloseoutModal,
  memoryWritten,
  memoryPollTimedOut,
  memoryPollError,
  projectDoneStatus,
  allJobsTerminal,
  showCloseoutButton,
  showMemoryPending,
  openCloseoutModal,
  handleCloseoutComplete,
  retryMemoryPoll,
  dismissMemoryPollError,
  reset: resetCloseout,
  cleanup: cleanupCloseout,
} = useProjectCloseout({
  project: localProject,
  projectId,
  sortedJobs,
  onComplete: () => emit('project-updated'),
})

// Auto-clear the unlocked banner when all jobs go terminal or project closes
watch([allJobsTerminal, projectDoneStatus], ([allTerminal, doneStatus]) => {
  if (allTerminal || doneStatus) showOrchUnlockedBanner.value = false
})

// Auto-clear once orchestrator drains its inbox
const orchMessagesWaiting = computed(() => {
  const orch = (sortedJobs.value || []).find((j) => j.agent_display_name === 'orchestrator')
  return orch?.messages_waiting_count ?? 0
})
watch(orchMessagesWaiting, (newCount, oldCount) => {
  if (showOrchUnlockedBanner.value && oldCount > 0 && newCount === 0) {
    showOrchUnlockedBanner.value = false
  }
})

// FE-6174c: show when viewed member needsReview (chain) or showCloseoutButton (solo).
const chainAwareShowCloseoutButton = computed(() => buildChainAwareShowCloseout(props.chainCtx, currentChainTab.value, showCloseoutButton.value))

// Chain: show green chip once reviewed (!needsReview); suppress while review pending; solo: unchanged.
const chainAwareProjectDoneStatus = computed(() => buildChainAwareProjectDoneStatus(props.chainCtx, currentChainTab.value, projectDoneStatus.value))

/**
 * Computed: Orchestrator is in closeout-blocked state (HITL Closeout Checkpoint).
 */
const orchestratorCloseoutBlocked = computed(() => {
  const jobs = sortedJobs.value || []
  const orch = jobs.find((j) => j.agent_display_name === 'orchestrator')
  return orch ? isAwaitingUser(orch.status) : false
})

/**
 * FE-5017 Phase C: orchestrator job_id used by CloseoutModal.
 */
const orchestratorJobId = computed(() => {
  const jobs = sortedJobs.value || []
  const orch = jobs.find((j) => j.agent_display_name === 'orchestrator')
  return orch?.job_id || null
})

/**
 * Computed: Check if orchestrator is already active
 */
const hasActiveOrchestrator = computed(() => {
  const state = projectStateStore.getProjectState(projectId.value)
  return Boolean(state?.stagingComplete)
})

/**
 * Computed: Stage button text lifecycle
 * BE-6047: staging_complete without implementation launched → "Re-Stage" recovery
 */
const stageButtonText = computed(() => {
  if (isProjectStaging.value) return 'Staging...'
  if (isProjectStaged.value) return 'Unstage'
  if (canRestage.value) return 'Re-Stage'
  return 'Stage Project'
})

/**
 * Computed: Stage button disabled state
 * BE-6047: staging_complete+implementationLaunched → button disabled (no recovery possible after Implement)
 */
const stageButtonDisabled = computed(() => {
  if (isProjectStaging.value) return true
  if (isProjectStaged.value) return false
  // staging_complete: enable Re-Stage only if implementation has NOT launched
  const state = projectStateStore.getProjectState(projectId.value)
  if (state?.stagingComplete && state?.implementationLaunched) return true
  if (canRestage.value) return false
  return !executionModeSelected.value || hasActiveOrchestrator.value
})

/**
 * Computed: Stage button color
 * BE-6047: Re-Stage uses warning-adjacent color to signal recovery action
 */
const stageButtonColor = computed(() => {
  if (isProjectStaged.value) return undefined
  if (canRestage.value) return 'warning'
  if (executionModeSelected.value && !hasActiveOrchestrator.value) return 'yellow-darken-2'
  return undefined
})

/**
 * Computed: Stage button title/tooltip
 */
const stageButtonTitle = computed(() => {
  if (isProjectStaging.value) return 'Staging is in progress — agent is working'
  if (isProjectStaged.value) return 'Revert to ready state (before agent makes contact)'
  const state = projectStateStore.getProjectState(projectId.value)
  if (state?.stagingComplete && state?.implementationLaunched) {
    return 'Cannot recover — implementation has already launched'
  }
  if (canRestage.value) return 'Reset staging so you can change execution mode and stage again'
  if (!executionModeSelected.value) return 'Select an execution mode first'
  if (hasActiveOrchestrator.value) return 'An orchestrator is already active for this project'
  return 'Generate orchestrator prompt'
})

useProjectTabsLifecycle({
  projectId,
  executionMode,
  executionPlatform,
  missionText,
  isProjectStaged,
  isProjectStaging,
  memoryWritten,
  resetCloseout,
  cleanupCloseout,
  getProject: () => props.project,
})

</script>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;
@use '@/styles/agent-colors.scss' as *;
@use '@/styles/design-tokens.scss' as *;

.project-tabs-container {
  background: rgb(var(--v-theme-background));
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden; /* Page doesn't scroll - only individual panels do */
}

/* Project Header - Title and ID (matches Products page pattern) */
.project-header {
  margin-bottom: 16px;
  flex-shrink: 0;

  .project-title-row {
    display: flex;
    align-items: center;
    gap: 4px;
    margin: 0;
  }

  .project-name-text {
    color: rgb(var(--v-theme-primary));
  }

  .project-name-text--truncated {
    cursor: help;
  }

  .project-badge {
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .project-id {
    color: var(--text-muted);
  }
}

/* Tab Pills */
.tab-pills {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-shrink: 0;
}

/* Shared pill button style */
.pill-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: $border-radius-pill;
  padding: 8px 18px;
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  transition: $transition-all-fast;
  background: transparent;
  color: var(--text-muted);
  border: none;
  --smooth-border-color: rgba(var(--v-theme-on-surface), 0.15);

  &:hover:not(:disabled) {
    color: var(--text-secondary);
    --smooth-border-color: rgba(var(--v-theme-on-surface), 0.25);
  }

  &.active,
  &.active:hover {
    background: rgba($color-brand-yellow, 0.12);
    color: $color-brand-yellow;
    box-shadow: none;
  }

  &:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
}

/* Action buttons row (centered) */
.action-buttons-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-shrink: 0;
}

/* Action buttons styling */
.stage-button {
  text-transform: none;
  font-weight: 500;
}

.launch-button {
  text-transform: none;
  font-weight: 500;
}

/* Execution mode row (centered) */
.execution-mode-row {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
}

/* Mobile / Portrait Responsive */
@media (max-width: 1024px) {
  .project-header .project-title-row {
    font-size: 1.2rem;
  }
}

@media (max-width: 600px) {
  .action-buttons-row {
    flex-wrap: wrap;
    gap: 8px;
  }
}
</style>
