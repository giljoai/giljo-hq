<template>
  <div>
    <!-- Title (above filter bar) -->
    <div class="tab-header mb-4 d-flex align-center">
      <h2 class="text-title-large">Agent Template Manager</h2>
      <v-tooltip location="bottom" max-width="360">
        <template #activator="{ props }">
          <v-icon v-bind="props" size="small" class="ml-2" color="medium-emphasis"
            >mdi-help-circle-outline</v-icon
          >
        </template>
        <span
          >Each active agent template consumes context tokens during orchestration. The 16-slot limit
          keeps prompt budgets manageable. 1 slot is reserved for the Orchestrator (managed in Admin
          Settings), leaving 15 for your custom agents. Run the giljo_setup tool (choose "Agents only")
          in your CLI tool to install or update templates.</span
        >
      </v-tooltip>
      <v-chip
        v-if="totalActiveAgents !== null"
        :color="remainingUserSlots === 0 ? 'warning' : 'default'"
        size="small"
        variant="tonal"
        class="ml-4"
      >
        {{ totalActiveAgents }} / {{ totalCapacity }}
      </v-chip>
    </div>

    <!-- Stale templates banner -->
    <v-alert
      v-if="hasStaleTemplates"
      type="warning"
      variant="tonal"
      density="compact"
      class="mb-4"
      icon="mdi-alert-circle-outline"
    >
      You need to update the agent templates, please run the <strong>giljo_setup</strong> tool (choose "Agents only") in your CLI tool.
    </v-alert>

    <!-- HITL Closeout Toggle -->
    <div class="hitl-toggle-bar">
      <v-switch
        v-model="closeoutModeHitl"
        color="primary"
        density="compact"
        hide-details
        aria-label="Require user approval before project closeout"
        data-testid="closeout-mode-toggle"
        @update:model-value="toggleCloseoutMode"
      />
      <span class="hitl-toggle-label">Require approval before closeout</span>
      <v-tooltip location="bottom" max-width="340">
        <template #activator="{ props }">
          <v-icon v-bind="props" size="16" class="hitl-toggle-info">mdi-information-outline</v-icon>
        </template>
        When enabled, the orchestrator pauses for your review before closing a project — but only if there are deferred findings to review. Clean closeouts proceed automatically.
      </v-tooltip>
    </div>

    <!-- BE-9084: Headless vs HITL launch toggle (account-wide, default HITL) -->
    <div class="hitl-toggle-bar">
      <v-switch
        v-model="allowHeadless"
        color="primary"
        density="compact"
        hide-details
        aria-label="Allow a headless CLI agent to self-advance from staging to implementation"
        data-testid="headless-launch-toggle"
        @update:model-value="toggleHeadless"
      />
      <span class="hitl-toggle-label">Allow headless CLI self-advance (skip the Implement click)</span>
      <v-tooltip location="bottom" max-width="360">
        <template #activator="{ props }">
          <v-icon v-bind="props" size="16" class="hitl-toggle-info">mdi-information-outline</v-icon>
        </template>
        This governs in-application, server-mediated launches only — the MCP launch_implementation tool that OAuth agent sessions use to advance a project from staging to building. Off (the default) keeps a human in the loop: the server will not authorize that launch until you press Implement. On lets a trusted CLI/OAuth agent self-advance without a click; only enable it for autonomous workflows you trust. It does not gate direct CLI interaction — an agent that reads a project and simply runs it locally never asks the server, so this toggle cannot reach it. Note: HITL guarantees the server will not authorize implementation early, but it cannot stop a non-compliant local orchestrator from inlining its own mission into an in-process subagent and working off the books (an accepted residual of local execution).
      </v-tooltip>
    </div>

    <!-- Filter bar with New Template button right-aligned -->
    <div class="filter-bar">
      <v-text-field
        v-model="search"
        prepend-inner-icon="mdi-magnify"
        placeholder="Search templates..."
        variant="solo"
        density="compact"
        clearable
        hide-details
        flat
        class="filter-search"
      />
      <v-select
        v-model="filterRole"
        :items="availableRoles"
        placeholder="Role"
        clearable
        variant="solo"
        flat
        density="compact"
        hide-details
        class="filter-select"
      />
      <v-select
        v-model="filterStatus"
        :items="statusOptions"
        placeholder="Status"
        clearable
        variant="solo"
        flat
        density="compact"
        hide-details
        class="filter-select"
      />
      <v-btn
        variant="tonal"
        color="primary"
        prepend-icon="mdi-account-multiple-plus"
        aria-label="Add default agents"
        :loading="importingDefaults"
        @click="importDefaultAgents"
      >
        Add Default Agents
      </v-btn>
      <v-btn
        color="primary"
        prepend-icon="mdi-plus"
        aria-label="Create new template"
        @click="openCreateDialog"
      >
        New Template
      </v-btn>
    </div>

    <v-card class="template-manager smooth-border">
      <v-card-text>
        <!-- Templates Table (presentational child) -->
        <TemplatesTable
          :templates="filteredTemplates"
          :loading="loading"
          :headers="headers"
          :search="search"
          :remaining-user-slots="remainingUserSlots"
          :user-agent-limit="userAgentLimit"
          @toggle-active="handleToggleActive"
          @edit="editTemplate"
          @duplicate="duplicateTemplate"
          @reset="confirmReset"
          @delete="confirmDelete"
          @mark-user-managed="markUserManaged"
        />
      </v-card-text>

      <!-- Create/Edit Dialog (presentational child) -->
      <TemplateEditDialog
        v-model="editDialog"
        :template="editingTemplate"
        :saving="saving"
        :generated-name="generatedName"
        :role-options="roleOptions"
        :has-changes="hasChanges"
        @save="saveTemplate"
        @close="closeEditDialog"
        @role-change="onRoleChange"
        @update:template="onUpdateTemplate"
      />

      <!-- Delete Confirmation Dialog -->
      <v-dialog v-model="deleteDialog" max-width="500px" persistent retain-focus>
        <v-card v-draggable class="smooth-border">
          <div class="dlg-header dlg-header--danger">
            <v-icon class="dlg-icon">mdi-alert</v-icon>
            <span class="dlg-title">Permanently Delete Template</span>
            <v-btn icon variant="text" class="dlg-close" aria-label="Close" @click="deleteDialog = false">
              <v-icon>mdi-close</v-icon>
            </v-btn>
          </div>
          <v-card-text>
            <v-alert type="error" variant="tonal" class="mb-4">
              <strong>This action cannot be undone.</strong>
            </v-alert>
            <p>
              Are you sure you want to permanently delete the template
              "<strong>{{ deletingTemplate?.name }}</strong>"?
            </p>
            <p class="text-body-small text-muted-a11y mt-2">
              This will remove the template and all its version history.
            </p>
          </v-card-text>
          <div class="dlg-footer">
            <v-spacer />
            <v-btn variant="text" @click="deleteDialog = false">Cancel</v-btn>
            <v-btn color="error" variant="flat" :loading="deleting" @click="deleteTemplate">
              Delete Permanently
            </v-btn>
          </div>
        </v-card>
      </v-dialog>

      <!-- Reset Confirmation Dialog -->
      <v-dialog v-model="resetDialog" max-width="600px" persistent retain-focus>
        <v-card v-draggable class="smooth-border">
          <div class="dlg-header dlg-header--warning">
            <v-icon class="dlg-icon">mdi-alert</v-icon>
            <span class="dlg-title">Confirm Reset to Default</span>
            <v-btn icon variant="text" class="dlg-close" aria-label="Close" @click="resetDialog = false">
              <v-icon>mdi-close</v-icon>
            </v-btn>
          </div>
          <v-card-text>
            <p class="mb-4">
              Are you sure you want to reset the template "{{ resettingTemplate?.name }}" to the
              system default?
            </p>
            <v-alert type="warning" variant="tonal" class="mb-4">
              This will overwrite your customizations with the latest system template. Your current
              version will be archived and can be restored later from the version history.
            </v-alert>
            <p class="text-body-small text-muted-a11y">
              This action creates a backup in version history before resetting.
            </p>
          </v-card-text>
          <div class="dlg-footer">
            <v-spacer />
            <v-btn variant="text" @click="resetDialog = false">Cancel</v-btn>
            <v-btn color="warning" variant="flat" :loading="resetting" @click="resetTemplate">
              Reset to Default
            </v-btn>
          </div>
        </v-card>
      </v-dialog>

    </v-card>
  </div>
</template>

<script setup>
import { ref, computed, inject, onMounted, onUnmounted, watch } from 'vue'
import api from '@/services/api'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'
import { getAgentColor as getAgentColorConfig } from '@/config/agentColors'
import { useTemplateData } from '@/composables/useTemplateData'
import TemplatesTable from './templates/TemplatesTable.vue'
import TemplateEditDialog from './templates/TemplateEditDialog.vue'

// Handover 0335: WebSocket setup for real-time export status updates
const userStore = useUserStore()
const { showToast } = useToast()
const currentTenantKey = computed(() => userStore.currentUser?.tenant_key)

// Handover 0335: Inject template export event from parent (UserSettings.vue)
const templateExportEvent = inject('templateExportEvent', ref(null))

// Search and filters (owned here, passed into composable)
const search = ref('')
const filterRole = ref(null)
const filterStatus = ref(null)

// Template data composable
const {
  templates,
  loading,
  editingTemplate,
  filteredTemplates,
  availableRoles,
  generatedName,
  totalActiveAgents,
  totalCapacity,
  remainingUserSlots,
  userAgentLimit,
  loadTemplates,
  loadActiveCount,
  resetEditingTemplate,
  importingDefaults,
  importDefaults,
} = useTemplateData(search, filterRole, filterStatus)

// HITL closeout mode
const closeoutModeHitl = ref(true)

// BE-9084: account-wide Headless-vs-HITL launch toggle (default false = HITL)
const allowHeadless = ref(false)

// Dirty tracking: snapshot original state on dialog open
const originalSnapshot = ref(null)
const TRACKED_FIELDS = ['role', 'custom_suffix', 'description', 'user_instructions', 'model', 'tools', 'cli_tool']
const hasChanges = computed(() => {
  if (!originalSnapshot.value) {
    // Create mode: require at least a role
    return !!editingTemplate.value.role
  }
  return TRACKED_FIELDS.some(
    (f) => (editingTemplate.value[f] ?? '') !== (originalSnapshot.value[f] ?? ''),
  )
})

const hasStaleTemplates = computed(() => templates.value.some((t) => t.may_be_stale && !t.user_managed_export))

// Dialog loading states
const saving = ref(false)
const deleting = ref(false)
const resetting = ref(false)

// Dialogs
const editDialog = ref(false)
const deleteDialog = ref(false)
const resetDialog = ref(false)

// Template being deleted / reset
const deletingTemplate = ref(null)
const resettingTemplate = ref(null)

// FE-9203: Export Status column sort — needs-export first (stale or never
// exported), then exported (oldest export first), then user-managed dismissals,
// system-managed rows last. Uses the real export signals on the API payload
// (may_be_stale, last_exported_at, user_managed_export).
const exportStatusRank = (t) => {
  if (t._system) return 3
  if (t.user_managed_export) return 2
  if (t.may_be_stale || !t.last_exported_at) return 0
  return 1
}
const sortExportStatus = (a, b) =>
  exportStatusRank(a) - exportStatusRank(b) ||
  new Date(a.last_exported_at || 0) - new Date(b.last_exported_at || 0)

// Table configuration
const headers = [
  { title: 'Agent Name', key: 'name', align: 'start' },
  { title: 'Role', key: 'role', align: 'start' },
  { title: 'Active', key: 'is_active', align: 'center' },
  { title: 'Export Status', key: 'export_status', align: 'center', sortRaw: sortExportStatus },
  { title: 'Updated', key: 'updated_at', align: 'start' },
  { title: 'Actions', key: 'actions', sortable: false, width: '4%', align: 'center' },
]

const roleOptions = [
  'analyzer',
  'designer',
  'frontend',
  'backend',
  'implementer',
  'tester',
  'reviewer',
  'documenter',
]

// FE-9203: agent templates have exactly two lifecycle states — is_active
// true/false. There is no archived/draft state on the model; do not add
// options here that the API cannot satisfy.
const statusOptions = [
  { title: 'Active', value: 'active' },
  { title: 'Inactive', value: 'inactive' },
]

// Handover 0075: Handle active toggle with validation
const handleToggleActive = async (template, newValue) => {
  try {
    await api.templates.update(template.id, { is_active: newValue })
    template.is_active = newValue
    await reloadActiveCount()
    if (newValue) {
      showToast({ message: 'Agent activated - re-export required', type: 'warning' })
    } else {
      showToast({ message: 'Agent deactivated', type: 'info' })
    }
    localStorage.setItem('agent_export_stale', 'true')
  } catch (error) {
    const errorMsg = error.response?.data?.detail || 'Failed to update agent'
    showToast({ message: errorMsg, type: 'error' })
    await reloadTemplates()
  }
}

// FE-9203: "Add default agents" — additive import; the server guards repeat clicks (skip-identical).
const importDefaultAgents = async () => {
  try {
    const summary = await importDefaults()
    const parts = []
    if (summary.added.length) parts.push(`${summary.added.length} added`)
    if (summary.added_as_duplicate.length) parts.push(`${summary.added_as_duplicate.length} added as duplicate`)
    if (summary.skipped_identical.length) parts.push(`${summary.skipped_identical.length} already present`)
    const anyAdded = summary.added.length > 0 || summary.added_as_duplicate.length > 0
    showToast({ message: `Default agents: ${parts.join(', ')}`, type: anyAdded ? 'success' : 'info' })
  } catch (error) {
    showToast({ message: error.response?.data?.detail || 'Failed to add default agents', type: 'error' })
  }
}

const openCreateDialog = () => {
  resetEditingTemplate()
  originalSnapshot.value = null
  editDialog.value = true
}

const editTemplate = (template) => {
  // Extract suffix from name: "implementer-backend" with role "implementer" → suffix "backend"
  const role = template.role || ''
  const name = template.name || ''
  const extractedSuffix = name.startsWith(`${role}-`) ? name.slice(role.length + 1) : ''

  const normalized = {
    ...template,
    user_instructions: template.user_instructions || '',
    cli_tool: template.cli_tool || 'claude',
    custom_suffix: extractedSuffix,
    background_color: template.background_color || '',
    model: template.model || 'sonnet',
    tools: template.tools || null,
  }
  editingTemplate.value = { ...normalized }
  originalSnapshot.value = { ...normalized }
  editDialog.value = true
}

const duplicateTemplate = (template) => {
  editingTemplate.value = {
    ...template,
    id: null,
    name: `${template.name} (Copy)`,
    user_instructions: template.user_instructions || '',
    cli_tool: template.cli_tool || 'claude',
    custom_suffix: '',
    background_color: template.background_color || '',
    model: template.model || 'sonnet',
    tools: template.tools || null,
  }
  originalSnapshot.value = null
  editDialog.value = true
}

const closeEditDialog = () => {
  editDialog.value = false
  originalSnapshot.value = null
  resetEditingTemplate()
}

// Handover 0103: Handle role change (auto-set background_color + write role back to editingTemplate)
// Called by TemplateEditDialog @role-change. Must mutate in-place so downstream
// spread in onUpdateTemplate does not clobber the role assignment.
const onRoleChange = (newRole) => {
  editingTemplate.value.role = newRole
  editingTemplate.value.background_color = getCategoryColor(newRole)
}

// Handle field updates emitted by TemplateEditDialog via @update:template.
// Merges the spread update into editingTemplate while preserving any concurrent mutations.
const onUpdateTemplate = (updated) => {
  editingTemplate.value = { ...editingTemplate.value, ...updated }
}

const saveTemplate = async () => {
  saving.value = true
  try {
    const data = {
      name: generatedName.value || editingTemplate.value.role,
      category: 'role',
      role: editingTemplate.value.role || null,
      cli_tool: editingTemplate.value.cli_tool,
      custom_suffix: editingTemplate.value.custom_suffix || null,
      background_color: editingTemplate.value.background_color,
      description: editingTemplate.value.description,
      user_instructions: editingTemplate.value.user_instructions,
      model: editingTemplate.value.model || null,
      tools: editingTemplate.value.tools,
      behavioral_rules: editingTemplate.value.behavioral_rules || [],
      success_criteria: editingTemplate.value.success_criteria || [],
      tags: editingTemplate.value.tags || [],
      is_default: editingTemplate.value.is_default || false,
    }

    if (editingTemplate.value.id) {
      await api.templates.update(editingTemplate.value.id, {
        name: data.name,
        role: data.role,
        cli_tool: data.cli_tool,
        background_color: data.background_color,
        user_instructions: data.user_instructions,
        description: data.description,
        model: data.model,
        tools: data.tools,
        behavioral_rules: data.behavioral_rules,
        success_criteria: data.success_criteria,
        tags: data.tags,
        is_default: data.is_default,
      })
    } else {
      await api.templates.create(data)
    }

    await reloadTemplates()
    await reloadActiveCount()
    showToast({ message: 'Template saved', type: 'success' })
    closeEditDialog()
  } catch (error) {
    console.error('Failed to save template:', error)
    const detail = error.response?.data?.detail || 'Failed to save template. Check your connection and try again.'
    const isNameCollision = error.response?.status === 400 && /already exists|unique/i.test(detail)
    showToast({
      message: detail,
      type: isNameCollision ? 'warning' : 'error',
      title: isNameCollision ? 'Name Already Exists' : 'Error',
    })
  } finally {
    saving.value = false
  }
}

const confirmDelete = (template) => {
  deletingTemplate.value = template
  deleteDialog.value = true
}

const deleteTemplate = async () => {
  deleting.value = true
  try {
    await api.templates.delete(deletingTemplate.value.id)
    await reloadTemplates()
    await reloadActiveCount()
    deleteDialog.value = false
    deletingTemplate.value = null
  } catch (error) {
    console.error('Failed to delete template:', error)
  } finally {
    deleting.value = false
  }
}

const getCategoryColor = (role) => getAgentColorConfig(role).hex

const confirmReset = (template) => {
  resettingTemplate.value = template
  resetDialog.value = true
}

const resetTemplate = async () => {
  resetting.value = true
  try {
    await api.templates.reset(resettingTemplate.value.id)
    await reloadTemplates()
    resetDialog.value = false
    resettingTemplate.value = null
  } catch (error) {
    console.error('Failed to reset template:', error)
  } finally {
    resetting.value = false
  }
}

// Handover 0335: Handle template export WebSocket event
const handleTemplateExported = (data) => {
  const { tenant_key: tenantKey, template_ids: templateIds, exported_at: exportedAt } = data
  if (!tenantKey || !templateIds || !exportedAt) return
  if (tenantKey !== currentTenantKey.value) return

  const templateIdSet = new Set(templateIds)
  templates.value.forEach((template) => {
    if (templateIdSet.has(template.id)) {
      template.last_exported_at = exportedAt
      template.may_be_stale = false
    }
  })
}

// Handle real-time template updates via WebSocket (enable/disable, field changes)
const handleTemplateUpdated = (data) => {
  if (!data?.template_id) return
  const template = templates.value.find((t) => t.id === data.template_id)
  if (template) {
    if (data.is_active !== undefined) template.is_active = data.is_active
    if (data.may_be_stale !== undefined) template.may_be_stale = data.may_be_stale
    // Refresh active count when is_active changes
    if (data.updated_fields?.includes('is_active')) reloadActiveCount()
  }
}

const markUserManaged = async (template) => {
  try {
    await api.templates.update(template.id, { user_managed_export: true })
    template.user_managed_export = true
    template.may_be_stale = false
    showToast({ message: 'Template marked as user managed', type: 'success' })
  } catch (error) {
    console.error('Failed to mark template:', error)
    showToast({ message: 'Failed to update template', type: 'error' })
  }
}

// Handle agent template downloads via MCP (giljo_setup, "Agents only") — clear staleness flags
const handleAgentsDownloaded = () => {
  const now = new Date().toISOString()
  templates.value.forEach((template) => {
    template.last_exported_at = now
    template.may_be_stale = false
    template.user_managed_export = false
  })
}

// HITL closeout mode toggle
async function toggleCloseoutMode(enabled) {
  const newMode = enabled ? 'hitl' : 'autonomous'
  const previousValue = closeoutModeHitl.value
  closeoutModeHitl.value = enabled
  try {
    await api.settings.updateGeneral({ closeout_mode: newMode })
    showToast({
      message: enabled
        ? 'User approval required before project closeout'
        : 'Orchestrator will close projects autonomously',
      type: 'success',
    })
  } catch {
    closeoutModeHitl.value = previousValue
    showToast({ message: 'Failed to save closeout setting.', type: 'error' })
  }
}

async function loadCloseoutMode() {
  try {
    const generalRes = await api.settings.getGeneral()
    const generalSettings = generalRes.data?.settings || {}
    if (generalSettings.closeout_mode) {
      closeoutModeHitl.value = generalSettings.closeout_mode === 'hitl'
    }
  } catch {
    // Default stays true (hitl)
  }
}

// BE-9084: Headless-vs-HITL launch toggle (account-wide). Optimistic update with
// revert-on-error, mirroring the closeout toggle above.
async function toggleHeadless(enabled) {
  const previousValue = allowHeadless.value
  allowHeadless.value = enabled
  try {
    await api.settings.updateHeadlessLaunch(enabled)
    showToast({
      message: enabled
        ? 'Headless mode on — a trusted CLI agent may self-advance to implementation'
        : 'HITL mode — the human Implement step is enforced',
      type: 'success',
    })
  } catch {
    allowHeadless.value = previousValue
    showToast({ message: 'Failed to save headless setting.', type: 'error' })
  }
}

async function loadHeadlessLaunch() {
  try {
    const res = await api.settings.getHeadlessLaunch()
    allowHeadless.value = !!res.data?.allow_headless_launch
  } catch {
    // Default stays false (HITL)
  }
}

// Tenant-scoped template queries (no product_id)
const reloadTemplates = () => loadTemplates()
const reloadActiveCount = () => loadActiveCount()

// Window event wrappers (event router dispatches as CustomEvent, not WS store)
const onAgentsDownloaded = (e) => handleAgentsDownloaded(e.detail)
const onTemplateExported = (e) => handleTemplateExported(e.detail)
const onTemplateUpdated = (e) => handleTemplateUpdated(e.detail)

// Lifecycle
onMounted(() => {
  reloadTemplates()
  reloadActiveCount()
  loadCloseoutMode()
  loadHeadlessLaunch()
  window.addEventListener('template:exported', onTemplateExported)
  window.addEventListener('setup:agents_downloaded', onAgentsDownloaded)
  window.addEventListener('template:updated', onTemplateUpdated)
})

onUnmounted(() => {
  window.removeEventListener('template:exported', onTemplateExported)
  window.removeEventListener('setup:agents_downloaded', onAgentsDownloaded)
  window.removeEventListener('template:updated', onTemplateUpdated)
})

// Handover 0335: Watch for export events from parent (UserSettings.vue)
watch(
  templateExportEvent,
  (newEvent) => {
    if (!newEvent) return
    if (newEvent.tenant_key !== currentTenantKey.value) return
    handleTemplateExported(newEvent)
  },
  { deep: true }
)
</script>

<style scoped lang="scss">
@use '../styles/design-tokens' as *;

/* HITL closeout toggle */
.hitl-toggle-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-left: 4px;
}

.hitl-toggle-label {
  font-size: 0.875rem;
  color: var(--text-muted);
}

.hitl-toggle-info {
  color: var(--text-muted);
  cursor: help;
}

.hitl-toggle-bar :deep(.v-switch .v-selection-control) {
  min-height: auto;
}

/* 0873: filter bar layout (matches TasksView pattern) */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
}

.filter-search {
  flex: 1;
}

.filter-search :deep(.v-field) {
  box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255, 255, 255, 0.10));
  border-radius: $border-radius-default;
}

.filter-search :deep(.v-field:focus-within) {
  box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.3);
}

.filter-select {
  flex: 0 0 160px;
}

.filter-select :deep(.v-field) {
  box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255, 255, 255, 0.10));
  border-radius: $border-radius-default;
}

.filter-clear-btn {
  color: $color-text-muted !important;
  font-size: 0.72rem;
  text-transform: none;
  letter-spacing: 0;
}

@media (max-width: 960px) {
  .filter-bar {
    flex-wrap: wrap;
  }
  .filter-search {
    max-width: 100%;
  }
}

.template-manager {
  border: none !important;
  border-radius: $border-radius-rounded !important;
  overflow: hidden;
  background: $elevation-raised;
}

// Custom toggle colors for HITL v-switch in this container: green when ON, faded blue when OFF
// Duplicated into TemplatesTable.vue for the row-level template toggles (scoped CSS boundary)
.v-switch {
  :deep(.v-switch__thumb) {
    background-color: rgba(33, 150, 243, 0.4); // Faded blue when OFF
  }

  :deep(.v-switch__track) {
    background-color: rgba(33, 150, 243, 0.2); // Faded blue track when OFF
  }
}

.v-switch :deep(.v-selection-control--dirty) {
  .v-switch__thumb {
    background-color: rgb(var(--v-theme-success));
  }

  .v-switch__track {
    background-color: rgba(76, 175, 80, 0.3); // Green track when ON
  }
}
</style>
