<template>
  <div>
    <div class="tab-header mb-4">
      <h2 class="text-title-large">Orchestrator prompt</h2>
    </div>

    <v-alert type="warning" variant="tonal" density="compact" class="mb-4" data-test="prompt-warning">
      Changing the orchestrator prompt can have adverse effects on the {{ productName }} product. Use custom additions with caution.
    </v-alert>

    <v-card variant="flat" class="smooth-border prompt-card" data-test="builtin-prompt">
      <v-card-text>
        <div id="builtin-prompt-label" class="prompt-card__label">System prompt (read only)</div>
        <div
          class="prompt-card__body scrollbar-standard"
          role="region"
          aria-labelledby="builtin-prompt-label"
          tabindex="0"
          v-html="builtInHtml"
        />
      </v-card-text>
    </v-card>

    <div class="instructions mt-8" data-test="instructions">
      <h3 class="text-title-large">Instructions</h3>
      <p class="text-body-small text-secondary-a11y mt-1 mb-4">You can customize your system prompt per product.</p>

      <v-select
        v-model="selectedProductId"
        :items="productItems"
        label="Product"
        variant="outlined"
        density="comfortable"
        hide-details
        class="product-select"
        data-test="product-select"
      />

      <div v-if="rungProposal" class="proposal-line mt-4" data-test="additions-proposal-notice">
        <span class="text-body-medium">{{ rungProposalSentence }}</span>
        <v-btn
          variant="text"
          size="small"
          data-test="additions-proposal-review"
          @click="openProposal = rungProposal"
        >
          Review proposed change
        </v-btn>
      </div>

      <div v-if="legacyMode" class="legacy-line mt-4" data-test="legacy-line">
        <span class="text-body-medium">{{ LEGACY_LINE }}</span>
        <v-btn variant="outlined" size="small" data-test="convert-to-additions" @click="convertToAdditions">
          Convert
        </v-btn>
      </div>

      <v-textarea
        v-model="additions"
        :loading="loading"
        :disabled="!loaded || legacyMode"
        :aria-label="textareaLabel"
        placeholder="Add instructions for this product. Leave blank to use the system prompt only."
        rows="6"
        max-rows="30"
        auto-grow
        variant="outlined"
        hide-details
        class="mt-4"
        data-test="additions-field"
      />

      <v-textarea
        v-if="showLegacyText"
        :model-value="legacyContent"
        readonly
        label="Old full prompt (read only)"
        rows="8"
        no-resize
        variant="outlined"
        hide-details
        class="mt-4"
        data-test="legacy-replacement"
      />

      <div class="d-flex justify-end mt-3">
        <v-btn
          color="primary"
          :loading="saving"
          :disabled="!canSave"
          data-test="save-prompt-btn"
          @click="save"
        >
          Save
        </v-btn>
      </div>
    </div>

    <BaseDialog
      v-if="showNoOpConfirm"
      v-model="showNoOpConfirm"
      type="warning"
      title="Save the built-in prompt as additions?"
      :message="NOOP_SAVE_WARNING"
      confirm-label="Save anyway"
      cancel-text="Cancel"
      data-test="noop-save-confirm"
      @confirm="confirmNoOpSave"
    />

    <TemplateProposalDialog
      :proposal="openProposal"
      @close="openProposal = null"
      @decided="onProposalDecided"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import api from '@/services/api'
import { PRODUCT_NAME } from '@/branding'
import { useProductStore } from '@/stores/products'
import { useToast } from '@/composables/useToast'
import { useSanitizeMarkdown } from '@/composables/useSanitizeMarkdown'
import BaseDialog from '@/components/common/BaseDialog.vue'
import TemplateProposalDialog from '@/components/templates/TemplateProposalDialog.vue'
import { useTemplateProposalsStore } from '@/stores/templateProposalsStore'
import { parseErrorResponse } from '@/utils/errorMessages'

const productName = PRODUCT_NAME

const LEGACY_LINE = 'This product uses an old full prompt instead of the one above.'
const NOOP_SAVE_WARNING =
  'These additions are identical to the built-in prompt, which every orchestrator already gets. Saving them sends it twice.'

const productStore = useProductStore()
const templateProposals = useTemplateProposalsStore()
const { showToast } = useToast()
const { sanitizeMarkdown } = useSanitizeMarkdown()

const selectedProductId = ref(null)
const builtIn = ref('')
const additions = ref('')
const additionsBaseline = ref('')
const mode = ref(null)
const legacyContent = ref('')
const converting = ref(false)
const loaded = ref(false)
const loading = ref(false)
const saving = ref(false)
const showNoOpConfirm = ref(false)
const openProposal = ref(null)

const productItems = computed(() =>
  productStore.products.map((product) => ({ title: product.name, value: product.id })),
)
const selectedProductName = computed(
  () => productStore.products.find((p) => p.id === selectedProductId.value)?.name || 'this product',
)
const textareaLabel = computed(() => `Instructions for ${selectedProductName.value}`)
const builtInHtml = computed(() => sanitizeMarkdown(builtIn.value))

const legacyMode = computed(() => mode.value === 'replace' && !converting.value)
const showLegacyText = computed(() => mode.value === 'replace' && converting.value)
const dirty = computed(() => converting.value || additions.value !== additionsBaseline.value)
const canSave = computed(
  () => Boolean(selectedProductId.value) && loaded.value && !saving.value && !legacyMode.value && dirty.value,
)

const rungProposal = computed(() =>
  selectedProductId.value ? templateProposals.additionsProposalFor('product', selectedProductId.value) : null,
)
const rungProposalSentence = computed(() => {
  const p = rungProposal.value
  if (!p) return ''
  const text = `${p.proposed_by || 'An agent'} proposed a change to these orchestrator additions: ${p.reason}`
  return text.charAt(0).toUpperCase() + text.slice(1)
})

function clearEditor() {
  additions.value = ''
  additionsBaseline.value = ''
  mode.value = null
  legacyContent.value = ''
  converting.value = false
  loaded.value = false
}

function applyResponse(data) {
  mode.value = data.mode ?? null
  legacyContent.value = mode.value === 'replace' ? data.content || '' : ''
  converting.value = false
  additions.value = mode.value === 'additions' ? data.additions || '' : ''
  additionsBaseline.value = additions.value
  builtIn.value = typeof data.default_content === 'string' ? data.default_content : ''
  loaded.value = true
}

let loadSeq = 0

async function loadPrompt() {
  const productId = selectedProductId.value
  if (!productId) return
  const seq = ++loadSeq
  loading.value = true
  try {
    const response = await api.system.getOrchestratorPrompt(productId)
    if (seq === loadSeq) applyResponse(response?.data || {})
  } catch (error) {
    if (seq === loadSeq) {
      showToast({ message: parseErrorResponse(error).message || 'Failed to load the orchestrator prompt.', type: 'error' })
    }
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

function save() {
  if (!canSave.value) return
  if (additions.value.trim() && additions.value === builtIn.value) {
    showNoOpConfirm.value = true
    return
  }
  return performSave()
}

function confirmNoOpSave() {
  showNoOpConfirm.value = false
  return performSave()
}

async function performSave() {
  const productId = selectedProductId.value
  const name = selectedProductName.value
  const clearing = !additions.value.trim()
  saving.value = true
  try {
    const response = clearing
      ? await api.system.resetOrchestratorPrompt(productId)
      : await api.system.updateOrchestratorPrompt(additions.value, productId)
    if (productId === selectedProductId.value) applyResponse(response?.data || {})
    showToast({
      message: clearing
        ? `Instructions cleared for ${name}. Its orchestrators use the system prompt only.`
        : `Instructions saved for ${name}.`,
      type: 'success',
    })
  } catch (error) {
    showToast({
      message: parseErrorResponse(error).message || `Failed to save instructions for ${name}.`,
      type: 'error',
    })
  } finally {
    saving.value = false
  }
}

function convertToAdditions() {
  converting.value = true
  additions.value = ''
  additionsBaseline.value = ''
}

async function onProposalDecided({ action }) {
  openProposal.value = null
  if (action === 'apply') await loadPrompt()
  showToast({
    message: action === 'apply' ? 'Proposed change applied.' : 'Proposal rejected.',
    type: action === 'apply' ? 'success' : 'info',
  })
}

watch(selectedProductId, () => {
  clearEditor()
  loadPrompt()
})

onMounted(async () => {
  templateProposals.ensureLoaded()
  if (!productStore.products.length) await productStore.fetchProducts()
  const ids = productStore.products.map((p) => p.id)
  const active = productStore.effectiveProductId
  selectedProductId.value = ids.includes(active) ? active : ids[0] || null
})
</script>

<style lang="scss" scoped>
@use '../../../styles/settings-tab-card' as settingsCard;
@use '../../../styles/design-tokens' as *;

.prompt-card {
  @include settingsCard.settings-tab-card-surface;
}

.prompt-card__label {
  font-size: 0.68rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 8px;
}

.prompt-card__body {
  max-height: 420px;
  overflow-y: auto;
  padding-right: 12px;
  font-size: 0.82rem;
  color: var(--text-secondary);

  :deep(h1),
  :deep(h2),
  :deep(h3),
  :deep(h4) {
    font-family: 'Outfit', sans-serif;
    font-weight: 600;
    color: $color-text-primary;
  }
  :deep(h1) { font-size: 1rem; margin: 2px 0 8px; }
  :deep(h2),
  :deep(h3),
  :deep(h4) { font-size: 0.92rem; margin: 16px 0 6px; }
  :deep(p) { margin: 0 0 8px; white-space: pre-line; }
  :deep(ul),
  :deep(ol) { margin: 0 0 8px 18px; }
  :deep(code) {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    color: $color-text-primary;
  }
  :deep(strong) { color: $color-text-primary; font-weight: 500; }
}

.product-select {
  max-width: 360px;
}

.proposal-line,
.legacy-line {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
