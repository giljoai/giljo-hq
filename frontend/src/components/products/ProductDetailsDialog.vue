<template>
  <v-dialog v-model="isOpen" max-width="600" scrollable data-testid="product-details-dialog">
    <v-card v-draggable class="smooth-border product-details-card">
      <div class="dlg-header">
        <v-icon class="dlg-icon" icon="mdi-information-outline" />
        <span class="dlg-title">Product Details</span>
        <v-btn icon variant="text" size="small" class="dlg-close" @click="handleClose">
          <v-icon icon="mdi-close" size="18" />
        </v-btn>
      </div>

      <v-divider />

      <v-card-text v-if="product" class="pa-4 dialog-body-scroll product-details-body">
        <!-- Product Name -->
        <div class="text-title-large mb-2">{{ product.name }}</div>
        <div class="text-body-small mb-4 text-muted-a11y font-mono product-id-text">ID: {{ product.id }}</div>

        <!-- Description -->
        <div class="mb-4">
          <div class="text-title-small mb-1">Description</div>
          <div class="text-body-medium">
            {{ product.description || 'No description provided' }}
          </div>
        </div>

        <!-- Statistics -->
        <div class="mb-4">
          <div class="text-title-small mb-2">Statistics</div>
          <v-row dense>
            <v-col cols="6">
              <div class="text-body-small text-muted-a11y">Unresolved Tasks</div>
              <div class="text-title-large text-secondary-a11y">{{ product.unresolved_tasks || 0 }}</div>
            </v-col>
            <v-col cols="6">
              <div class="text-body-small text-muted-a11y">Unfinished Projects</div>
              <div class="text-title-large text-secondary-a11y">{{ product.unfinished_projects || 0 }}</div>
            </v-col>
          </v-row>
        </div>

        <!-- Vision Documents -->
        <div>
          <div class="text-title-small mb-2 d-flex align-center justify-space-between">
            <span>Vision Documents ({{ visionDocuments.length }})</span>
            <v-btn
              v-if="product?.id"
              icon
              variant="text"
              size="x-small"
              title="View deleted documents"
              aria-label="View deleted vision documents"
              data-testid="deleted-vision-btn"
              @click="openDeletedDialog"
            >
              <v-icon>mdi-delete-restore</v-icon>
            </v-btn>
          </div>

          <!-- Product-level vision context summary chevron.
               Replaces the prior aggregate stats card and the
               "Consolidated Vision Summaries" card chrome. Gated on
               consolidated_vision_light existing (analysis has run). -->
          <div
            v-if="product?.consolidated_vision_light"
            class="vision-context-card smooth-border mb-3"
          >
            <button
              type="button"
              class="detail-section-toggle detail-section-toggle--compact"
              @click="toggleContextSummary"
            >
              <span class="detail-section-title-wrap">
                <span class="detail-section-title">Vision context summary</span>
              </span>
              <v-icon size="18">{{ contextSummaryOpen ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
            </button>

            <div v-if="contextSummaryOpen" class="detail-section-body">
              <div class="summary-action-grid">
                <button
                  type="button"
                  class="summary-action-btn"
                  :style="consolidatedTierStyle('light')"
                  @click="showConsolidatedSummary('light')"
                >
                  <span>33% · {{ formatTokens(product.consolidated_vision_light_tokens) }} tokens</span>
                </button>
                <button
                  type="button"
                  class="summary-action-btn"
                  :style="consolidatedTierStyle('medium')"
                  :disabled="!product?.consolidated_vision_medium"
                  @click="showConsolidatedSummary('medium')"
                >
                  <span>66% · {{ formatTokens(product.consolidated_vision_medium_tokens) }} tokens</span>
                </button>
                <button
                  type="button"
                  class="summary-action-btn"
                  :style="consolidatedTierStyle('full')"
                  :disabled="!visionDocuments.length"
                  @click="showConsolidatedSummary('full')"
                >
                  <span v-if="fullDepthTokenEstimate">100% · {{ formatTokens(fullDepthTokenEstimate) }} tokens</span>
                  <span v-else>100%</span>
                </button>
              </div>
              <div v-if="product?.consolidated_at" class="text-body-small mt-3 text-muted-a11y">
                <v-icon size="14" class="mr-1">mdi-clock-outline</v-icon>
                Last modified: {{ formatDate(product.consolidated_at) }}
                <span v-if="product?.consolidated_vision_hash" class="ml-2">
                  Hash: {{ product.consolidated_vision_hash.substring(0, 8) }}...
                </span>
              </div>
            </div>
          </div>

          <v-list v-if="visionDocuments.length > 0" density="compact">
            <v-card
              v-for="doc in visionDocuments"
              :key="doc.id"
              variant="flat"
              class="smooth-border mb-2 doc-entry-card"
            >
              <div class="doc-card-header px-3 py-3">
                <div class="doc-card-heading">
                  <v-icon color="primary" class="mr-2">mdi-file-document</v-icon>
                  <div class="doc-card-heading-text">
                    <div class="doc-card-title">{{ doc.filename || doc.document_name }}</div>
                    <div class="doc-card-meta">
                      <!-- BE-5118: per-doc analysis status pill based on
                           whether the AI agent has written light+medium
                           summaries for this specific document. -->
                      <span
                        class="doc-meta-pill doc-analysis-pill smooth-border"
                        :style="docAnalysisPillStyle(doc)"
                      >
                        {{ docAnalysisLabel(doc) }}
                      </span>
                      <span class="doc-meta-pill">{{ formatFileSize(doc.file_size || 0) }}</span>
                      <span v-if="doc.chunked" class="doc-meta-pill">Chunked · {{ doc.chunk_count }} chunks</span>
                      <span v-if="doc.original_token_count" class="doc-meta-pill">{{ formatTokens(doc.original_token_count) }} tokens</span>
                    </div>
                  </div>
                </div>
              </div>
            </v-card>
          </v-list>

          <v-alert v-else type="info" variant="tonal" density="compact">
            No vision documents attached
          </v-alert>

          <!-- AI Analysis Result (Handover 0842d) -->
          <v-alert
            v-if="visionAnalysisResult"
            type="success"
            variant="tonal"
            density="compact"
            class="mt-3 mb-3"
            closable
            @click:close="visionAnalysisResult = null"
          >
            <div class="text-body-medium">
              AI populated {{ visionAnalysisResult.fields_written }} product fields —
              <span
                class="text-primary cursor-pointer"
                role="button"
                tabindex="0"
                @click="$emit('refresh-product')"
                @keydown.enter="$emit('refresh-product')"
              >review in Product Info</span>
            </div>
          </v-alert>
        </div>

        <!-- Configuration Data Display -->
        <div v-if="product.tech_stack || product.architecture || product.test_config || product.core_features || product.brand_guidelines" class="mt-4">
          <v-divider class="mb-3"></v-divider>
          <div class="text-title-small mb-2">Configuration Data</div>

          <v-expansion-panels variant="accordion">
            <!-- Tech Stack -->
            <v-expansion-panel v-if="product.tech_stack">
              <v-expansion-panel-title>
                <v-icon start>mdi-code-tags</v-icon>
                Tech Stack
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <div v-if="product.tech_stack.programming_languages" class="mb-2">
                  <div class="text-body-small font-weight-bold">Programming Languages:</div>
                  <div class="text-body-medium">{{ product.tech_stack.programming_languages }}</div>
                </div>
                <div v-if="product.tech_stack.frontend_frameworks" class="mb-2">
                  <div class="text-body-small font-weight-bold">Frontend Frameworks:</div>
                  <div class="text-body-medium">{{ product.tech_stack.frontend_frameworks }}</div>
                </div>
                <div v-if="product.tech_stack.backend_frameworks" class="mb-2">
                  <div class="text-body-small font-weight-bold">Backend Frameworks:</div>
                  <div class="text-body-medium">{{ product.tech_stack.backend_frameworks }}</div>
                </div>
                <div v-if="product.tech_stack.databases_storage" class="mb-2">
                  <div class="text-body-small font-weight-bold">Databases & Storage:</div>
                  <div class="text-body-medium">{{ product.tech_stack.databases_storage }}</div>
                </div>
                <div v-if="product.target_platforms && product.target_platforms.length">
                  <div class="text-body-small font-weight-bold">Target Platforms:</div>
                  <div class="text-body-medium">{{ product.target_platforms.map(p => formatPlatform(p)).join(', ') }}</div>
                </div>
              </v-expansion-panel-text>
            </v-expansion-panel>

            <!-- Architecture -->
            <v-expansion-panel v-if="product.architecture">
              <v-expansion-panel-title>
                <v-icon start>mdi-sitemap</v-icon>
                Architecture
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <div v-if="product.architecture.primary_pattern" class="mb-2">
                  <div class="text-body-small font-weight-bold">Primary Pattern:</div>
                  <div class="text-body-medium">{{ product.architecture.primary_pattern }}</div>
                </div>
                <div v-if="product.architecture.api_style" class="mb-2">
                  <div class="text-body-small font-weight-bold">API Style:</div>
                  <div class="text-body-medium">{{ product.architecture.api_style }}</div>
                </div>
                <div v-if="product.architecture.design_patterns" class="mb-2">
                  <div class="text-body-small font-weight-bold">Design Patterns:</div>
                  <div class="text-body-medium">
                    {{ product.architecture.design_patterns }}
                  </div>
                </div>
                <div v-if="product.architecture.coding_conventions">
                  <div class="text-body-small font-weight-bold">Coding Conventions:</div>
                  <div class="text-body-medium text-pre-line">{{ product.architecture.coding_conventions }}</div>
                </div>
              </v-expansion-panel-text>
            </v-expansion-panel>

            <!-- Features & Testing -->
            <!-- Brand Guidelines -->
            <v-expansion-panel v-if="product.brand_guidelines">
              <v-expansion-panel-title>
                <v-icon start>mdi-palette-outline</v-icon>
                Brand & Design Guidelines
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <div class="text-body-medium text-pre-line">{{ product.brand_guidelines }}</div>
              </v-expansion-panel-text>
            </v-expansion-panel>

            <!-- Features & Testing -->
            <v-expansion-panel
              v-if="product.core_features || product.test_config"
            >
              <v-expansion-panel-title>
                <v-icon start>mdi-star-outline</v-icon>
                Features & Testing
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <div v-if="product.core_features" class="mb-2">
                  <div class="text-body-small font-weight-bold">Core Features:</div>
                  <div class="text-body-medium">{{ product.core_features }}</div>
                </div>
                <div v-if="product.test_config?.test_strategy" class="mb-2">
                  <div class="text-body-small font-weight-bold">Test Strategy:</div>
                  <div class="text-body-medium">{{ product.test_config.test_strategy }}</div>
                </div>
                <div v-if="product.test_config?.coverage_target">
                  <div class="text-body-small font-weight-bold">Coverage Target:</div>
                  <div class="text-body-medium">
                    {{ product.test_config.coverage_target }}%
                  </div>
                </div>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>
        </div>

        <!-- Created/Updated -->
        <div class="text-body-small text-muted-a11y mt-4">
          Created: {{ formatDate(product.created_at) }}<br />
          Updated: {{ formatDate(product.updated_at) }}
        </div>
      </v-card-text>

      <v-divider />

      <div class="dlg-footer">
        <v-spacer />
        <v-btn variant="text" @click="handleClose">Close</v-btn>
      </div>
    </v-card>
  </v-dialog>

  <!-- FE-6138: Deleted vision documents recovery dialog -->
  <VisionDeletedDialog
    v-model="showDeletedDialog"
    :deleted-documents="deletedDocuments"
    :restoring-id="restoringId"
    @restore="handleRestore"
  />

  <!-- Consolidated Summary Viewer Dialog (Handover 0377) -->
  <v-dialog v-model="consolidatedSummaryDialog" max-width="800" scrollable>
    <v-card v-draggable class="smooth-border">
      <div class="dlg-header">
        <v-icon class="dlg-icon" color="teal" icon="mdi-database-merge" />
        <span class="dlg-title">{{ consolidatedSummaryTitle }}</span>
        <v-chip size="small" :color="consolidatedSummaryColor" variant="tonal" class="mr-2">
          {{ consolidatedSummaryLevel }}
        </v-chip>
        <v-btn icon variant="text" size="small" class="dlg-close" @click="consolidatedSummaryDialog = false">
          <v-icon icon="mdi-close" size="18" />
        </v-btn>
      </div>

      <v-divider />

      <v-card-text class="summary-content pa-4 dialog-body-scroll">
        <div class="text-body-small text-muted-a11y mb-2">
          <v-icon size="14" class="mr-1">mdi-counter</v-icon>
          ~{{ formatTokens(consolidatedSummaryTokens) }} tokens
          <span v-if="consolidatedSummaryHash" class="ml-2">
            Hash: {{ consolidatedSummaryHash.substring(0, 12) }}...
          </span>
        </div>
        <div class="text-body-medium text-pre-wrap">{{ consolidatedSummaryContent }}</div>
      </v-card-text>

      <v-divider />

      <div class="dlg-footer">
        <v-spacer />
        <v-btn variant="text" @click="consolidatedSummaryDialog = false">Close</v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import api from '@/services/api'
import { useFormatDate } from '@/composables/useFormatDate'
import { useToast } from '@/composables/useToast'
import { hexToRgba } from '@/utils/colorUtils'
import { getAgentColor } from '@/config/agentColors'
import { getStatusColor } from '@/utils/statusConfig'
import VisionDeletedDialog from '@/components/products/VisionDeletedDialog.vue'

const { formatDate } = useFormatDate()
const { showToast } = useToast()

// Summary level color tokens (status-complete green, tester yellow, implementer blue)
const CONSOLIDATED_TIER_COLORS = {
  light: getStatusColor('complete'),
  medium: getAgentColor('tester').hex,
  full: getAgentColor('implementer').hex,
}

// intentional fallback — not a hardcoded-color violation: this feeds hexToRgba() directly;
// var() would break the rgba() computation. Matches --text-muted (#8895a8).
const FALLBACK_MUTED = '#8895a8'

// BE-5118: status colors for analysis pills. Green for analyzed (matches
// status-complete elsewhere in the dashboard), tester yellow for pending
// (warmer than warning-red, more accurate semantically — "in flight" not
// "broken"). Both pass WCAG AA on the #12202e card surface when used at
// full brightness over rgba(color, 0.15) backgrounds.
const ANALYSIS_PILL_ANALYZED_HEX = getStatusColor('complete')
const ANALYSIS_PILL_PENDING_HEX = getAgentColor('tester').hex

function consolidatedTierStyle(level) {
  const hex = CONSOLIDATED_TIER_COLORS[level] || FALLBACK_MUTED
  return { background: hexToRgba(hex, 0.15), color: hex }
}

// BE-5118: per-document analysis state. A doc is "Analyzed" once the AI
// agent has populated BOTH summary_light and summary_medium via the
// update_product_context tool. Anything else is "Pending analysis".
function docIsAnalyzed(doc) {
  return Boolean(doc?.summary_light && doc?.summary_medium)
}

function docAnalysisLabel(doc) {
  return docIsAnalyzed(doc) ? 'Analyzed' : 'Pending analysis'
}

function docAnalysisPillStyle(doc) {
  const hex = docIsAnalyzed(doc) ? ANALYSIS_PILL_ANALYZED_HEX : ANALYSIS_PILL_PENDING_HEX
  return {
    background: hexToRgba(hex, 0.15),
    color: hex,
    '--smooth-border-color': hexToRgba(hex, 0.45),
  }
}

const props = defineProps({
  modelValue: {
    type: Boolean,
    required: true,
  },
  product: {
    type: Object,
    default: () => ({}),
  },
  visionDocuments: {
    type: Array,
    default: () => [],
  },
  stats: {
    type: Object,
    default: () => ({ unresolved_tasks: 0, unfinished_projects: 0 }),
  },
})

const emit = defineEmits(['update:modelValue', 'refresh-product'])

// FE-6138: Deleted vision documents recovery
const showDeletedDialog = ref(false)
const deletedDocuments = ref([])
const restoringId = ref(null)

async function openDeletedDialog() {
  showDeletedDialog.value = true
  try {
    const response = await api.visionDocuments.getDeletedByProduct(props.product.id)
    deletedDocuments.value = response.data || []
  } catch (error) {
    console.error('[ProductDetailsDialog] Failed to load deleted vision documents:', error)
    showToast({ message: 'Could not load deleted documents. Try again.', type: 'error' })
    deletedDocuments.value = []
  }
}

async function handleRestore(doc) {
  restoringId.value = doc.id
  try {
    await api.visionDocuments.restore(doc.id)
    deletedDocuments.value = deletedDocuments.value.filter((d) => d.id !== doc.id)
    showToast({
      message: `Restored: ${doc.filename || doc.document_name}`,
      type: 'success',
    })
    // Notify parent to refresh vision docs and product data
    emit('refresh-product')
  } catch (error) {
    console.error('[ProductDetailsDialog] Failed to restore vision document:', error)
    showToast({ message: 'Failed to restore document. Try again.', type: 'error' })
  } finally {
    restoringId.value = null
  }
}

// Product-level vision context summary chevron state.
const contextSummaryOpen = ref(false)

function toggleContextSummary() {
  contextSummaryOpen.value = !contextSummaryOpen.value
}

// Vision analysis result (Handover 0842d)
const visionAnalysisResult = ref(null)

function handleVisionAnalysisComplete(event) {
  if (event.detail?.product_id === props.product?.id) {
    visionAnalysisResult.value = event.detail
  }
}

onMounted(() => {
  window.addEventListener('vision-analysis-complete', handleVisionAnalysisComplete)
})

onUnmounted(() => {
  window.removeEventListener('vision-analysis-complete', handleVisionAnalysisComplete)
})

watch(
  () => props.modelValue,
  (open) => {
    if (!open) {
      contextSummaryOpen.value = false
    }
  },
)

const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const handleClose = () => {
  emit('update:modelValue', false)
}

// Consolidated summary dialog state (Handover 0377)
const consolidatedSummaryDialog = ref(false)
const consolidatedSummaryContent = ref('')
const consolidatedSummaryTitle = ref('')
const consolidatedSummaryLevel = ref('')
const consolidatedSummaryTokens = ref(0)
const consolidatedSummaryHash = ref('')

const consolidatedSummaryColor = computed(() => {
  // Handover 0377: Consolidated vision summaries
  switch (consolidatedSummaryLevel.value) {
    case 'Light (33%)': return 'success'
    case 'Medium (66%)': return 'warning'
    case 'Full (100%)': return 'primary-lighten-1'
    default: return 'teal'
  }
})

function formatTokens(tokens) {
  if (!tokens) return '0'
  if (tokens >= 1000) {
    return `${(tokens / 1000).toFixed(1)  }K`
  }
  return tokens.toString()
}

// 100%-tier token estimate: backend doesn't persist a
// consolidated_vision_full_tokens column (full depth is per-doc raw
// concatenation built on demand by get_vision_doc). Sum the raw
// original_token_count of each vision doc as a meaningful approximation.
const fullDepthTokenEstimate = computed(() => {
  const sum = props.visionDocuments.reduce(
    (acc, doc) => acc + (doc.original_token_count || 0),
    0,
  )
  return sum > 0 ? sum : 0
})

// Helper functions
function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes  } B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)  } KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)  } MB`
}


function formatPlatform(platform) {
  const labels = {
    windows: 'Windows',
    linux: 'Linux',
    macos: 'macOS',
    android: 'Android',
    ios: 'iOS',
    web: 'Web',
    all: 'All (Cross-platform)',
  }
  return labels[platform] || platform
}

/**
 * Show consolidated vision summary (Handover 0377)
 * Displays light, medium, or full (per-doc concatenated) vision context.
 */
async function showConsolidatedSummary(depth) {
  if (depth === 'full') {
    // 100% tier is per-doc raw text concatenated with `# {filename}`
    // headers. Backend already exposes this via get_vision_doc; here we
    // synthesize the same shape client-side from cached doc data so the
    // viewer dialog can render without an extra fetch round-trip when
    // possible. If raw vision_document content is not loaded yet, hydrate
    // each missing doc individually.
    if (!props.visionDocuments.length) return
    try {
      const parts = []
      let totalTokens = 0
      for (const doc of props.visionDocuments) {
        let content = doc.vision_document
        if (!content) {
          try {
            const response = await api.visionDocuments.get(doc.id)
            const fullDoc = response.data
            content = fullDoc.vision_document
            doc.vision_document = content
            doc.original_token_count = fullDoc.original_token_count
          } catch (err) {
            console.warn('[ProductDetailsDialog] failed to hydrate doc', doc.id, err)
            content = ''
          }
        }
        const name = doc.filename || doc.document_name || `doc_${doc.id}`
        parts.push(`# ${name}\n\n${content || ''}`)
        totalTokens += doc.original_token_count || 0
      }
      consolidatedSummaryContent.value = parts.join('\n\n---\n\n')
      consolidatedSummaryTitle.value = 'Vision context — Full (100%)'
      consolidatedSummaryLevel.value = 'Full (100%)'
      consolidatedSummaryTokens.value = totalTokens
      consolidatedSummaryHash.value = props.product?.consolidated_vision_hash || ''
      consolidatedSummaryDialog.value = true
    } catch (error) {
      console.error('Failed to assemble full vision context:', error)
      showToast({ message: 'Could not load full vision context.', type: 'error' })
    }
    return
  }

  const depthMap = {
    light: {
      field: 'consolidated_vision_light',
      tokens: 'consolidated_vision_light_tokens',
      label: 'Light (33%)',
    },
    medium: {
      field: 'consolidated_vision_medium',
      tokens: 'consolidated_vision_medium_tokens',
      label: 'Medium (66%)',
    },
  }

  const config = depthMap[depth]
  if (!config || !props.product[config.field]) return

  consolidatedSummaryContent.value = props.product[config.field]
  consolidatedSummaryTitle.value = 'Consolidated Vision Summary'
  consolidatedSummaryLevel.value = config.label
  consolidatedSummaryTokens.value = props.product[config.tokens] || 0
  consolidatedSummaryHash.value = props.product.consolidated_vision_hash || ''
  consolidatedSummaryDialog.value = true
}
</script>

<style lang="scss" scoped>
@use '../../styles/design-tokens' as *;
.product-id-text {
  font-size: 0.65rem;
}

:deep(.product-details-card) {
  display: flex;
  flex-direction: column;
  max-height: min(80vh, 900px);
  overflow: hidden;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.10) !important; /* !important: :deep() must override Vuetify v-card inline box-shadow */
}

:deep(.product-details-body) {
  flex: 1 1 auto;
  min-height: 0;
}

:deep(.doc-entry-card) {
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.10) !important; /* !important: :deep() must override Vuetify v-card inline box-shadow */
}

.detail-section {
  overflow: hidden;
  background: rgba(255, 255, 255, 0.03);
}

.detail-section-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  background: transparent;
  border: none;
  color: var(--color-text-primary);
  text-align: left;
  cursor: pointer;
}

.detail-section-toggle:hover {
  background: rgba(255, 255, 255, 0.03);
}

.detail-section-toggle--compact {
  padding: 10px 14px;
}

.detail-section-title-wrap {
  display: inline-flex;
  align-items: center;
  min-width: 0;
}

.detail-section-title {
  font-size: 0.82rem;
  font-weight: 600;
}

.detail-section-body {
  padding: 0 14px 14px;
}

.detail-section-subtitle {
  margin-bottom: 10px;
}

.doc-card-header {
  display: flex;
  align-items: flex-start;
}

.doc-card-heading {
  display: flex;
  align-items: flex-start;
  width: 100%;
}

.doc-card-heading-text {
  min-width: 0;
  flex: 1;
}

.doc-card-title {
  font-size: 0.85rem;
  font-weight: 600;
  line-height: 1.4;
  word-break: break-word;
}

.doc-card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.doc-meta-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: $border-radius-pill;
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-muted);
  font-size: 0.66rem;
  line-height: 1.4;
}

// BE-5118: analysis pills are tinted, square-edged badges. Color is set
// inline via JS so the same component handles all agent-color tokens
// without per-status CSS classes.
.doc-analysis-pill {
  font-weight: 600;
  letter-spacing: 0.02em;
  background: transparent;
}

.vision-context-card {
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.10);
  border-radius: $border-radius-default;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.02);
}

.summary-action-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.summary-action-btn {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  border: none;
  border-radius: $border-radius-default;
  font-size: 0.74rem;
  font-weight: 600;
  cursor: pointer;
  transition: transform $transition-fast ease, opacity $transition-fast ease;
}

.summary-action-btn:hover:not(:disabled) {
  opacity: 0.9;
  transform: translateY(-1px);
}

.summary-action-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.summary-action-btn:focus-visible,
.detail-section-toggle:focus-visible {
  outline: 2px solid rgba(255, 195, 0, 0.45);
  outline-offset: 2px;
}

@media (max-width: 640px) {
  .summary-action-grid {
    grid-template-columns: 1fr;
  }
}
</style>
