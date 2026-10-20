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
          <p class="text-body-small text-muted-a11y mt-1" data-testid="jobs-board-count-line">{{ countLine }}</p>
        </v-col>
      </v-row>

      <p v-if="sequenceRunStore.error" class="text-body-medium mb-3" data-testid="jobs-board-chain-error">
        <v-icon size="16" color="error" class="mr-1">mdi-alert-circle</v-icon>
        Could not load the chains: {{ sequenceRunStore.error }}
      </p>

      <JobsBoardToolbar
        v-if="hasBoard"
        :side="side"
        :side-counts="sideCounts"
        :status-counts="statusCounts"
        :is-compact="isCompact"
        @select-side="selectSide"
        @select-density="setDensity"
      />

      <div
        v-if="!hasBoard"
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
          <div v-if="group.projects.length" class="jb-grid" data-testid="jobs-board-grid">
            <JobsBoardCard
              v-for="project in group.projects"
              :key="project.id"
              v-bind="cardShared(project)"
              v-on="cardListeners"
            />
          </div>
          <JobsBoardDoneGroup v-if="group.unreviewed.length" :count="group.unreviewed.length">
            <div class="jb-grid">
              <JobsBoardCard
                v-for="project in group.unreviewed"
                :key="project.id"
                v-bind="cardShared(project)"
                v-on="cardListeners"
              />
            </div>
          </JobsBoardDoneGroup>
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
          @steps="handleStepsClick"
          @agent-mission-edit="openMissionEdit"
        />

        <div v-if="sideProjects.length" class="jb-grid" data-testid="jobs-board-grid">
          <JobsBoardCard
            v-for="project in sideProjects"
            :key="project.id"
            v-bind="cardShared(project)"
            v-on="cardListeners"
          />
        </div>
        <JobsBoardDoneGroup v-if="sideUnreviewed.length" :count="sideUnreviewed.length">
          <div class="jb-grid">
            <JobsBoardCard
              v-for="project in sideUnreviewed"
              :key="project.id"
              v-bind="cardShared(project)"
              v-on="cardListeners"
            />
          </div>
        </JobsBoardDoneGroup>
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
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/projects'
import { useProductStore } from '@/stores/products'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { registerReconnectResync } from '@/stores/websocketEventRouter'
import { api } from '@/services/api'
import { jobsSectionLabelFor } from '@/utils/jobsSectionLabel'
import { extractJobsFromResponse } from '@/composables/useAgentJobs'
import { useJobActions } from '@/composables/useJobActions'
import { useBoardDensity } from '@/composables/useBoardDensity'
import JobsBoardCard from '@/components/projects/JobsBoardCard.vue'
import JobsBoardDetailModal from '@/components/projects/JobsBoardDetailModal.vue'
import ChainGroup from '@/components/projects/chain/ChainGroup.vue'
import ProjectCreateEditDialog from '@/components/projects/ProjectCreateEditDialog.vue'
import JobsBoardDoneGroup from '@/components/projects/JobsBoardDoneGroup.vue'
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
import { useJobsBoardSides } from '@/composables/useJobsBoardSides'
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
const { gitEnabled, resolved: integrationsResolved } = useIntegrationStatus()
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

const soloUnreviewed = computed(() =>
  projectStore.unreviewedProjectsMeta.filter((project) => !chainMemberIds.value.has(project.id)),
)
const hasBoard = computed(
  () => projects.value.length > 0 || chainRunIds.value.length > 0 || soloUnreviewed.value.length > 0,
)

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
  isOnBoard: (pid) =>
    projects.value.some((project) => project.id === pid) ||
    soloUnreviewed.value.some((project) => project.id === pid) ||
    chainMemberIds.value.has(pid),
  refreshAgents: (pid) => loadAgentsFor({ id: pid }),
  refreshBoard: (named) => refreshBoardLive(named),
})

function sectionLabelOf(project) {
  return jobsSectionLabelFor(project, agentsByProject.value[project.id] || [])
}

const {
  side,
  selectSide,
  sideOf,
  sideOfRun,
  sideCounts,
  sideProjects,
  sideUnreviewed,
  sideChainRunIds,
  countLine,
  statusCounts,
  arrivalProjectId,
  highlightedRunId,
  land,
} =
  useJobsBoardSides({
    route,
    router,
    projects,
    soloUnreviewed,
    chainRuns,
    runMembers,
    sectionLabelOf,
    board,
    openDetail,
    productGroups: () => productGroups.value,
    groupFold,
    refresh: () => fetchBoard(),
  })

const chainMemberProjects = computed(() =>
  [...projectStore.activeProjectsMeta, ...projectStore.unreviewedProjectsMeta].filter((project) =>
    chainMemberIds.value.has(project.id),
  ),
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
        unreviewed: sideUnreviewed.value,
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

function cardShared(project) {
  return {
    project,
    agents: agentsByProject.value[project.id] || [],
    now: now.value,
    headlessAllowed: headlessAllowed.value,
    density: density.value,
    gitEnabled: gitEnabled.value,
    integrationsResolved: integrationsResolved.value,
    'data-testid': 'jobs-board-card-wrap',
    'data-arrival': project.id === arrivalProjectId.value ? 'true' : undefined,
    class: { 'jb-card--arrival': project.id === arrivalProjectId.value },
  }
}
const cardListeners = {
  'open-detail': openDetail,
  'open-hub': openHub,
  changed: () => fetchBoard(),
  'edit-description': openEditDialog,
  review: (project) => board.openReview(project),
  steps: handleStepsClick,
  'agent-mission-edit': openMissionEdit,
  'agent-messages': (agent, project) => handleMessages(agent, project.id),
  'agent-role': handleAgentRole,
  'agent-job': handleAgentJob,
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

function agentsLoadFailed(ids, error) {
  agentsByProject.value = { ...agentsByProject.value, ...Object.fromEntries(ids.map((id) => [id, []])) }
  notifyFailure(notificationStore, {
    operation: 'jobs.load',
    entityId: ids.length === 1 ? ids[0] || 'none' : 'board',
    error,
    fallbackMessage: 'Failed to load agent jobs. Refresh the page or try again.',
    title: 'Agent jobs unavailable',
  })
}

async function loadAgentsFor(project) {
  try {
    const response = await api.agentJobs.list(project.id)
    agentsByProject.value = {
      ...agentsByProject.value,
      [project.id]: extractJobsFromResponse(response?.data),
    }
  } catch (error) {
    agentsLoadFailed([project.id], error)
  }
}

const AGENT_READ_IDS_MAX = 200
async function loadAgentsForMany(ids) {
  for (let start = 0; start < ids.length; start += AGENT_READ_IDS_MAX) {
    const chunk = ids.slice(start, start + AGENT_READ_IDS_MAX)
    let data, jobs
    try {
      data = (await api.agentJobs.listMany(chunk))?.data
      jobs = extractJobsFromResponse(data)
    } catch (error) {
      agentsLoadFailed(chunk, error)
      continue
    }
    if (data.total > jobs.length) {
      await Promise.all(chunk.map((id) => loadAgentsFor({ id })))
      continue
    }
    const byProject = Object.fromEntries(chunk.map((id) => [id, []]))
    for (const job of jobs) byProject[job.project_id]?.push(job)
    agentsByProject.value = { ...agentsByProject.value, ...byProject }
  }
}

function boardIds() {
  return [...projects.value, ...soloUnreviewed.value].map((project) => project.id)
}
async function loadBoard() {
  const scope = { allProducts: allProducts.value }
  await Promise.all([projectStore.fetchActiveProject(scope), sequenceRunStore.hydrate(undefined, scope)])
  const ids = new Set([...boardIds(), ...chainMemberIds.value])
  await loadAgentsForMany([...ids])
}
const fetchBoard = coalesceAsync(loadBoard)

const liveNamed = new Set()
const reloadLive = coalesceAsync(async () => {
  const named = new Set(liveNamed)
  liveNamed.clear()
  const scope = { allProducts: allProducts.value }
  await Promise.all([projectStore.fetchActiveProject(scope), sequenceRunStore.hydrate(undefined, scope)])
  const onBoard = new Set([...boardIds(), ...chainMemberIds.value])
  const stale = [...onBoard].filter((id) => named.has(id) || !(id in agentsByProject.value))
  await loadAgentsForMany(stale)
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
  land()
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

.jb-card--arrival {
  --smooth-border-color: #{$color-brand-yellow};
  outline: 2px solid rgba($color-brand-yellow, 0.35);
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
