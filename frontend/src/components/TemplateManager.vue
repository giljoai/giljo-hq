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

    <!-- FE-9555 (operator direction 2026-09-04): the account-wide policy switches
         moved OUT of here and into the "Agent Behaviour Settings" group ToolsView
         renders ABOVE this roster. They never described the template roster around
         them -- OrchestrationToggles' own docstring already said they only lived
         here because this tab had room. -->
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
import { ref, computed, onMounted } from 'vue'
import api from '@/services/api'
import { useToast } from '@/composables/useToast'
import { useTemplateData } from '@/composables/useTemplateData'
import { useProductAgentAssignments } from '@/composables/useProductAgentAssignments'
import { useTemplateEditDialog } from '@/composables/useTemplateEditDialog'
import { useTemplateRealtime } from '@/composables/useTemplateRealtime'
import TemplatesTable from './templates/TemplatesTable.vue'
import TemplateEditDialog from './templates/TemplateEditDialog.vue'
import {
  TEMPLATE_TABLE_HEADERS,
  TEMPLATE_ROLE_OPTIONS,
  TEMPLATE_STATUS_OPTIONS,
} from './templates/templateTableConfig'

const { showToast } = useToast()

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

const { loadProductAssignments, toggleAgent } = useProductAgentAssignments(templates, loadActiveCount)

// BE-9394: the dialog's own state machine (open/close, dirty tracking, field updates)
// lives in its own composable -- see useTemplateEditDialog for why.
const {
  editDialog,
  hasChanges,
  retireChanged,
  openCreateDialog,
  editTemplate,
  duplicateTemplate,
  closeEditDialog,
  onRoleChange,
  onUpdateTemplate,
} = useTemplateEditDialog(editingTemplate, resetEditingTemplate)

const hasStaleTemplates = computed(() => templates.value.some((t) => t.may_be_stale && !t.user_managed_export))

// Dialog loading states
const saving = ref(false)
const deleting = ref(false)
const resetting = ref(false)

// Dialogs (editDialog is owned by useTemplateEditDialog)
const deleteDialog = ref(false)
const resetDialog = ref(false)

// Template being deleted / reset
const deletingTemplate = ref(null)
const resettingTemplate = ref(null)

// Table/filter configuration lives in templateTableConfig.js. Re-bound locally
// because the template and the characterization spec both read these names.
const headers = TEMPLATE_TABLE_HEADERS
const roleOptions = TEMPLATE_ROLE_OPTIONS
const statusOptions = TEMPLATE_STATUS_OPTIONS

// Handover 0075 + BE-9385a: the switch writes the PER-PRODUCT junction (see
// useProductAgentAssignments); tenant `is_active` is the retire switch in the dialog.
const handleToggleActive = async (template, newValue) => {
  try {
    const at = (await toggleAgent(template, newValue)) ? ' for this product' : ''
    showToast({
      message: newValue ? `Agent enabled${at} - re-export required` : `Agent disabled${at}`,
      type: newValue ? 'warning' : 'info' })
    localStorage.setItem('agent_export_stale', 'true')
  } catch (error) {
    showToast({ message: error.response?.data?.detail || 'Failed to update agent', type: 'error' })
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
      is_active: true, // BE-9391: born active — create is the only path that assumes it.
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
        // BE-9394: the tenant-wide retire switch, sent ONLY when the user moved it.
        // An ordinary edit must never carry this field -- see retireChanged.
        ...(retireChanged.value ? { is_active: editingTemplate.value.is_active } : {}),
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

// Tenant-scoped template queries; BE-9385a overlays the per-product state on top.
const reloadTemplates = async () => (await loadTemplates(), loadProductAssignments())
const reloadActiveCount = () => loadActiveCount()

// Export/update/download signals from the event router and the parent view.
// Self-wiring: registers and tears down its own window listeners.
useTemplateRealtime(templates, reloadActiveCount)

// Lifecycle
onMounted(() => {
  reloadTemplates()
  reloadActiveCount()
})
</script>

<style scoped lang="scss">
@use '../styles/design-tokens' as *;

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
</style>
