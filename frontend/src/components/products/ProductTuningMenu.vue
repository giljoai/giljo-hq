<template>
  <div class="product-tuning-menu">
    <v-btn
      v-if="!hideTrigger"
      variant="outlined"
      color="primary"
      :loading="loadingSections"
      :disabled="loadingSections"
      data-testid="product-tuning-trigger"
      @click="togglePanel"
    >
      <v-icon start>mdi-tune</v-icon>
      Tune Context
    </v-btn>

    <v-expand-transition>
      <v-card v-if="panelOpen" variant="flat" class="mt-3 smooth-border tuning-card">
        <v-card-title class="text-body-large d-flex align-center">
          <v-icon start size="20">mdi-format-list-checks</v-icon>
          Select Sections to Tune
        </v-card-title>

        <v-divider />

        <v-card-text>
          <div v-if="loadingSections" class="d-flex align-center justify-center py-4">
            <v-progress-circular indeterminate color="primary" size="24" class="mr-3" />
            <span class="text-body-medium">Loading available sections...</span>
          </div>

          <v-alert
            v-else-if="sectionsError"
            type="error"
            variant="tonal"
            density="compact"
            class="mb-0"
          >
            {{ sectionsError }}
          </v-alert>

          <div v-else-if="sections.length > 0">
            <v-checkbox
              :model-value="allSelected"
              :indeterminate="someSelected && !allSelected"
              label="Select All"
              density="compact"
              hide-details
              color="primary"
              class="mb-1"
              @update:model-value="toggleSelectAll"
            />

            <v-divider class="my-2" />

            <v-checkbox
              v-for="section in sections"
              :key="section"
              v-model="selectedSections"
              :value="section"
              :label="getSectionLabel(section)"
              density="compact"
              hide-details
              color="primary"
              class="mb-1"
            />
          </div>

          <v-alert
            v-else
            type="info"
            variant="tonal"
            density="compact"
            class="mb-0"
          >
            No tunable sections available for this product.
          </v-alert>
        </v-card-text>

        <v-divider v-if="sections.length > 0" />

        <v-card-actions v-if="sections.length > 0">
          <v-spacer />
          <v-btn
            variant="text"
            data-testid="product-tuning-cancel"
            @click="panelOpen = false"
          >
            Cancel
          </v-btn>
          <v-btn
            variant="flat"
            color="primary"
            :loading="generatingPrompt"
            :disabled="selectedSections.length === 0 || generatingPrompt"
            data-testid="product-tuning-generate"
            @click="generatePrompt"
          >
            <v-icon start>mdi-creation</v-icon>
            Generate Tuning Prompt
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-expand-transition>

    <v-expand-transition>
      <v-card v-if="generatedPrompt" ref="generatedPromptCard" variant="flat" class="mt-3 smooth-border tuning-card">
        <v-card-title class="text-body-large d-flex align-center">
          <v-icon start size="20">mdi-text-box-outline</v-icon>
          Generated Tuning Prompt
          <v-spacer />
          <v-btn
            variant="text"
            size="small"
            :color="copied ? 'success' : 'primary'"
            @click="copyPrompt"
          >
            <v-icon start size="16">{{ copied ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>
            {{ copied ? 'Copied' : 'Copy' }}
          </v-btn>
        </v-card-title>

        <v-divider />

        <v-card-text>
          <v-textarea
            :model-value="generatedPrompt"
            readonly
            auto-grow
            rows="8"
            max-rows="20"
            variant="outlined"
            density="compact"
            hide-details
            aria-label="Generated tuning prompt"
          />
        </v-card-text>

        <v-card-actions>
          <v-spacer />
          <v-btn
            variant="text"
            @click="generatedPrompt = ''"
          >
            Dismiss
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-expand-transition>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import api from '@/services/api'
import { useClipboard } from '@/composables/useClipboard'
import { useToast } from '@/composables/useToast'

const props = defineProps({
  productId: {
    type: String,
    required: true,
  },
  hideTrigger: {
    type: Boolean,
    default: false,
  },
  initiallyOpen: {
    type: Boolean,
    default: false,
  },
})

const { copy: clipboardCopy, copied } = useClipboard()
const { showToast } = useToast()

const panelOpen = ref(false)
const sections = ref([])
const selectedSections = ref([])
const loadingSections = ref(false)
const sectionsError = ref('')

const generatingPrompt = ref(false)
const generatedPrompt = ref('')
const generatedPromptCard = ref(null)

const SECTION_LABELS = {
  description: 'Product Description',
  tech_stack: 'Tech Stack',
  architecture: 'Architecture',
  core_features: 'Core Features',
  codebase_structure: 'Codebase Structure',
  database_type: 'Database',
  backend_framework: 'Backend Framework',
  frontend_framework: 'Frontend Framework',
  quality_standards: 'Quality Standards',
  target_platforms: 'Target Platforms',
  vision_documents: 'Vision Documents',
}

const allSelected = computed(() => {
  return sections.value.length > 0 && selectedSections.value.length === sections.value.length
})

const someSelected = computed(() => {
  return selectedSections.value.length > 0
})

function getSectionLabel(section) {
  return SECTION_LABELS[section] || section.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

async function togglePanel() {
  if (panelOpen.value) {
    panelOpen.value = false
    return
  }

  panelOpen.value = true
  await fetchSections()
}

async function fetchSections() {
  loadingSections.value = true
  sectionsError.value = ''

  try {
    const response = await api.products.getTuningSections(props.productId)
    const data = response.data
    sections.value = data.sections || []
    selectedSections.value = [...sections.value]
  } catch (error) {
    const message = error.response?.data?.detail || 'Failed to load tuning sections'
    sectionsError.value = message
    console.error('[ProductTuningMenu] Failed to fetch sections:', error)
  } finally {
    loadingSections.value = false
  }
}

watch(
  () => props.initiallyOpen,
  async (shouldOpen) => {
    if (!shouldOpen || panelOpen.value) {
      return
    }

    panelOpen.value = true
    await fetchSections()
  },
  { immediate: true },
)

function toggleSelectAll(value) {
  if (value) {
    selectedSections.value = [...sections.value]
  } else {
    selectedSections.value = []
  }
}

async function generatePrompt() {
  generatingPrompt.value = true

  try {
    const response = await api.products.generateTuningPrompt(
      props.productId,
      selectedSections.value,
    )

    const data = response.data
    generatedPrompt.value = data.prompt || data.generated_prompt || ''

    if (!generatedPrompt.value) {
      showToast({ message: 'No prompt was generated. Check that selected sections have data.', type: 'warning' })
    } else {
      await nextTick()
      requestAnimationFrame(() => {
        const el = generatedPromptCard.value?.$el ?? generatedPromptCard.value
        if (el && typeof el.scrollIntoView === 'function') {
          el.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }
      })
    }
  } catch (error) {
    const message = error.response?.data?.detail || 'Failed to generate tuning prompt'
    showToast({ message, type: 'error' })
    console.error('[ProductTuningMenu] Failed to generate prompt:', error)
  } finally {
    generatingPrompt.value = false
  }
}

async function copyPrompt() {
  const success = await clipboardCopy(generatedPrompt.value)
  if (success) {
    showToast({ message: 'Tuning prompt copied. Paste so your agent can refine the selected sections.', type: 'success' })
  } else {
    showToast({ message: 'Clipboard blocked. Select the prompt and press Ctrl+C to copy manually.', type: 'error' })
  }
}
</script>

<style lang="scss" scoped>
@use '../../styles/design-tokens' as *;

.tuning-card {
  border-radius: $border-radius-md;
}
</style>
