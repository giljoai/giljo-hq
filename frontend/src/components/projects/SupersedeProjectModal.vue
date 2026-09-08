<template>
  <v-dialog
    :model-value="show"
    :fullscreen="isMobile"
    :max-width="isMobile ? undefined : '520'"
    persistent
    class="supersede-project-modal"
    role="dialog"
    aria-labelledby="supersede-project-title"
    data-testid="supersede-project-modal"
    @keydown.esc="handleClose"
  >
    <v-card v-draggable class="smooth-border">
      <!-- Modal header -->
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

        <!-- Error state -->
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

      <!-- Modal actions -->
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
import { useDisplay } from 'vuetify'
import { useProjectStore } from '@/stores/projects'

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

// Vuetify display breakpoints
const { mobile } = useDisplay()
const isMobile = computed(() => mobile.value)

// Reactive state
const candidates = ref([])
const loadingCandidates = ref(false)
const successorProjectId = ref(null)
const submitting = ref(false)
const error = ref(null)

// FE-9508: lead with the taxonomy alias, the convention every other project
// surface uses (e.g. ProjectsTable's serial badge) — plain names left the
// operator unable to tell picker options apart (four candidates, none
// identifiable by serial). Falls back to the bare name when a project has no
// alias yet (e.g. a staged-but-unopened project).
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

// The parent renders this dialog under v-if, so it mounts already-open — load
// candidates on mount too (the show watcher only fires on a later transition).
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
    error.value = err.response?.data?.detail || err.response?.data?.message || 'Failed to mark project superseded'
  } finally {
    submitting.value = false
  }
}
</script>
