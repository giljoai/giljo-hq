<template>
  <v-container>
    <!-- Header -->
    <v-row class="align-center mb-4 main-window-reveal main-window-reveal--hero main-window-delay-1">
      <v-col>
        <h1 class="text-headline-large">Project Management</h1>
        <p class="text-body-medium text-muted-a11y mt-1">
          Use the /giljo skill to have the AI coding agent add new projects to the Project dashboard, or look up existing projects without leaving your AI tool.
          <v-tooltip location="bottom start" max-width="600">
            <template #activator="{ props }">
              <v-icon v-bind="props" size="16" class="help-icon">mdi-help-circle-outline</v-icon>
            </template>
            <div>
              <div class="font-weight-bold mb-1">Project Field Reference</div>
              <div class="text-body-small mb-2 text-muted-a11y">Instructions for /giljo</div>
              <div><span class="font-weight-medium">name (required):</span> Free text</div>
              <div class="mt-1"><span class="font-weight-medium">description (recommended):</span> Free text</div>
              <div class="mt-1"><span class="font-weight-medium">status (optional):</span></div>
              <div class="ml-2 text-body-small">inactive · active · completed · cancelled · parked · deleted</div>
              <div class="mt-2"><span class="font-weight-medium">project_type (optional):</span></div>
              <div class="text-body-small text-center">Taxonomy category abbreviation (e.g. BE, FE, API)</div>
              <div class="mt-1"><span class="font-weight-medium">series_number (optional):</span></div>
              <div class="text-body-small text-center">Sequential number within a type (e.g. 1 → BE-0001)</div>
              <div class="mt-1"><span class="font-weight-medium">subseries (optional):</span></div>
              <div class="text-body-small text-center">Single-letter suffix (e.g. a → BE-0001a)</div>
              <div class="mt-2"><span class="font-weight-medium">Examples:</span></div>
              <div class="ml-2 text-body-small">/giljo add project ... description ...</div>
              <div class="ml-2 text-body-small">/giljo list projects status=active</div>
            </div>
          </v-tooltip>
        </p>
      </v-col>
    </v-row>

    <!-- No Active Product Alert -->
    <v-alert v-if="!activeProduct" type="info" variant="tonal" class="ma-4 main-window-reveal main-window-delay-2" closable>
      No active product selected. Please activate a product to view and manage its projects.
    </v-alert>

    <!-- Filter Bar -->
    <div v-if="activeProduct" class="filter-bar main-window-reveal main-window-delay-2">
      <v-text-field
        v-model="searchQuery"
        prepend-inner-icon="mdi-magnify"
        placeholder="Search projects..."
        variant="solo"
        density="compact"
        clearable
        hide-details
        flat
        aria-label="Search projects by name"
        class="filter-search"
      />
      <v-select
        v-model="selectedStatuses"
        :items="statusSelectOptions"
        multiple
        placeholder="Status"
        variant="solo"
        density="compact"
        clearable
        hide-details
        flat
        class="filter-select"
      >
        <!-- BE-6078: compact summary instead of one chip per checked status. -->
        <template #selection="{ index }">
          <span v-if="index === 0" class="status-summary">{{ statusSummary }}</span>
        </template>
      </v-select>
      <!-- BE-2002: hidden is a separate axis, user-facing name "Archived".
           Circular archive-icon toggle (was the "Show hidden (N)" text button):
           yellow (theme `warning` token) when archived rows are being shown.
           Re-fetches + LISTS archived rows via include_hidden — never re-tags. -->
      <v-btn
        v-if="hiddenCount > 0 || showHidden"
        :color="showHidden ? 'warning' : undefined"
        :variant="showHidden ? 'flat' : 'outlined'"
        :icon="showHidden ? 'mdi-archive' : 'mdi-archive-outline'"
        :disabled="!activeProduct"
        :title="showHidden ? 'Hide archived projects' : `Show archived projects (${hiddenCount})`"
        aria-label="Toggle archived projects"
        class="filter-cta-archive"
        @click="onToggleShowHidden"
      />
      <!-- FE-6176: icon-only [+] / chain-link / trash buttons -->
      <v-btn
        color="primary"
        variant="flat"
        icon="mdi-plus"
        :disabled="!activeProduct"
        title="New project"
        aria-label="Create new project"
        class="filter-cta-new"
        @click="openNewProjectDialog"
      />
      <v-btn
        :color="linkMode ? 'primary' : undefined"
        :variant="linkMode ? 'flat' : 'outlined'"
        icon="mdi-link-variant"
        :disabled="!activeProduct"
        :title="linkMode ? 'Exit link mode' : 'Link projects (chain mode)'"
        aria-label="Toggle link mode"
        class="filter-cta-link"
        @click="linkMode = !linkMode"
      />
      <!-- FE-6179: roadmap-order sort — orders the list by each project's roadmap
           position (the SAME ordering /roadmap renders). Uses the navbar's Roadmap
           icon (mdi-map-marker-path). Toggle: on -> roadmap order; off -> default
           (newest first). -->
      <v-btn
        :color="roadmapSortActive ? 'primary' : undefined"
        :variant="roadmapSortActive ? 'flat' : 'outlined'"
        icon="mdi-map-marker-path"
        :disabled="!activeProduct"
        :title="roadmapSortActive ? 'Clear roadmap-order sort' : 'Sort by roadmap order'"
        aria-label="Toggle roadmap-order sort"
        class="filter-cta-roadmap"
        @click="toggleRoadmapSort"
      />
      <v-btn
        variant="outlined"
        icon="mdi-delete-restore"
        :disabled="deletedCount === 0"
        :title="deletedCount > 0 ? `Deleted projects (${deletedCount})` : 'No deleted projects'"
        aria-label="View deleted projects"
        class="filter-cta-deleted"
        @click="showDeletedDialog = true"
      />
    </div>

    <!-- Projects Table (extracted child component) — BE-6076 server mode:
         shows the current server PAGE; pagination/sort/filter all server-driven.
         FE-6131e: wrapped in SequenceLauncher, which renders the "Run sequential"
         bulk bar + confirm modal and feeds the row checkboxes via its slot. -->
    <SequenceLauncher v-if="activeProduct" v-slot="{ selectedIds, toggle, electionActive }">
    <ProjectsTable
      :current-page="currentPage"
      :items-per-page="itemsPerPage"
      :sort-by="sortBy"
      :projects="projects"
      :total="projectsTotal"
      :loading="loading"
      :has-active-project="hasActiveProject"
      :selected-ids="selectedIds"
      :election-active="electionActive"
      :in-chain-ids="sequenceRunStore.activeChainProjectIds"
      :locked-chain-ids="lockedChainProjectIds"
      :link-mode="linkMode || chainActive"
      @update:options="onTableOptions"
      @toggle-select="(item) => handleProjectToggle(item, toggle)"
      @open-project="openProject"
      @activate-launch="activateAndLaunch"
      @status-action="handleStatusAction"
      @edit-project="editProject"
      @duplicate-project="duplicateProject"
      @toggle-hidden="toggleHidden"
      @confirm-delete="confirmDelete"
      @new-project="showCreateDialog = true"
    />
    </SequenceLauncher>

    <!-- Create/Edit Dialog -->
    <ProjectCreateEditDialog
      ref="createEditDialogRef"
      v-model="showCreateDialog"
      :editing-project="editingProject"
      :active-product="activeProduct"
      :project-types="projectTypes"
      @saved="onDialogSaved"
      @clear-mission="showClearMissionDialog = true"
      @type-created="onTypeCreated"
    />

    <!-- Delete Confirmation Dialog -->
    <BaseDialog
      v-model="showDeleteDialog"
      type="danger"
      title="Delete Project?"
      confirm-label="Delete"
      size="sm"
      @confirm="deleteProject"
      @cancel="showDeleteDialog = false"
    >
      <p class="mb-3">
        Are you sure you want to delete project <strong>"{{ projectToDelete?.name }}"</strong>?
      </p>
      <v-alert type="info" variant="tonal" density="compact">
        This will move the project to <strong>Deleted Projects</strong> for 10 days.
        It can be restored during that time. After 10 days it will be permanently purged.
      </v-alert>
    </BaseDialog>

    <!-- Cancel Project Confirmation Dialog -->
    <BaseDialog
      v-model="showCancelDialog"
      type="warning"
      title="Cancel Project?"
      confirm-label="Cancel Project"
      size="sm"
      @confirm="executeCancelProject"
      @cancel="showCancelDialog = false"
    >
      <p class="mb-3">
        Are you sure you want to cancel project <strong>"{{ projectToCancel?.name }}"</strong>?
      </p>
      <v-alert type="warning" variant="tonal" density="compact">
        Cancelled projects can be reopened later if needed.
      </v-alert>
    </BaseDialog>

    <!-- FE-6180: Deactivate Chain / Reset confirmation (destructive rewind) -->
    <BaseDialog
      v-model="resetDialog.show"
      type="danger"
      :title="resetDialog.kind === 'chain' ? 'Deactivate chain?' : 'Reset project?'"
      :confirm-label="resetDialog.kind === 'chain' ? 'Deactivate Chain' : 'Reset'"
      size="sm"
      @confirm="performReset"
      @cancel="resetDialog.show = false"
    >
      <p class="mb-3">
        This returns {{ resetDialog.kind === 'chain' ? 'all linked projects' : 'this project' }}
        to their <strong>original state</strong>.
      </p>
      <v-alert type="warning" variant="tonal" density="compact">
        Staging and missions are cleared and any running agents and jobs are deleted.
        <strong>No audit log is kept</strong> — for a graceful, auditable exit use
        <strong>Terminate</strong> instead. This cannot be undone.
      </v-alert>
    </BaseDialog>

    <!-- Clear Mission Confirmation Dialog -->
    <BaseDialog
      v-model="showClearMissionDialog"
      type="warning"
      title="Clear Mission?"
      confirm-label="Clear"
      size="sm"
      @confirm="onClearMissionConfirmed"
      @cancel="showClearMissionDialog = false"
    >
      <p>Clear the mission? It will be regenerated on next staging.</p>
    </BaseDialog>

    <!-- Purge Single Project Confirmation Dialog -->
    <BaseDialog
      v-model="showPurgeSingleDialog"
      type="danger"
      title="Permanently Delete Project?"
      confirm-label="Delete Forever"
      size="sm"
      @confirm="purgeDeletedProject(projectToPurge); showPurgeSingleDialog = false"
      @cancel="showPurgeSingleDialog = false"
    >
      <p class="mb-3">
        Permanently delete <strong>"{{ projectToPurge?.name }}"</strong>?
      </p>
      <v-alert type="error" variant="tonal" density="compact">
        This will remove all associated data and <strong>cannot be undone</strong>.
      </v-alert>
    </BaseDialog>

    <!-- Purge All Deleted Projects Confirmation Dialog -->
    <BaseDialog
      v-model="showPurgeAllDialog"
      type="danger"
      title="Permanently Delete All?"
      confirm-label="Delete All Forever"
      size="sm"
      @confirm="executePurgeAll"
      @cancel="showPurgeAllDialog = false"
    >
      <p class="mb-3">
        Permanently delete <strong>all {{ deletedProjects.length }}</strong> projects in the Deleted Projects list?
      </p>
      <v-alert type="error" variant="tonal" density="compact">
        This will remove all associated data and <strong>cannot be undone</strong>.
      </v-alert>
    </BaseDialog>

    <!-- Deleted Projects Dialog -->
    <ProjectDeletedDialog
      v-model="showDeletedDialog"
      :deleted-projects="deletedProjects"
      :purging-project-id="purgingProjectId"
      :purging-all-deleted="purgingAllDeleted"
      @restore="restoreFromDelete"
      @purge="confirmPurgeDeleted"
      @purge-all="confirmPurgeAllDeleted"
    />

    <!-- Manual Closeout Modal -->
    <ManualCloseoutModal
      :show="showCloseoutModal"
      :project-id="closeoutProjectId"
      :project-name="closeoutProjectName"
      @close="handleCloseoutClose"
      @completed="handleCloseoutComplete"
    />

    <ProjectReviewModal
      :show="showReviewModal"
      :project-id="reviewProjectId"
      :product-id="reviewProductId"
      @close="showReviewModal = false; reviewProjectId = null; reviewProductId = null"
    />
  </v-container>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/projects'
import { useProductStore } from '@/stores/products'
import { useNotificationStore } from '@/stores/notifications'
import { useProjectStatusesStore } from '@/stores/projectStatusesStore'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { registerReconnectResync } from '@/stores/websocketEventRouter'
import { storeToRefs } from 'pinia'
import ManualCloseoutModal from '@/components/orchestration/ManualCloseoutModal.vue'
import ProjectReviewModal from '@/components/projects/ProjectReviewModal.vue'
import BaseDialog from '@/components/common/BaseDialog.vue'
import ProjectCreateEditDialog from '@/components/projects/ProjectCreateEditDialog.vue'
import ProjectDeletedDialog from '@/components/projects/ProjectDeletedDialog.vue'
import api from '@/services/api'
import { useToast } from '@/composables/useToast'
import { useFormatDate } from '@/composables/useFormatDate'
import { useProjectFilters } from '@/composables/useProjectFilters'
import { useProjectDeletion } from '@/composables/useProjectDeletion'
import ProjectsTable from './projects/ProjectsTable.vue'
import SequenceLauncher from '@/components/sequence/SequenceLauncher.vue'

// Router
const router = useRouter()

// Stores
const projectStore = useProjectStore()
const productStore = useProductStore()
const notificationStore = useNotificationStore()
const projectStatusesStore = useProjectStatusesStore()
const sequenceRunStore = useSequenceRunStore()
const { statuses: projectStatuses } = storeToRefs(projectStatusesStore)

// FE-6176: link/chain mode toggle — shows "Linked" checkbox column, hides play button column.
const linkMode = ref(false)

// FE-6171b: ids whose active chain run is in the LOCKED (Staged) tier.
// Drives tickbox disable on /projects — distinct from inChainIds which is ALL chain members.
const lockedChainProjectIds = computed(() =>
  sequenceRunStore.activeChainProjectIds.filter((pid) => sequenceRunStore.isProjectRunLocked(pid)),
)
// FE-6180: a chain is active when any project belongs to an active run — the Linked column
// then auto-shows (and stays) regardless of the manual Link toggle, so a returning user always sees their selection.
const chainActive = computed(() => sequenceRunStore.activeChainProjectIds.length > 0)

// FE-6180: confirm gate for the destructive Deactivate Chain / Reset back-out.
const resetDialog = ref({ show: false, kind: 'chain', runId: null, projectId: null })

async function performReset() {
  const { kind, runId, projectId } = resetDialog.value
  resetDialog.value = { ...resetDialog.value, show: false }
  try {
    if (kind === 'chain') {
      await api.sequenceRuns.deactivate(runId)
      await sequenceRunStore.hydrate()
      showToast({ message: 'Chain deactivated — all projects reset to original state.', type: 'success' })
    } else {
      await api.projects.reset(projectId)
      showToast({ message: 'Project reset to original state.', type: 'success' })
    }
    await reloadProjects()
  } catch (err) {
    console.error('[ProjectsView] reset/deactivate failed', err)
    showToast({ message: 'Reset failed. Refresh and try again.', type: 'error' })
    await reloadProjects()
  }
}
const { showToast } = useToast()
// eslint-disable-next-line no-unused-vars -- exposed on vm for test assertions
const { formatDateWithTime } = useFormatDate()

// FE-6165f: reconnect resync cleanup fn (unregistered on unmount).
let _unsubResync = null

// Dialog ref for imperative calls
const createEditDialogRef = ref(null)

// Dialog visibility
const showCreateDialog = ref(false)
const showDeletedDialog = ref(false)
const showCloseoutModal = ref(false)
const showClearMissionDialog = ref(false)
const showReviewModal = ref(false)

// Editing state
const editingProject = ref(null)

// Closeout / review state
const closeoutProjectId = ref(null)
const closeoutProjectName = ref('')
const reviewProjectId = ref(null)
const reviewProductId = ref(null)

// Project types (fetched on mount)
const projectTypes = ref([])

// Store computeds
const activeProduct = computed(() => productStore.activeProduct)
// BE-6076: `projects` is now the current SERVER PAGE; `projectsTotal` the
// filtered total (X-Total-Count) bound to the table :items-length.
const projects = computed(() => projectStore.projects)
const projectsTotal = computed(() => projectStore.projectsTotal)
const loading = computed(() => projectStore.loading)
const deletedProjects = computed(() => projectStore.deletedProjects)
const deletedCount = computed(() => deletedProjects.value.length)
// BE-6076: the active project may be off the current page, so derive this from
// the dedicated /projects/active read (store.activeProjectMeta), not the page.
const hasActiveProject = computed(() => !!projectStore.activeProjectMeta)

// BE-6078/6076: "Show hidden" view toggle. Now drives the server include_hidden
// param (hidden rows join the page); hiddenProjects only powers the (N) count.
const showHidden = ref(false)
const hiddenProjects = computed(() => projectStore.hiddenProjects)

// Filters composable — owns search / multi-status / sort / pagination state and
// builds the server query (BE-6076). Filtering itself is server-side now.
const {
  searchQuery,
  selectedStatuses,
  currentPage,
  itemsPerPage,
  sortBy,
  statusSelectOptions,
  hiddenCount,
  buildServerParams,
} = useProjectFilters({
  activeProduct,
  projectStatuses,
  hiddenProjects,
  showHidden,
})

// FE-6179: roadmap-order sort. The list is server-paginated (BE-6076), so the
// ordering can't be done client-side over one page — the roadmap-icon button
// flips the server sort key to 'roadmap' (the repository orders by the project's
// roadmap_items.sort_order, the SAME single source /roadmap renders). Toggling
// off restores the default newest-first order. `must-sort` on the table forbids
// an empty sort, so "off" is the default sort, not no sort.
const ROADMAP_SORT_KEY = 'roadmap'
const DEFAULT_SORT = { key: 'created_at', order: 'desc' }
const roadmapSortActive = computed(() => sortBy.value?.[0]?.key === ROADMAP_SORT_KEY)

function toggleRoadmapSort() {
  sortBy.value = roadmapSortActive.value
    ? [{ ...DEFAULT_SORT }]
    : [{ key: ROADMAP_SORT_KEY, order: 'asc' }]
  currentPage.value = 1
  fetchPage()
}

// ── BE-6076: server-side page fetching ──────────────────────────────────────
// Single fetch entry point with dedupe so a page-reset echoing back through the
// table's @update:options never double-fetches the identical query.
let _lastParamsJson = null
let _searchDebounce = null

async function fetchPage() {
  const params = buildServerParams()
  const json = JSON.stringify(params)
  if (json === _lastParamsJson) return
  _lastParamsJson = json
  await projectStore.fetchProjects(params)
}

// v-data-table-server reports page / itemsPerPage / sortBy together. Apply them
// to the composable state, then fetch (deduped).
function onTableOptions(options) {
  if (!options) return
  if (typeof options.page === 'number') currentPage.value = options.page
  if (typeof options.itemsPerPage === 'number') itemsPerPage.value = options.itemsPerPage
  if (Array.isArray(options.sortBy)) sortBy.value = options.sortBy
  fetchPage()
}

// Search: debounce input, reset to page 1, re-fetch.
watch(searchQuery, () => {
  if (_searchDebounce) clearTimeout(_searchDebounce)
  _searchDebounce = setTimeout(() => {
    currentPage.value = 1
    fetchPage()
  }, 300)
})

// Status multi-select + Show-hidden: reset to page 1, re-fetch immediately.
watch(
  [selectedStatuses, showHidden],
  () => {
    currentPage.value = 1
    fetchPage()
  },
  { deep: true },
)

// Compact status-filter summary for the multi-select chip area.
const statusSummary = computed(() => {
  const total = statusSelectOptions.value.length
  const n = selectedStatuses.value.length
  if (total > 0 && n === total) return 'All statuses'
  if (n === 0) return 'No statuses'
  return `${n} selected`
})

// BE-6076: re-fetch the CURRENT server page (same filters/sort/page) after a
// mutation. Forces past the dedupe guard (the data changed even though the query
// params didn't) and refreshes the off-page active-project flag.
async function reloadProjects() {
  _lastParamsJson = null
  await Promise.all([fetchPage(), projectStore.fetchActiveProject()])
}

// Destructive project-lifecycle workflow (delete / cancel / restore / purge)
// lives in a cohesive composable (INF-6055). Its returns stay top-level setup
// bindings, so the template + tests reference them unchanged.
const {
  showDeleteDialog,
  projectToDelete,
  projectToCancel,
  showCancelDialog,
  projectToPurge,
  showPurgeSingleDialog,
  showPurgeAllDialog,
  purgingProjectId,
  purgingAllDeleted,
  confirmDelete,
  deleteProject,
  executeCancelProject,
  restoreFromDelete,
  confirmPurgeDeleted,
  purgeDeletedProject,
  confirmPurgeAllDeleted,
  executePurgeAll,
} = useProjectDeletion({ showDeletedDialog, reloadProjects })

// "Show archived (N)" — a pure read view (backend field is `hidden`). Re-fetch
// the archived set fresh, then list it. BE-6076: flipping showHidden drives the
// server include_hidden param via the watcher (re-fetches the page); never
// re-tags — unarchive stays the per-row hamburger action. Refresh the
// archived-count set when turning the view on.
async function onToggleShowHidden() {
  if (!showHidden.value) {
    await projectStore.fetchHiddenProjects()
  }
  showHidden.value = !showHidden.value
}

// Activate project and navigate to its jobs page
async function activateAndLaunch(projectId) {
  await projectStore.activateProject(projectId)
  const project = projectStore.projects.find((p) => p.id === projectId)
  const staged = project && (project.staging_status === 'staged' || project.staging_status === 'staging_complete')
  router.push({ name: 'ProjectLaunch', params: { projectId }, query: { via: 'jobs', ...(staged ? { tab: 'jobs' } : {}) } })
}

// FE-5061: Open project via Serial-badge click
function openProject(item) {
  if (!item?.id) return
  const status = item.status || 'inactive'

  if (status === 'completed' || status === 'cancelled' || status === 'terminated') {
    reviewProjectId.value = item.id
    reviewProductId.value = item.product_id
    showReviewModal.value = true
  } else if (status === 'active') {
    const staged = item.staging_status === 'staged' || item.staging_status === 'staging_complete'
    if (staged) {
      router.push({ name: 'ProjectLaunch', params: { projectId: item.id }, query: { tab: 'jobs' } })
    } else {
      router.push({ name: 'ProjectLaunch', params: { projectId: item.id } })
    }
  } else {
    editProject(item)
  }
}

function openNewProjectDialog() {
  editingProject.value = null
  showCreateDialog.value = true
}

async function editProject(project) {
  // IMP-1002: the list endpoint now returns trimmed ProjectListResponse rows
  // (no mission/description). Fetch the full detail first so the dialog is
  // seeded from the complete object; saving without this would wipe the
  // orchestrator-generated mission (irreversible data loss).
  const fullProject = await projectStore.fetchProject(project.id)
  if (!fullProject) {
    showToast({ message: 'Could not load project details. Please try again.', type: 'error' })
    return
  }
  editingProject.value = fullProject
  showCreateDialog.value = true
}

async function duplicateProject(project) {
  try {
    // IMP-1002: list rows carry trimmed ProjectListResponse (no description).
    // Fetch the full detail so the duplicated project gets the real description
    // rather than an empty string degraded from the trimmed row.
    const fullProject = await projectStore.fetchProject(project.id)
    const sourceDescription = (fullProject || project).description || ''
    const createData = {
      name: project.name,
      description: `${sourceDescription} #2`.trim(),
      mission: '',
      status: 'inactive',
      project_type_id: null,
      series_number: null,
      subseries: null,
      product_id: activeProduct.value?.id,
    }
    await projectStore.createProject(createData)
    await reloadProjects()
    showToast({ message: `Duplicated project "${project.name}"`, type: 'success' })
  } catch (error) {
    console.error('[PROJECTS] Failed to duplicate project:', error)
    showToast({ message: error.response?.data?.detail || 'Failed to duplicate project', type: 'error' })
  }
}

async function toggleHidden(project) {
  try {
    // BE-2002: field stays `hidden` on the backend; UI copy says "archived".
    await projectStore.updateProject(project.id, { hidden: !project.hidden })
    showToast({ message: project.hidden ? `"${project.name}" restored from archive` : `"${project.name}" archived`, type: 'success' })
    // BE-6078: hidden is server-side now — reload so the row moves between the
    // visible list and the hidden set, and "Show hidden (N)" updates its count.
    await Promise.all([reloadProjects(), projectStore.fetchHiddenProjects()])
  } catch (error) {
    console.error('[PROJECTS] Failed to toggle hidden:', error)
    showToast({ message: 'Failed to update project visibility', type: 'error' })
  }
}

// FE-6180: in-chain tickboxes are disabled (passive indicator) — toggle only ever
// fires for a non-chain row. Back-out of a chain is the kebab Deactivate Chain.
function handleProjectToggle(item, toggle) {
  const projectId = item?.id
  if (!projectId) return
  if (!sequenceRunStore.isProjectInActiveChain(projectId)) toggle(item)
}

async function handleStatusAction({ action, projectId }) {
  try {
    switch (action) {
      case 'activate':
        await projectStore.activateProject(projectId)
        break
      case 'deactivate':
        await projectStore.deactivateProject(projectId)
        break
      case 'deactivate-chain': {
        // FE-6180: warn (destructive rewind) then dissolve the chain — BE resets EVERY member to original (clears staging + hard-deletes agents/jobs, no audit).
        const chainRun = sequenceRunStore.runForProject(projectId)
        if (!chainRun) {
          showToast({ message: 'Project is not in a chain run.', type: 'warning' })
          return
        }
        resetDialog.value = { show: true, kind: 'chain', runId: chainRun.id, projectId }
        return
      }
      case 'reset':
        // FE-6180: warn then reset a SOLO project to original (same destructive rewind).
        resetDialog.value = { show: true, kind: 'project', runId: null, projectId }
        return
      case 'complete': {
        const projectToClose = projectStore.projectById(projectId)
        if (projectToClose) {
          closeoutProjectId.value = projectId
          closeoutProjectName.value = projectToClose.name
          showCloseoutModal.value = true
        }
        break
      }
      case 'review': {
        const projectToReview = projectStore.projectById(projectId)
        reviewProjectId.value = projectId
        reviewProductId.value = projectToReview?.product_id
        showReviewModal.value = true
        break
      }
      case 'reopen':
        await api.projects.restore(projectId)
        break
      case 'cancel': {
        const projectToCancelById = projectStore.projectById(projectId)
        if (projectToCancelById) {
          projectToCancel.value = projectToCancelById
          showCancelDialog.value = true
        }
        return // Early return — dialog handles the action
      }
      case 'delete': {
        const projectToDeleteById = projectStore.projectById(projectId)
        if (projectToDeleteById) {
          confirmDelete(projectToDeleteById)
        }
        break
      }
      case 'park': // IMP-9258: generic PATCH (see ProjectsTable.vue statusActionDefs)
      case 'unpark':
        await projectStore.updateProject(projectId, { status: action === 'park' ? 'parked' : 'inactive' })
    }
    await reloadProjects()
  } catch (error) {
    console.error('Failed to perform action:', error)
    showToast({ message: 'Failed to update project status. Try refreshing the page to get the latest state.', type: 'error' })
    await reloadProjects()
  }
}

async function handleCloseoutComplete() {
  const projectIdToClear = closeoutProjectId.value
  showCloseoutModal.value = false
  closeoutProjectId.value = null
  closeoutProjectName.value = ''
  notificationStore.clearForProject(projectIdToClear)
  await reloadProjects()
}

function handleCloseoutClose() {
  showCloseoutModal.value = false
  closeoutProjectId.value = null
  closeoutProjectName.value = ''
}

function onDialogSaved() {
  editingProject.value = null
}

function onClearMissionConfirmed() {
  createEditDialogRef.value?.clearMissionData()
  showClearMissionDialog.value = false
}

function onTypeCreated() {
  // No-op: useProjectTaxonomy.handleTypeCreated already pushes to projectTypes
}

// Lifecycle
onMounted(async () => {
  projectStatusesStore.ensureLoaded().catch((error) => {
    console.warn('[ProjectsView] Failed to load project statuses:', error)
  })
  // FE-6165f: hydrate the active-chain set on mount so "In chain" state is
  // immediately visible. Re-hydrate on WS reconnect so a run that completed
  // while disconnected unlocks the checkboxes without a manual refresh.
  _unsubResync = registerReconnectResync(() => sequenceRunStore.hydrate())
  try {
    // BE-6076: load the active product FIRST so the server page query is scoped
    // to it (product_id), then fetch the first page + the active-project flag +
    // the hidden-count set + deleted. The table's own initial @update:options is
    // deduped against this fetch.
    await Promise.all([productStore.fetchProducts(), productStore.fetchActiveProduct()])
    await Promise.all([
      fetchPage(),
      projectStore.fetchActiveProject(),
      projectStore.fetchHiddenProjects(),
      projectStore.fetchDeletedProjects(),
      sequenceRunStore.hydrate(),
    ])
    try {
      const typesResponse = await api.taxonomyTypes.list()
      projectTypes.value = typesResponse.data || []
    } catch {
      console.error('Failed to load project types')
    }
  } catch (error) {
    console.error('Failed to load data:', error)
  }
})

// Drop the remembered server-mode query when leaving the page so the store's
// anti-clobber guard deactivates and other views that call a bare
// fetchProjects() (e.g. WelcomeView) get the true default list, not this
// page's last filter.
onUnmounted(() => {
  projectStore.clearListQuery()
  if (_unsubResync) _unsubResync()
})
</script>

<style lang="scss" scoped>
@use '../styles/variables' as *;
@use '../styles/design-tokens' as *;
@use '../styles/list-filter-bar' as filterBar;

@include filterBar.list-filter-bar;
@include filterBar.list-filter-bar-responsive;

/* CSS custom properties for template-level token references —
   moved here from ProjectsTable.vue so :deep(.v-container) targets
   this view's root element (the table has no v-container root). */
:deep(.v-container) {
  --color-status-success: #{$color-status-success};
  --color-text-muted: #{$color-text-muted};
}

.filter-select {
  /* ~20px wider than before: gives the "All statuses" summary room so the
     multi-select stays one row (the extra width comes off the flex:1 search). */
  flex: 0 0 180px;
}

/* BE-6078: compact summary inside the Status multi-select chip area. */
.status-summary {
  font-size: 0.85rem;
  color: $color-text-primary;
  /* Keep the summary on a single line so "All statuses" never wraps the field
     to two rows. */
  white-space: nowrap;
}

/* FE-6050: compact filter-bar row order (≤960px).
 * Row 1: New Project + Deleted (order 1) — primary CTAs float to top
 * Row 2: Search (order 2, full width) — search below CTAs
 * Row 3: Status + Archived toggle (order 3) — filter controls last
 * flex-basis: 100% on search forces it onto its own line between rows 1 and 3.
 */
@media (max-width: 960px) {
  .filter-bar > .v-text-field.filter-search {
    order: 2;
    flex-basis: 100%;
  }
  .filter-bar > .v-select.filter-select {
    order: 3;
  }
  .filter-bar > .filter-cta-archive {
    order: 3;
  }
  .filter-bar > .filter-cta-new {
    order: 1;
  }
  .filter-bar > .filter-cta-deleted {
    order: 1;
  }
}
</style>
