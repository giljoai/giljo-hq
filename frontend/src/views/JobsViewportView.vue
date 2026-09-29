<template>
  <v-container class="jobs-board">
    <div v-if="loading" class="d-flex justify-center align-center" style="height: 60vh">
      <v-progress-circular indeterminate size="64" color="primary" />
    </div>

    <template v-else>
      <v-row class="align-center mb-4">
        <v-col>
          <h1 class="text-headline-large">Jobs</h1>
          <p class="text-body-medium text-muted-a11y mt-1">
            Every project in flight<template v-if="allProducts"> across <strong>{{ productGroupsTotal }} {{ productGroupsTotal === 1 ? 'product' : 'products' }}</strong>, grouped by product</template><span v-else-if="productName"> for <strong>{{ productName }}</strong></span>, and what its agents are doing right now.
          </p>
        </v-col>
      </v-row>

      <JobsBoardToolbar
        v-if="projects.length > 0 || chainRunIds.length > 0"
        :side="side"
        :side-counts="sideCounts"
        :filter="filter"
        :filter-options="filterOptions"
        :is-compact="isCompact"
        :count-note="countNote"
        @select-side="selectSide"
        @select-filter="(value) => (filter = value)"
        @select-density="setDensity"
      />

      <div
        v-if="projects.length === 0 && chainRunIds.length === 0"
        class="jb-empty"
        data-testid="jobs-board-empty"
      >
        <h2 class="text-headline-medium">{{ allProducts ? 'Nothing in flight' : 'Nothing in flight for this product' }}</h2>
        <p class="text-body-medium jb-empty-sub">Stage a project to see its agents here.</p>
        <v-btn color="primary" to="/projects">Go to Projects</v-btn>
      </div>

      <template v-if="allProducts">
        <JobsBoardProductGroup
          v-for="group in productGroups"
          :key="group.id"
          :group="group"
          :folded="groupFold.isFolded(group.id)"
          :side="side"
          @toggle="groupFold.toggle"
        >
          <ChainGroup
            v-for="runId in group.runIds"
            :key="runId"
            :run-id="runId"
            :agents-by-project="agentsByProject"
            :now="now"
            :headless-allowed="headlessAllowed"
            :density="density"
            :highlighted="runId === highlightedRunId"
            @open-detail="openDetail"
            @open-hub="openHub"
            @changed="fetchBoard"
            @agent-messages="(agent, project) => handleMessages(agent, project.id)"
            @agent-role="handleAgentRole"
            @agent-job="handleAgentJob"
            @edit-description="openEditDialog"
            @review="board.openReview"
            @steps="handleStepsClick"
            @agent-mission-edit="openMissionEdit"
          />
          <div v-if="filterGroup(group.projects).length" class="jb-grid" data-testid="jobs-board-grid">
            <JobsBoardCard
              v-for="project in filterGroup(group.projects)"
              :key="project.id"
              :project="project"
              :agents="agentsByProject[project.id] || []"
              :now="now"
              :headless-allowed="headlessAllowed"
              :density="density"
              :git-enabled="gitEnabled"
              :serena-enabled="serenaEnabled"
              :integrations-resolved="integrationsResolved"
              :data-arrival="project.id === arrivalProjectId ? 'true' : undefined"
              data-testid="jobs-board-card-wrap"
              @open-detail="openDetail"
              @open-hub="openHub"
              @changed="fetchBoard"
              @edit-description="openEditDialog"
              @review="board.openReview"
              @steps="handleStepsClick"
              @agent-mission-edit="openMissionEdit"
              @agent-messages="(agent, project) => handleMessages(agent, project.id)"
              @agent-role="handleAgentRole"
              @agent-job="handleAgentJob"
            />
          </div>
        </JobsBoardProductGroup>
      </template>

      <template v-else>
        <ChainGroup
          v-for="runId in sideChainRunIds"
          :key="runId"
          :run-id="runId"
          :agents-by-project="agentsByProject"
          :now="now"
          :headless-allowed="headlessAllowed"
          :density="density"
          :highlighted="runId === highlightedRunId"
          @open-detail="openDetail"
          @open-hub="openHub"
          @changed="fetchBoard"
          @agent-messages="(agent, project) => handleMessages(agent, project.id)"
          @agent-role="handleAgentRole"
          @agent-job="handleAgentJob"
          @edit-description="openEditDialog"
          @review="board.openReview"
          @steps="handleStepsClick"
          @agent-mission-edit="openMissionEdit"
        />

        <div v-if="filteredProjects.length" class="jb-grid" data-testid="jobs-board-grid">
          <JobsBoardCard
            v-for="project in filteredProjects"
            :key="project.id"
            :project="project"
            :agents="agentsByProject[project.id] || []"
            :now="now"
            :headless-allowed="headlessAllowed"
            :density="density"
            :git-enabled="gitEnabled"
            :serena-enabled="serenaEnabled"
            :integrations-resolved="integrationsResolved"
            :data-arrival="project.id === arrivalProjectId ? 'true' : undefined"
            data-testid="jobs-board-card-wrap"
            @open-detail="openDetail"
            @open-hub="openHub"
            @changed="fetchBoard"
            @edit-description="openEditDialog"
            @review="board.openReview"
            @steps="handleStepsClick"
            @agent-mission-edit="openMissionEdit"
            @agent-messages="(agent, project) => handleMessages(agent, project.id)"
            @agent-role="handleAgentRole"
            @agent-job="handleAgentJob"
          />
        </div>
      </template>
    </template>

    <div v-if="editingProject" data-testid="jobs-board-edit-dialog">
      <ProjectCreateEditDialog
        ref="editDialogRef"
        v-model="editDialogOpen"
        :editing-project="editingProject"
        :active-product="productStore.currentProduct || productStore.activeProduct"
        :project-types="projectTypes"
        @saved="onEditSaved"
        @clear-mission="clearMissionOpen = true"
        @update:model-value="(open) => !open && (editingProject = null)"
      />
    </div>
    <BaseDialog
      v-model="clearMissionOpen"
      type="warning"
      title="Clear Mission?"
      confirm-label="Clear"
      size="sm"
      data-testid="jobs-board-clear-mission-dialog"
      @confirm="onClearMissionConfirmed"
      @cancel="clearMissionOpen = false"
    >
      <p>Clear the mission? It will be regenerated on next staging.</p>
    </BaseDialog>

    <JobsBoardDetailModal
      v-model="detailModalOpen"
      :project="detailProject"
      :agents="detailProject ? agentsByProject[detailProject.id] || [] : []"
      :now="now"
      :chain-ctx="detailProject ? chainCtxFor(detailProject.id) : null"
      :banner="detailProject && board.focusProject === detailProject ? board.banner : null"
      @open-closeout="board.openReview(detailProject)"
      @open-decision="board.openDecision(detailProject)"
      @dismiss-orch-unlocked="board.showOrchUnlockedBanner = false"
      @retry-memory-poll="board.retryMemoryPoll"
      @close-without-summary="board.closeWithoutSummary"
    />

    <CloseoutModal
      v-if="board.focusProject"
      :show="board.showCloseoutModal"
      :project-id="board.focusProject.id"
      :project-name="board.focusProject.name"
      :product-id="board.focusProject.product_id"
      :project-status="board.focusProject.status"
      :orchestrator-closeout-blocked="board.orchestratorCloseoutBlocked"
      :orchestrator-job-id="board.orchestratorJobId"
      suppress-navigation
      @close="board.showCloseoutModal = false"
      @closeout="board.handleCloseoutComplete"
    />
    <DecisionModal
      v-if="board.focusProject"
      :show="board.showDecisionModal"
      :orchestrator-job-id="board.orchestratorJobId"
      @close="board.showDecisionModal = false"
      @approval-decided="board.onApprovalDecided"
    />

    <AgentMissionEditModal
      v-if="missionEditAgent"
      v-model="missionEditOpen"
      :agent="missionEditAgent"
      @mission-updated="onMissionUpdated"
    />

    <AgentDetailsModal v-if="selectedAgent" v-model="showAgentDetailsModal" :agent="selectedAgent" />
    <AgentJobModal
      v-if="selectedAgent"
      :show="showAgentJobModal"
      :agent="selectedAgent"
      :initial-tab="jobModalInitialTab"
      @close="showAgentJobModal = false"
    />
  </v-container>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/projects'
import { useProductStore } from '@/stores/products'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { registerReconnectResync } from '@/stores/websocketEventRouter'
import { api } from '@/services/api'
import { jobsSectionLabelFor, JOBS_SECTION_LABELS } from '@/utils/jobsSectionLabel'
import { extractJobsFromResponse } from '@/composables/useAgentJobs'
import { useJobActions } from '@/composables/useJobActions'
import { useBoardDensity } from '@/composables/useBoardDensity'
import JobsBoardCard from '@/components/projects/JobsBoardCard.vue'
import JobsBoardDetailModal from '@/components/projects/JobsBoardDetailModal.vue'
import ChainGroup from '@/components/projects/chain/ChainGroup.vue'
import ProjectCreateEditDialog from '@/components/projects/ProjectCreateEditDialog.vue'
import JobsBoardProductGroup from '@/components/projects/JobsBoardProductGroup.vue'
import JobsBoardToolbar from '@/components/projects/JobsBoardToolbar.vue'
import { useJobsScopeStore } from '@/stores/jobsScope'
import { groupBoardByProduct } from '@/utils/jobsBoardProductGroups'
import { useFoldSet } from '@/composables/useFoldSet'
import AgentDetailsModal from '@/components/projects/AgentDetailsModal.vue'
import AgentJobModal from '@/components/projects/AgentJobModal.vue'
import AgentMissionEditModal from '@/components/projects/AgentMissionEditModal.vue'
import CloseoutModal from '@/components/orchestration/CloseoutModal.vue'
import DecisionModal from '@/components/orchestration/DecisionModal.vue'
import { useBoardCloseout } from '@/composables/useBoardCloseout'
import { useIntegrationStatus } from '@/composables/useIntegrationStatus'
import { useToast } from '@/composables/useToast'
import { useNotificationStore } from '@/stores/notifications'
import { notifyFailure } from '@/utils/notifyFailure'
import BaseDialog from '@/components/common/BaseDialog.vue'
import { useWebSocketStore } from '@/stores/websocket'
import { useJobsBoardLiveRefresh } from '@/composables/useJobsBoardLiveRefresh'
import { coalesceAsync } from '@/utils/coalesceAsync'

const projectStore = useProjectStore()
const productStore = useProductStore()
const sequenceRunStore = useSequenceRunStore()
const jobsScope = useJobsScopeStore()
const allProducts = computed(() => jobsScope.allProducts)
const groupFold = useFoldSet('jobs.groupFold')
const route = useRoute()
const loading = ref(true)
const agentsByProject = ref({})

function findAgent(jobId) {
  if (!jobId) return null
  for (const agents of Object.values(agentsByProject.value)) {
    const hit = agents.find((a) => (a.job_id || a.agent_id) === jobId)
    if (hit) return hit
  }
  return null
}
const {
  showAgentDetailsModal,
  showAgentJobModal,
  jobModalInitialTab,
  selectedAgent,
  handleMessages,
  handleStepsClick,
  handleAgentRole,
  handleAgentJob,
} = useJobActions(findAgent)

const router = useRouter()
const { showToast } = useToast()
const notificationStore = useNotificationStore()
const board = useBoardCloseout({ agentsFor: (id) => agentsByProject.value[id] || [], refresh: () => fetchBoard() })
const { gitEnabled, serenaEnabled, resolved: integrationsResolved } = useIntegrationStatus()
const arrivalProjectId = computed(() => (typeof route.query.project === 'string' ? route.query.project : null))
function chainCtxFor(projectId) {
  const run = chainRuns.value.find((r) => runMembers(r).includes(projectId))
  return run ? { runId: run.id, conductor: { agentId: run.conductor_agent_id || '' } } : null
}
const missionEditAgent = ref(null)
const missionEditOpen = ref(false)
function openMissionEdit(agent) {
  missionEditAgent.value = agent
  missionEditOpen.value = true
}
async function onMissionUpdated({ jobId }) {
  showToast({ message: 'Agent mission updated successfully', type: 'success' })
  const owner = Object.entries(agentsByProject.value).find(([, list]) => list.some((a) => (a.job_id || a.agent_id) === jobId))
  if (owner) await loadAgentsFor({ id: owner[0] })
}
async function consumeArrival() {
  if (!arrivalProjectId.value) return
  const project = projectStore.activeProjectsMeta.find((p) => p.id === arrivalProjectId.value)
  if (project) {
    board.focus(project)
    selectSide(sideOf(project))
  }
  const rest = board.consumeArrival(route.query, project, { onDetail: openDetail })
  if (rest) router.replace({ query: rest })
  await nextTick()
  document.querySelector('[data-arrival="true"]')?.scrollIntoView?.({ block: 'start' })
}

const headlessAllowed = ref(null)

const { density, isCompact, setDensity } = useBoardDensity()

async function loadHeadlessSetting() {
  try {
    const res = await api.settings.getHeadlessLaunch()
    headlessAllowed.value = !!res.data?.allow_headless_launch
  } catch {
    headlessAllowed.value = null
  }
}

function runMembers(run) {
  return run.resolved_order?.length ? run.resolved_order : run.project_ids || []
}
const chainRuns = computed(() => [
  ...sequenceRunStore.runsById.values(),
  ...sequenceRunStore.reviewPendingById.values(),
])
const chainRunIds = computed(() => chainRuns.value.map((run) => run.id))
const chainMemberIds = computed(() => new Set(chainRuns.value.flatMap(runMembers)))

const projects = computed(() =>
  projectStore.activeProjectsMeta.filter((project) => !chainMemberIds.value.has(project.id)),
)

const highlightedRunId = computed(() => (typeof route.query.run === 'string' ? route.query.run : null))
async function revealHighlightedRun() {
  if (!highlightedRunId.value) return
  const run = chainRuns.value.find((r) => r.id === highlightedRunId.value)
  if (run) selectSide(sideOfRun(run))
  for (const group of productGroups.value) {
    if (group.runIds.includes(highlightedRunId.value)) groupFold.unfold(group.id)
  }
  await nextTick()
  const group = [...document.querySelectorAll('[data-run-id]')].find(
    (el) => el.dataset.runId === highlightedRunId.value,
  )
  group?.scrollIntoView?.({ block: 'start' })
}
const productName = computed(
  () => productStore.currentProduct?.name || productStore.activeProduct?.name || '',
)

const now = ref(Date.now())
let tickerId = null
onMounted(() => {
  tickerId = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})
onUnmounted(() => {
  if (tickerId) {
    clearInterval(tickerId)
    tickerId = null
  }
})

useJobsBoardLiveRefresh({
  wsStore: useWebSocketStore(),
  isOnBoard: (pid) => projects.value.some((project) => project.id === pid) || chainMemberIds.value.has(pid),
  refreshAgents: (pid) => loadAgentsFor({ id: pid }),
  refreshBoard: (named) => refreshBoardLive(named),
})

function sectionLabelOf(project) {
  return jobsSectionLabelFor(project, agentsByProject.value[project.id] || [])
}

const STAGING_SIDE_LABELS = new Set([
  JOBS_SECTION_LABELS.ACTIVATED,
  JOBS_SECTION_LABELS.PLANNING,
  JOBS_SECTION_LABELS.STAGED,
])
const CHAIN_IMPLEMENTATION_STATUSES = new Set(['running', 'stalled', 'completed', 'failed', 'terminated', 'cancelled'])
function sideOf(project) {
  return STAGING_SIDE_LABELS.has(sectionLabelOf(project)) ? 'staging' : 'implementation'
}
function sideOfRun(run) {
  return CHAIN_IMPLEMENTATION_STATUSES.has(run?.status) ? 'implementation' : 'staging'
}
const sideCounts = computed(() => {
  const counts = { staging: 0, implementation: 0 }
  for (const project of projects.value) counts[sideOf(project)]++
  for (const run of chainRuns.value) counts[sideOfRun(run)]++
  return counts
})
const side = ref('implementation')
let sideChosen = false
watch(
  sideCounts,
  (counts) => {
    if (sideChosen) return
    side.value = counts.implementation > 0 || counts.staging === 0 ? 'implementation' : 'staging'
  },
  { immediate: true },
)
function selectSide(value) {
  sideChosen = true
  side.value = value
  filter.value = 'all'
}
const sideProjects = computed(() => projects.value.filter((project) => sideOf(project) === side.value))

const chainMemberProjects = computed(() =>
  projectStore.activeProjectsMeta.filter((project) => chainMemberIds.value.has(project.id)),
)
const productsById = computed(() => {
  const map = { ...(productStore.productsById || {}) }
  for (const product of productStore.products || []) map[product.id] = product
  return map
})
const productGroups = computed(() =>
  allProducts.value
    ? groupBoardByProduct({
        projects: projects.value,
        chainMembers: chainMemberProjects.value,
        runs: chainRuns.value,
        membersOf: runMembers,
        productsById: productsById.value,
        sideOf,
        sideOfRun,
        side: side.value,
      })
    : [],
)
const productGroupsTotal = computed(() => productGroups.value.length)
function filterGroup(groupProjects) {
  if (filter.value === 'all') return groupProjects
  const wanted = FILTER_TO_LABEL[filter.value]
  return groupProjects.filter((project) => sectionLabelOf(project) === wanted)
}
const sideChainRunIds = computed(() =>
  chainRuns.value.filter((run) => sideOfRun(run) === side.value).map((run) => run.id),
)
const countNote = computed(() =>
  side.value === 'staging'
    ? `${sideCounts.value.staging} waiting for a go · staged projects move to Implementation when you press Play`
    : `${sideCounts.value.implementation} in flight · reviewed projects leave the board`,
)

const filter = ref('all')
const filterOptions = computed(() => {
  const counts = {
    all: sideProjects.value.length,
    activated: 0,
    planning: 0,
    'needs-input': 0,
    implementing: 0,
    staged: 0,
    review: 0,
  }
  for (const project of sideProjects.value) {
    const label = sectionLabelOf(project)
    if (label === JOBS_SECTION_LABELS.NEEDS_INPUT) counts['needs-input']++
    else if (label === JOBS_SECTION_LABELS.IMPLEMENTING) counts.implementing++
    else if (label === JOBS_SECTION_LABELS.STAGED) counts.staged++
    else if (label === JOBS_SECTION_LABELS.REVIEW) counts.review++
    else if (label === JOBS_SECTION_LABELS.PLANNING) counts.planning++
    else if (label === JOBS_SECTION_LABELS.ACTIVATED) counts.activated++
  }
  if (side.value === 'staging') {
    return [
      { value: 'all', label: 'All', count: counts.all },
      { value: 'activated', label: 'Activated', count: counts.activated },
      { value: 'planning', label: 'Planning', count: counts.planning },
      { value: 'staged', label: 'Staged', count: counts.staged },
    ]
  }
  return [
    { value: 'all', label: 'All', count: counts.all },
    { value: 'needs-input', label: 'Needs input', count: counts['needs-input'] },
    { value: 'implementing', label: 'Implementing', count: counts.implementing },
    { value: 'review', label: 'Review', count: counts.review },
  ]
})

const FILTER_TO_LABEL = {
  activated: JOBS_SECTION_LABELS.ACTIVATED,
  planning: JOBS_SECTION_LABELS.PLANNING,
  'needs-input': JOBS_SECTION_LABELS.NEEDS_INPUT,
  implementing: JOBS_SECTION_LABELS.IMPLEMENTING,
  staged: JOBS_SECTION_LABELS.STAGED,
  review: JOBS_SECTION_LABELS.REVIEW,
}

const filteredProjects = computed(() => {
  if (filter.value === 'all') return sideProjects.value
  const wanted = FILTER_TO_LABEL[filter.value]
  return sideProjects.value.filter((project) => sectionLabelOf(project) === wanted)
})

const editingProject = ref(null)
const editDialogOpen = ref(false)
const projectTypes = ref([])
async function openEditDialog(project) {
  if (!projectTypes.value.length) {
    try {
      const response = await api.taxonomyTypes.list()
      projectTypes.value = response?.data || []
    } catch {
      projectTypes.value = []
    }
  }
  editingProject.value = project
  editDialogOpen.value = true
}
async function onEditSaved() {
  editDialogOpen.value = false
  editingProject.value = null
  await fetchBoard()
}
const editDialogRef = ref(null)
const clearMissionOpen = ref(false)
function onClearMissionConfirmed() {
  editDialogRef.value?.clearMissionData?.()
  clearMissionOpen.value = false
}

const detailModalOpen = ref(false)
const detailProject = ref(null)

function openDetail(project) {
  detailProject.value = project
  board.focus(project)
  detailModalOpen.value = true
}

function openHub(project) {
  handleMessages({}, project.id)
}

async function loadAgentsFor(project) {
  try {
    const response = await api.agentJobs.list(project.id)
    agentsByProject.value = {
      ...agentsByProject.value,
      [project.id]: extractJobsFromResponse(response?.data),
    }
  } catch (error) {
    agentsByProject.value = { ...agentsByProject.value, [project.id]: [] }
    notifyFailure(notificationStore, {
      operation: 'jobs.load',
      entityId: project.id || 'none',
      error,
      fallbackMessage: 'Failed to load agent jobs. Refresh the page or try again.',
      title: 'Agent jobs unavailable',
    })
  }
}

async function loadBoard() {
  const scope = { allProducts: allProducts.value }
  await Promise.all([projectStore.fetchActiveProject(scope), sequenceRunStore.hydrate(undefined, scope)])
  const ids = new Set([...projects.value.map((project) => project.id), ...chainMemberIds.value])
  await Promise.all([...ids].map((id) => loadAgentsFor({ id })))
}
const fetchBoard = coalesceAsync(loadBoard)

const liveNamed = new Set()
const reloadLive = coalesceAsync(async () => {
  const named = new Set(liveNamed)
  liveNamed.clear()
  const scope = { allProducts: allProducts.value }
  await Promise.all([projectStore.fetchActiveProject(scope), sequenceRunStore.hydrate(undefined, scope)])
  const onBoard = new Set([...projects.value.map((project) => project.id), ...chainMemberIds.value])
  const stale = [...onBoard].filter((id) => named.has(id) || !(id in agentsByProject.value))
  await Promise.all(stale.map((id) => loadAgentsFor({ id })))
})
function refreshBoardLive(named = []) {
  named.forEach((id) => liveNamed.add(id))
  return reloadLive()
}
const unregisterResync = registerReconnectResync(() => fetchBoard())
onUnmounted(() => unregisterResync())

onMounted(async () => {
  try {
    loadHeadlessSetting()
    await fetchBoard()
  } finally {
    loading.value = false
  }
  revealHighlightedRun()
  consumeArrival()
})

watch(allProducts, async () => {
  loading.value = true
  try {
    await fetchBoard()
  } finally {
    loading.value = false
  }
})

watch(
  () => productStore.effectiveProductId,
  async () => {
    loading.value = true
    try {
      await fetchBoard()
    } finally {
      loading.value = false
    }
  },
)

defineExpose({ fetchBoard })
</script>

<style scoped lang="scss">
@use '../styles/design-tokens' as *;

.jb-grid {
  display: grid;
  gap: 20px;
  grid-template-columns: repeat(auto-fill, minmax(370px, 1fr));
}

.jb-empty {
  border: 1px dashed $color-border-secondary;
  border-radius: $border-radius-rounded;
  padding: 48px 24px;
  text-align: center;
  color: $color-text-secondary;
  margin-top: 26px;
}

.jb-empty-sub {
  margin: 0 0 18px;
}
</style>
