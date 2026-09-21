<template>
  <v-container class="project-tabs-container">
    <div class="project-header">
      <h1 class="text-headline-large project-title-row">
        Project:
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
      <ChainModeBar
      v-if="chainCtx"
      :counter="chainCtx.counter"
      :mode="chainScreenControls.showModeLabel ? chainScreenControls.modeLabel : ''"
      class="mb-0"
    />
      <p v-else class="text-body-medium project-id mb-0">
        Project ID: {{ localProject?.project_id || localProject?.id || 'N/A' }}
      </p>
    </div>

    <ProjectTabStrip
      v-if="chainCtx"
      :tabs="chainCtx.tabs"
      :active-pid="projectId"
      @select="handleTabSelect"
    />

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
      <ChainStopControl
        v-if="chainScreenControls.showStopChain"
        :run="chainCtx?.run"
        :model-value="showChainStopConfirm"
        :stopping="chainStopping"
        @open="openChainStopConfirm"
        @confirm="handleChainStop"
        @cancel="cancelChainStop"
      />
    </div>

    <div v-if="activeTab === 'launch' && (!chainCtx || chainScreenControls.showModeSelector)" class="execution-mode-row">
      <ExecutionModeSelector
        :execution-platform="chainCtx ? (chainCtx.run.execution_mode || null) : executionPlatform"
        :is-execution-mode-locked="chainCtx ? chainCtx.locked : isExecutionModeLocked"
        @change="onModeChange"
      />
      <HarnessChip v-if="!chainCtx" :harness="orchestrator?.detected_harness" />
    </div>

    <div v-if="activeTab === 'launch'" class="action-buttons-row">
      <ChainStagingActions
        v-if="chainCtx && chainScreenControls.showStageButton"
        :stage-text="chainStageText"
        :stage-title="chainStageTitle"
        :stage-color="chainStageColor"
        :stage-disabled="chainStageDisabled"
        :staging="chainStaging"
        :implement-ready="chainImplementReady"
        @stage="handleChainStage"
        @implement="handleChainImplement"
      />

      <template v-if="!chainCtx">
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

    <ChainStagingHeader v-if="chainCtx && activeTab === 'launch'" :chain-ctx="chainCtx" />

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

    <DecisionModal
      :show="showDecisionModal"
      :orchestrator-job-id="orchestratorJobId"
      @close="showDecisionModal = false"
      @approval-decided="handleApprovalDecided"
    />

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
import ChainStopControl from './chain/ChainStopControl.vue'
import ChainStagingActions from './chain/ChainStagingActions.vue'
import { resolveTaxonomyColor, isReservedTaskAlias } from '@/utils/taxonomyBadge'
import { buildChainAwareShowCloseout, buildReviewDispatcher, buildChainAwareProjectDoneStatus } from './reviewDispatch.js'

const props = defineProps({
  project: {
    type: Object,
    required: true,
  },
  orchestrator: {
    type: Object,
    default: null,
  },
  chainCtx: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits([
  'edit-description',
  'project-updated',
])

const route = useRoute()
const router = useRouter()

const projectStore = useProjectStore()
const projectStateStore = useProjectStateStore()
const { sortedJobs } = useAgentJobs()

const {
  gitEnabled,
  serenaEnabled,
  resolved: integrationsResolved,
} = useIntegrationStatus()

const projectId = computed(() => props.project?.project_id || props.project?.id || null)

const currentChainTab = computed(() => (props.chainCtx?.tabs || []).find((t) => t.projectId === projectId.value) || null)

const localProject = computed(
  () => (projectId.value && projectStore.projectById(projectId.value)) || props.project || {},
)

const missionText = computed(
  () => projectStateStore.getProjectState(projectId.value)?.mission || '',
)

const isProjectStaged = computed(() => {
  const state = projectStateStore.getProjectState(projectId.value)
  return Boolean(state?.isStaged)
})

const isProjectStaging = computed(() => {
  const state = projectStateStore.getProjectState(projectId.value)
  return Boolean(state?.isStaging)
})

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

const activeTab = ref('launch')

if (route.query.tab && ['launch', 'jobs'].includes(route.query.tab)) {
  activeTab.value = route.query.tab
}

if (route.query.via === 'jobs' && !route.query.tab) {
  const stop = watchEffect(() => {
    const state = projectStateStore.getProjectState(projectId.value)
    if (props.project?.status === 'active' && state?.stagingComplete) {
      activeTab.value = 'jobs'
      nextTick(() => stop())
    }
  })
}

watch(activeTab, (newTab) => {
  if (route.query.tab !== newTab) {
    router.replace({
      query: { ...route.query, tab: newTab },
      hash: route.hash
    })
  }
})

const readyToLaunch = computed(() => {
  const state = projectStateStore.getProjectState(projectId.value)
  return Boolean(state?.stagingComplete && !state?.isStaging)
})

const canRestage = computed(() => {
  const state = projectStateStore.getProjectState(projectId.value)
  return Boolean(state?.stagingComplete && !state?.implementationLaunched && !state?.isStaging)
})

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

onLaunchSuccess(() => {
  activeTab.value = 'jobs'
  if (route.query.via !== 'jobs') {
    router.replace({ query: { ...route.query, via: 'jobs' } })
  }
})

function handleLaunchJobs() {
  return _handleLaunchJobsBase(props.project)
}

const chainCtxRef = computed(() => props.chainCtx)

const { markUserAction } = useChainAutoNav({ chainCtx: chainCtxRef, projectId, activeTab, router, route })

function setActiveTab(tab) {
  markUserAction()
  activeTab.value = tab
}

const {
  chainScreenControls,
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
  chainStopping,
  showChainStopConfirm,
  openChainStopConfirm,
  cancelChainStop,
  handleChainStop,
} = useChainTabControls({ chainCtx: chainCtxRef, projectId, router, route, activeTab, onUserNav: markUserAction })

function onModeChange(mode) {
  if (props.chainCtx) {
    patchRunMode(mode)
    return
  }
  handleExecutionModeChange(mode)
}

const showDecisionModal = ref(false)
const showOrchUnlockedBanner = ref(false)

function openDecisionModal() {
  showDecisionModal.value = true
}

if (route.query.decide === '1') {
  activeTab.value = 'jobs'
  openDecisionModal()
  const { decide: _decide, ...rest } = route.query
  router.replace({ query: rest })
}

function handleApprovalDecided() {
  showDecisionModal.value = false
  showOrchUnlockedBanner.value = true
}

function onReviewProjectClick() {
  buildReviewDispatcher(props.chainCtx, currentChainTab.value, handleTabReview, openCloseoutModal)()
}

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

if (route.query.review === '1') {
  activeTab.value = 'jobs'
  if (showCloseoutButton.value) openCloseoutModal()
  const { review: _review, ...rest } = route.query
  router.replace({ query: rest })
}

watch([allJobsTerminal, projectDoneStatus], ([allTerminal, doneStatus]) => {
  if (allTerminal || doneStatus) showOrchUnlockedBanner.value = false
})

const orchMessagesWaiting = computed(() => {
  const orch = (sortedJobs.value || []).find((j) => j.agent_display_name === 'orchestrator')
  return orch?.messages_waiting_count ?? 0
})
watch(orchMessagesWaiting, (newCount, oldCount) => {
  if (showOrchUnlockedBanner.value && oldCount > 0 && newCount === 0) {
    showOrchUnlockedBanner.value = false
  }
})

const chainAwareShowCloseoutButton = computed(() => buildChainAwareShowCloseout(props.chainCtx, currentChainTab.value, showCloseoutButton.value))

const chainAwareProjectDoneStatus = computed(() => buildChainAwareProjectDoneStatus(props.chainCtx, currentChainTab.value, projectDoneStatus.value))

const orchestratorCloseoutBlocked = computed(() => {
  const jobs = sortedJobs.value || []
  const orch = jobs.find((j) => j.agent_display_name === 'orchestrator')
  return orch ? isAwaitingUser(orch.status) : false
})

const orchestratorJobId = computed(() => {
  const jobs = sortedJobs.value || []
  const orch = jobs.find((j) => j.agent_display_name === 'orchestrator')
  return orch?.job_id || null
})

const hasActiveOrchestrator = computed(() => {
  const state = projectStateStore.getProjectState(projectId.value)
  return Boolean(state?.stagingComplete)
})

const stageButtonText = computed(() => {
  if (isProjectStaging.value) return 'Staging...'
  if (isProjectStaged.value) return 'Unstage'
  if (canRestage.value) return 'Re-Stage'
  return 'Stage Project'
})

const stageButtonDisabled = computed(() => {
  if (isProjectStaging.value) return true
  if (isProjectStaged.value) return false
  const state = projectStateStore.getProjectState(projectId.value)
  if (state?.stagingComplete && state?.implementationLaunched) return true
  if (canRestage.value) return false
  return !executionModeSelected.value || hasActiveOrchestrator.value
})

const stageButtonColor = computed(() => {
  if (isProjectStaged.value) return undefined
  if (canRestage.value) return 'warning'
  if (executionModeSelected.value && !hasActiveOrchestrator.value) return 'yellow-darken-2'
  return undefined
})

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
