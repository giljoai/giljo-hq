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

      <!-- FE-9408: viewing a PRODUCT while an account-wide override exists.
           When the server answers scope==='tenant' the status line below already
           says "Inherited"; but when this product owns its own override the
           server answers scope==='product' and the shadowed account-wide row is
           invisible from here -- which is how a wrong persona survives on every
           other product unnoticed. Renders on an explicit `true` only, so an
           older server (field absent) shows nothing. -->
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

      <!-- FE-9408: the account-wide rung, seen from itself. The row's age is
           what tells you whether it is still wanted, and Restore Default is the
           way out of it -- so say the date and stop hiding the exit. -->
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

      <!-- BE-9385d: which rung of the ladder this editor is reading and writing.
           Hidden entirely when no product is selected -- there is nothing to choose
           between, and the tenant-wide rung is then the only meaningful target.
           Two plain v-btns rather than v-btn-toggle: the toggle ships in the app
           bundle but does not resolve under the component set the unit tests
           register, so a control built on it could not be asserted as rendered. -->
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

      <!-- FE-9413: which prompt this PRODUCT is actually getting, standing and
           always visible while a product is selected. The two rung tabs above stay
           freely clickable; this is the answer they never gave. Hidden entirely
           when the answer is not knowable -- see showServingIndicator. -->
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

      <!-- FE-9413: the honest activation control. Removing this product's override
           is HOW you put it back on the shared prompt, so say what it lands on --
           the account-wide override if one exists, the packaged default otherwise.
           Sits directly above the action it describes. -->
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

    <!-- FE-9408: saving the packaged text as an override looks like a no-op and
         is not -- it pins the account to today's seed text and detaches it from
         every later improvement to it. `v-if` as well as `v-model` because the
         unit-test v-dialog stub renders its slot regardless of modelValue, and
         a closed dialog must be genuinely absent from the DOM for "the guard
         did not fire" to be assertable. -->
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

// State
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
  // FE-9408: kept RAW. `undefined` (an older server that does not send the
  // field) must stay distinguishable from an explicit `false`, so every reader
  // below tests `=== true` rather than truthiness.
  tenantOverrideExists: undefined,
  tenantOverrideUpdatedAt: null,
})
// FE-9408: the effective packaged default, as the server computes it. Null when
// the server did not send one -- which disarms the no-op guard entirely.
const defaultContent = ref(null)
const showNoOpConfirm = ref(false)
const promptError = ref(null)
const promptFeedback = ref(null)

// The operator's copy, verbatim. The em dash is his; do not restyle it.
const NOOP_SAVE_WARNING =
  "Identical to the built-in default — saving pins your account to today's text and it stops receiving improvements."

// FE-9413 -----------------------------------------------------------------
// One sentence: most specific rung wins, remove a rung to fall through.
const SERVING_LADDER_EXPLANATION =
  "The most specific prompt wins: this product's own override, then your all-products override, then the built-in default, so removing a rung lets this product fall through to the next one."
// Named per rung, and iconed to match the two rung tabs above so the indicator
// and the tab it points at read as the same thing.
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
// FE-9413: does THIS product own an override row? The ladder answers it only on
// the product rung -- a tenant-rung request short-circuits before it ever looks at
// a product row, so its response says nothing about one. So it is measured where
// it is knowable and remembered, which is sound precisely BECAUSE saving one rung
// never touches another. Stamped with the product it was measured for: switching
// product while standing on the all-products rung does not re-read that rung, and
// an answer about the previous product must not be presented as this one's.
const productOverrideExists = ref(false)
const productOverrideMeasuredFor = ref(null)
// -------------------------------------------------------------------------

// BE-9385d: the editor reads/writes one rung of the product -> tenant -> seed ladder.
// The active product comes from the EXISTING store getter -- this component resolves
// nothing itself.
const productStore = useProductStore()
// Start on the product rung only when there IS a product; with none selected the
// tenant-wide rung is the only reachable one, and that is the pre-ladder behavior.
const scopeSelection = ref(productStore.effectiveProductId ? 'product' : 'tenant')

const activeProductId = computed(() => productStore.effectiveProductId)
const hasActiveProduct = computed(() => Boolean(activeProductId.value))
const activeProductName = computed(
  () => productStore.currentProduct?.name || productStore.activeProduct?.name || 'This product'
)
// The id sent to the API: null targets the tenant-wide rung.
const scopedProductId = computed(() =>
  scopeSelection.value === 'product' && hasActiveProduct.value ? activeProductId.value : null
)
const editingProductScope = computed(() => Boolean(scopedProductId.value))

// Computed
const textareaLabel = computed(() =>
  editingProductScope.value ? `Orchestrator Prompt — ${activeProductName.value}` : 'Orchestrator Prompt — all products'
)
const saveLabel = computed(() =>
  editingProductScope.value ? `Save for ${activeProductName.value}` : 'Save for all products'
)
// Restoring is only meaningful when there is an override AT THIS RUNG to remove.
const canRestore = computed(() => {
  if (editingProductScope.value) return promptMetadata.value.scope === 'product'
  return promptMetadata.value.scope === 'tenant'
})
const restoreLabel = computed(() => (editingProductScope.value ? 'Remove product override' : 'Restore Default'))

// FE-9408 -----------------------------------------------------------------
// Provenance. Three response fields, all feature-detected: on a server that
// predates them every computed below resolves to "nothing to say" and no
// branch can throw.
const tenantOverrideExists = computed(() => promptMetadata.value.tenantOverrideExists === true)

// YYYY-MM-DD from the browser's LOCAL calendar day, matching the local-time
// rendering promptStatus already uses. Returns '' for a missing or unparseable
// value so callers drop the clause instead of printing "saved Invalid Date".
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

// Removing the account-wide row is the whole point of this screen once you can
// see the row, so promote the button from quiet to filled when there is one.
const restoreProminent = computed(() => showTenantOverrideSummary.value && canRestore.value)

// Byte-identical: no trim, no normalization. A single differing character is a
// real edit and must save without friction.
const savingIsNoOp = computed(
  () => typeof defaultContent.value === 'string' && prompt.value === defaultContent.value
)
// -------------------------------------------------------------------------

// FE-9413 -----------------------------------------------------------------
// The standing per-product answer, and the fallback the remove action lands on.
//
//   serving = product override, else account-wide override, else built-in default
//
// It shows only what it actually knows. `tenant_override_exists` absent means an
// older server and the rung behind this one is unknowable; a product switch under
// the all-products rung means the remembered product answer belongs to a different
// product. Either way the indicator says nothing rather than naming a guess.
const tenantOverrideKnown = computed(
  () => typeof promptMetadata.value.tenantOverrideExists === 'boolean'
)
const productOverrideKnown = computed(
  () => hasActiveProduct.value && productOverrideMeasuredFor.value === activeProductId.value
)
const showServingIndicator = computed(
  () => hasActiveProduct.value && tenantOverrideKnown.value && productOverrideKnown.value
)
const servingRung = computed(() => {
  if (productOverrideExists.value) return 'product'
  return tenantOverrideExists.value ? 'tenant' : 'default'
})
const servingLabel = computed(() => SERVING_LABELS[servingRung.value])
const servingIcon = computed(() => SERVING_ICONS[servingRung.value])

// Only where there is a product override to remove, and only when the rung behind
// it is known -- an unnamed fallback would be worse than no copy at all. Tied to
// `canRestore` so the sentence cannot describe a button the user cannot press.
const showFallbackHint = computed(
  () => editingProductScope.value && canRestore.value && tenantOverrideKnown.value
)
const fallbackHint = computed(
  () =>
    `${restoreLabel.value} switches ${activeProductName.value} to ${
      tenantOverrideExists.value ? 'your all-products prompt' : 'the built-in default'
    }.`
)
// -------------------------------------------------------------------------

const promptStatus = computed(() => {
  const { isOverride, updatedAt, updatedBy, scope } = promptMetadata.value
  const saved = updatedAt ? ` (saved ${updatedAt.toLocaleString()} by ${updatedBy || 'admin'})` : ''

  if (isOverride && scope === 'product') {
    return `Override for ${activeProductName.value} only${saved}`
  }
  // Viewing a product that has no override of its own: be explicit that what is on
  // screen is INHERITED, so saving is understood as creating a new, narrower override.
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

// Methods
// One place that maps a prompt response onto local state -- the three calls
// (load / save / restore) previously repeated this block three times, and the
// ladder adds a fourth field to keep in step.
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
  // FE-9413: measured only on the rung that can answer it. A tenant-rung response
  // leaves it alone -- that rung cannot create or delete this product's row.
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
    promptError.value = error.response?.data?.detail || 'Failed to load orchestrator prompt.'
  } finally {
    loading.value = false
  }
}

async function savePrompt() {
  if (!promptDirty.value) return
  // FE-9408: the one save that looks harmless and is not.
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
    promptError.value = error.response?.data?.detail || 'Failed to save orchestrator prompt.'
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
    // Removing a PRODUCT override reveals whatever the ladder resolves next -- the
    // all-products override if one exists, otherwise the packaged default. Say which.
    promptFeedback.value = editingProductScope.value
      ? `Removed the override for ${activeProductName.value}; it now follows ${
          promptMetadata.value.scope === 'tenant' ? 'your all-products prompt' : 'the default prompt'
        }.`
      : 'Reverted to default orchestrator prompt.'
  } catch (error) {
    console.error('[SYSTEM] Failed to reset orchestrator prompt:', error)
    promptError.value = error.response?.data?.detail || 'Failed to restore default prompt.'
  } finally {
    saving.value = false
  }
}

// Watch for changes
watch(prompt, (value) => {
  promptDirty.value = value !== promptBaseline.value
})

// Switching rung -- or switching product while on the product rung -- re-reads that
// rung. These are different stored values, so the textarea must never keep showing
// the one you just navigated away from.
watch(scopeSelection, () => {
  loadPrompt()
})
watch(activeProductId, () => {
  if (scopeSelection.value === 'product') loadPrompt()
})

// Lifecycle
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
