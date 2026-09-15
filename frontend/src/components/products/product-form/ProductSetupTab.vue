<template>
  <div>
    <div class="text-body-large mb-1">Product Setup</div>
    <div class="text-body-small text-warning mb-4">Always used as context source by orchestrator.</div>

    <v-alert
      v-if="showStalenessBanner"
      type="warning"
      variant="tonal"
      density="compact"
      class="mb-4"
      data-test="ctx-staleness-banner"
    >
      <div class="d-flex align-center flex-wrap ga-3">
        <div class="text-body-medium flex-grow-1">
          {{ stalenessBannerText }}
        </div>
        <v-btn
          color="warning"
          variant="flat"
          size="small"
          :loading="ctxLaunching"
          :disabled="ctxLaunching"
          data-test="ctx-update-cta"
          @click="$emit('open-ctx-confirm')"
        >
          Update AI context
        </v-btn>
      </div>
    </v-alert>

    <v-text-field
      v-model="form.name"
      label="Product Name"
      :rules="[(v) => !!v || 'Product name is required']"
      variant="outlined"
      density="comfortable"
      required
      maxlength="255"
      counter="255"
      class="mb-4 mt-2"
    ></v-text-field>

    <div class="text-title-small mt-2 mb-1">Vision Documents</div>
    <div class="text-body-small text-muted-a11y mb-4">
      Optionally included as context source by orchestrator.
      <v-chip size="x-small" color="success" variant="tonal" class="ml-2">Activated in Context Manager</v-chip>
    </div>

    <v-alert
      v-if="visionUploadError"
      type="error"
      variant="tonal"
      density="compact"
      dismissible
      class="mb-4"
      @click:close="$emit('clear-upload-error')"
    >
      {{ visionUploadError }}
    </v-alert>

    <v-alert
      v-if="uploadingVision"
      type="info"
      variant="tonal"
      density="compact"
      class="mb-4"
    >
      <div class="d-flex align-center mb-2">
        <v-progress-circular indeterminate size="20" width="2" class="mr-2" />
        <span>Uploading and processing documents...</span>
      </div>
      <v-progress-linear
        :model-value="uploadProgress"
        color="primary"
        height="6"
        class="mt-2"
      />
    </v-alert>

    <div v-if="existingVisionDocuments.length > 0" class="mb-4">
      <div class="text-title-small mb-2">
        Existing Documents ({{ existingVisionDocuments.length }})
      </div>

      <v-list density="compact" class="mb-3">
        <v-list-item
          v-for="doc in existingVisionDocuments"
          :key="doc.id"
          class="border rounded mb-2"
        >
          <template #prepend>
            <v-icon :color="(doc.is_summarized || doc.chunked) ? 'success' : 'warning'">
              {{ (doc.is_summarized || doc.chunked) ? 'mdi-check-circle' : 'mdi-clock-outline' }}
            </v-icon>
          </template>

          <v-list-item-title>{{ doc.filename || doc.document_name }}</v-list-item-title>
          <v-list-item-subtitle>
            {{ doc.is_summarized ? 'Analyzed' : 'Pending analysis' }}
            <span v-if="doc.chunked"> • {{ doc.chunk_count }} chunks</span>
            • {{ formatDate(doc.created_at) }}
          </v-list-item-subtitle>

          <template #append>
            <v-btn
              icon
              size="small"
              variant="text"
              color="error"
              @click="$emit('remove-vision', doc)"
            >
              <v-icon size="20">mdi-delete</v-icon>
            </v-btn>
          </template>
        </v-list-item>
      </v-list>
    </div>

    <v-file-input
      v-model="localVisionFiles"
      accept=".txt,.md,.markdown,text/plain,text/markdown"
      label="Choose files"
      variant="outlined"
      density="comfortable"
      multiple
      show-size
      clearable
      prepend-icon="mdi-folder-open"
      hint="TXT or MD, max 5 MB"
      persistent-hint
      :disabled="createBlank || !form.name?.trim()"
      class="mb-3"
      @update:model-value="onFilesAttached"
    ></v-file-input>

    <v-checkbox
      v-if="!isEdit"
      v-model="skipAiAnalysis"
      label="Skip AI Analysis"
      :disabled="createBlank"
      hint="Upload a document for context, then fill the product details yourself. The document is still saved and chunked — only the AI analysis step is skipped."
      persistent-hint
      density="comfortable"
      class="mb-2"
    />

    <v-alert
      v-if="!isEdit && skipAiAnalysis"
      type="info"
      variant="tonal"
      density="compact"
      class="mb-3 mt-2"
    >
      <span class="text-body-medium">
        Your document still uploads and is chunked for later AI analysis — only
        the agent prompt step is skipped. Fill the remaining tabs manually.
      </span>
    </v-alert>

    <div v-if="!isEdit" class="mt-1 mb-2 d-flex align-center ga-2 flex-wrap">
      <v-btn
        variant="text"
        size="small"
        color="primary"
        density="comfortable"
        data-test="create-blank-toggle"
        @click="createBlank = !createBlank"
      >
        <v-icon start size="small">{{ createBlank ? 'mdi-check-circle' : 'mdi-file-document-outline' }}</v-icon>
        {{ createBlank ? 'Creating a blank product' : 'Or create a blank product (no document)' }}
      </v-btn>
      <v-btn
        v-if="createBlank"
        variant="text"
        size="small"
        density="comfortable"
        data-test="create-blank-undo"
        @click="createBlank = false"
      >
        Add a document instead
      </v-btn>
    </div>

    <v-alert
      v-if="!isEdit && createBlank"
      type="warning"
      variant="tonal"
      density="compact"
      class="mb-3"
    >
      <span class="text-body-medium">
        (!) No document — the product description and AI context start empty. You
        can add a document and analyze it later from the product.
      </span>
    </v-alert>

    <v-expansion-panels
      v-if="!skipAiAnalysis && !createBlank && existingVisionDocuments.length > 0"
      variant="accordion"
      class="mt-2"
    >
      <v-expansion-panel>
        <v-expansion-panel-title class="text-body-medium py-2" style="min-height: 40px;">
          Customize product extraction instructions
        </v-expansion-panel-title>
        <v-expansion-panel-text>
          <v-textarea
            v-model="form.extractionCustomInstructions"
            placeholder="Add domain-specific instructions for AI document analysis (e.g., 'This is a mobile-first app targeting iOS 17+')"
            variant="outlined"
            density="compact"
            rows="2"
            auto-grow
            hide-details
            persistent-placeholder
          ></v-textarea>
        </v-expansion-panel-text>
      </v-expansion-panel>
    </v-expansion-panels>

    <v-alert
      v-if="promptFallbackText"
      type="warning"
      variant="tonal"
      density="compact"
      class="mt-3"
    >
      <div class="text-body-medium mb-1">Clipboard unavailable — copy this prompt manually:</div>
      <v-textarea
        :model-value="promptFallbackText"
        variant="outlined"
        density="compact"
        rows="3"
        readonly
        hide-details
        @focus="$event.target.select()"
      />
    </v-alert>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useFormatDate } from '@/composables/useFormatDate'

const props = defineProps({
  form: {
    type: Object,
    required: true,
  },
  isEdit: {
    type: Boolean,
    default: false,
  },
  skipAiAnalysis: {
    type: Boolean,
    default: false,
  },
  createBlank: {
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
  promptFallbackText: {
    type: String,
    default: null,
  },
  showStalenessBanner: {
    type: Boolean,
    default: false,
  },
  stalenessBannerText: {
    type: String,
    default: '',
  },
  ctxLaunching: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits([
  'update:skipAiAnalysis',
  'update:createBlank',
  'remove-vision',
  'clear-upload-error',
  'upload-vision-files',
  'open-ctx-confirm',
])

const { formatDate } = useFormatDate()

const localVisionFiles = ref([])

const skipAiAnalysis = computed({
  get: () => props.skipAiAnalysis,
  set: (value) => emit('update:skipAiAnalysis', value),
})
const createBlank = computed({
  get: () => props.createBlank,
  set: (value) => emit('update:createBlank', value),
})

function onFilesAttached(files) {
  if (!files || files.length === 0) return
  if (!props.form.name?.trim()) return
  emit('upload-vision-files', { productName: props.form.name, files: [...files] })
  localVisionFiles.value = []
}
</script>
