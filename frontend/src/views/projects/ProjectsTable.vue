<template>
  <v-card class="project-table-card smooth-border main-window-reveal main-window-delay-3">
    <div class="project-list-container">
      <!-- BE-6076: server mode — the server applies search/filter/sort/pagination.
           :items is the current page, :items-length the filtered total, and
           @update:options reports page/itemsPerPage/sortBy changes upward so the
           parent re-fetches (no client-side slicing or sort). -->
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
        <!-- FE-6131e: Select column — checkbox for sequential-run selection.
             Only INACTIVE projects are runnable, so only they get a checkbox.
             FE-6180: once a project is in an active chain (any pending/running/stalled
             run) its tickbox is a PASSIVE indicator — force-ticked + DISABLED by
             membership (inChainIds), not just run.locked. Back-out is via the kebab
             (Deactivate Chain), never by unticking. Non-chain rows tick freely. -->
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

        <!-- Name Column -->
        <template #item.name="{ item }">
          <div class="py-2">
            <span class="project-name-text">{{ item.name }}</span>
            <!-- BE-2002: "Archived" badge on archived (hidden) rows — surfaced so
                 search results that include archived projects are visibly tagged.
                 Backend field is `hidden`; UI calls it "archived". -->
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

        <!-- Serial Column (colorized tinted badge) -->
        <!-- FE-5061: badge is the sole click target for opening a project -->
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

        <!-- Quick Action Column — play button to activate + launch -->
        <template #item.quick_action="{ item }">
          <!-- FE-6178: no solo activate-launch for an in-chain project — it's part of an
               active chain; "Deactivate Chain" in the kebab is its only toggle. -->
          <v-tooltip v-if="normalizeStatus(item.status) === 'inactive' && !inChainIds.includes(item.id)" :text="electionActive ? 'Projects are elected — use Run Sequential to launch them' : (hasActiveProject ? 'Another project is active — complete or deactivate it first' : (isProjectStaged(item) ? 'Activate & resume' : 'Activate & launch'))">
            <template #activator="{ props: ttProps }">
              <button
                v-bind="ttProps"
                type="button"
                class="play-circle-btn icon-interactive-play"
                :class="{ 'play-btn-disabled': hasActiveProject || electionActive }"
                :disabled="hasActiveProject || electionActive"
                aria-label="Activate project"
                @click.stop="!hasActiveProject && !electionActive && $emit('activate-launch', item.id)"
              >
                <v-icon size="18">mdi-play</v-icon>
              </button>
            </template>
          </v-tooltip>
        </template>

        <!-- Staged Column (0870h: tinted style) -->
        <template #item.staging_status="{ item }">
          <v-icon
            v-if="isProjectStaged(item)"
            size="18"
            style="color: var(--color-accent-success)"
            aria-label="Staged"
          >mdi-check</v-icon>
          <span v-else class="staged-dash">—</span>
        </template>

        <!-- Created Date Column -->
        <template #item.created_at="{ item }">
          <span class="date-full date-cell">{{ formatDateWithTime(item.created_at) }}</span>
          <span class="date-compact date-cell">{{ formatDateCompactWithTime(item.created_at) }}</span>
        </template>

        <!-- Completed Date Column.
             BE-9343: no `|| item.updated_at` fallback. This column is headed COMPLETED
             but rendered last-modified, so ANY later write — including the archive/hide
             toggle, which is usually the last thing to touch a finished project —
             silently moved the date on screen, and it disagreed with the sort (which
             reads the real column). The backend now stamps completed_at on every
             terminal transition and ce_0088 backfilled the historical rows, so the real
             column is the one to show. A terminal row still lacking one gets the same
             em-dash as a running project rather than a borrowed date. -->
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

        <!-- Status Column (display-only badge).
             FE-6170: "In chain" pill shown here (moved from select cell).
             FE-6171b (item C): when a project is in-chain AND inactive, show ONE badge
             "In chain" using the inactive StatusBadge design token — REPLACING the
             inactive badge (kills the double [inactive][In chain] anti-pattern).
             FE-6221b: when a project is in-chain AND active/implementing, show the
             status badge AND an "In chain" pill alongside it — so chain membership
             is always visible regardless of the member's run phase, matching /roadmap. -->
        <template #item.status="{ item }">
          <div class="d-flex align-center justify-center gap-1 flex-wrap">
            <!-- FE-6171b: in-chain + inactive → single "In chain" badge using the SAME
                 styling as the inactive StatusBadge (the span reuses .in-chain-pill which
                 we now style identically to StatusBadge for inactive). The separate
                 inactive StatusBadge is suppressed for these rows. -->
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
            <!-- FE-6221b: in-chain + active/implementing → show the live status badge
                 AND an "In chain" pill. Members transition out of inactive when the
                 conductor drives them; their badge must reflect both the active state
                 and the chain membership. Matches /roadmap's persistent "In chain" pill. -->
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

        <!-- Actions Column -->
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
                <!-- FE-6178/6180: Deactivate Chain — back out of the WHOLE chain (resets
                     every member to original + dissolves the run). The single chain
                     back-out; the per-project Unlink was removed (FE-6180). -->
                <v-list-item
                  v-if="inChainIds.includes(item.id)"
                  prepend-icon="mdi-pause-circle-outline"
                  title="Deactivate Chain"
                  data-testid="deactivate-chain-item"
                  @click="$emit('status-action', { action: 'deactivate-chain', projectId: item.id })"
                ></v-list-item>
                <!-- FE-6180: Reset — return a SOLO staged/launched project to original
                     state (clears staging + agents/jobs, no audit). The chain equivalent
                     is Deactivate Chain above; hidden for chain members + clean projects. -->
                <v-list-item
                  v-if="!inChainIds.includes(item.id) && item.staging_status"
                  prepend-icon="mdi-backup-restore"
                  title="Reset to original"
                  data-testid="reset-project-item"
                  @click="$emit('status-action', { action: 'reset', projectId: item.id })"
                ></v-list-item>
                <!-- Status-aware actions (Activate is suppressed for in-chain projects) -->
                <v-list-item
                  v-for="sa in getStatusActions(item)"
                  :key="sa.key"
                  :prepend-icon="sa.icon"
                  :title="sa.label"
                  :class="sa.color ? `text-${sa.color}` : undefined"
                  @click="onStatusAction(sa.key, item)"
                ></v-list-item>

                <v-divider class="my-1" />

                <!-- Edit (not available for completed/cancelled/terminated) -->
                <v-list-item
                  v-if="!['completed', 'cancelled', 'terminated'].includes(normalizeStatus(item.status))"
                  prepend-icon="mdi-pencil"
                  title="Edit Project"
                  @click="$emit('edit-project', item)"
                ></v-list-item>
                <!-- Duplicate -->
                <v-list-item
                  prepend-icon="mdi-content-copy"
                  title="Duplicate"
                  @click="$emit('duplicate-project', item)"
                ></v-list-item>
                <!-- CE-OPT-4 / BE-2002: Archive/Unarchive toggle (backend field is
                     `hidden`; UI copy says "archived"). -->
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

        <!-- No data state -->
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

  <!-- BE-9157: Mark Superseded successor picker (self-contained store write).
       v-if so the store/Vuetify-dependent dialog only mounts when actually
       opened — never at table render (keeps presentational table specs green). -->
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
  // BE-6076: server mode — `projects` is the current page (not the full set).
  projects: {
    type: Array,
    required: true,
  },
  // BE-6076: filtered total from the server (X-Total-Count) for :items-length.
  total: {
    type: Number,
    default: 0,
  },
  loading: {
    type: Boolean,
    default: false,
  },
  hasActiveProject: {
    type: Boolean,
    default: false,
  },
  // Controlled by useProjectFilters in the parent (server-driven pagination/sort).
  currentPage: {
    type: Number,
    default: 1,
  },
  itemsPerPage: {
    type: Number,
    default: 10,
  },
  // Single-column server sort state owned by the parent composable.
  sortBy: {
    type: Array,
    default: () => [{ key: 'created_at', order: 'desc' }],
  },
  // FE-6131e: ids currently selected for a sequential run (drives the checkboxes).
  selectedIds: {
    type: Array,
    default: () => [],
  },
  // FE-6165a: true while ANY project is elected for a sequential run. Fades +
  // disables the per-row play button so the only launch affordance is Run
  // Sequential.
  electionActive: {
    type: Boolean,
    default: false,
  },
  // FE-6165f: project ids that are members of an active (in-flight) chain run.
  // Checkbox is force-ticked + locked (disabled) for these rows; an "In chain"
  // pill is rendered next to the checkbox.
  inChainIds: {
    type: Array,
    default: () => [],
  },
  // FE-6171b: project ids whose run is in the locked (Staged) tier (run.locked=true).
  // Drives tickbox disable on /projects. Distinct from inChainIds: a project in-chain
  // with run.locked=false (Editing tier) has its tickbox ENABLED for removeMember.
  lockedChainIds: {
    type: Array,
    default: () => [],
  },
  // FE-6176: link/chain mode — swaps the play-button "Actions" column for the
  // "Linked" checkbox column so users select projects for Run Sequential without
  // any play-button disable logic.
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
  // BE-6076: bundled page/itemsPerPage/sortBy change from v-data-table-server.
  'update:options',
  // FE-6131e: toggle a project's selection for a sequential run.
  'toggle-select',
])

// BE-9157: the "Mark Superseded" kebab action opens a self-contained successor
// picker here (rather than a parent-owned dialog) — the parent ProjectsView is
// held at its file-size budget, so the small feature lives with the trigger. The
// modal writes through the store (reactive status-chip update); on success we
// re-emit ``status-action`` so the parent reloads the list uniformly, exactly as
// it does after every other status action (the superseded row then filters out).
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
  // Uniform parent contract: any status action ends in a list reload.
  emit('status-action', { action: 'superseded', projectId: supersededId })
}

const { formatDateWithTime, formatDateCompactWithTime } = useFormatDate()

// FE-6050: responsive display breakpoint
const { smAndDown } = useDisplay()

// BE-9455: this table is SERVER-mode — every page size becomes an HTTP `limit`,
// so the options may only offer sizes the endpoint will actually serve (max
// API_MAX_PAGE_SIZE). Vuetify's default list ends in `{ value: -1, title: 'All' }`,
// and that "All" could never be honoured here: the server caps a page well below
// this tenant's project count, so the option promised something no single request
// can return, and shipped a 422 instead of a wider list. Offering the true
// maximum is the honest version of it — a control that cannot keep its promise is
// worse than one that is absent. (Plain client-side v-data-table mounts elsewhere
// keep their "All"; there it is true, because they already hold every row.)
const itemsPerPageOptions = [10, 25, 50, 100, API_MAX_PAGE_SIZE]

// FE-6176: Two header variants per breakpoint.
// Normal  → play-button "Actions" column; no checkbox column (de-clutter).
// Link    → "Linked" checkbox column placed after Completed; no play-button column.
// The select (checkbox) and quick_action (play) slots are defined in the template
// for both keys; the headers array determines which one actually renders.
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

// FE-2004: the collapsed status dot must carry the SAME active color as the
// full-size StatusBadge pill, which resolves the `color-agent-implementer`
// token (#6db3e4, blue). Sourcing from getAgentColor('implementer') keeps the
// dot and pill on one color source — the old COLOR_SURFACE (#ffffff) rendered
// the active dot white in the ≤1280px collapsed view.
const DOT_ACTIVE = getAgentColor('implementer').hex

// IMP-9258: the collapsed "parked" dot mirrors the full-size StatusBadge pill,
// which resolves the `color-agent-reviewer` (Lavender) token — same technique
// as DOT_ACTIVE above, so the dot and pill never drift onto separate palettes.
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
  // IMP-9258: Park sets a project aside without cancelling it — non-destructive
  // and fully resumable (unlike Cancel), so no confirm dialog.
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
  // IMP-9258: parked is a two-way door (not lifecycle-finished, not immutable)
  // — its only status-aware action is Unpark, straight back to inactive.
  parked: ['unpark'],
}

function getStatusActions(item) {
  const normalized = normalizeStatus(item.status)
  let keys = [...(actionsByStatus[normalized] || [])]
  if (normalized === 'cancelled' && !isProjectStaged(item)) {
    keys.unshift('reopen')
  }
  // FE-6178: a project in a chain IS the activated chain member — "Deactivate Chain"
  // is its single activate/deactivate counterpart, so suppress the solo
  // activate/deactivate actions (they'd be wrong: you back out the whole chain, not
  // one member). complete/cancel/review stay available.
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

/* ── Compact breakpoint (≤1280px) ── */
@media (max-width: 1280px) {
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

/* ── Mobile breakpoint (≤600px) ── */
@media (max-width: 600px) {
  .project-id-text {
    display: none;
  }
}
</style>
