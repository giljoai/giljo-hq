<template>
  <div>
    <div class="tab-header mb-4">
      <h2 class="text-title-large">System Orchestrator Prompt</h2>
      <p class="text-body-medium text-muted-a11y mt-1">Core instructions for the Giljo Orchestrator (admin override only)</p>
    </div>
    <v-card variant="flat" class="smooth-border prompt-card">
    <v-card-text>
      <v-alert type="info" variant="tonal" class="mb-6">
        <p class="mb-3">
          {{ productName }} ships pre-packaged prompts so you don't have to write lengthy instructions for
          every request. They reduce errors, ensure consistency, and give your agents precise operating
          instructions out of the box.
        </p>
        <p class="mb-3">
          Behind the scenes, the MCP server applies dynamic protocol layers to these prompts based on
          your product definition, enabled integrations, and context depth settings. These protocol
          layers are not editable; they've been calibrated to ensure agents interact correctly with the
          server and with each other.
        </p>
        <p class="mb-3">
          The general orchestrator prompt below <strong>is</strong> editable, though we don't recommend
          modifying it unless you have a specific reason. We believe in putting control in your hands,
          so we expose it here for transparency. The protocol layers remain hidden and will continue to
          adapt based on the context you've already defined.
        </p>
        <p class="mb-3">
          <strong>The philosophy is simple: define your product once, and every agent works from that
          shared understanding, no tedious per-request prompt tuning required.</strong>
        </p>
        <p class="mb-0">
          <strong>You can customise this per product, or once for everything.</strong> A product
          override wins for that product; anything without one falls back to your all-products
          prompt, and then to the packaged default.
        </p>
      </v-alert>

      <v-alert type="warning" variant="tonal" class="mb-4">
        Editing this prompt can break orchestrator coordination. Only proceed if you understand the
        full impact. Always keep a backup and verify flows after saving.
      </v-alert>

      <v-alert
        v-if="showAccountOverrideNotice"
        type="warning"
        variant="tonal"
        class="mb-4"
        data-test="account-override-notice"
      >
        <p class="mb-3">{{ accountOverrideNotice }}</p>
        <v-btn
          variant="outlined"
          color="warning"
          size="small"
          data-test="account-override-manage"
          @click="scopeSelection = 'tenant'"
        >
          <v-icon start size="small">mdi-earth</v-icon>
          Manage the account-wide override
        </v-btn>
      </v-alert>

      <v-alert
        v-if="showTenantOverrideSummary"
        type="info"
        variant="tonal"
        class="mb-4"
        data-test="tenant-override-summary"
      >
        {{ tenantOverrideSummary }}
      </v-alert>

      <v-alert
        v-if="promptError"
        type="error"
        variant="tonal"
        class="mb-4"
        closable
        data-test="error-alert"
        @click:close="promptError = null"
      >
        {{ promptError }}
      </v-alert>

      <v-alert
        v-if="promptFeedback"
        type="success"
        variant="tonal"
        class="mb-4"
        closable
        data-test="success-alert"
        @click:close="promptFeedback = null"
      >
        {{ promptFeedback }}
      </v-alert>

      <div v-if="hasActiveProduct" class="scope-switch mb-4" data-test="prompt-scope-toggle">
        <v-btn
          :variant="editingProductScope ? 'flat' : 'outlined'"
          color="primary"
          size="small"
          data-test="prompt-scope-product"
          @click="scopeSelection = 'product'"
        >
          <v-icon start size="small">mdi-package-variant-closed</v-icon>
          {{ activeProductName }}
        </v-btn>
        <v-btn
          :variant="editingProductScope ? 'outlined' : 'flat'"
          color="primary"
          size="small"
          data-test="prompt-scope-tenant"
          @click="scopeSelection = 'tenant'"
        >
          <v-icon start size="small">mdi-earth</v-icon>
          All products
        </v-btn>
      </div>

      <div v-if="showServingIndicator" class="serving-indicator mb-4" data-test="serving-indicator">
        <v-icon size="small">{{ servingIcon }}</v-icon>
        <span class="text-body-small">
          Serving this product:
          <strong data-test="serving-value">{{ servingLabel }}</strong>
        </span>
        <v-tooltip activator="parent" location="bottom" :text="SERVING_LADDER_EXPLANATION" />
      </div>

      <v-textarea
        v-model="prompt"
        :loading="loading"
        :readonly="loading"
        :label="textareaLabel"
        class="mono-textarea"
        rows="18"
        max-rows="30"
        auto-grow
        variant="outlined"
        spellcheck="false"
      />

      <div class="text-body-small mt-2" data-test="prompt-status">
        {{ promptStatus }}
      </div>

      <div
        v-if="showFallbackHint"
        class="text-body-small text-muted-a11y mt-2"
        data-test="fallback-hint"
      >
        {{ fallbackHint }}
      </div>
    </v-card-text>

    <v-card-actions>
      <v-btn
        :variant="restoreProminent ? 'flat' : 'text'"
        color="warning"
        :disabled="loading || saving || !canRestore"
        data-test="restore-prompt-btn"
        @click="restorePrompt"
      >
        <v-icon start>mdi-backup-restore</v-icon>
        {{ restoreLabel }}
      </v-btn>
      <v-spacer />
      <v-btn
        color="primary"
        :loading="saving"
        :disabled="!promptDirty || saving"
        data-test="save-prompt-btn"
        @click="savePrompt"
      >
        <v-icon start>mdi-content-save</v-icon>
        {{ saveLabel }}
      </v-btn>
    </v-card-actions>
  </v-card>

    <BaseDialog
      v-if="showNoOpConfirm"
      v-model="showNoOpConfirm"
      type="warning"
      title="Save a copy of the built-in default?"
      :message="NOOP_SAVE_WARNING"
      confirm-label="Save anyway"
      cancel-text="Cancel"
      data-test="noop-save-confirm"
      @confirm="confirmNoOpSave"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import api from '@/services/api'
import { PRODUCT_NAME } from '@/branding'
import { useProductStore } from '@/stores/products'
import BaseDialog from '@/components/common/BaseDialog.vue'
import { parseErrorResponse } from '@/utils/errorMessages'

const productName = PRODUCT_NAME
const prompt = ref('')
const promptBaseline = ref('')
const loading = ref(false)
const saving = ref(false)
const promptDirty = ref(false)
const promptMetadata = ref({
  isOverride: false,
  updatedAt: null,
  updatedBy: null,
  scope: 'default',
  tenantOverrideExists: false,
  tenantOverrideUpdatedAt: null,
})
const defaultContent = ref(null)
const showNoOpConfirm = ref(false)
const promptError = ref(null)
const promptFeedback = ref(null)

const NOOP_SAVE_WARNING =
  "Identical to the built-in default — saving pins your account to today's text and it stops receiving improvements."

const SERVING_LADDER_EXPLANATION =
  "The most specific prompt wins: this product's own override, then your all-products override, then the built-in default, so removing a rung lets this product fall through to the next one."
const SERVING_LABELS = {
  product: 'product override',
  tenant: 'account-wide override',
  default: 'built-in default',
}
const SERVING_ICONS = {
  product: 'mdi-package-variant-closed',
  tenant: 'mdi-earth',
  default: 'mdi-cube-outline',
}
const productOverrideExists = ref(false)
const productOverrideMeasuredFor = ref(null)

const productStore = useProductStore()
const scopeSelection = ref(productStore.effectiveProductId ? 'product' : 'tenant')

const activeProductId = computed(() => productStore.effectiveProductId)
const hasActiveProduct = computed(() => Boolean(activeProductId.value))
const activeProductName = computed(
  () => productStore.currentProduct?.name || productStore.activeProduct?.name || 'This product'
)
const scopedProductId = computed(() =>
  scopeSelection.value === 'product' && hasActiveProduct.value ? activeProductId.value : null
)
const editingProductScope = computed(() => Boolean(scopedProductId.value))

const textareaLabel = computed(() =>
  editingProductScope.value ? `Orchestrator Prompt — ${activeProductName.value}` : 'Orchestrator Prompt — all products'
)
const saveLabel = computed(() =>
  editingProductScope.value ? `Save for ${activeProductName.value}` : 'Save for all products'
)
const canRestore = computed(() => {
  if (editingProductScope.value) return promptMetadata.value.scope === 'product'
  return promptMetadata.value.scope === 'tenant'
})
const restoreLabel = computed(() => (editingProductScope.value ? 'Remove product override' : 'Restore Default'))

const tenantOverrideExists = computed(() => promptMetadata.value.tenantOverrideExists === true)

function formatSavedDate(value) {
  if (!(value instanceof Date) || Number.isNaN(value.getTime())) return ''
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${value.getFullYear()}-${month}-${day}`
}

const tenantOverrideSavedDate = computed(() =>
  formatSavedDate(promptMetadata.value.tenantOverrideUpdatedAt)
)

const showAccountOverrideNotice = computed(
  () => editingProductScope.value && tenantOverrideExists.value
)
const accountOverrideNotice = computed(() => {
  const saved = tenantOverrideSavedDate.value ? ` (saved ${tenantOverrideSavedDate.value})` : ''
  return `An account-wide override${saved} currently governs every product without its own override — including this one.`
})

const showTenantOverrideSummary = computed(
  () => !editingProductScope.value && tenantOverrideExists.value
)
const tenantOverrideSummary = computed(() => {
  const saved = tenantOverrideSavedDate.value
    ? ` It was saved ${tenantOverrideSavedDate.value}.`
    : ''
  return `This account-wide override applies to every product without its own override.${saved} Restore Default removes it and returns those products to the packaged prompt.`
})

const restoreProminent = computed(() => showTenantOverrideSummary.value && canRestore.value)

const savingIsNoOp = computed(
  () => typeof defaultContent.value === 'string' && prompt.value === defaultContent.value
)

const productOverrideKnown = computed(
  () => hasActiveProduct.value && productOverrideMeasuredFor.value === activeProductId.value
)
const showServingIndicator = computed(() => hasActiveProduct.value && productOverrideKnown.value)
const servingRung = computed(() => {
  if (productOverrideExists.value) return 'product'
  return tenantOverrideExists.value ? 'tenant' : 'default'
})
const servingLabel = computed(() => SERVING_LABELS[servingRung.value])
const servingIcon = computed(() => SERVING_ICONS[servingRung.value])

const showFallbackHint = computed(() => editingProductScope.value && canRestore.value)
const fallbackHint = computed(
  () =>
    `${restoreLabel.value} switches ${activeProductName.value} to ${
      tenantOverrideExists.value ? 'your all-products prompt' : 'the built-in default'
    }.`
)

const promptStatus = computed(() => {
  const { isOverride, updatedAt, updatedBy, scope } = promptMetadata.value
  const saved = updatedAt ? ` (saved ${updatedAt.toLocaleString()} by ${updatedBy || 'admin'})` : ''

  if (isOverride && scope === 'product') {
    return `Override for ${activeProductName.value} only${saved}`
  }
  if (isOverride && scope === 'tenant' && editingProductScope.value) {
    return `Inherited from your all-products override${saved}. Saving here overrides it for ${activeProductName.value} only.`
  }
  if (isOverride) {
    return `Override applied to all products${saved}`
  }
  if (editingProductScope.value) {
    return `Using the packaged default (no override for ${activeProductName.value} and none for all products)`
  }
  return 'Using the default orchestrator prompt (you have not saved an override)'
})

function applyPromptResponse(response, { keepOnEmpty = false } = {}) {
  const data = response?.data || {}
  prompt.value = data.content || (keepOnEmpty ? prompt.value : '')
  promptBaseline.value = prompt.value
  promptMetadata.value = {
    isOverride: Boolean(data.is_override),
    updatedAt: data.updated_at ? new Date(data.updated_at) : null,
    updatedBy: data.updated_by || null,
    scope: data.scope || 'default',
    tenantOverrideExists: data.tenant_override_exists,
    tenantOverrideUpdatedAt: data.tenant_override_updated_at
      ? new Date(data.tenant_override_updated_at)
      : null,
  }
  defaultContent.value = typeof data.default_content === 'string' ? data.default_content : null
  if (editingProductScope.value) {
    productOverrideExists.value = (data.scope || 'default') === 'product'
    productOverrideMeasuredFor.value = activeProductId.value
  }
  promptDirty.value = false
}

async function loadPrompt() {
  loading.value = true
  promptError.value = null
  promptFeedback.value = null

  try {
    const response = await api.system.getOrchestratorPrompt(scopedProductId.value)
    applyPromptResponse(response)
  } catch (error) {
    console.error('[SYSTEM] Failed to load orchestrator prompt:', error)
    promptError.value = parseErrorResponse(error).message || 'Failed to load orchestrator prompt.'
  } finally {
    loading.value = false
  }
}

async function savePrompt() {
  if (!promptDirty.value) return
  if (savingIsNoOp.value) {
    showNoOpConfirm.value = true
    return
  }
  await performSave()
}

async function confirmNoOpSave() {
  showNoOpConfirm.value = false
  await performSave()
}

async function performSave() {
  saving.value = true
  promptError.value = null
  promptFeedback.value = null

  try {
    const response = await api.system.updateOrchestratorPrompt(prompt.value, scopedProductId.value)
    applyPromptResponse(response, { keepOnEmpty: true })
    promptFeedback.value = editingProductScope.value
      ? `Override saved for ${activeProductName.value}.`
      : 'Override saved for all products.'
  } catch (error) {
    console.error('[SYSTEM] Failed to save orchestrator prompt:', error)
    promptError.value = parseErrorResponse(error).message || 'Failed to save orchestrator prompt.'
  } finally {
    saving.value = false
  }
}

async function restorePrompt() {
  saving.value = true
  promptError.value = null
  promptFeedback.value = null

  try {
    const response = await api.system.resetOrchestratorPrompt(scopedProductId.value)
    applyPromptResponse(response)
    promptFeedback.value = editingProductScope.value
      ? `Removed the override for ${activeProductName.value}; it now follows ${
          promptMetadata.value.scope === 'tenant' ? 'your all-products prompt' : 'the default prompt'
        }.`
      : 'Reverted to default orchestrator prompt.'
  } catch (error) {
    console.error('[SYSTEM] Failed to reset orchestrator prompt:', error)
    promptError.value = parseErrorResponse(error).message || 'Failed to restore default prompt.'
  } finally {
    saving.value = false
  }
}

watch(prompt, (value) => {
  promptDirty.value = value !== promptBaseline.value
})

watch(scopeSelection, () => {
  loadPrompt()
})
watch(activeProductId, () => {
  if (scopeSelection.value === 'product') loadPrompt()
})

onMounted(() => {
  loadPrompt()
})
</script>

<style lang="scss" scoped>
@use '../../../styles/settings-tab-card' as settingsCard;
.prompt-card {
  @include settingsCard.settings-tab-card-surface;
}

.mono-textarea :deep(textarea) {
  font-family: 'Roboto Mono', monospace;
}

/* BE-9385d: the product / all-products scope switch. */
.scope-switch {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* FE-9413: the standing per-product answer, in the toolbar area beside the rungs. */
.serving-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
</style>
