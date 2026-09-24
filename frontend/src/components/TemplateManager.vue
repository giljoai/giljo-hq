<template>
  <div>
    <div v-if="activeView === 'roster'" class="tab-header mb-4 d-flex align-center">
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

    <TemplateToolbar
      v-model:search="search"
      v-model:filter-role="filterRole"
      v-model:filter-status="filterStatus"
      v-model:scope-mode="scopeMode"
      v-model:view="activeView"
      :available-roles="availableRoles"
      :status-options="statusOptions"
      :show-prompt="canEditPrompt"
      :can-bulk="!!loadedProductId && !showAllProducts"
      :can-create="!!viewedProductId && !showAllProducts"
      :bulk-running="bulkRunning || importingDefaults"
      @bulk-set-all="setAllHere"
      @add-defaults="importDefaultAgents"
      @reset-all="confirmResetAll"
      @create="openCreateDialog"
    />

    <AgentBehaviourView v-if="activeView === 'behaviour'" />

    <HandoverTemplateView v-if="activeView === 'handover'" />

    <SystemPromptTab v-if="activeView === 'prompt' && canEditPrompt" />

    <v-card v-if="activeView === 'roster'" class="template-manager smooth-border">
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
            :can-edit-prompt="canEditPrompt"
            @toggle-active="handleToggleActive"
            @edit="editTemplate"
            @duplicate="duplicateTemplate"
            @reset="confirmReset"
            @delete="confirmDelete"
            @download-profile="downloadProfile"
            @clear-filters="clearFilters"
            @edit-orchestrator-prompt="activeView = 'prompt'"
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
              Are you sure you want to reset the agent "{{ resettingTemplate?.name }}" to the
              default?
            </p>
            <v-alert type="warning" variant="tonal" class="mb-4" data-testid="reset-warning">
              This replaces this agent's instructions, rules and success criteria with the current
              default. Your customizations will be lost. A copy is kept in version history.
            </v-alert>
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

      <v-dialog v-model="resetAllDialog" max-width="600px" persistent retain-focus>
        <v-card v-draggable class="smooth-border">
          <div class="dlg-header dlg-header--warning">
            <v-icon class="dlg-icon">mdi-alert</v-icon>
            <span class="dlg-title">Reset All Agents to Default</span>
            <v-btn icon variant="text" class="dlg-close" aria-label="Close" @click="resetAllDialog = false">
              <v-icon>mdi-close</v-icon>
            </v-btn>
          </div>
          <v-card-text>
            <p class="mb-4" data-testid="reset-all-count">
              This resets {{ resettableCount }}
              {{ resettableCount === 1 ? 'agent' : 'agents' }} in this product.
            </p>
            <v-alert type="warning" variant="tonal" class="mb-4">
              This replaces each agent's instructions, rules and success criteria with the current
              default. Your customizations will be lost. A copy of each is kept in version history.
            </v-alert>
            <p class="text-body-small text-muted-a11y">
              Agents you created yourself have no default to return to and are left alone.
            </p>
          </v-card-text>
          <div class="dlg-footer">
            <v-spacer />
            <v-btn variant="text" @click="resetAllDialog = false">Cancel</v-btn>
            <v-btn
              color="warning"
              variant="flat"
              :loading="resettingAll"
              :disabled="resettableCount === 0"
              data-testid="reset-all-confirm"
              @click="resetAllAgents"
            >
              Reset {{ resettableCount }} {{ resettableCount === 1 ? 'Agent' : 'Agents' }}
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
import { useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import { useTemplateData } from '@/composables/useTemplateData'
import { useProductAgentAssignments } from '@/composables/useProductAgentAssignments'
import { useTemplateEditDialog } from '@/composables/useTemplateEditDialog'
import { useTemplateRealtime } from '@/composables/useTemplateRealtime'
import { useProductStore } from '@/stores/products'
import { useUserStore } from '@/stores/user'
import TemplatesTable from './templates/TemplatesTable.vue'
import TemplateToolbar from './templates/TemplateToolbar.vue'
import TemplateEditDialog from './templates/TemplateEditDialog.vue'
import EmptyState from './common/EmptyState.vue'
import AgentBehaviourView from './settings/AgentBehaviourView.vue'
import HandoverTemplateView from './settings/tabs/HandoverTemplateView.vue'
import SystemPromptTab from './settings/tabs/SystemPromptTab.vue'
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

const scopeMode = computed({
  get: () => (showAllProducts.value ? 'all' : 'product'),
  set: (value) => {
    showAllProducts.value = value === 'all'
  },
})

const router = useRouter()
const activeView = ref(router.currentRoute.value.query.view || 'roster')
watch(activeView, (view) => {
  const query = { ...router.currentRoute.value.query }
  if (view === 'roster') delete query.view
  else query.view = view
  router.replace({ query })
})
watch(
  () => router.currentRoute.value.query.view,
  (view) => {
    activeView.value = view || 'roster'
  },
)

const userStore = useUserStore()
const canEditPrompt = computed(() => userStore.isAdmin)
watch(
  canEditPrompt,
  (allowed) => {
    if (!allowed && activeView.value === 'prompt') activeView.value = 'roster'
  },
  { immediate: true },
)

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
const resettingAll = ref(false)

const deleteDialog = ref(false)
const resetDialog = ref(false)
const resetAllDialog = ref(false)

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

const resettableCount = computed(
  () => templates.value.filter((t) => t.can_reset && !t._system).length,
)

const confirmResetAll = () => {
  resetAllDialog.value = true
}

const resetAllAgents = async () => {
  resettingAll.value = true
  try {
    const { data } = await api.templates.resetAll(viewedProductId.value)
    await reloadTemplates()
    resetAllDialog.value = false

    if (data.failed.length) {
      showToast({
        message: `${data.failed.length} could not be reset: ${data.failed.map((f) => f.name).join(', ')}`,
        type: 'error',
        title: 'Partly applied',
      })
    }
    const n = `${data.reset.length} agent${data.reset.length === 1 ? '' : 's'}`
    showToast({
      message: data.reset.length ? `Reset ${n} to default` : 'No agents had a default to return to',
      type: data.reset.length ? 'success' : 'info',
    })
  } catch (error) {
    showToast({
      message: error.response?.data?.detail || 'Failed to reset agents',
      type: 'error',
      title: 'Error',
    })
  } finally {
    resettingAll.value = false
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

.template-manager {
  border: none !important;
  border-radius: $border-radius-rounded !important;
  overflow: hidden;
  background: $elevation-raised;
}
</style>
