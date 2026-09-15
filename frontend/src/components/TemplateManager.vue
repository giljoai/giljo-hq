<template>
  <div>
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
          Settings), leaving 15 for your custom agents. Agents receive their profile from the server when a
          job starts; nothing needs installing. Use a row's menu to download any profile as Markdown.</span
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
      <v-switch
        :model-value="showAllProducts"
        label="All products"
        color="primary"
        density="compact"
        hide-details
        class="filter-showall"
        data-testid="show-all-products"
        @update:model-value="showAllProducts = $event"
      />
      <v-menu>
        <template #activator="{ props: menuProps }">
          <v-btn
            v-bind="menuProps"
            variant="tonal"
            prepend-icon="mdi-playlist-check"
            aria-label="Bulk actions for this product"
            data-testid="product-bulk-menu"
            :disabled="!loadedProductId || showAllProducts"
            :loading="bulkRunning"
          >
            This Product
          </v-btn>
        </template>
        <v-list density="compact" min-width="240">
          <v-list-item
            prepend-icon="mdi-check-all"
            title="Enable all for this product"
            data-testid="bulk-enable-product"
            @click="setAllHere(true)"
          />
          <v-list-item
            prepend-icon="mdi-close-box-multiple-outline"
            title="Disable all for this product"
            data-testid="bulk-disable-product"
            @click="setAllHere(false)"
          />
        </v-list>
      </v-menu>
      <v-btn
        variant="tonal"
        color="primary"
        prepend-icon="mdi-account-multiple-plus"
        aria-label="Add default agents"
        data-testid="add-default-agents"
        :disabled="!viewedProductId || showAllProducts"
        :loading="importingDefaults"
        @click="importDefaultAgents"
      >
        Add Default Agents
      </v-btn>
      <v-btn
        color="primary"
        prepend-icon="mdi-plus"
        aria-label="Create new template"
        :disabled="!viewedProductId || showAllProducts"
        @click="openCreateDialog"
      >
        New Template
      </v-btn>
    </div>

    <v-card class="template-manager smooth-border">
      <v-card-text>
        <EmptyState
          v-if="!viewedProductId && !showAllProducts"
          icon="mdi-package-variant-closed"
          title="No product selected"
          description="Agents belong to a product. Open or create a product, and it arrives with a full crew of agents you can rename, tune and switch on."
          data-testid="empty-no-product"
        />

        <EmptyState
          v-else-if="noAgentsAtAll"
          icon="mdi-account-multiple-outline"
          title="No agents for this product"
          description="This product has no agents, so a job started for it runs on whatever default agent your coding tool provides. Add the default set to get a crew you can rename, tune and switch on."
          data-testid="empty-no-agents"
        >
          <v-btn
            color="primary"
            variant="flat"
            prepend-icon="mdi-account-multiple-plus"
            :loading="importingDefaults"
            data-testid="empty-add-defaults"
            @click="importDefaultAgents"
          >
            Add Default Agents
          </v-btn>
        </EmptyState>

        <template v-else>
          <EmptyState
            v-if="noneActiveHere && !showAllProducts"
            icon="mdi-toggle-switch-off-outline"
            title="Every agent is switched off for this product"
            description="This product has agents, but none are switched on, so a job started for it runs on whatever default agent your coding tool provides. Switch on the ones you want, or enable them all in one step."
            compact
            data-testid="empty-none-active"
          >
            <v-btn
              color="primary"
              variant="flat"
              prepend-icon="mdi-check-all"
              :loading="bulkRunning"
              data-testid="empty-enable-all"
              @click="setAllHere(true)"
            >
              Enable all for this product
            </v-btn>
          </EmptyState>

          <TemplatesTable
            :templates="filteredTemplates"
            :loading="loading"
            :assignments-loading="assignmentsLoading"
            :headers="headers"
            :search="search"
            :show-all-products="showAllProducts"
            :viewed-product-id="viewedProductId"
            :product-name-for="productNameFor"
            :remaining-user-slots="remainingUserSlots"
            :user-agent-limit="userAgentLimit"
            @toggle-active="handleToggleActive"
            @edit="editTemplate"
            @duplicate="duplicateTemplate"
            @reset="confirmReset"
            @delete="confirmDelete"
            @download-profile="downloadProfile"
            @clear-filters="clearFilters"
          />
        </template>
      </v-card-text>

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
import { ref, computed, onMounted, watch } from 'vue'
import api from '@/services/api'
import { useToast } from '@/composables/useToast'
import { useTemplateData } from '@/composables/useTemplateData'
import { useProductAgentAssignments } from '@/composables/useProductAgentAssignments'
import { useTemplateEditDialog } from '@/composables/useTemplateEditDialog'
import { useTemplateRealtime } from '@/composables/useTemplateRealtime'
import { useProductStore } from '@/stores/products'
import TemplatesTable from './templates/TemplatesTable.vue'
import TemplateEditDialog from './templates/TemplateEditDialog.vue'
import EmptyState from './common/EmptyState.vue'
import {
  TEMPLATE_ROLE_OPTIONS,
  TEMPLATE_STATUS_OPTIONS,
  templateRowActive,
  templateTableHeaders,
  templateOwningProductName,
} from './templates/templateTableConfig'

const { showToast } = useToast()

const search = ref('')
const filterRole = ref(null)
const filterStatus = ref(null)

const productStore = useProductStore()
const viewedProductId = computed(() => productStore.effectiveProductId || null)

const showAllProducts = ref(false)

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
} = useTemplateData(search, filterRole, filterStatus, viewedProductId, showAllProducts)

const {
  loadProductAssignments,
  toggleAgent,
  setAllForProduct,
  loadedProductId,
  assignmentsLoading,
  bulkRunning,
} = useProductAgentAssignments(templates, loadActiveCount)

const productsById = computed(() =>
  Object.fromEntries((productStore.products || []).map((p) => [p.id, p])),
)
const headers = computed(() =>
  templateTableHeaders({ showAllProducts: showAllProducts.value, productsById: productsById.value }),
)

const noAgentsAtAll = computed(
  () => !loading.value && !!viewedProductId.value && templates.value.length === 0,
)
const noneActiveHere = computed(
  () =>
    !loading.value &&
    !assignmentsLoading.value &&
    templates.value.length > 0 &&
    !templates.value.some((t) => templateRowActive(t)),
)

const productNameFor = (template) => templateOwningProductName(template, productsById.value)

const clearFilters = () => {
  search.value = ''
  filterRole.value = null
  filterStatus.value = null
}

const {
  editDialog,
  hasChanges,
  openCreateDialog,
  editTemplate,
  duplicateTemplate,
  closeEditDialog,
  onRoleChange,
  onUpdateTemplate,
} = useTemplateEditDialog(editingTemplate, resetEditingTemplate)

const saving = ref(false)
const deleting = ref(false)
const resetting = ref(false)

const deleteDialog = ref(false)
const resetDialog = ref(false)

const deletingTemplate = ref(null)
const resettingTemplate = ref(null)

const roleOptions = TEMPLATE_ROLE_OPTIONS
const statusOptions = TEMPLATE_STATUS_OPTIONS

const handleToggleActive = async (template, newValue) => {
  try {
    if (!(await toggleAgent(template, newValue))) {
      showToast({ message: 'Pick a product tab first - agents belong to a product.', type: 'info' })
      return
    }
    showToast({
      message: newValue
        ? 'Agent enabled for this product'
        : 'Agent disabled for this product',
      type: newValue ? 'warning' : 'info' })
    localStorage.setItem('agent_export_stale', 'true')
  } catch (error) {
    const overBudget = error.response?.status === 409
    showToast({
      message:
        error.response?.data?.detail ||
        (overBudget ? 'This product is at its agent limit.' : 'Failed to update agent'),
      type: overBudget ? 'warning' : 'error',
      title: overBudget ? 'Agent limit reached' : 'Error',
    })
    await reloadTemplates()
  }
}

const setAllHere = async (isActive) => {
  const { changed, failed, overBudget } = await setAllForProduct(isActive)
  await reloadTemplates()
  await reloadActiveCount()

  if (overBudget.length) {
    showToast({
      message: `${overBudget.length} more would exceed this product's limit of ${userAgentLimit.value} agent roles. Switch a role off first: ${overBudget.join(', ')}`,
      type: 'warning',
      title: 'Agent limit reached',
    })
  }
  if (failed.length) {
    showToast({
      message: `${failed.length} agent${failed.length === 1 ? '' : 's'} could not be updated: ${failed.join(', ')}`,
      type: 'error',
      title: 'Partly applied',
    })
  }
  if (!changed) {
    if (!failed.length && !overBudget.length) {
      showToast({
        message: isActive
          ? 'Every agent was already enabled for this product'
          : 'Every agent was already disabled for this product',
        type: 'info',
      })
    }
    return
  }
  const n = `${changed} agent${changed === 1 ? '' : 's'}`
  showToast({
    message: isActive ? `Enabled ${n} for this product` : `Disabled ${n} for this product`,
    type: isActive ? 'warning' : 'info',
  })
  localStorage.setItem('agent_export_stale', 'true')
}

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
  const owner = viewedProductId.value
  if (!editingTemplate.value.id && !owner) {
    showToast({
      message: 'Pick a product tab first - a new agent belongs to the product you create it in.',
      type: 'warning',
    })
    return
  }
  saving.value = true
  try {
    const data = {
      product_id: owner,
      name: generatedName.value || editingTemplate.value.role,
      category: 'role',
      role: editingTemplate.value.role || null,
      cli_tool: editingTemplate.value.cli_tool,
      custom_suffix: editingTemplate.value.custom_suffix || null,
      background_color: editingTemplate.value.background_color,
      description: editingTemplate.value.description,
      user_instructions: editingTemplate.value.user_instructions,
      model: editingTemplate.value.model || 'inherit',
      effort: editingTemplate.value.effort || 'inherit',
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
        effort: data.effort,
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

const downloadProfile = (template) => {
  window.open(api.templates.profileDownloadUrl(template.id), '_blank')
}

const reloadTemplates = async () => (await loadTemplates(), loadProductAssignments())
const reloadActiveCount = () => loadActiveCount()

useTemplateRealtime(templates, reloadActiveCount)

onMounted(() => {
  reloadTemplates()
  reloadActiveCount()
})

watch([() => productStore.effectiveProductId, showAllProducts], () => {
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
