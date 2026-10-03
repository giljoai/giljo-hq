<template>
  <div>
    <div class="tab-header mb-4">
      <h2 class="text-title-large">Handover template</h2>
      <p class="text-body-medium text-muted-a11y mt-1">
        Agents start every handover they write from this, and the three required sections are
        always included. The handover form in Tasks has its own plain fields and does not use it.
      </p>
    </div>
    <v-card variant="flat" class="smooth-border handover-card">
      <v-card-text>
        <v-alert type="info" variant="tonal" class="mb-4">
          Add whatever sections you want. The three headings the server requires are appended if
          you leave one out, so this template can never ask for a handover the server would
          refuse.
        </v-alert>

        <v-alert
          v-if="templateError"
          type="error"
          variant="tonal"
          class="mb-4"
          closable
          data-test="handover-error-alert"
          @click:close="templateError = null"
        >
          {{ templateError }}
        </v-alert>

        <v-alert
          v-if="templateFeedback"
          type="success"
          variant="tonal"
          class="mb-4"
          closable
          data-test="handover-success-alert"
          @click:close="templateFeedback = null"
        >
          {{ templateFeedback }}
        </v-alert>

        <v-textarea
          v-model="template"
          :loading="loading"
          :readonly="loading"
          label="Handover template"
          class="mono-textarea"
          rows="18"
          max-rows="30"
          auto-grow
          variant="outlined"
          spellcheck="false"
          data-test="handover-template-textarea"
        />

        <div class="text-body-small text-muted-a11y mt-2" data-test="handover-template-status">
          {{ statusText }}
        </div>
      </v-card-text>

      <v-card-actions>
        <v-btn
          variant="text"
          color="warning"
          :disabled="loading || saving || isDefault"
          data-test="handover-reset-btn"
          @click="resetTemplate"
        >
          <v-icon start>mdi-backup-restore</v-icon>
          Reset to default
        </v-btn>
        <v-spacer />
        <v-btn
          color="primary"
          :loading="saving"
          :disabled="!dirty || saving"
          data-test="handover-save-btn"
          @click="saveTemplate"
        >
          <v-icon start>mdi-content-save</v-icon>
          Save
        </v-btn>
      </v-card-actions>
    </v-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import api from '@/services/api'
import { parseErrorResponse } from '@/utils/errorMessages'

const template = ref('')
const baseline = ref('')
const isDefault = ref(true)
const loading = ref(false)
const saving = ref(false)
const dirty = ref(false)
const templateError = ref(null)
const templateFeedback = ref(null)

const statusText = computed(() =>
  isDefault.value
    ? 'Using the shipped default template.'
    : 'Using your own template for this account.',
)

function applyResponse(data) {
  template.value = data?.handover_template || ''
  baseline.value = template.value
  isDefault.value = Boolean(data?.is_default)
  dirty.value = false
}

async function loadTemplate() {
  loading.value = true
  templateError.value = null
  templateFeedback.value = null
  try {
    const response = await api.settings.getHandoverTemplate()
    applyResponse(response?.data)
  } catch (error) {
    templateError.value = parseErrorResponse(error).message || 'Failed to load the handover template.'
  } finally {
    loading.value = false
  }
}

async function saveTemplate() {
  if (!dirty.value) return
  saving.value = true
  templateError.value = null
  templateFeedback.value = null
  try {
    const response = await api.settings.updateHandoverTemplate(template.value)
    applyResponse(response?.data)
    templateFeedback.value = 'Handover template saved.'
  } catch (error) {
    templateError.value = parseErrorResponse(error).message || 'Failed to save the handover template.'
  } finally {
    saving.value = false
  }
}

async function resetTemplate() {
  saving.value = true
  templateError.value = null
  templateFeedback.value = null
  try {
    const response = await api.settings.resetHandoverTemplate()
    applyResponse(response?.data)
    templateFeedback.value = 'Reverted to the default handover template.'
  } catch (error) {
    templateError.value = parseErrorResponse(error).message || 'Failed to reset the handover template.'
  } finally {
    saving.value = false
  }
}

watch(template, (value) => {
  dirty.value = value !== baseline.value
})

onMounted(loadTemplate)
</script>

<style lang="scss" scoped>
@use '../../../styles/settings-tab-card' as settingsCard;
.handover-card {
  @include settingsCard.settings-tab-card-surface;
}

.mono-textarea :deep(textarea) {
  font-family: 'Roboto Mono', monospace;
}
</style>
