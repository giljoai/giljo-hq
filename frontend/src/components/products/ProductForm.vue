<template>
  <v-dialog v-model="isOpen" max-width="950" persistent retain-focus scrollable>
    <v-card v-draggable class="product-form-card smooth-border">
      <div class="dlg-header">
        <v-icon class="dlg-icon">{{ isEdit ? 'mdi-pencil' : 'mdi-plus' }}</v-icon>
        <span class="dlg-title">{{ isEdit ? 'Edit Product' : 'Create New Product' }}</span>
        <v-btn icon variant="text" class="dlg-close" aria-label="Close" data-testid="product-form-close" @click="closeDialog">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </div>

      <v-divider></v-divider>

      <v-card-text style="min-height: 400px; max-height: 600px; overflow-y: auto">
        <v-btn-toggle
          v-model="dialogTab"
          mandatory
          variant="outlined"
          divided
          rounded="t-lg"
          color="primary"
          class="mb-0"
        >
          <v-btn value="setup" data-testid="product-form-tab-setup">
            <v-icon start size="small">mdi-cog</v-icon>
            Product Setup
          </v-btn>
          <v-btn value="info" data-testid="product-form-tab-info" :disabled="analysisInProgress || isTabLocked('info')">
            <v-icon start size="small">mdi-information-outline</v-icon>
            Product Info
            <v-tooltip v-if="isTabLocked('info')" activator="parent" location="bottom">
              Run analysis to unlock
            </v-tooltip>
          </v-btn>
          <v-btn value="tech" data-testid="product-form-tab-tech" :disabled="analysisInProgress || isTabLocked('tech')">
            <v-icon start size="small">mdi-code-braces</v-icon>
            Tech Stack
            <v-tooltip v-if="isTabLocked('tech')" activator="parent" location="bottom">
              Run analysis to unlock
            </v-tooltip>
          </v-btn>
          <v-btn value="arch" data-testid="product-form-tab-arch" :disabled="analysisInProgress || isTabLocked('arch')">
            <v-icon start size="small">mdi-sitemap</v-icon>
            Architecture
            <v-tooltip v-if="isTabLocked('arch')" activator="parent" location="bottom">
              Run analysis to unlock
            </v-tooltip>
          </v-btn>
          <v-btn value="features" data-testid="product-form-tab-features" :disabled="analysisInProgress || isTabLocked('features')">
            <v-icon start size="small">mdi-test-tube</v-icon>
            Testing
            <v-tooltip v-if="isTabLocked('features')" activator="parent" location="bottom">
              Run analysis to unlock
            </v-tooltip>
          </v-btn>
        </v-btn-toggle>

        <v-alert v-if="analysisInProgress" type="info" variant="tonal" density="compact" class="mb-0 mt-2">
          <div class="d-flex align-center">
            <v-progress-circular indeterminate size="16" width="2" class="mr-2" />
            <span class="text-body-medium">Analyzing vision documents... Paste the prompt in your coding tool.</span>
          </div>
          <div v-if="analysisHintVisible" class="text-body-small text-muted-a11y mt-2">
            Taking too long? Check that your AI coding agent received and ran the prompt.
          </div>
        </v-alert>

        <div class="bordered-tabs-content smooth-border">
          <v-form ref="formRef" v-model="formValid">
            <v-window v-model="dialogTab" class="global-tabs-window">
            <v-window-item value="setup">
              <ProductSetupTab
                :form="productForm"
                :is-edit="isEdit"
                :skip-ai-analysis="skipAiAnalysis"
                :create-blank="createBlank"
                :existing-vision-documents="existingVisionDocuments"
                :uploading-vision="uploadingVision"
                :upload-progress="uploadProgress"
                :vision-upload-error="visionUploadError"
                :prompt-fallback-text="promptFallbackText"
                :show-staleness-banner="showStalenessBanner"
                :staleness-banner-text="stalenessBannerText"
                :ctx-launching="ctxLaunching"
                @update:skip-ai-analysis="onSkipAiAnalysis"
                @update:create-blank="onCreateBlank"
                @remove-vision="deleteVisionDocument"
                @clear-upload-error="emit('clear-upload-error')"
                @upload-vision-files="onFilesAttached"
                @open-ctx-confirm="openCtxConfirm"
              />
            </v-window-item>

            <v-window-item value="info">
              <ProductInfoTab :form="productForm" />
            </v-window-item>

            <v-window-item value="tech">
              <ProductTechTab
                :form="productForm"
                :platform-validation-error="platformValidationError"
                @platform-change="handlePlatformChange"
                @all-platform-change="handleAllPlatformChange"
              />
            </v-window-item>

            <v-window-item value="arch">
              <ProductArchTab :form="productForm" />
            </v-window-item>

            <v-window-item value="features">
              <ProductTestingTab :form="productForm" />
            </v-window-item>
            </v-window>
          </v-form>
        </div>
      </v-card-text>

      <v-divider></v-divider>

      <div class="dlg-footer">
        <v-spacer></v-spacer>
        <v-btn variant="text" :disabled="isFirstTab" data-testid="product-form-back" @click="goPrevTab">Back</v-btn>
        <v-btn
          color="primary"
          variant="flat"
          :disabled="nextOrSaveDisabled"
          :loading="isEdit ? saving : isLastTab ? saving : false"
          data-testid="product-form-primary"
          @click="onPrimaryClick"
        >
          <template v-if="primaryButtonState === 'analyzing'">
            Analyzing<span class="dot dot-1">.</span><span class="dot dot-2">.</span><span class="dot dot-3">.</span>
          </template>
          <template v-else>
            {{ primaryButtonLabel }}
          </template>
        </v-btn>
      </div>
    </v-card>

    <!-- FE-5073: CTX bootstrap confirmation dialog. Inline to stay inside the
         file-count budget. Uses the dlg-header/dlg-footer design-system anatomy. -->
    <v-dialog v-model="ctxConfirmOpen" max-width="520" persistent>
      <v-card class="smooth-border">
        <div class="dlg-header dlg-header--warning">
          <v-icon class="dlg-icon">mdi-refresh-circle</v-icon>
          <span class="dlg-title">Refresh AI context?</span>
          <v-btn
            icon
            variant="text"
            class="dlg-close"
            aria-label="Close"
            :disabled="ctxLaunching"
            @click="ctxConfirmOpen = false"
          >
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </div>
        <v-divider />
        <v-card-text class="pa-4">
          <div class="text-body-medium" data-test="ctx-confirm-body">
            Spawning project CTX-#### — run this next to refresh your AI's product
            context. The project will appear in your projects list.
          </div>
        </v-card-text>
        <v-divider />
        <div class="dlg-footer">
          <v-spacer />
          <v-btn variant="text" :disabled="ctxLaunching" @click="ctxConfirmOpen = false">
            Cancel
          </v-btn>
          <v-btn
            color="warning"
            variant="flat"
            :loading="ctxLaunching"
            :disabled="ctxLaunching"
            data-test="ctx-confirm-launch"
            @click="confirmCtxLaunch"
          >
            Spawn CTX project
          </v-btn>
        </div>
      </v-card>
    </v-dialog>
  </v-dialog>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useVisionAnalysis } from '@/composables/useVisionAnalysis'
import { useProductFormTabs } from '@/composables/useProductFormTabs'
import { useProductStore } from '@/stores/products'
import { useToast } from '@/composables/useToast'
import api from '@/services/api'
import ProductSetupTab from './product-form/ProductSetupTab.vue'
import ProductInfoTab from './product-form/ProductInfoTab.vue'
import ProductTechTab from './product-form/ProductTechTab.vue'
import ProductArchTab from './product-form/ProductArchTab.vue'
import ProductTestingTab from './product-form/ProductTestingTab.vue'
const props = defineProps({
  modelValue: {
    type: Boolean,
    required: true,
  },
  product: {
    type: Object,
    default: () => null,
  },
  isEdit: {
    type: Boolean,
    default: false,
  },
  existingVisionDocuments: {
    type: Array,
    default: () => [],
  },
  uploadingVision: {
    type: Boolean,
    default: false,
  },
  uploadProgress: {
    type: Number,
    default: 0,
  },
  visionUploadError: {
    type: String,
    default: null,
  },
  // Parent-driven spinner state. Bound via v-model:saving so the parent
  // can reset the button to idle on error (see ProductsView.saveProduct
  // catch block). Without this, a 4xx from the backend left the button
  // permanently in :loading state and looked like a frozen UI.
  saving: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits([
  'update:modelValue',
  'update:saving',
  'save',
  'cancel',
  'remove-vision',
  'clear-upload-error',
  'upload-vision-files',
])

// Internal proxy mirrors the v-model:saving prop so the rest of the
// component reads/writes through one symbol. setSaving() forwards to
// the parent so the parent stays the source of truth.
const saving = computed({
  get: () => props.saving,
  set: (value) => emit('update:saving', value),
})
const formValid = ref(false)
const formRef = ref(null)
// New-product onboarding paths (create mode only). Mutually exclusive:
//   - skipAiAnalysis: a document IS required and still uploads + chunks; only
//     the AI/agent prompt step is skipped. Tabs unlock for manual fill once a
//     doc is attached (Path B).
//   - createBlank: explicit doc-LESS escape — unlocks tabs immediately with no
//     document (Path C). The only path that bypasses the document requirement.
// Path A (AI-assisted) is unchanged: agent finishes -> optimistic WS unlock.
const skipAiAnalysis = ref(false)
const createBlank = ref(false)

// Choosing one path clears the other so the gate has a single active intent.
function onSkipAiAnalysis(value) {
  skipAiAnalysis.value = value
  if (value) createBlank.value = false
}
function onCreateBlank(value) {
  createBlank.value = value
  if (value) skipAiAnalysis.value = false
}

// eslint-disable-next-line no-unused-vars -- tabOrder exposed on vm for test assertions
const { dialogTab, tabOrder, isFirstTab, isLastTab, goNextTab, goPrevTab, resetTab } = useProductFormTabs()

const productStore = useProductStore()

// BE-5118/FE-9121: vision_analysis_complete gate. The flag lives on the
// Product model. Read priority:
//   1. productStore.getProductById(props.product.id) — the store's per-id
//      cache, write-through refreshed on WS event regardless of whether this
//      product is the globally selected one.
//   2. Fallback to props.product if the store doesn't have a fresh copy yet.
// The store path is the source of truth so the gate flips reactively when the
// vision:analysis_complete WebSocket event fires without requiring the dialog
// to close+reopen.
const visionAnalysisComplete = computed(() => {
  const sp = productStore.getProductById(props.product?.id)
  if (sp && typeof sp.vision_analysis_complete === 'boolean') {
    return sp.vision_analysis_complete
  }
  return Boolean(props.product?.vision_analysis_complete)
})

const hasVisionDoc = computed(() => props.existingVisionDocuments.length > 0)

// FE-6088: a NEW product is LOCKED BY DEFAULT (a document is the default-required
// input) and unlocks only via one of the three explicit paths:
//   A. AI analysis complete (optimistic WS unlock).
//   B. "Skip AI Analysis" checked AND a document attached.
//   C. "Create blank" chosen (no document).
// "Skip AI Analysis" with NO document does NOT unlock — Path B requires the doc.
const newProductUnlocked = computed(() => {
  if (createBlank.value) return true
  if (skipAiAnalysis.value && hasVisionDoc.value) return true
  return visionAnalysisComplete.value
})

// Gate is closed for a new product until one of the three paths opens it. Edit
// mode (saved products) is never blocked — FE-5073 staleness banner covers the
// re-analysis flow for saved products. FE-6007.
const gateActive = computed(() => !props.isEdit && !newProductUnlocked.value)

// Tabs beyond setup are locked while the gate is closed. The setup tab itself
// stays available so the user can attach a document, stage analysis, or pick
// the manual/blank paths.
const TAB_LOCKABLE_VALUES = ['info', 'tech', 'arch', 'features']
function isTabLocked(tabValue) {
  return gateActive.value && TAB_LOCKABLE_VALUES.includes(tabValue)
}

const {
  promptFallbackText,
  analysisInProgress,
  analysisAgentConnected,
  analysisHintVisible,
  resetAnalysisState,
  stageAnalysis: runStageAnalysis,
  onVisionAnalysisStarted,
  onVisionAnalysisComplete,
} = useVisionAnalysis((formData) => { productForm.value = formData })

// Footer single-CTA state machine. The Setup-tab now drives the primary
// button through 4 logical states (create mode) plus the existing
// Save/Create flow (edit + final tab). See ProductForm.spec.js for the
// authoritative regression matrix.
const primaryButtonState = computed(() => {
  if (props.isEdit) return 'save'
  if (isLastTab.value) return 'create'
  if (analysisAgentConnected.value || analysisInProgress.value) return 'analyzing'
  // Path C (blank) and Path B (skip+doc) and Path A (analysis complete) all
  // unlock the wizard, so the CTA advances to "Next".
  if (newProductUnlocked.value) return 'next'
  // "Skip AI Analysis" checked but no doc yet: the path is chosen but blocked
  // on the document — show "Next" (disabled until a doc is attached).
  if (skipAiAnalysis.value) return 'next'
  // Idle on Setup tab — no docs yet OR docs present but not analyzed.
  // Both surface as "Stage analysis" so the CTA is consistent regardless of
  // whether the user has attached files. The disabled-ness differs (see
  // nextOrSaveDisabled).
  return 'stage'
})

const primaryButtonLabel = computed(() => {
  switch (primaryButtonState.value) {
    case 'save': return 'Save Changes'
    case 'create': return 'Create Product'
    case 'analyzing': return 'Analyzing'
    case 'stage': return 'Stage analysis'
    case 'next':
    default: return 'Next'
  }
})

// Composite disabled-state for the footer primary button. Matrix:
//   - saving spinner → disabled
//   - edit mode → form must be valid + not analyzing
//   - final-tab create → form must be valid
//   - analyzing → disabled (spinner-like state)
//   - stage analysis, no docs → disabled (must attach at least one doc)
//   - stage analysis, docs present → enabled (user clicks to stage)
//   - next (create blank) → requires product name only
//   - next (skip AI Analysis) → requires product name AND a document (Path B)
//   - next (analysis complete) → enabled
const nextOrSaveDisabled = computed(() => {
  if (saving.value) return true
  if (props.isEdit) {
    return !formValid.value || analysisInProgress.value
  }
  if (isLastTab.value) {
    return !formValid.value
  }
  if (primaryButtonState.value === 'analyzing') return true
  if (primaryButtonState.value === 'stage') {
    // Need a product name AND at least one vision doc to actually stage.
    const hasName = !!productForm.value.name?.trim()
    return !hasName || !hasVisionDoc.value
  }
  if (primaryButtonState.value === 'next') {
    const hasName = !!productForm.value.name?.trim()
    // Path C (create blank): name is the only gate (no document required).
    if (createBlank.value) return !hasName
    // Path B (skip AI Analysis): a document is mandatory before advancing.
    if (skipAiAnalysis.value) return !hasName || !hasVisionDoc.value
    // Path A (analysis complete): name was required to attach docs already.
    return false
  }
  return false
})

// ============================================
// FE-5073: AI context staleness banner + CTX bootstrap CTA
// ============================================
//
// All banner-visibility / counter state is derived from the live store
// (productStore.getProductById) — NOT props.product — so WebSocket-driven
// mutations like vision_doc_added or consolidation_complete update the
// banner without requiring the dialog to close+reopen (memory:
// feedback_frontend_prop_vs_store_source_of_truth).
//
// Hash semantics (see src/giljo_mcp/services/vision_hash.py):
//   * vision_inputs_hash carries a `sha256:` prefix; sentinel `sha256:empty`
//     means no active docs.
//   * consolidated_vision_hash is raw hex (no prefix), null until first
//     consolidation. Comparison strips the prefix from vision_inputs_hash.
const VISION_HASH_PREFIX = 'sha256:'
const VISION_HASH_EMPTY = 'sha256:empty'

function stripHashPrefix(h) {
  if (!h) return ''
  return h.startsWith(VISION_HASH_PREFIX) ? h.slice(VISION_HASH_PREFIX.length) : h
}

const router = useRouter()
const { showToast } = useToast()
const ctxConfirmOpen = ref(false)
const ctxLaunching = ref(false)

// Resolve the most-current product snapshot. The store's per-id cache wins
// when it has a fresher copy of the edited product; otherwise fall back to
// props. Banner derivation MUST flow through this so a WS event refreshing
// productStore.productsById re-renders the banner.
const liveProduct = computed(() => {
  return productStore.getProductById(props.product?.id) || props.product || null
})

// True iff the current vision inputs no longer match the last consolidated
// hash. Banner is gated additionally on isEdit + presence of input docs.
const visionContextIsStale = computed(() => {
  const p = liveProduct.value
  if (!p) return false
  const inputs = p.vision_inputs_hash
  if (!inputs || inputs === VISION_HASH_EMPTY) return false
  const persisted = p.consolidated_vision_hash
  if (!persisted) {
    // First-run case: docs exist but consolidation never happened. Treat as
    // stale only if there is at least one input doc (inputs hash is real).
    return true
  }
  return stripHashPrefix(inputs) !== persisted
})

// "New documents since the last refresh" heuristic. Uses
// existingVisionDocuments (the canonical visible list passed by parent) and
// counts docs whose created_at exceeds product.consolidated_at. Falls back to
// total doc count when consolidated_at is null (never consolidated).
const newDocsSinceLastRefresh = computed(() => {
  const p = liveProduct.value
  if (!p) return 0
  const docs = props.existingVisionDocuments || []
  const cutoff = p.consolidated_at ? new Date(p.consolidated_at).getTime() : null
  if (!cutoff) return docs.length
  return docs.filter((d) => {
    const ts = d?.created_at ? new Date(d.created_at).getTime() : 0
    return ts > cutoff
  }).length
})

const showStalenessBanner = computed(() => {
  if (!props.isEdit) return false
  return visionContextIsStale.value
})

const stalenessBannerText = computed(() => {
  const n = newDocsSinceLastRefresh.value
  if (n > 0) {
    const noun = n === 1 ? 'document' : 'documents'
    return `${n} ${noun} added since the last AI context refresh — your AI's context is stale at the Light and Medium depth tiers.`
  }
  return "Your vision documents have changed since the last AI context refresh."
})

function openCtxConfirm() {
  ctxConfirmOpen.value = true
}

// Look up the CTX taxonomy row id at click-time. We avoid prefetching to keep
// the modal's mount cheap and because the taxonomy is small (one extra GET).
async function resolveCtxProjectTypeId() {
  const resp = await api.taxonomyTypes.list()
  const types = resp?.data || []
  const ctx = types.find((t) => (t?.abbreviation || '').toUpperCase() === 'CTX')
  return ctx?.id || null
}

// Cap payload to backend 422 limits: max 50 docs, each string <=200 chars.
function buildBootstrapTemplateVars(docs) {
  const trim = (s) => (s ? String(s).slice(0, 200) : '')
  const truncated = (docs || []).slice(0, 50).map((d) => ({
    document_name: trim(d?.filename || d?.document_name || ''),
    document_type: trim(d?.document_type || d?.mime_type || ''),
  }))
  return { new_documents: truncated }
}

async function confirmCtxLaunch() {
  const product = liveProduct.value
  if (!product?.id) return
  ctxLaunching.value = true
  try {
    // Idempotency probe: if an open CTX project already exists for this
    // product, prefer the server's hash_matches signal over re-launching.
    try {
      const existing = await api.products.getContextUpdateProject(product.id)
      const data = existing?.data
      if (data?.project_id) {
        ctxConfirmOpen.value = false
        emit('update:modelValue', false)
        if (data.hash_matches) {
          showToast({
            message: 'Already fresh — no update needed.',
            type: 'info',
          })
        } else {
          showToast({
            message: `Project ${data.taxonomy_alias || 'CTX'} already exists — go to projects to run it.`,
            type: 'info',
          })
        }
        try {
          await router.push({ path: '/projects', query: { project_id: data.project_id } })
        } catch {
          // Navigation cancelled (user clicked elsewhere) — toast already shown.
        }
        return
      }
    } catch (err) {
      // 404 is the expected "no open CTX project" path — proceed to create.
      if (err?.response?.status !== 404) throw err
    }

    const projectTypeId = await resolveCtxProjectTypeId()
    if (!projectTypeId) {
      showToast({
        message: 'CTX project type is not registered. Contact your admin.',
        type: 'error',
      })
      return
    }

    const payload = {
      name: `Context update for ${product.name}`,
      description: 'Refresh AI vision-context aggregates for this product.',
      product_id: product.id,
      project_type_id: projectTypeId,
      bootstrap_template_vars: buildBootstrapTemplateVars(props.existingVisionDocuments),
    }
    const createResp = await api.projects.create(payload)
    const created = createResp?.data
    const alias = created?.taxonomy_alias || created?.project_alias || 'CTX-####'
    ctxConfirmOpen.value = false
    emit('update:modelValue', false)
    showToast({
      message: `Project ${alias} created — go to projects to run it.`,
      type: 'success',
    })
    if (created?.id) {
      try {
        await router.push({ path: '/projects', query: { project_id: created.id } })
      } catch {
        // Navigation cancelled — toast already shown.
      }
    }
  } catch (err) {
    console.error('[FE-5073] CTX launch failed:', err)
    showToast({
      message: err?.response?.data?.detail || 'Failed to create context-update project.',
      type: 'error',
    })
  } finally {
    ctxLaunching.value = false
  }
}

// Product form data — single source of truth for the default shape
function getDefaultFormState() {
  return {
    name: '',
    description: '',
    projectPath: '',
    targetPlatforms: ['all'],
    techStack: {
      programming_languages: '',
      frontend_frameworks: '',
      backend_frameworks: '',
      databases_storage: '',
      infrastructure: '',
    },
    architecture: {
      primary_pattern: '',
      design_patterns: '',
      api_style: '',
      architecture_notes: '',
      coding_conventions: '',
    },
    coreFeatures: '',
    brandGuidelines: '',
    testConfig: {
      quality_standards: '',
      test_strategy: 'TDD',
      coverage_target: 80,
      testing_frameworks: '',
    },
    extractionCustomInstructions: '',
  }
}

const productForm = ref(getDefaultFormState())

// Computed v-model for dialog
const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

// Handover 0425: Platform selection state
const platformValidationError = ref('')

function closeDialog() {
  emit('cancel')
  emit('update:modelValue', false)
}

function saveProduct() {
  if (!formValid.value) return
  if (!validatePlatforms()) return

  saving.value = true

  const productData = {
    name: productForm.value.name,
    description: productForm.value.description,
    project_path: productForm.value.projectPath,
    target_platforms: productForm.value.targetPlatforms,
    tech_stack: productForm.value.techStack,
    architecture: productForm.value.architecture,
    test_config: productForm.value.testConfig,
    core_features: productForm.value.coreFeatures,
    brand_guidelines: productForm.value.brandGuidelines,
    extraction_custom_instructions: productForm.value.extractionCustomInstructions,
  }

  emit('save', { productData })
}

function deleteVisionDocument(doc) {
  emit('remove-vision', doc)
}


function stageAnalysis() {
  return runStageAnalysis(productForm.value, props.product?.id)
}

// Single dispatcher for the footer primary CTA. Branches on the computed
// state from primaryButtonState. Edit + final-tab save flows go to
// saveProduct(); the staging state goes to stageAnalysis(); everything else
// advances the tab.
function onPrimaryClick() {
  if (props.isEdit) {
    saveProduct()
    return
  }
  if (isLastTab.value) {
    saveProduct()
    return
  }
  if (primaryButtonState.value === 'stage') {
    stageAnalysis()
    return
  }
  // 'next' (skip ON, or analysis complete) — advance to next tab.
  goNextTab()
}

// Called from ProductSetupTab's @upload-vision-files event.
// The tab emits {productName, files} so we forward to the parent view.
// Also accepts a raw File[] for backward compat with the existing spec tests.
function onFilesAttached(payload) {
  // Support both {productName, files} (from ProductSetupTab) and File[] (tests)
  if (Array.isArray(payload)) {
    if (!payload.length) return
    emit('upload-vision-files', { productName: productForm.value.name, files: [...payload] })
    return
  }
  if (!payload?.files || payload.files.length === 0) return
  emit('upload-vision-files', payload)
}

// Handover 0425: Platform selection handlers
function handleAllPlatformChange(value) {
  platformValidationError.value = ''
  if (value && productForm.value.targetPlatforms.includes('all')) {
    productForm.value.targetPlatforms = ['all']
  } else if (!value) {
    productForm.value.targetPlatforms = productForm.value.targetPlatforms.filter(p => p !== 'all')
  }
  validatePlatforms()
}

function handlePlatformChange() {
  platformValidationError.value = ''
  if (productForm.value.targetPlatforms.includes('all') && productForm.value.targetPlatforms.length > 1) {
    productForm.value.targetPlatforms = productForm.value.targetPlatforms.filter(p => p !== 'all')
  }
  validatePlatforms()
}

function validatePlatforms() {
  const valid = productForm.value.targetPlatforms.length > 0
  platformValidationError.value = valid ? '' : 'At least one platform must be selected'
  if (!valid) formValid.value = false
  return valid
}

function loadProductData() {
  if (!props.isEdit || !props.product) {
    productForm.value = getDefaultFormState()
    return
  }
  const p = props.product
  const ts = p.tech_stack || {}
  const arch = p.architecture || {}
  const tc = p.test_config || {}
  productForm.value = {
    name: p.name || '',
    description: p.description || '',
    projectPath: p.project_path || '',
    targetPlatforms: p.target_platforms || ['all'],
    techStack: {
      programming_languages: ts.programming_languages || '',
      frontend_frameworks: ts.frontend_frameworks || '',
      backend_frameworks: ts.backend_frameworks || '',
      databases_storage: ts.databases_storage || '',
      infrastructure: ts.infrastructure || '',
    },
    architecture: {
      primary_pattern: arch.primary_pattern || '',
      design_patterns: arch.design_patterns || '',
      api_style: arch.api_style || '',
      architecture_notes: arch.architecture_notes || '',
      coding_conventions: arch.coding_conventions || '',
    },
    coreFeatures: p.core_features || '',
    brandGuidelines: p.brand_guidelines || '',
    testConfig: {
      quality_standards: tc.quality_standards || '',
      test_strategy: tc.test_strategy || 'TDD',
      coverage_target: tc.coverage_target || 80,
      testing_frameworks: tc.testing_frameworks || '',
    },
    extractionCustomInstructions: p.extraction_custom_instructions || '',
  }
}
watch(() => props.modelValue, (newVal) => {
  if (newVal) {
    resetTab()
    saving.value = false
    skipAiAnalysis.value = false
    createBlank.value = false
    ctxConfirmOpen.value = false
    ctxLaunching.value = false
    resetAnalysisState()
    loadProductData()
  }
})

watch(() => props.product, () => {
  if (props.modelValue && props.isEdit) loadProductData()
}, { deep: true })

function handleVisionAnalysisStarted(event) {
  onVisionAnalysisStarted(event, props.product?.id)
}

function handleVisionAnalysisComplete(event) {
  return onVisionAnalysisComplete(event, props.product?.id)
}

onMounted(() => {
  window.addEventListener('vision-analysis-started', handleVisionAnalysisStarted)
  window.addEventListener('vision-analysis-complete', handleVisionAnalysisComplete)
})

onUnmounted(() => {
  window.removeEventListener('vision-analysis-started', handleVisionAnalysisStarted)
  window.removeEventListener('vision-analysis-complete', handleVisionAnalysisComplete)
})
</script>

<style lang="scss" scoped>
@use '../../styles/design-tokens' as *;

/* Card uses darker background color for layered effect */
/* Header and footer inherit this dark background, content area is lighter */
.product-form-card {
  background: rgb(var(--v-theme-background)) !important;
}

/* Button toggle tabs styling - matches Settings page pattern */
.bordered-tabs-content {
  border: none;
  border-top: none;
  border-radius: 0 $border-radius-default $border-radius-default $border-radius-default;
  padding: 16px;
  background: rgb(var(--v-theme-surface));
}

/* All tabs - transparent background by default, remove bottom border */
:deep(.v-btn-toggle > .v-btn) {
  background: transparent !important;
  border-bottom-color: transparent !important;
}

/* Inactive tabs - faded text, transparent background (shows darker card bg) */
:deep(.v-btn-toggle > .v-btn:not(.v-btn--active)) {
  color: rgba(255, 255, 255, 0.5) !important;
  background: transparent !important;
}

/* Active tab - lighter surface background that matches content area */
:deep(.v-btn-toggle > .v-btn.v-btn--active) {
  background: rgb(var(--v-theme-surface)) !important;
  color: white !important;
}

/* Override Vuetify overlay on active button */
:deep(.v-btn-toggle > .v-btn.v-btn--active > .v-btn__overlay) {
  opacity: 0 !important;
}

/* Animated waiting dots — each dot fades in sequentially then all reset */
.dot {
  opacity: 0;
  animation: dot-pulse 1.4s infinite steps(1, end);
}

.dot-1 { animation-delay: 0s; }
.dot-2 { animation-delay: 0.35s; }
.dot-3 { animation-delay: 0.7s; }

@keyframes dot-pulse {
  0%   { opacity: 0; }
  25%  { opacity: 1; }
  100% { opacity: 0; }
}
</style>
