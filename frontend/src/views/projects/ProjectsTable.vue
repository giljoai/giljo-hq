<template>
  <v-card class="project-table-card smooth-border main-window-reveal main-window-delay-3">
    <div class="project-list-container">
      <v-data-table-server
        :headers="headers"
        :items="projects"
        :items-length="total"
        :loading="loading"
        :items-per-page="itemsPerPage"
        :items-per-page-options="itemsPerPageOptions"
        :page="currentPage"
        :sort-by="sortBy"
        must-sort
        class="elevation-0"
        item-key="id"
        fixed-header
        :item-props="getRowProps"
        @update:options="$emit('update:options', $event)"
      >
        <template #item.select="{ item }">
          <div v-if="normalizeStatus(item.status) === 'inactive'" class="select-cell">
            <v-checkbox-btn
              :model-value="selectedIds.includes(item.id) || inChainIds.includes(item.id)"
              :disabled="inChainIds.includes(item.id)"
              density="compact"
              hide-details
              :aria-label="`Select ${item.taxonomy_alias || item.name} for a sequential run`"
              :data-testid="`project-select-checkbox-${item.id}`"
              @click.stop
              @update:model-value="$emit('toggle-select', item)"
            />
          </div>
        </template>

        <template #item.name="{ item }">
          <div class="py-2">
            <span class="project-name-text">{{ item.name }}</span>
            <v-chip
              v-if="item.hidden"
              size="x-small"
              color="warning"
              variant="tonal"
              prepend-icon="mdi-archive"
              class="ml-2 archived-badge"
              data-test="project-archived-badge"
            >Archived</v-chip>
            <div class="project-uuid-text project-id-text">
              Project ID: {{ item.id }}
            </div>
          </div>
        </template>

        <template #item.series_number="{ item }">
          <button
            v-if="item.taxonomy_alias"
            type="button"
            class="project-id-badge"
            :style="taxonomyBadgeStyle(resolveTaxonomyColor({
              abbreviation: item.project_type?.abbreviation,
              alias: item.taxonomy_alias,
              color: item.project_type?.color,
            }))"
            :title="isReservedTaskAlias(item.taxonomy_alias) ? 'Converted from task' : undefined"
            :aria-label="isReservedTaskAlias(item.taxonomy_alias)
              ? `Open project ${item.taxonomy_alias} (converted from task)`
              : `Open project ${item.taxonomy_alias}`"
            @click.stop="$emit('open-project', item)"
          >
            {{ item.taxonomy_alias }}
          </button>
          <span v-else class="staged-dash">—</span>
        </template>

        <template #item.quick_action="{ item }">
          <v-tooltip v-if="normalizeStatus(item.status) === 'inactive' && !inChainIds.includes(item.id)" :text="electionActive ? 'Projects are elected — use Run Sequential to launch them' : (isProjectStaged(item) ? 'Activate & resume' : 'Activate & launch')">
            <template #activator="{ props: ttProps }">
              <button
                v-bind="ttProps"
                type="button"
                class="play-circle-btn icon-interactive-play"
                :class="{ 'play-btn-disabled': electionActive }"
                :disabled="electionActive"
                aria-label="Activate project"
                @click.stop="!electionActive && $emit('activate-launch', item.id)"
              >
                <v-icon size="18">mdi-play</v-icon>
              </button>
            </template>
          </v-tooltip>
        </template>

        <template #item.staging_status="{ item }">
          <v-icon
            v-if="isProjectStaged(item)"
            size="18"
            style="color: var(--color-accent-success)"
            aria-label="Staged"
          >mdi-check</v-icon>
          <span v-else class="staged-dash">—</span>
        </template>

        <template #item.created_at="{ item }">
          <span class="date-full date-cell">{{ formatDateWithTime(item.created_at) }}</span>
          <span class="date-compact date-cell">{{ formatDateCompactWithTime(item.created_at) }}</span>
        </template>

        <template #item.completed_at="{ item }">
          <div class="text-center">
            <template
              v-if="(item.status === 'completed' || item.status === 'cancelled' || item.status === 'terminated') && item.completed_at"
            >
              <span class="date-full date-cell">{{ formatDateWithTime(item.completed_at) }}</span>
              <span class="date-compact date-cell">{{ formatDateCompactWithTime(item.completed_at) }}</span>
            </template>
            <template v-else><span class="date-cell date-cell--empty">—</span></template>
          </div>
        </template>

        <template #item.status="{ item }">
          <div class="d-flex align-center justify-center gap-1 flex-wrap">
            <template v-if="inChainIds.includes(item.id) && normalizeStatus(item.status) === 'inactive'">
              <span
                class="in-chain-pill"
                data-testid="project-in-chain-pill"
              >In chain</span>
              <v-tooltip text="inactive (in chain)">
                <template #activator="{ props: ttProps }">
                  <span
                    v-bind="ttProps"
                    class="status-dot"
                    :style="{ backgroundColor: statusDotColor('inactive') }"
                  >C</span>
                </template>
              </v-tooltip>
            </template>
            <template v-else-if="inChainIds.includes(item.id)">
              <span class="status-full d-flex align-center gap-1">
                <StatusBadge :status="normalizeStatus(item.status)" />
                <span
                  class="in-chain-pill"
                  data-testid="project-in-chain-pill"
                >In chain</span>
              </span>
              <v-tooltip :text="`${normalizeStatus(item.status)} (in chain)`">
                <template #activator="{ props: ttProps }">
                  <span
                    v-bind="ttProps"
                    class="status-dot"
                    :style="{ backgroundColor: statusDotColor(normalizeStatus(item.status)) }"
                  >{{ normalizeStatus(item.status).charAt(0).toUpperCase() }}</span>
                </template>
              </v-tooltip>
            </template>
            <template v-else>
              <span class="status-full">
                <StatusBadge :status="normalizeStatus(item.status)" />
              </span>
              <v-tooltip :text="normalizeStatus(item.status)">
                <template #activator="{ props: ttProps }">
                  <span
                    v-bind="ttProps"
                    class="status-dot"
                    :style="{ backgroundColor: statusDotColor(normalizeStatus(item.status)) }"
                  >{{ normalizeStatus(item.status).charAt(0).toUpperCase() }}</span>
                </template>
              </v-tooltip>
            </template>
          </div>
        </template>

        <template #item.menu="{ item }">
          <div class="d-flex align-center justify-center">
            <v-menu>
              <template #activator="{ props }">
                <v-btn
                  icon="mdi-dots-vertical"
                  size="small"
                  variant="text"
                  v-bind="props"
                  aria-label="Project actions"
                ></v-btn>
              </template>

              <v-list density="compact" min-width="180">
                <v-list-item
                  v-if="inChainIds.includes(item.id)"
                  prepend-icon="mdi-pause-circle-outline"
                  title="Deactivate Chain"
                  data-testid="deactivate-chain-item"
                  @click="$emit('status-action', { action: 'deactivate-chain', projectId: item.id })"
                ></v-list-item>
                <v-list-item
                  v-if="!inChainIds.includes(item.id) && item.staging_status"
                  prepend-icon="mdi-backup-restore"
                  title="Reset to original"
                  data-testid="reset-project-item"
                  @click="$emit('status-action', { action: 'reset', projectId: item.id })"
                ></v-list-item>
                <v-list-item
                  v-for="sa in getStatusActions(item)"
                  :key="sa.key"
                  :prepend-icon="sa.icon"
                  :title="sa.label"
                  :class="sa.color ? `text-${sa.color}` : undefined"
                  @click="onStatusAction(sa.key, item)"
                ></v-list-item>

                <v-divider class="my-1" />

                <v-list-item
                  v-if="!['completed', 'cancelled', 'terminated'].includes(normalizeStatus(item.status))"
                  prepend-icon="mdi-pencil"
                  title="Edit Project"
                  @click="$emit('edit-project', item)"
                ></v-list-item>
                <v-list-item
                  prepend-icon="mdi-content-copy"
                  title="Duplicate"
                  @click="$emit('duplicate-project', item)"
                ></v-list-item>
                <v-list-item
                  :prepend-icon="item.hidden ? 'mdi-archive-arrow-up' : 'mdi-archive'"
                  :title="item.hidden ? 'Unarchive' : 'Archive'"
                  @click="$emit('toggle-hidden', item)"
                ></v-list-item>
                <v-divider class="my-1" />
                <v-list-item
                  prepend-icon="mdi-delete"
                  title="Delete Project"
                  class="text-error"
                  @click="$emit('confirm-delete', item)"
                ></v-list-item>
              </v-list>
            </v-menu>
          </div>
        </template>

        <template #no-data>
          <div class="text-center py-8">
            <v-icon size="48" color="medium-emphasis" class="mb-4">mdi-folder-open</v-icon>
            <p class="text-body-medium text-muted-a11y">No projects found</p>
            <v-btn size="small" color="primary" class="mt-4" @click="$emit('new-project')">
              Create First Project
            </v-btn>
          </div>
        </template>
      </v-data-table-server>
    </div>
  </v-card>

  <SupersedeProjectModal
    v-if="showSupersedeModal"
    :show="showSupersedeModal"
    :project-id="supersedeProjectId"
    :project-name="supersedeProjectName"
    @close="showSupersedeModal = false; supersedeProjectId = null; supersedeProjectName = ''"
    @superseded="onSupersedeDone"
  />
</template>

<script setup>
import { computed, ref } from 'vue'
import { useDisplay } from 'vuetify'
import { TEXT_MUTED_MATERIAL as DOT_MUTED, DOT_SUCCESS, DOT_WARNING, DOT_ERROR } from '@/config/colorTokens'
import { getAgentColor } from '@/config/agentColors'
import StatusBadge from '@/components/StatusBadge.vue'
import SupersedeProjectModal from '@/components/projects/SupersedeProjectModal.vue'
import { taxonomyBadgeStyle, resolveTaxonomyColor, isReservedTaskAlias } from '@/utils/taxonomyBadge'
import { useFormatDate } from '@/composables/useFormatDate'
import { API_MAX_PAGE_SIZE } from '@/composables/useProjectFilters'

const props = defineProps({
  projects: {
    type: Array,
    required: true,
  },
  total: {
    type: Number,
    default: 0,
  },
  loading: {
    type: Boolean,
    default: false,
  },
  currentPage: {
    type: Number,
    default: 1,
  },
  itemsPerPage: {
    type: Number,
    default: 10,
  },
  sortBy: {
    type: Array,
    default: () => [{ key: 'created_at', order: 'desc' }],
  },
  selectedIds: {
    type: Array,
    default: () => [],
  },
  electionActive: {
    type: Boolean,
    default: false,
  },
  inChainIds: {
    type: Array,
    default: () => [],
  },
  lockedChainIds: {
    type: Array,
    default: () => [],
  },
  linkMode: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits([
  'open-project',
  'activate-launch',
  'status-action',
  'edit-project',
  'duplicate-project',
  'toggle-hidden',
  'confirm-delete',
  'new-project',
  'update:options',
  'toggle-select',
])

const showSupersedeModal = ref(false)
const supersedeProjectId = ref(null)
const supersedeProjectName = ref('')

function onStatusAction(action, item) {
  if (action === 'superseded') {
    supersedeProjectId.value = item.id
    supersedeProjectName.value = item.name
    showSupersedeModal.value = true
    return
  }
  emit('status-action', { action, projectId: item.id })
}

function onSupersedeDone() {
  const supersededId = supersedeProjectId.value
  showSupersedeModal.value = false
  supersedeProjectId.value = null
  supersedeProjectName.value = ''
  emit('status-action', { action: 'superseded', projectId: supersededId })
}

const { formatDateWithTime, formatDateCompactWithTime } = useFormatDate()

const { smAndDown } = useDisplay()

const itemsPerPageOptions = [10, 25, 50, 100, API_MAX_PAGE_SIZE]

const FULL_BASE = [
  { title: 'Serial', key: 'series_number', sortable: true, width: '10%' },
  { title: 'Name', key: 'name', sortable: true, width: '28%' },
  { title: 'Status', key: 'status', sortable: true, width: '14%', align: 'center' },
  { title: 'Staged', key: 'staging_status', sortable: true, width: '9%', align: 'center' },
  { title: 'Created', key: 'created_at', sortable: true, width: '13%' },
  { title: 'Completed', key: 'completed_at', sortable: true, width: '13%', align: 'center' },
]
const FULL_HEADERS_NORMAL = [
  ...FULL_BASE,
  { title: 'Actions', key: 'quick_action', sortable: false, width: '5%', align: 'center' },
  { title: '', key: 'menu', sortable: false, width: '3%', align: 'center' },
]
const FULL_HEADERS_LINK = [
  ...FULL_BASE,
  { title: 'Linked', key: 'select', sortable: false, width: '8%', align: 'center' },
  { title: '', key: 'menu', sortable: false, width: '3%', align: 'center' },
]
const COMPACT_HEADERS_NORMAL = [
  { title: 'Serial', key: 'series_number', sortable: true, width: '40%' },
  { title: 'Status', key: 'status', sortable: true, width: '30%', align: 'center' },
  { title: 'Actions', key: 'quick_action', sortable: false, width: '20%', align: 'center' },
  { title: '', key: 'menu', sortable: false, width: '10%', align: 'center' },
]
const COMPACT_HEADERS_LINK = [
  { title: 'Serial', key: 'series_number', sortable: true, width: '45%' },
  { title: 'Status', key: 'status', sortable: true, width: '30%', align: 'center' },
  { title: 'Linked', key: 'select', sortable: false, width: '25%', align: 'center' },
]
const headers = computed(() => {
  if (smAndDown.value) return props.linkMode ? COMPACT_HEADERS_LINK : COMPACT_HEADERS_NORMAL
  return props.linkMode ? FULL_HEADERS_LINK : FULL_HEADERS_NORMAL
})

function getRowProps({ item }) {
  const rowProps = { 'data-testid': 'project-card' }
  if (normalizeStatus(item.status) === 'cancelled') {
    rowProps.class = 'cancelled-row'
  }
  return rowProps
}

const DOT_ACTIVE = getAgentColor('implementer').hex

const DOT_PARKED = getAgentColor('reviewer').hex

function statusDotColor(status) {
  const colors = {
    active: DOT_ACTIVE,
    inactive: DOT_MUTED,
    completed: DOT_SUCCESS,
    cancelled: DOT_WARNING,
    terminated: DOT_ERROR,
    deleted: DOT_ERROR,
    parked: DOT_PARKED,
  }
  return colors[status] || DOT_MUTED
}

const isProjectStaged = (project) =>
  project.staging_status === 'staged' || project.staging_status === 'staging_complete'

function normalizeStatus(status) {
  return status || 'inactive'
}

const statusActionDefs = {
  activate: { label: 'Activate', icon: 'mdi-play-circle', color: 'success', confirm: false },
  deactivate: { label: 'Deactivate', icon: 'mdi-pause-circle', color: null, confirm: true },
  complete: { label: 'Complete', icon: 'mdi-check-circle', color: null, confirm: true },
  cancel: { label: 'Cancel Project', icon: 'mdi-cancel', color: 'warning', confirm: true },
  park: { label: 'Park Project', icon: 'mdi-parking', color: null, confirm: false },
  unpark: { label: 'Unpark', icon: 'mdi-play-circle-outline', color: 'success', confirm: false },
  reopen: { label: 'Reopen', icon: 'mdi-refresh', color: 'success', confirm: false },
  review: { label: 'Review', icon: 'mdi-eye', color: null, confirm: false },
  superseded: { label: 'Mark Superseded', icon: 'mdi-file-replace-outline', color: null, confirm: false },
}

const actionsByStatus = {
  inactive: ['activate', 'complete', 'cancel', 'park', 'superseded'],
  active: ['deactivate', 'complete', 'cancel', 'park', 'superseded'],
  completed: ['review', 'superseded'],
  cancelled: ['review'],
  terminated: ['review'],
  parked: ['unpark'],
}

function getStatusActions(item) {
  const normalized = normalizeStatus(item.status)
  let keys = [...(actionsByStatus[normalized] || [])]
  if (normalized === 'cancelled' && !isProjectStaged(item)) {
    keys.unshift('reopen')
  }
  if (props.inChainIds.includes(item.id)) {
    keys = keys.filter((key) => key !== 'activate' && key !== 'deactivate')
  }
  return keys.map((key) => ({ key, ...statusActionDefs[key] }))
}
</script>

<style lang="scss" scoped>
@use '../../styles/variables' as *;
@use '../../styles/design-tokens' as *;

/* 0873: smooth-border table panel */
.project-table-card {
  border: none !important;
  border-radius: $border-radius-rounded !important;
  overflow: hidden;

  :deep(.v-table) {
    background: transparent;
  }

  :deep(.v-data-table__th) {
    background: transparent !important;
  }
}

/* Cancelled project rows: greyed out for visual distinction */
:deep(.cancelled-row) {
  opacity: 0.5;
}

/* 0870h: table header styling */
:deep(.v-data-table__thead th) {
  @include table-header-label;
  border-bottom: 1px solid $color-border-subtle !important;
}

/* 0870h: table cell row separators */
:deep(.v-data-table__td) {
  @include table-row-separator;
}

:deep(.v-data-table__tr:last-child .v-data-table__td) {
  border-bottom: none !important;
}

/* Project list container — no height constraint */
.project-list-container {
  overflow: visible;
}

.project-list-container :deep(.v-table__wrapper) {
  overflow: visible;
}

/* 0870h: Square tinted project ID badge.
   FE-5061: now a <button> */
.project-id-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border: none;
  border-radius: $border-radius-sharp;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
}

.project-id-badge:focus-visible {
  outline: 2px solid $color-brand-yellow;
  outline-offset: 2px;
}

/* 0870h: Project name text */
.project-name-text {
  font-size: 0.82rem;
  font-weight: 500;
}

/* 0870h: Project UUID text */
.project-uuid-text {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem;
  color: var(--text-muted);
  margin-top: 2px;
}

/* 0870h: Date cell styling */
.date-cell {
  font-size: 0.72rem;
  color: var(--text-secondary);
  white-space: nowrap;
}

.date-cell--empty {
  color: var(--text-muted);
}

/* Staged column: check or dash */
.staged-dash {
  color: var(--text-muted);
  font-size: 0.85rem;
}

/* Force center alignment on Staged column cells (3rd column) */
.project-table-card :deep(td:nth-child(3)) {
  text-align: center;
}

/* FE-6165f: select cell wrapper (checkbox only — pill moved to status col in FE-6170). */
.select-cell {
  display: flex;
  align-items: center;
}

/* FE-6165f / FE-6170: "In chain" badge (now in Status column). Tinted badge —
   FE-6171b (item C): uses the same design token as the inactive StatusBadge
   so "In chain" replaces (not appends to) the inactive badge visually.
   --text-muted (#8895a8) is the canonical inactive badge color. */
.in-chain-pill {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 8px; /* tinted badge = 8px radius per design-system */
  font-size: 0.68rem;
  font-weight: 600;
  white-space: nowrap;
  line-height: 1.4;
  /* Mirrors StatusBadge inactive: rgba(--text-muted, 0.15) bg + full-brightness text */
  background-color: rgba(136, 149, 168, 0.15);
  color: var(--text-muted, #8895a8);
}

/* Play-circle activate button */
.play-circle-btn {
  width: 32px;
  height: 32px;
  border: none !important;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
}

.play-circle-btn :deep(.v-icon) {
  color: $color-brand-yellow;
}

.play-btn-disabled {
  opacity: 0.3;
  cursor: not-allowed;
  pointer-events: none;
}

/* ── Responsive compact elements ── */
.status-dot,
.date-compact {
  display: none;
}

.status-dot {
  width: 22px;
  height: 22px;
  min-width: 22px;
  border-radius: 50%;
  font-size: 11px;
  font-weight: 700;
  color: $darkest-blue;
  line-height: 22px;
  text-align: center;
}

/* ── Compact breakpoint (FE-9536: shared $breakpoint-compact = 1280px) ── */
@media (max-width: $breakpoint-compact) {
  .status-full,
  .date-full {
    display: none !important;
  }
  .status-dot,
  .date-compact {
    display: inline-block;
  }
  .project-id-text {
    display: none;
  }
}

/* ── Mobile breakpoint (FE-9536: shared $breakpoint-mobile = 600px) ── */
@media (max-width: $breakpoint-mobile) {
  .project-id-text {
    display: none;
  }
}
</style>
