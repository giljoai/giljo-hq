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
          <v-btn
            v-for="tab in LOCKABLE_TABS"
            :key="tab.value"
            :value="tab.value"
            :data-testid="`product-form-tab-${tab.value}`"
            :disabled="analysisInProgress || isTabLocked(tab.value)"
          >
            <v-icon start size="small">{{ tab.icon }}</v-icon>
            {{ tab.label }}
            <v-tooltip v-if="isTabLocked(tab.value)" activator="parent" location="bottom">
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
import { parseErrorResponse } from '@/utils/errorMessages'
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

const saving = computed({
  get: () => props.saving,
  set: (value) => emit('update:saving', value),
})
const formValid = ref(false)
const formRef = ref(null)
const skipAiAnalysis = ref(false)
const createBlank = ref(false)

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

const visionAnalysisComplete = computed(() => {
  const sp = productStore.getProductById(props.product?.id)
  if (sp && typeof sp.vision_analysis_complete === 'boolean') {
    return sp.vision_analysis_complete
  }
  return Boolean(props.product?.vision_analysis_complete)
})

const hasVisionDoc = computed(() => props.existingVisionDocuments.length > 0)

const newProductUnlocked = computed(() => {
  if (createBlank.value) return true
  if (skipAiAnalysis.value && hasVisionDoc.value) return true
  return visionAnalysisComplete.value
})

const gateActive = computed(() => !props.isEdit && !newProductUnlocked.value)

const LOCKABLE_TABS = [
  { value: 'info', icon: 'mdi-information-outline', label: 'Product Info' },
  { value: 'tech', icon: 'mdi-code-braces', label: 'Tech Stack' },
  { value: 'arch', icon: 'mdi-sitemap', label: 'Architecture' },
  { value: 'features', icon: 'mdi-test-tube', label: 'Testing' },
]
function isTabLocked(tabValue) {
  return gateActive.value && LOCKABLE_TABS.some((t) => t.value === tabValue)
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

const primaryButtonState = computed(() => {
  if (props.isEdit) return 'save'
  if (isLastTab.value) return 'create'
  if (analysisAgentConnected.value || analysisInProgress.value) return 'analyzing'
  if (newProductUnlocked.value) return 'next'
  if (skipAiAnalysis.value) return 'next'
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
    const hasName = !!productForm.value.name?.trim()
    return !hasName || !hasVisionDoc.value
  }
  if (primaryButtonState.value === 'next') {
    const hasName = !!productForm.value.name?.trim()
    if (createBlank.value) return !hasName
    if (skipAiAnalysis.value) return !hasName || !hasVisionDoc.value
    return false
  }
  return false
})

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

const liveProduct = computed(() => {
  return productStore.getProductById(props.product?.id) || props.product || null
})

const visionContextIsStale = computed(() => {
  const p = liveProduct.value
  if (!p) return false
  const inputs = p.vision_inputs_hash
  if (!inputs || inputs === VISION_HASH_EMPTY) return false
  const persisted = p.consolidated_vision_hash
  if (!persisted) {
    return true
  }
  return stripHashPrefix(inputs) !== persisted
})

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

async function resolveCtxProjectTypeId() {
  const resp = await api.taxonomyTypes.list()
  const types = resp?.data || []
  const ctx = types.find((t) => (t?.abbreviation || '').toUpperCase() === 'CTX')
  return ctx?.id || null
}

function buildBootstrapTemplateVars(docs) {
  const trim = (s) => (s ? String(s).slice(0, 200) : '')
  const truncated = (docs || []).slice(0, 50).map((d) => ({
    document_name: trim(d?.document_name || ''),
    document_type: trim(d?.document_type || d?.mime_type || ''),
  }))
  return { new_documents: truncated }
}

async function confirmCtxLaunch() {
  const product = liveProduct.value
  if (!product?.id) return
  ctxLaunching.value = true
  try {
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
      message: parseErrorResponse(err).message || 'Failed to create context-update project.',
      type: 'error',
    })
  } finally {
    ctxLaunching.value = false
  }
}

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

const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

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
  goNextTab()
}

function onFilesAttached(payload) {
  if (!payload?.files || payload.files.length === 0) return
  emit('upload-vision-files', payload)
}

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
