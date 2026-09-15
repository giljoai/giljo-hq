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
            Every project in flight<span v-if="productName"> for <strong>{{ productName }}</strong></span>, and what its agents are doing right now.
          </p>
        </v-col>
      </v-row>

      <div v-if="projects.length > 0" class="jb-toolbar" data-testid="jobs-board-toolbar">
        <div class="jb-filter-group" role="group" aria-label="Filter by state">
          <button
            v-for="option in filterOptions"
            :key="option.value"
            type="button"
            class="jb-filter"
            :class="{ 'jb-filter--active': filter === option.value }"
            :data-testid="`jobs-filter-${option.value}`"
            @click="filter = option.value"
          >
            {{ option.label }}
            <span class="jb-filter-n" :class="{ 'jb-filter-n--hot': option.value === 'needs-input' && option.count > 0 }">
              {{ option.count }}
            </span>
          </button>
        </div>
        <span class="jb-count-note">{{ projects.length }} in flight · reviewed projects leave the board</span>
      </div>

      <div
        v-if="projects.length === 0"
        class="jb-empty"
        data-testid="jobs-board-empty"
      >
        <h2 class="text-headline-medium">Nothing in flight for this product</h2>
        <p class="text-body-medium jb-empty-sub">Stage a project to see its agents here.</p>
        <v-btn color="primary" to="/projects">Go to Projects</v-btn>
      </div>

      <div v-else class="jb-grid" data-testid="jobs-board-grid">
        <JobsBoardCard
          v-for="project in filteredProjects"
          :key="project.id"
          :project="project"
          :agents="agentsByProject[project.id] || []"
          :now="now"
          :headless-allowed="headlessAllowed"
          :selectable="isSelectable(project)"
          :selected="selectedIds.includes(project.id)"
          data-testid="jobs-board-card-wrap"
          @open-detail="openDetail"
          @open-hub="openHub"
          @toggle-select="toggleSelect"
        />
      </div>

      <div v-if="selectedProjects.length" class="jb-launch-bar" data-testid="jobs-launch-bar">
        <span class="jb-launch-count">
          {{ selectedProjects.length }} staged project{{ selectedProjects.length === 1 ? '' : 's' }} selected
        </span>
        <v-btn variant="text" size="small" data-testid="jobs-launch-clear" @click="clearSelection">
          Clear
        </v-btn>
        <v-btn
          color="primary"
          variant="flat"
          size="small"
          data-testid="jobs-launch-open"
          @click="launchDialogOpen = true"
        >
          Launch staged…
        </v-btn>
      </div>
    </template>

    <LaunchStagedDialog v-model="launchDialogOpen" :projects="selectedProjects" />

    <JobsBoardDetailModal
      v-model="detailModalOpen"
      :project="detailProject"
      :agents="detailProject ? agentsByProject[detailProject.id] || [] : []"
      :now="now"
    />
  </v-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useProjectStore } from '@/stores/projects'
import { useProductStore } from '@/stores/products'
import { api } from '@/services/api'
import { jobsSectionLabelFor, JOBS_SECTION_LABELS } from '@/utils/jobsSectionLabel'
import { extractJobsFromResponse } from '@/composables/useAgentJobs'
import { useJobActions } from '@/composables/useJobActions'
import JobsBoardCard from '@/components/projects/JobsBoardCard.vue'
import JobsBoardDetailModal from '@/components/projects/JobsBoardDetailModal.vue'
import LaunchStagedDialog from '@/components/projects/LaunchStagedDialog.vue'

const projectStore = useProjectStore()
const productStore = useProductStore()
const { handleMessages } = useJobActions(() => null)
const loading = ref(true)
const agentsByProject = ref({})

const headlessAllowed = ref(null)

async function loadHeadlessSetting() {
  try {
    const res = await api.settings.getHeadlessLaunch()
    headlessAllowed.value = !!res.data?.allow_headless_launch
  } catch {
    headlessAllowed.value = null
  }
}

const projects = computed(() => projectStore.activeProjectsMeta)
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

function sectionLabelOf(project) {
  return jobsSectionLabelFor(project, agentsByProject.value[project.id] || [])
}

const filter = ref('all')
const filterOptions = computed(() => {
  const counts = {
    all: projects.value.length,
    activated: 0,
    planning: 0,
    'needs-input': 0,
    implementing: 0,
    staged: 0,
    review: 0,
  }
  for (const project of projects.value) {
    const label = sectionLabelOf(project)
    if (label === JOBS_SECTION_LABELS.NEEDS_INPUT) counts['needs-input']++
    else if (label === JOBS_SECTION_LABELS.IMPLEMENTING) counts.implementing++
    else if (label === JOBS_SECTION_LABELS.STAGED) counts.staged++
    else if (label === JOBS_SECTION_LABELS.REVIEW) counts.review++
    else if (label === JOBS_SECTION_LABELS.PLANNING) counts.planning++
    else if (label === JOBS_SECTION_LABELS.ACTIVATED) counts.activated++
  }
  return [
    { value: 'all', label: 'All', count: counts.all },
    { value: 'activated', label: 'Activated', count: counts.activated },
    { value: 'planning', label: 'Planning', count: counts.planning },
    { value: 'needs-input', label: 'Needs input', count: counts['needs-input'] },
    { value: 'implementing', label: 'Implementing', count: counts.implementing },
    { value: 'staged', label: 'Staged', count: counts.staged },
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
  if (filter.value === 'all') return projects.value
  const wanted = FILTER_TO_LABEL[filter.value]
  return projects.value.filter((project) => sectionLabelOf(project) === wanted)
})

const selectedIds = ref([])
const launchDialogOpen = ref(false)

function isSelectable(project) {
  return sectionLabelOf(project) === JOBS_SECTION_LABELS.STAGED
}

function toggleSelect(project) {
  const at = selectedIds.value.indexOf(project.id)
  if (at === -1) selectedIds.value = [...selectedIds.value, project.id]
  else selectedIds.value = selectedIds.value.filter((id) => id !== project.id)
}

function clearSelection() {
  selectedIds.value = []
}

const selectedProjects = computed(() =>
  selectedIds.value
    .map((id) => projects.value.find((project) => project.id === id))
    .filter((project) => project && isSelectable(project)),
)

const detailModalOpen = ref(false)
const detailProject = ref(null)

function openDetail(project) {
  detailProject.value = project
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
  } catch {
    agentsByProject.value = { ...agentsByProject.value, [project.id]: [] }
  }
}

async function fetchBoard() {
  await projectStore.fetchActiveProject()
  await Promise.all(projects.value.map(loadAgentsFor))
}

onMounted(async () => {
  try {
    loadHeadlessSetting()
    await fetchBoard()
  } finally {
    loading.value = false
  }
})

defineExpose({ selectedIds, selectedProjects, launchDialogOpen, fetchBoard })
</script>

<style scoped lang="scss">
@use '../styles/design-tokens' as *;

.jb-launch-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 24px;
  padding: 12px 16px;
  background: $color-container-background;
  border: 1px solid $color-border-secondary;
  border-radius: $border-radius-pill;
}

.jb-launch-count {
  flex: 1;
}

.jb-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 24px;
}

.jb-filter-group {
  display: flex;
  background: $color-container-background;
  border: 1px solid $color-border-secondary;
  border-radius: $border-radius-pill;
  padding: 3px;
}

.jb-filter {
  background: none;
  border: 0;
  color: $color-text-secondary;
  cursor: pointer;
  padding: 6px 15px;
  border-radius: $border-radius-pill;
  font-size: 0.8rem;
  font-family: inherit;
  display: flex;
  align-items: center;
  gap: 6px;

  &--active {
    background: rgba($color-brand-yellow, 0.14);
    color: $color-brand-yellow;
    font-weight: 600;

    .jb-filter-n {
      background: rgba($color-brand-yellow, 0.22);
    }
  }
}

.jb-filter-n {
  font-size: 0.68rem;
  background: rgba(255, 255, 255, 0.09);
  padding: 0 6px;
  border-radius: $border-radius-pill;

  &--hot {
    background: rgba($color-status-blocked, 0.25);
    color: $color-status-blocked;
  }
}

.jb-count-note {
  color: $color-text-secondary;
  font-size: 0.8rem;
  margin-left: auto;
}

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

@media (max-width: $breakpoint-mobile) {
  .jb-grid {
    grid-template-columns: 1fr;
  }
}
</style>
