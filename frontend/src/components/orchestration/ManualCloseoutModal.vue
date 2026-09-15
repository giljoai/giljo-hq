<template>
  <v-dialog
    :model-value="show"
    :fullscreen="isMobile"
    :max-width="isMobile ? undefined : '640'"
    persistent
    class="manual-closeout-modal"
    role="dialog"
    aria-labelledby="manual-closeout-title"
    data-testid="manual-closeout-modal"
    @keydown.esc="handleClose"
  >
    <v-card v-draggable class="smooth-border">
      <div id="manual-closeout-title" class="dlg-header dlg-header--primary dlg-header--sticky">
        <v-icon class="dlg-icon" icon="mdi-check-circle-outline" />
        <span class="dlg-title">Complete Project: {{ projectName }}</span>
        <v-btn icon variant="text" size="small" class="dlg-close" aria-label="Close modal" @click="handleClose">
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
            <span class="text-body-medium font-weight-medium">Why detailed closeout matters</span>
          </template>
          <span class="text-body-medium">
            This closeout data becomes part of your product's <strong>360 Memory</strong> and provides
            context for future projects. The more detailed your summary, the better future orchestrators
            can learn from this work.
          </span>
        </v-alert>

        <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-4" closable @click:close="error = null">
          {{ error }}
        </v-alert>

        <div class="mb-4">
          <v-textarea
            v-model="summary"
            data-testid="summary-field"
            label="Project Summary (360 Memory)"
            placeholder="Describe what was accomplished in this project, key outcomes, decisions made, and any learnings for future projects..."
            variant="outlined"
            rows="6"
            counter="1500"
            maxlength="1500"
            :rules="[v => v.length >= 50 || 'Please provide at least 50 characters']"
            hint="This summary will be stored in 360 Memory for future project context"
            persistent-hint
          />
        </div>

        <div class="commit-section mb-4">
          <div class="commit-section__header mb-2">
            <span class="text-body-medium font-weight-medium" style="color: var(--text-secondary)">
              Git Commits
            </span>
            <span class="text-body-medium ml-1" style="color: var(--text-muted)">
              (optional)
            </span>
          </div>

          <div
            v-for="(row, idx) in commitRows"
            :key="row.id"
            class="commit-row smooth-border mb-2 pa-3"
            :data-testid="`commit-row-${idx}`"
          >
            <div class="commit-row__required d-flex gap-2 mb-2">
              <v-text-field
                v-model="row.sha"
                :data-testid="`commit-sha-${idx}`"
                label="SHA"
                placeholder="e.g. abc1234"
                variant="outlined"
                density="compact"
                class="commit-row__sha"
                aria-label="Commit SHA"
                hide-details
              />
              <v-text-field
                v-model="row.message"
                :data-testid="`commit-msg-${idx}`"
                label="Commit message"
                placeholder="e.g. feat: add commit capture UI"
                variant="outlined"
                density="compact"
                class="commit-row__message"
                aria-label="Commit message"
                hide-details
              />
              <v-btn
                icon
                variant="text"
                size="small"
                :data-testid="`remove-commit-${idx}`"
                :aria-label="`Remove commit row ${idx + 1}`"
                @click="removeCommitRow(idx)"
              >
                <v-icon icon="mdi-close" size="16" />
              </v-btn>
            </div>

            <div class="commit-row__optional d-flex gap-2">
              <v-text-field
                v-model="row.author"
                :data-testid="`commit-author-${idx}`"
                label="Author"
                placeholder="e.g. GiljoAI"
                variant="outlined"
                density="compact"
                class="commit-row__author"
                aria-label="Commit author"
                hide-details
              />
              <v-text-field
                v-model="row.date"
                :data-testid="`commit-date-${idx}`"
                label="Date (ISO-8601)"
                placeholder="e.g. 2026-06-05T10:00:00Z"
                variant="outlined"
                density="compact"
                class="commit-row__date"
                aria-label="Commit date"
                hide-details
              />
            </div>
          </div>

          <v-btn
            variant="text"
            size="small"
            class="commit-section__add-btn"
            data-testid="add-commit-btn"
            aria-label="Add commit row"
            @click="addCommitRow"
          >
            <v-icon icon="mdi-plus" start size="16" />
            Add commit
          </v-btn>
        </div>

        <div class="mt-4">
          <v-checkbox
            v-model="confirmed"
            color="primary"
            hide-details
            data-testid="manual-confirm-checkbox"
          >
            <template #label>
              <span class="text-body-medium">I am manually completing this project</span>
            </template>
          </v-checkbox>
        </div>
      </v-card-text>

      <v-divider />

      <div class="dlg-footer">
        <v-btn variant="text" @click="handleClose">
          Cancel
        </v-btn>
        <v-spacer />
        <v-btn
          color="success"
          variant="elevated"
          :disabled="!canSubmit"
          :loading="completing"
          data-testid="manual-complete-btn"
          @click="handleComplete"
        >
          <v-icon icon="mdi-check-circle" start />
          Complete Project
        </v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useDisplay } from 'vuetify'
import api from '@/services/api'

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

const emit = defineEmits(['close', 'completed'])

const { mobile } = useDisplay()
const isMobile = computed(() => mobile.value)

const summary = ref('')
const confirmed = ref(false)
const completing = ref(false)
const error = ref(null)

let _rowCounter = 0
const commitRows = ref([])

const canSubmit = computed(() => {
  return confirmed.value && summary.value.length >= 50
})

const addCommitRow = () => {
  commitRows.value.push({
    id: ++_rowCounter,
    sha: '',
    message: '',
    author: '',
    date: '',
  })
}

const removeCommitRow = (idx) => {
  commitRows.value.splice(idx, 1)
}

const buildGitCommits = () => {
  const commits = []
  for (const row of commitRows.value) {
    const sha = row.sha.trim()
    const message = row.message.trim()
    if (!sha || !message) continue

    const entry = { sha, message }
    const author = row.author.trim()
    const date = row.date.trim()
    if (author) entry.author = author
    if (date) entry.date = date
    commits.push(entry)
  }
  return commits
}

const handleClose = () => {
  resetState()
  emit('close')
}

const handleComplete = async () => {
  if (!canSubmit.value) return

  completing.value = true
  error.value = null

  try {
    const commits = buildGitCommits()

    const payload = {
      summary: summary.value,
      key_outcomes: ['Manually completed by user'],
      decisions_made: [],
      confirm_closeout: true,
    }

    if (commits.length > 0) {
      payload.git_commits = commits
    }

    const response = await api.projects.completeWithData(props.projectId, payload)

    emit('completed', response.data || { project_id: props.projectId })
    resetState()
  } catch (err) {
    console.error('[ManualCloseoutModal] Failed to complete project:', err)
    error.value = err.response?.data?.detail || err.response?.data?.message || 'Failed to complete project'
  } finally {
    completing.value = false
  }
}

const resetState = () => {
  summary.value = ''
  confirmed.value = false
  error.value = null
  commitRows.value = []
  _rowCounter = 0
}
</script>

<style scoped>
.commit-section__header {
  display: flex;
  align-items: center;
}

.commit-row {
  border-radius: 8px;
  background-color: rgba(var(--v-theme-surface-variant, 0, 0, 0), 0.04);
}

.commit-row__required {
  align-items: flex-start;
}

.commit-row__sha {
  flex: 0 0 140px;
  min-width: 100px;
}

.commit-row__message {
  flex: 1 1 auto;
}

.commit-row__optional {
  align-items: flex-start;
}

.commit-row__author {
  flex: 0 0 160px;
  min-width: 120px;
}

.commit-row__date {
  flex: 1 1 auto;
}

.commit-section__add-btn {
  color: var(--text-muted);
}

.gap-2 {
  gap: 8px;
}
</style>
