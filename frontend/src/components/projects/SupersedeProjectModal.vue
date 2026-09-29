<template>
  <v-dialog
    :model-value="show"
    max-width="520"
    persistent
    class="supersede-project-modal"
    role="dialog"
    aria-labelledby="supersede-project-title"
    data-testid="supersede-project-modal"
    @keydown.esc="handleClose"
  >
    <v-card v-draggable class="smooth-border">
      <div id="supersede-project-title" class="dlg-header">
        <v-icon class="dlg-icon" icon="mdi-file-replace-outline" />
        <span class="dlg-title">Mark Superseded: {{ projectName }}</span>
        <v-btn icon variant="text" size="small" class="dlg-close" aria-label="Close modal" @click="handleClose">
          <v-icon icon="mdi-close" size="18" />
        </v-btn>
      </div>

      <v-divider />

      <v-card-text class="pa-4">
        <p class="text-body-medium mb-4" style="color: var(--text-secondary)">
          Superseding this project marks it read-only and links it to the project that replaces it.
          This cannot be undone.
        </p>

        <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-4" closable @click:close="error = null">
          {{ error }}
        </v-alert>

        <v-select
          v-model="successorProjectId"
          data-testid="successor-select"
          label="Successor project"
          placeholder="Choose the project that replaces this one"
          :items="successorOptions"
          :loading="loadingCandidates"
          variant="outlined"
          density="comfortable"
          hide-details
        />
      </v-card-text>

      <v-divider />

      <div class="dlg-footer">
        <v-btn variant="text" @click="handleClose">
          Cancel
        </v-btn>
        <v-spacer />
        <v-btn
          color="primary"
          variant="elevated"
          :disabled="!successorProjectId"
          :loading="submitting"
          data-testid="confirm-supersede-btn"
          @click="handleConfirm"
        >
          <v-icon icon="mdi-file-replace-outline" start />
          Mark Superseded
        </v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useProjectStore } from '@/stores/projects'
import { parseErrorResponse } from '@/utils/errorMessages'

const props = defineProps({
  show: {
    type: Boolean,
    required: true,
  },
  projectId: {
    type: [String, null],
    default: null,
  },
  projectName: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['close', 'superseded'])

const projectStore = useProjectStore()


const candidates = ref([])
const loadingCandidates = ref(false)
const successorProjectId = ref(null)
const submitting = ref(false)
const error = ref(null)

const successorOptions = computed(() =>
  candidates.value.map((p) => ({
    title: p.taxonomy_alias ? `${p.taxonomy_alias} — ${p.name}` : p.name,
    value: p.id,
  })),
)

async function loadCandidates() {
  loadingCandidates.value = true
  try {
    candidates.value = await projectStore.fetchSuccessorCandidates(props.projectId)
  } catch (err) {
    console.error('[SupersedeProjectModal] Failed to load successor candidates:', err)
    error.value = 'Failed to load candidate projects. Please try again.'
    candidates.value = []
  } finally {
    loadingCandidates.value = false
  }
}

function resetState() {
  candidates.value = []
  successorProjectId.value = null
  error.value = null
  submitting.value = false
}

watch(() => props.show, (open) => {
  if (open && props.projectId) {
    loadCandidates()
  } else {
    resetState()
  }
})

onMounted(() => {
  if (props.show && props.projectId) {
    loadCandidates()
  }
})

const handleClose = () => {
  resetState()
  emit('close')
}

const handleConfirm = async () => {
  if (!successorProjectId.value) return

  submitting.value = true
  error.value = null

  try {
    const result = await projectStore.supersedeProject(props.projectId, successorProjectId.value)
    emit('superseded', result)
    resetState()
  } catch (err) {
    console.error('[SupersedeProjectModal] Failed to supersede project:', err)
    error.value = parseErrorResponse(err).message || 'Failed to mark project superseded'
  } finally {
    submitting.value = false
  }
}
</script>
