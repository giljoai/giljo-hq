<template>
  <v-container class="jobs-board">
    <div v-if="loading" class="d-flex justify-center align-center" style="height: 60vh">
      <v-progress-circular indeterminate size="64" color="primary" />
    </div>

    <template v-else>
      <!-- Header (harmonized with ProjectsView / RoadmapView) -->
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

      <!-- FE-9555: the board-level launch gesture. Appears only once something is
           selected, so an untouched board stays a status board. Deliberately NOT
           gated on the Headless toggle: this is ergonomics, and the
           real gate is server-side. -->
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
/**
 * JobsViewportView.vue — FE-9548
 *
 * The plural Jobs board: one card per in-flight project of the viewed
 * product, rebuilt strictly to design mock jobs-board-proposal-v4.html
 * (operator: "be strict with the design I sent you") after the FE-9525d
 * version shipped with none of the house design-system treatments applied
 * (v-card variant="outlined", v-card-title, plain-grey text, no agent
 * badges) despite its own DoD naming design-system-sample-v2.html.
 *
 * Layout/arithmetic is delegated to reusable pieces so this view stays a
 * thin composition root:
 *   - JobsBoardCard.vue -- one project card (tokens, taxonomy pill, gate
 *     note, stat strip, agent rows, footer buttons)
 *   - JobsBoardAgentRow.vue -- the compact per-agent row AgentRow.vue's
 *     display logic feeds (badge/status/duration/messages, no name text)
 *   - JobsBoardDetailModal.vue -- ONE shared "Jobs detail" diagnostics modal
 *     instance, its project/agents swapped in via openDetail() rather than
 *     mounting one modal per card
 *   - utils/jobsSectionLabel.js, jobsBoardLifecycle.js, jobsBoardCardStats.js,
 *     durationFormat.js -- pure helpers, independently unit tested
 *
 * Filter segmented control (All/Needs input/Implementing/Staged/Review) is
 * local UI state -- the underlying project list is unchanged, this view just
 * narrows what's rendered. Reviewed projects leave the board "for free": once
 * a project is actually closed out, its status flips off 'active' and
 * activeProjectsMeta (BE-9525a/b) stops returning it -- no extra removal
 * logic needed here.
 *
 * Live updates: activeProjectsMeta is the SAME reactive field the store's WS
 * status_changed handler already keeps current (mirrors FE-9525d). The
 * per-project agent list is fetched once per project on mount, mirroring
 * JobsTab's own useAgentJobs.loadJobs -- live agent-level updates within an
 * open project are JobsTab's job, not duplicated here. A 1s ticker (mirroring
 * JobsTab's own durationTickerId) drives every card's live "elapsed"/duration
 * text without a WS round-trip.
 *
 * Edition scope: Both.
 */
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
// FE-9548: reuse the EXISTING project-bound-Hub-thread resolver (JobsTab's
// own 💬/messages action) for the board card's 💬 button, rather than a new
// nav path. getJob is unused here (no agent-detail modal on this view).
const { handleMessages } = useJobActions(() => null)
const loading = ref(true)
// project_id -> agent execution list (one fetch per card; not a store, this
// view owns it, same shape/technique as the pre-FE-9548 version).
const agentsByProject = ref({})

// FE-9549: the tenant's real headless-self-advance setting, so the Staged card's
// gate note states a fact instead of inferring one from the card's own state.
// Stays null until the read resolves; the note renders only on an explicit false.
const headlessAllowed = ref(null)

async function loadHeadlessSetting() {
  try {
    const res = await api.settings.getHeadlessLaunch()
    headlessAllowed.value = !!res.data?.allow_headless_launch
  } catch {
    // Unknown on failure -- suppress the note rather than assert either way.
    headlessAllowed.value = null
  }
}

const projects = computed(() => projectStore.activeProjectsMeta)
const productName = computed(
  () => productStore.currentProduct?.name || productStore.activeProduct?.name || '',
)

// FE-9548: one ticker drives every card's live duration text (mirrors
// JobsTab's own durationTickerId pattern) rather than each card/row owning
// a timer.
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

// FE-9551: the filter must cover every state a card can actually display.
// `get_active_projects` (backend) filters on Project.status == ACTIVE only --
// it does NOT filter on staging_status -- so a project mid-staging
// (staging_status 'staging', Planning) can legitimately sit on this board
// alongside a never-staged one (Activated). A state that can render a badge
// but can't be filtered is a hole.
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

// FE-9555: board-level selection for the "Launch staged..." gesture.
//
// Only a STAGED card is eligible: staging finished and implementation has not
// launched, which is the one state where handing someone a conductor seed is the
// right next step. Offering it on an Implementing card would mint a prompt to
// start work that is already running.
//
// An ARRAY, not a Set, because the order the user ticked things in IS the run
// order the master prompt is built from -- a Set would silently reorder a
// decision the user made deliberately.
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

// Resolved against the LIVE board rows, and in selection order. Resolving rather
// than storing the row keeps a renamed or re-labelled project current, and the
// filter drops anything that has left the board -- a project launched elsewhere
// stops being staged and its card goes, and a stale id left selected would be
// counted in the bar and built into the prompt for a card the user cannot see.
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
  // handleMessages(agent, projectIdOverride) resolves the project-bound
  // thread by projectIdOverride when it's passed, so a stub agent object is
  // fine -- no agent-level fields it needs are read on that path.
  handleMessages({}, project.id)
}

async function loadAgentsFor(project) {
  try {
    const response = await api.agentJobs.list(project.id)
    // FE-9545: /api/agent-jobs/ answers with a PAGINATED ENVELOPE
    // ({jobs, total, limit, offset}), not a bare array. Reuse the one reader
    // that already tolerates array | {jobs} | {rows} rather than guessing here.
    agentsByProject.value = {
      ...agentsByProject.value,
      [project.id]: extractJobsFromResponse(response?.data),
    }
  } catch {
    // Non-fatal: the card still renders with the lifecycle-only label.
    agentsByProject.value = { ...agentsByProject.value, [project.id]: [] }
  }
}

// FE-9555: named so a refresh has ONE home. Selection is pruned by the
// selectedProjects computed rather than here, so a board refresh cannot leave a
// vanished project counted in the launch bar.
async function fetchBoard() {
  await projectStore.fetchActiveProject()
  await Promise.all(projects.value.map(loadAgentsFor))
}

onMounted(async () => {
  try {
    // FE-9549: the headless read is independent of the project fetch and must not
    // block the board, so it runs alongside rather than gating the render.
    loadHeadlessSetting()
    await fetchBoard()
  } finally {
    loading.value = false
  }
})

// Exposed for unit tests (selection state + the one refresh entry point).
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
