<template>
  <div class="upload-screen">
    <div class="beat-eyebrow">Vision document · upload</div>
    <h2 class="beat-title">Attach your vision document.</h2>
    <p class="beat-sub">GiljoAI ingests it, stages an analysis, and your agent proposes the product setup from it.</p>

    <div class="upload-stage">
      <!-- Step 1: drop zone (until a document is uploaded) -->
      <div
        v-if="!analysisStarted"
        :class="['drop-zone', { 'drop-zone--over': dragOver }]"
        data-testid="tutorial-drop-zone"
        @dragover.prevent="dragOver = true"
        @dragleave.prevent="dragOver = false"
        @drop.prevent="onDrop"
      >
        <v-icon size="34" class="drop-icon">mdi-file-upload-outline</v-icon>
        <span class="drop-title">Drop your vision document here</span>
        <span class="drop-or">or</span>
        <v-btn
          color="primary"
          variant="flat"
          class="browse-btn"
          data-testid="tutorial-browse"
          :loading="uploadingVision"
          @click="fileInput?.click()"
        >
          Browse your files
        </v-btn>
        <input
          ref="fileInput"
          type="file"
          class="file-input"
          multiple
          @change="onBrowse"
        />

        <!-- The upload did not produce a product this beat can work with. Shown
             here rather than only as a toast: a toast is seconds long, and the
             operator is standing on a screen that would otherwise look
             untouched. It names the possibility that a product WAS created,
             because retrying blindly would then make a second one. -->
        <!-- FE-9553c: the same error+retry shape FE-9566 gave door D
             (tutorial-prompt-error / -retry / -error-manual). Doors A and B
             never got it, so this beat explained itself and its sibling went
             quiet; matching the shape means the tour behaves the same way
             whichever door the operator walked in through.

             The retry is withheld when a product WAS created but could not be
             bound, because pressing it again would mint a second one. The
             manual escape is always offered: a failure the operator cannot
             clear must not be a dead end. -->
        <div v-if="uploadFailure" class="upload-failure" data-testid="tutorial-upload-failure">
          <p class="upload-failure-text">
            <v-icon size="16" class="mr-1">mdi-alert-circle-outline</v-icon>
            {{ uploadFailure }}
          </p>
          <div class="upload-failure-actions">
            <v-btn
              v-if="retryIsSafe"
              variant="text"
              class="failure-btn"
              data-testid="tutorial-upload-retry"
              :disabled="retrying"
              prepend-icon="mdi-refresh"
              @click="retryUpload"
            >
              {{ retrying ? 'Trying again…' : 'Try again' }}
            </v-btn>
            <v-btn
              variant="text"
              class="failure-btn"
              data-testid="tutorial-upload-manual"
              @click="$emit('manual')"
            >
              Fill it in myself instead
            </v-btn>
          </div>
        </div>
      </div>

      <!-- Step 2: discovery prompt staged, waiting on the agent's analysis.
           FE-9320: the prompt is VISIBLE and copying it is an explicit button —
           uploading a file no longer takes the clipboard on the user's behalf. -->
      <div v-else class="analysis-panel" data-testid="tutorial-analysis-panel">
        <p class="analysis-lead">
          Your document is uploaded. Copy this prompt and paste it into an AI agent that is
          connected to {{ PRODUCT_NAME }} — it reads the document and fills in your product card.
        </p>

        <div class="prompt-box" data-testid="tutorial-analysis-prompt">{{ analysisPromptText }}</div>

        <v-btn
          color="primary"
          variant="flat"
          class="copy-btn"
          data-testid="tutorial-copy-analysis-prompt"
          :prepend-icon="promptCopied ? 'mdi-check' : 'mdi-content-copy'"
          @click="copyAnalysisPrompt"
        >
          {{ promptCopied ? 'Copied' : 'Copy discovery prompt' }}
        </v-btn>

        <div class="analysis-status">
          <span class="waiting-dot" />
          <span>Waiting for your agent's analysis…</span>
        </div>

        <!-- Honest dead-end state: this step cannot finish without a connected
             agent, and the wizard lets you skip the Connect step, so say so and
             offer a real way out instead of spinning forever. -->
        <div v-if="analysisHintVisible" class="analysis-stalled" data-testid="tutorial-analysis-stalled">
          <p class="analysis-hint">
            Nothing back yet. This step only completes when an agent connected to
            {{ PRODUCT_NAME }} runs the prompt — a chat tool with no connection cannot finish it.
            If you have not connected one yet, you can fill the product in yourself instead.
          </p>
          <v-btn
            variant="text"
            class="stalled-btn"
            data-testid="tutorial-analysis-manual"
            @click="$emit('manual')"
          >
            Fill it in myself instead
          </v-btn>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useProductStore } from '@/stores/products'
import { useClipboard } from '@/composables/useClipboard'
import { useProductVisionUpload } from '@/composables/useProductVisionUpload'
import { useVisionAnalysis } from '@/composables/useVisionAnalysis'
import { PRODUCT_NAME } from '@/branding'

const props = defineProps({
  /** THE tutorial-run product id, threaded via useTutorialState (gate F3). */
  productId: {
    type: String,
    default: null,
  },
})

const emit = defineEmits(['review', 'product-created', 'product-invalidated', 'manual'])

const productStore = useProductStore()

const fileInput = ref(null)
const dragOver = ref(false)
const analysisStarted = ref(false)
// What to tell the operator when the upload did not produce a usable product.
// Rendered on the drop-zone beat; null means nothing has gone wrong.
const uploadFailure = ref(null)
// FE-9553c: whether the failure above is one a retry can clear.
//   true  -- nothing was created, pressing again is clean
//   false -- a product WAS created but could not be bound, so a retry mints a
//            second one; the button is withheld and the copy says why
const retryIsSafe = ref(false)
const retrying = ref(false)
// The files from the last attempt, so "Try again" repeats it rather than
// asking the operator to find and drag the same document a second time.
const lastFiles = ref(null)

// Silent-create refs owned by the caller per the composable contract. GATE F3:
// a re-entered upload screen (A → back → A) must NOT create a second product —
// when the run already owns one (threaded productId), pre-seed editingProduct
// so the composable takes its EDIT branch instead of creating.
const editingProduct = ref(null)
const autoSavedForAnalysis = ref(null)

onMounted(async () => {
  if (!props.productId) return
  editingProduct.value = { id: props.productId, name: '' }
  const row = await productStore.fetchProductById(props.productId)
  if (row) {
    editingProduct.value = row
    return
  }
  // TSK-9206: the run-owned draft is gone — fetchProductById returns null when the
  // product was deleted externally mid-flow (it swallows the 404). Drop the stale
  // {id, name:''} stub AND the run's productId (via product-invalidated) so the
  // next upload takes the fresh-create branch instead of targeting a dead product
  // id, which would fail server-side.
  editingProduct.value = null
  emit('product-invalidated')
})

const {
  uploadingVision,
  visionUploadError,
  visionUploadRetrySafe,
  uploadVisionFilesOnAttach,
} = useProductVisionUpload({ editingProduct, autoSavedForAnalysis })

// patchProductForm is invoked exactly once per completed analysis (event path
// and FE-9166 poll path both funnel through it) — it is the completion hook.
// FE-9320: copyPromptOnStage:false — staging happens as a side effect of
// dropping a file here, and a clipboard write must never be a side effect of
// another action. The prompt is rendered instead, with the explicit copy button
// below. (ProductForm stages from a button the user pressed, so it keeps the
// automatic copy — that path is correct and is left alone.)
const {
  analysisPromptText,
  analysisHintVisible,
  stageAnalysis,
  onVisionAnalysisComplete,
  resetAnalysisState,
} = useVisionAnalysis(() => emit('review'), { copyPromptOnStage: false })

const { copy } = useClipboard()
const promptCopied = ref(false)
let copiedTimer = null

// Same shape as TutorialPromptScreen.copyPrompt: the affirmative state is only
// set when the copy is verified, never on a failed write.
async function copyAnalysisPrompt() {
  const ok = await copy(analysisPromptText.value)
  if (!ok) return
  promptCopied.value = true
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => { promptCopied.value = false }, 1500)
}

function onVisionCompleteEvent(event) {
  onVisionAnalysisComplete(event, editingProduct.value?.id)
}

async function handleFiles(files) {
  if (!files || files.length === 0) return
  lastFiles.value = files
  const hadProduct = Boolean(editingProduct.value?.id)
  // Product name defaults to the first file's stem (mirrors the uploaded
  // document_name); the user can rename from the product form afterwards.
  const productName = files[0].name.replace(/\.[^/.]+$/, '')
  await uploadVisionFilesOnAttach({ productName, files })
  const productId = editingProduct.value?.id
  if (!productId) {
    // The upload did not yield a product this screen can work with. It used to
    // return here in SILENCE, which is the defect: the operator was
    // left on the drop zone as though nothing had happened, while a product
    // could already exist server-side named after their file. Two bad halves
    // from one action, and no way to tell which had occurred.
    //
    // The composable publishes what went wrong (including the case where a
    // product WAS created but could not be bound), so the beat now says so
    // instead of stranding. Deliberately not advancing: advancing would claim
    // an analysis is running when none is.
    uploadFailure.value =
      visionUploadError.value ||
      'That upload could not be attached to a product. Check Products before trying again.'
    // FE-9553c: read the composable's published verdict rather than inferring
    // it from the copy -- a caller string-matching the message would start
    // offering the wrong remedy the first time anyone reworded it.
    // Defaults to withholding the retry when the verdict is unknown: offering a
    // retry that duplicates work is worse than making the operator go and look.
    retryIsSafe.value = visionUploadRetrySafe.value === true
    return
  }
  uploadFailure.value = null
  retryIsSafe.value = false
  // Register a fresh silent-create with the state machine so every later
  // screen (and a re-entry of this one) reuses THE run-owned product.
  if (!hadProduct) emit('product-created', productId)

  window.addEventListener('vision-analysis-complete', onVisionCompleteEvent)
  await stageAnalysis({ name: editingProduct.value.name || productName }, productId)
  analysisStarted.value = true
}

/**
 * Repeat the last attempt.
 *
 * Only reachable when the composable said nothing was created, so this cannot
 * mint a duplicate. It re-drives handleFiles rather than re-implementing the
 * upload, so the retry path and the first attempt cannot drift -- a separate
 * retry implementation is how the second attempt ends up subtly different from
 * the first.
 */
async function retryUpload() {
  if (retrying.value || !lastFiles.value) return
  retrying.value = true
  try {
    await handleFiles(lastFiles.value)
  } finally {
    retrying.value = false
  }
}

function onDrop(event) {
  dragOver.value = false
  handleFiles(Array.from(event.dataTransfer?.files || []))
}

function onBrowse(event) {
  handleFiles(Array.from(event.target?.files || []))
  if (event.target) event.target.value = ''
}

onBeforeUnmount(() => {
  window.removeEventListener('vision-analysis-complete', onVisionCompleteEvent)
  clearTimeout(copiedTimer)
  resetAnalysisState()
})
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.upload-screen {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.beat-eyebrow {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.2em;
  color: $color-brand-yellow;
  text-transform: uppercase;
  margin-bottom: 10px;
}

.beat-title {
  margin: 0 0 6px;
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 700;
  font-size: 26px;
  letter-spacing: -0.02em;
  color: $color-text-primary;
}

.beat-sub {
  margin: 0 0 14px;
  font-size: 14px;
  line-height: 1.55;
  color: var(--text-secondary);
}

.upload-stage {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.drop-zone {
  width: 440px;
  border-radius: $border-radius-rounded;
  border: 2px dashed rgba(255, 255, 255, 0.18);
  padding: 34px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 11px;
  text-align: center;
}

.drop-zone--over {
  border-color: rgba($color-brand-yellow, 0.6);
  background: rgba($color-brand-yellow, 0.04);
}

.drop-icon {
  color: $color-brand-yellow;
}

.drop-title {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 600;
  font-size: 15px;
  color: $color-text-primary;
}

.upload-failure {
  margin-top: 14px;
  max-width: 34rem;
  text-align: center;
}

.upload-failure-text {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 6px;
  font-size: 0.85rem;
  color: rgb(var(--v-theme-error));
}

.upload-failure-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  flex-wrap: wrap;
}

.drop-or {
  font-size: 12px;
  color: var(--text-muted);
}

.browse-btn {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 600;
  border-radius: $border-radius-default;
  background: $color-brand-yellow !important;
  color: $color-on-yellow-ink !important;

  &:hover {
    background: $color-brand-yellow-hover !important;
  }
}

.file-input {
  display: none;
}

/* Matches TutorialPromptScreen's copy control — same brand-yellow primary. */
.copy-btn {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 600;
  border-radius: $border-radius-default;
  background: $color-brand-yellow !important;
  color: $color-on-yellow-ink !important;

  &:hover {
    background: $color-brand-yellow-hover !important;
  }
}

.analysis-panel {
  width: 480px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  text-align: center;
  align-items: center;
}

.analysis-lead {
  margin: 0;
  font-size: 14px;
  line-height: 1.55;
  color: var(--text-secondary);
}

.prompt-box {
  align-self: stretch;
  background: $color-background-primary;
  border-radius: $border-radius-md;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1);
  padding: 12px 14px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  line-height: 1.7;
  color: var(--text-secondary);
  white-space: pre-wrap;
  text-align: left;
  max-height: 180px;
  overflow-y: auto;
  user-select: all;
}

.analysis-stalled {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.stalled-btn {
  color: var(--text-secondary) !important;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14);
  border-radius: $border-radius-default;
}

.analysis-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  color: var(--text-muted);
}

.waiting-dot {
  width: 8px;
  height: 8px;
  border-radius: $border-radius-pill;
  background: $color-status-waiting;
  animation: tutorialPulse 1.6s ease infinite;
}

@keyframes tutorialPulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 1; }
}

.analysis-hint {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}
</style>
