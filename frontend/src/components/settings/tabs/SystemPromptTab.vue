<template>
  <div>
    <div class="tab-header mb-4">
      <h2 class="text-title-large">System Orchestrator Prompt</h2>
      <p class="text-body-medium text-muted-a11y mt-1">Core instructions for the Giljo Orchestrator (admin override only)</p>
    </div>
    <v-card variant="flat" class="smooth-border prompt-card">
    <v-card-text>
      <v-alert type="info" variant="tonal" class="mb-6">
        <p class="mb-3">
          {{ productName }} ships pre-packaged prompts so you don't have to write lengthy instructions for
          every request. They reduce errors, ensure consistency, and give your agents precise operating
          instructions out of the box.
        </p>
        <p class="mb-3">
          Behind the scenes, the MCP server applies dynamic protocol layers to these prompts based on
          your product definition, enabled integrations, and context depth settings. These protocol
          layers are not editable; they've been calibrated to ensure agents interact correctly with the
          server and with each other.
        </p>
        <p class="mb-3">
          The general orchestrator prompt below <strong>is</strong> editable, though we don't recommend
          modifying it unless you have a specific reason. We believe in putting control in your hands,
          so we expose it here for transparency. The protocol layers remain hidden and will continue to
          adapt based on the context you've already defined.
        </p>
        <p class="mb-3">
          <strong>The philosophy is simple: define your product once, and every agent works from that
          shared understanding, no tedious per-request prompt tuning required.</strong>
        </p>
        <p class="mb-0">
          <strong>Changes to this prompt apply to this tenant only.</strong>
        </p>
      </v-alert>

      <v-alert type="warning" variant="tonal" class="mb-4">
        Editing this prompt can break orchestrator coordination. Only proceed if you understand the
        full impact. Always keep a backup and verify flows after saving.
      </v-alert>

      <v-alert
        v-if="promptError"
        type="error"
        variant="tonal"
        class="mb-4"
        closable
        data-test="error-alert"
        @click:close="promptError = null"
      >
        {{ promptError }}
      </v-alert>

      <v-alert
        v-if="promptFeedback"
        type="success"
        variant="tonal"
        class="mb-4"
        closable
        data-test="success-alert"
        @click:close="promptFeedback = null"
      >
        {{ promptFeedback }}
      </v-alert>

      <v-textarea
        v-model="prompt"
        :loading="loading"
        :readonly="loading"
        label="Orchestrator Prompt"
        class="mono-textarea"
        rows="18"
        max-rows="30"
        auto-grow
        variant="outlined"
        spellcheck="false"
      />

      <div class="text-body-small mt-2">
        {{ promptStatus }}
      </div>
    </v-card-text>

    <v-card-actions>
      <v-btn
        variant="text"
        color="warning"
        :disabled="loading || saving"
        data-test="restore-prompt-btn"
        @click="restorePrompt"
      >
        <v-icon start>mdi-backup-restore</v-icon>
        Restore Default
      </v-btn>
      <v-spacer />
      <v-btn
        color="primary"
        :loading="saving"
        :disabled="!promptDirty || saving"
        data-test="save-prompt-btn"
        @click="savePrompt"
      >
        <v-icon start>mdi-content-save</v-icon>
        Save Override
      </v-btn>
    </v-card-actions>
  </v-card>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import api from '@/services/api'
import { PRODUCT_NAME } from '@/branding'

// State
const productName = PRODUCT_NAME
const prompt = ref('')
const promptBaseline = ref('')
const loading = ref(false)
const saving = ref(false)
const promptDirty = ref(false)
const promptMetadata = ref({
  isOverride: false,
  updatedAt: null,
  updatedBy: null,
})
const promptError = ref(null)
const promptFeedback = ref(null)

// Computed
const promptStatus = computed(() => {
  if (promptMetadata.value.isOverride && promptMetadata.value.updatedAt) {
    const timestamp = promptMetadata.value.updatedAt.toLocaleString()
    const actor = promptMetadata.value.updatedBy || 'admin'
    return `Override saved ${timestamp} by ${actor}`
  }
  return 'Using the default orchestrator prompt (you have not saved an override for your tenant)'
})

// Methods
async function loadPrompt() {
  loading.value = true
  promptError.value = null
  promptFeedback.value = null

  try {
    const response = await api.system.getOrchestratorPrompt()
    const data = response.data || {}
    prompt.value = data.content || ''
    promptBaseline.value = prompt.value
    promptMetadata.value = {
      isOverride: Boolean(data.is_override),
      updatedAt: data.updated_at ? new Date(data.updated_at) : null,
      updatedBy: data.updated_by || null,
    }
    promptDirty.value = false
  } catch (error) {
    console.error('[SYSTEM] Failed to load orchestrator prompt:', error)
    promptError.value = error.response?.data?.detail || 'Failed to load orchestrator prompt.'
  } finally {
    loading.value = false
  }
}

async function savePrompt() {
  if (!promptDirty.value) return
  saving.value = true
  promptError.value = null
  promptFeedback.value = null

  try {
    const response = await api.system.updateOrchestratorPrompt(prompt.value)
    const data = response.data || {}
    prompt.value = data.content || prompt.value
    promptBaseline.value = prompt.value
    promptMetadata.value = {
      isOverride: Boolean(data.is_override),
      updatedAt: data.updated_at ? new Date(data.updated_at) : null,
      updatedBy: data.updated_by || null,
    }
    promptDirty.value = false
    promptFeedback.value = 'Override saved successfully.'
  } catch (error) {
    console.error('[SYSTEM] Failed to save orchestrator prompt:', error)
    promptError.value = error.response?.data?.detail || 'Failed to save orchestrator prompt.'
  } finally {
    saving.value = false
  }
}

async function restorePrompt() {
  saving.value = true
  promptError.value = null
  promptFeedback.value = null

  try {
    const response = await api.system.resetOrchestratorPrompt()
    const data = response.data || {}
    prompt.value = data.content || ''
    promptBaseline.value = prompt.value
    promptMetadata.value = {
      isOverride: Boolean(data.is_override),
      updatedAt: data.updated_at ? new Date(data.updated_at) : null,
      updatedBy: data.updated_by || null,
    }
    promptDirty.value = false
    promptFeedback.value = 'Reverted to default orchestrator prompt.'
  } catch (error) {
    console.error('[SYSTEM] Failed to reset orchestrator prompt:', error)
    promptError.value = error.response?.data?.detail || 'Failed to restore default prompt.'
  } finally {
    saving.value = false
  }
}

// Watch for changes
watch(prompt, (value) => {
  promptDirty.value = value !== promptBaseline.value
})

// Lifecycle
onMounted(() => {
  loadPrompt()
})
</script>

<style lang="scss" scoped>
@use '../../../styles/settings-tab-card' as settingsCard;
.prompt-card {
  @include settingsCard.settings-tab-card-surface;
}

.mono-textarea :deep(textarea) {
  font-family: 'Roboto Mono', monospace;
}
</style>
