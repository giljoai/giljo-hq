<template>
  <v-dialog
    :model-value="show"
    :fullscreen="isMobile"
    :max-width="isMobile ? undefined : '900'"
    persistent
    class="closeout-modal"
    role="dialog"
    :aria-labelledby="'closeout-modal-title'"
    data-testid="closeout-modal"
    @keydown.esc="handleClose"
  >
    <v-card v-draggable data-testid="closeout-modal" class="smooth-border">
      <div id="closeout-modal-title" class="dlg-header dlg-header--primary dlg-header--sticky">
        <v-icon class="dlg-icon" icon="mdi-memory" />
        <span class="dlg-title">Project 360 Memory: {{ projectName }}</span>
        <v-btn icon variant="text" size="small" class="dlg-close" :aria-label="'Close modal'" @click="handleClose">
          <v-icon icon="mdi-close" size="18" />
        </v-btn>
      </div>

      <v-divider />

      <v-card-text class="pa-4">
        <v-alert
          type="info"
          variant="tonal"
          density="compact"
          class="mb-4"
          icon="mdi-information"
        >
          <template #title>
            <span class="text-body-medium font-weight-medium">360 Memory Entries</span>
          </template>
          <span class="text-body-medium">
            Review the cumulative knowledge and project history stored in this product's 360 Memory.
            These entries provide context for future projects and orchestrator decision-making.
          </span>
        </v-alert>

        <div v-if="loading" class="text-center py-8">
          <v-progress-circular indeterminate color="primary" size="64" />
          <div class="text-body-large mt-4">Loading 360 memory entries...</div>
        </div>

        <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-4">
          {{ error }}
        </v-alert>

        <v-alert
          v-if="!loading && !error && memoryEntries.length === 0"
          type="info"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          No 360 memory entries found for this project yet. Memory entries are created when
          projects are completed or when orchestrators trigger handovers.
        </v-alert>

        <div v-if="!loading && !error && memoryEntries.length > 0">
          <div class="text-body-large font-weight-medium mb-3">
            {{ memoryEntries.length }} Memory
            {{ memoryEntries.length === 1 ? 'Entry' : 'Entries' }} Found
          </div>

          <v-expansion-panels v-model="expandedPanels" multiple variant="accordion">
            <v-expansion-panel
              v-for="(entry, index) in memoryEntries"
              :key="index"
              :value="index"
            >
              <v-expansion-panel-title>
                <div class="d-flex align-center w-100">
                  <v-icon icon="mdi-book-open-page-variant" class="mr-2" size="small" />
                  <span class="font-weight-medium">
                    {{ entry.project_name || 'Entry #' + entry.sequence }} - {{ formatEntryType(entry.entry_type) }}
                  </span>
                  <v-spacer />
                  <span class="text-body-small text-muted-a11y">
                    {{ formatDateTime(entry.timestamp) }}
                  </span>
                </div>
              </v-expansion-panel-title>

              <v-expansion-panel-text>
                <div v-if="entry.summary" class="mb-4">
                  <h4 class="text-title-small font-weight-bold mb-2">Summary</h4>
                  <div class="text-body-medium summary-text">{{ entry.summary }}</div>
                </div>

                <div v-if="entry.key_outcomes && entry.key_outcomes.length > 0" class="mb-4">
                  <h4 class="text-title-small font-weight-bold mb-2">Key Outcomes</h4>
                  <v-list density="compact" class="outcomes-list">
                    <v-list-item
                      v-for="(outcome, outcomeIndex) in entry.key_outcomes"
                      :key="outcomeIndex"
                      class="px-0"
                    >
                      <template #prepend>
                        <v-icon icon="mdi-check-circle" color="success" size="small" class="mr-2" />
                      </template>
                      <v-list-item-title class="text-body-medium">{{ outcome }}</v-list-item-title>
                    </v-list-item>
                  </v-list>
                </div>

                <div v-if="entry.decisions_made && entry.decisions_made.length > 0" class="mb-4">
                  <h4 class="text-title-small font-weight-bold mb-2">Decisions Made</h4>
                  <v-list density="compact" class="decisions-list">
                    <v-list-item
                      v-for="(decision, decisionIndex) in entry.decisions_made"
                      :key="decisionIndex"
                      class="px-0"
                    >
                      <template #prepend>
                        <v-icon icon="mdi-lightbulb" color="warning" size="small" class="mr-2" />
                      </template>
                      <v-list-item-title class="text-body-medium">{{ decision }}</v-list-item-title>
                    </v-list-item>
                  </v-list>
                </div>

                <div v-if="entry.git_commits && entry.git_commits.length > 0" class="mb-4">
                  <h4 class="text-title-small font-weight-bold mb-2">
                    Git Commits ({{ entry.git_commits.length }})
                  </h4>
                  <v-list density="compact" class="git-commits-list" max-height="300" style="overflow-y: auto">
                    <v-list-item
                      v-for="(commit, commitIndex) in entry.git_commits"
                      :key="commitIndex"
                      class="px-2 py-1"
                    >
                      <template #prepend>
                        <v-icon icon="mdi-source-commit" color="info" size="small" class="mr-2" />
                      </template>
                      <v-list-item-title class="text-body-medium">
                        {{ commitTitle(commit) }}
                      </v-list-item-title>
                      <v-list-item-subtitle class="text-body-small">
                        {{ commit.author }} - {{ formatCommitDate(commit.timestamp) }}
                      </v-list-item-subtitle>
                    </v-list-item>
                  </v-list>
                </div>

                <div class="metadata-section mt-4 pt-3" style="border-top: 1px solid rgba(0,0,0,0.12)">
                  <div class="text-body-small text-muted-a11y">
                    <strong>Type:</strong> {{ formatEntryType(entry.entry_type) }}
                    <span v-if="entry.sequence" class="ml-3">|</span>
                    <span v-if="entry.sequence" class="ml-3"><strong>Sequence:</strong> #{{ entry.sequence }}</span>
                    <span v-if="entry.source" class="ml-3">|</span>
                    <span v-if="entry.source" class="ml-3"><strong>Source:</strong> {{ entry.source }}</span>
                  </div>
                </div>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>
        </div>

        <v-alert
          v-if="!loading && !error"
          type="success"
          variant="tonal"
          density="compact"
          class="mt-4"
          icon="mdi-check-circle"
        >
          <template #title>
            <span class="text-body-medium font-weight-medium">Next Steps</span>
          </template>
          <div class="text-body-medium">
            <template v-if="props.projectStatus === 'completed'">
              <strong>Close:</strong> Mark this project reviewed and continue the chain.
            </template>
            <template v-else>
              <strong>Close:</strong> Archive this project and mark it as completed in 360 Memory.
            </template>
          </div>
        </v-alert>
      </v-card-text>

      <v-divider />

      <div class="dlg-footer">
        <template v-if="orchestratorCloseoutBlocked">
          <div class="closeout-blocked-indicator" data-testid="closeout-blocked-indicator">
            <v-icon icon="mdi-clipboard-check-outline" size="18" class="closeout-blocked-icon" />
            <div class="closeout-blocked-text">
              <span class="closeout-blocked-label">Awaiting decision</span>
              <span class="closeout-blocked-note">
                Resolve the orchestrator's request in the dedicated decision dialog before closing out.
              </span>
            </div>
          </div>
          <v-spacer />
          <v-btn
            variant="text"
            :aria-label="'Cancel'"
            @click="handleClose"
          >
            Cancel
          </v-btn>
        </template>
        <template v-else>
          <v-btn
            color="success"
            variant="elevated"
            :loading="closeoutLoading"
            prepend-icon="mdi-check-circle"
            :aria-label="'Close'"
            data-testid="close-out-btn"
            @click="handleCloseOutProject"
          >
            Close
          </v-btn>
          <v-spacer />
          <v-btn
            variant="text"
            :disabled="closeoutLoading"
            :aria-label="'Cancel'"
            @click="handleClose"
          >
            Cancel
          </v-btn>
        </template>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useDisplay } from 'vuetify'
import { useRouter } from 'vue-router'
import { useFormatDate } from '@/composables/useFormatDate'
import { useToast } from '@/composables/useToast'
import { commitTitle } from '@/utils/gitCommitDisplay'
import api from '@/services/api'

const { formatDateTime } = useFormatDate()
const router = useRouter()
const { showToast } = useToast()

const props = defineProps({
  show: {
    type: Boolean,
    required: true,
  },
  projectId: {
    type: String,
    required: true,
  },
  projectName: {
    type: String,
    required: true,
  },
  productId: {
    type: String,
    required: true,
  },
  projectStatus: {
    type: String,
    default: 'active',
  },
  orchestratorCloseoutBlocked: {
    type: Boolean,
    default: false,
  },
  orchestratorJobId: {
    type: String,
    default: null,
  },
  suppressNavigation: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['close', 'closeout'])

const { mobile } = useDisplay()
const isMobile = computed(() => mobile.value)

const loading = ref(false)
const error = ref(null)
const memoryEntries = ref([])
const expandedPanels = ref([])
const closeoutLoading = ref(false)

const loadMemoryEntries = async () => {
  loading.value = true
  error.value = null
  memoryEntries.value = []

  try {
    const response = await api.products.getMemoryEntries(
      props.productId,
      {
        project_id: props.projectId,
        limit: 10
      }
    )

    memoryEntries.value = response.data.entries || []
  } catch (err) {
    console.error('[CloseoutModal] Failed to load 360 memory:', err)
    error.value =
      err.response?.data?.message || err.message || 'Failed to load 360 memory entries'
  } finally {
    loading.value = false
  }
}

const handleCloseOutProject = async () => {
  closeoutLoading.value = true
  error.value = null

  try {
    let responseData = null
    if (props.projectStatus !== 'completed') {
      const response = await api.projects.archive(props.projectId)
      responseData = response.data
    }

    emit('closeout', responseData)
    emit('close')

    showToast({ message: 'Project closed out successfully', type: 'success' })
    if (!props.suppressNavigation) {
      router.push('/projects')
    }
  } catch (err) {
    console.error('[CloseoutModal] Failed to close out project:', err)
    error.value = err.response?.data?.message || err.message || 'Failed to close out project'
  } finally {
    closeoutLoading.value = false
  }
}

const handleClose = () => {
  if (!closeoutLoading.value) {
    emit('close')
  }
}


const formatCommitDate = (timestamp) => {
  if (!timestamp) return ''
  try {
    const date = new Date(timestamp)
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  } catch {
    return timestamp
  }
}

const formatEntryType = (type) => {
  if (!type) return 'Unknown'
  return type
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

const resetState = () => {
  expandedPanels.value = []
  error.value = null
  memoryEntries.value = []
  closeoutLoading.value = false
}

watch(
  () => props.show,
  (newValue) => {
    if (newValue) {
      loadMemoryEntries()
      expandedPanels.value = [0]
    } else {
      resetState()
    }
  },
  { immediate: true },
)
</script>

<style lang="scss" scoped>
@use '../../styles/design-tokens' as *;
.summary-text {
  white-space: pre-wrap;
  word-wrap: break-word;
  line-height: 1.6;
}

.outcomes-list,
.decisions-list {
  background-color: transparent;
}

.git-commits-list {
  background-color: rgba(0, 0, 0, 0.02);
  border-radius: $border-radius-sharp;
  padding: 8px 0;
}

.metadata-section {
  background-color: rgba(0, 0, 0, 0.02);
  padding: 12px;
  border-radius: $border-radius-sharp;
}

/* Focus trap for accessibility */
.v-dialog {
  outline: none;
}

/* Ensure proper spacing */
.v-list-item {
  min-height: 40px;
}

/* Mobile optimizations */
@media (max-width: 600px) {
  .git-commits-list {
    max-height: 200px;
  }
}

/* Expansion panel styling */
:deep(.v-expansion-panel-title) {
  font-size: 0.95rem;
  padding: 12px 16px;
}

:deep(.v-expansion-panel-text__wrapper) {
  padding: 16px 20px;
}

/* HITL Closeout: Amber blocked indicator in footer */
.closeout-blocked-indicator {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 12px;
  border-radius: $border-radius-md;
  background: rgba($color-status-warning, 0.10);
  max-width: 500px;
}

.closeout-blocked-icon {
  color: $color-status-warning;
  flex-shrink: 0;
  margin-top: 2px;
}

.closeout-blocked-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.closeout-blocked-label {
  font-weight: 600;
  font-size: 0.82rem;
  color: $color-status-warning;
}

.closeout-blocked-note {
  font-size: 0.75rem;
  color: var(--text-muted);
  line-height: 1.4;
}
</style>
