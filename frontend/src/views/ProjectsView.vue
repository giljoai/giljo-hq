<template>
  <v-container>
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

    <v-alert v-if="!activeProduct" type="info" variant="tonal" class="ma-4 main-window-reveal main-window-delay-2" closable>
      No product is open. Add a product to view and manage its projects.
    </v-alert>

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
        <template #selection="{ index }">
          <span v-if="index === 0" class="status-summary">{{ statusSummary }}</span>
        </template>
      </v-select>
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
      <DeletedCountButton
        :count="deletedCount"
        entity="projects"
        class="filter-cta-deleted"
        @click="showDeletedDialog = true"
      />
    </div>

    <SequenceLauncher v-if="activeProduct" v-slot="{ selectedIds, toggle, electionActive }">
    <ProjectsTable
      :current-page="currentPage"
      :items-per-page="itemsPerPage"
      :sort-by="sortBy"
      :projects="projects"
      :total="projectsTotal"
      :loading="loading"
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

    <ProjectDeletedDialog
      v-model="showDeletedDialog"
      :deleted-projects="deletedProjects"
      :purging-project-id="purgingProjectId"
      :purging-all-deleted="purgingAllDeleted"
      @restore="restoreFromDelete"
      @purge="confirmPurgeDeleted"
      @purge-all="confirmPurgeAllDeleted"
    />

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
import DeletedCountButton from '@/components/common/DeletedCountButton.vue'
import ProjectCreateEditDialog from '@/components/projects/ProjectCreateEditDialog.vue'
import ProjectDeletedDialog from '@/components/projects/ProjectDeletedDialog.vue'
import api from '@/services/api'
import { useToast } from '@/composables/useToast'
import { useFormatDate } from '@/composables/useFormatDate'
import { useProjectFilters } from '@/composables/useProjectFilters'
import { useProjectDeletion } from '@/composables/useProjectDeletion'
import ProjectsTable from './projects/ProjectsTable.vue'
import SequenceLauncher from '@/components/sequence/SequenceLauncher.vue'

const router = useRouter()

const projectStore = useProjectStore()
const productStore = useProductStore()
const notificationStore = useNotificationStore()
const projectStatusesStore = useProjectStatusesStore()
const sequenceRunStore = useSequenceRunStore()
const { statuses: projectStatuses } = storeToRefs(projectStatusesStore)

const linkMode = ref(false)

const lockedChainProjectIds = computed(() =>
  sequenceRunStore.activeChainProjectIds.filter((pid) => sequenceRunStore.isProjectRunLocked(pid)),
)
const chainActive = computed(() => sequenceRunStore.activeChainProjectIds.length > 0)

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

let _unsubResync = null

const createEditDialogRef = ref(null)

const showCreateDialog = ref(false)
const showDeletedDialog = ref(false)
const showCloseoutModal = ref(false)
const showClearMissionDialog = ref(false)
const showReviewModal = ref(false)

const editingProject = ref(null)

const closeoutProjectId = ref(null)
const closeoutProjectName = ref('')
const reviewProjectId = ref(null)
const reviewProductId = ref(null)

const projectTypes = ref([])

const activeProduct = computed(() => productStore.currentProduct)
const projects = computed(() => projectStore.projects)
const projectsTotal = computed(() => projectStore.projectsTotal)
const loading = computed(() => projectStore.loading)
const deletedProjects = computed(() => projectStore.deletedProjects)
const deletedCount = computed(() => deletedProjects.value.length)

const showHidden = ref(false)
const hiddenProjects = computed(() => projectStore.hiddenProjects)

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

let _lastParamsJson = null
let _searchDebounce = null

async function fetchPage() {
  const params = buildServerParams()
  const json = JSON.stringify(params)
  if (json === _lastParamsJson) return
  _lastParamsJson = json
  await projectStore.fetchProjects(params)
}

function onTableOptions(options) {
  if (!options) return
  if (typeof options.page === 'number') currentPage.value = options.page
  if (typeof options.itemsPerPage === 'number') itemsPerPage.value = options.itemsPerPage
  if (Array.isArray(options.sortBy)) sortBy.value = options.sortBy
  fetchPage()
}

watch(searchQuery, () => {
  if (_searchDebounce) clearTimeout(_searchDebounce)
  _searchDebounce = setTimeout(() => {
    currentPage.value = 1
    fetchPage()
  }, 300)
})

watch(
  [selectedStatuses, showHidden],
  () => {
    currentPage.value = 1
    fetchPage()
  },
  { deep: true },
)

const statusSummary = computed(() => {
  const total = statusSelectOptions.value.length
  const n = selectedStatuses.value.length
  if (total > 0 && n === total) return 'All statuses'
  if (n === 0) return 'No statuses'
  return `${n} selected`
})

async function reloadProjects() {
  _lastParamsJson = null
  await Promise.all([fetchPage(), projectStore.fetchActiveProject()])
}

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

async function onToggleShowHidden() {
  if (!showHidden.value) {
    await projectStore.fetchHiddenProjects()
  }
  showHidden.value = !showHidden.value
}

async function activateAndLaunch(projectId) {
  await projectStore.activateProject(projectId)
  const project = projectStore.projects.find((p) => p.id === projectId)
  const staged = project && (project.staging_status === 'staged' || project.staging_status === 'staging_complete')
  router.push({ name: 'ProjectLaunch', params: { projectId }, query: { via: 'jobs', ...(staged ? { tab: 'jobs' } : {}) } })
}

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
    await projectStore.updateProject(project.id, { hidden: !project.hidden })
    showToast({ message: project.hidden ? `"${project.name}" restored from archive` : `"${project.name}" archived`, type: 'success' })
    await Promise.all([reloadProjects(), projectStore.fetchHiddenProjects()])
  } catch (error) {
    console.error('[PROJECTS] Failed to toggle hidden:', error)
    showToast({ message: 'Failed to update project visibility', type: 'error' })
  }
}

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
        const chainRun = sequenceRunStore.runForProject(projectId)
        if (!chainRun) {
          showToast({ message: 'Project is not in a chain run.', type: 'warning' })
          return
        }
        resetDialog.value = { show: true, kind: 'chain', runId: chainRun.id, projectId }
        return
      }
      case 'reset':
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
        return
      }
      case 'delete': {
        const projectToDeleteById = projectStore.projectById(projectId)
        if (projectToDeleteById) {
          confirmDelete(projectToDeleteById)
        }
        break
      }
      case 'park':
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

onMounted(async () => {
  projectStatusesStore.ensureLoaded().catch((error) => {
    console.warn('[ProjectsView] Failed to load project statuses:', error)
  })
  _unsubResync = registerReconnectResync(() => sequenceRunStore.hydrate())
  try {
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
