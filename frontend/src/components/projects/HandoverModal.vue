<template>
  <v-dialog
    :model-value="show"
    :fullscreen="isMobile"
    :max-width="isMobile ? undefined : '480'"
    persistent
    class="handover-modal"
    role="dialog"
    :aria-labelledby="'handover-modal-title'"
    data-testid="handover-modal"
    @keydown.esc="handleClose"
  >
    <v-card v-draggable data-testid="handover-modal-card" class="smooth-border">
      <div id="handover-modal-title" class="dlg-header dlg-header--primary dlg-header--sticky">
        <v-icon class="dlg-icon" icon="mdi-refresh" />
        <span class="dlg-title">Session Handover</span>
        <v-tooltip location="bottom" max-width="300">
          <template #activator="{ props: tooltipProps }">
            <v-icon
              v-bind="tooltipProps"
              icon="mdi-information-outline"
              size="small"
              class="ml-2 opacity-80"
              aria-label="Handover information"
            />
          </template>
          Refreshes the orchestrator's context by retiring the current session
          and starting a new one.
        </v-tooltip>
        <v-btn icon variant="text" size="small" class="dlg-close" aria-label="Close modal" @click="handleClose">
          <v-icon icon="mdi-close" size="18" />
        </v-btn>
      </div>

      <v-divider />

      <v-card-text class="pa-4">
        <v-checkbox
          v-model="subagentsConfirmed"
          color="warning"
          density="compact"
          hide-details
          class="mb-4"
          data-testid="subagents-checkbox"
        >
          <template #label>
            <span class="text-body-medium" style="color: rgba(255,255,255,0.85)">
              I confirm all subagents have finished their work
            </span>
          </template>
        </v-checkbox>

        <div class="step-row mb-3" data-testid="step-1">
          <v-avatar :color="step1Done ? 'success' : 'grey-darken-1'" size="26" class="mr-3 flex-shrink-0">
            <span class="text-body-small font-weight-bold" style="color: white">1</span>
          </v-avatar>
          <span class="step-label text-body-medium">Copy and paste this prompt to the current terminal window running the orchestrator</span>
          <v-spacer />
          <v-btn
            size="small"
            :variant="step1Done ? 'tonal' : 'elevated'"
            :color="step1Done ? 'success' : 'warning'"
            :disabled="!subagentsConfirmed"
            :prepend-icon="step1Done ? 'mdi-check' : 'mdi-content-copy'"
            data-testid="copy-retirement-btn"
            class="ml-3 flex-shrink-0"
            @click="copyRetirementPrompt"
          >
            {{ step1Done ? 'Copied' : 'Copy' }}
          </v-btn>
        </div>

        <div class="step-row" data-testid="step-2">
          <v-avatar :color="step2Done ? 'success' : 'grey-darken-1'" size="26" class="mr-3 flex-shrink-0">
            <span class="text-body-small font-weight-bold" style="color: white">2</span>
          </v-avatar>
          <span class="step-label text-body-medium">Copy and paste this prompt into a fresh terminal to continue</span>
          <v-spacer />
          <v-btn
            size="small"
            :variant="step2Done ? 'tonal' : 'elevated'"
            :color="step2Done ? 'success' : 'warning'"
            :disabled="!step1Done"
            :prepend-icon="step2Done ? 'mdi-check' : 'mdi-content-copy'"
            data-testid="copy-continuation-btn"
            class="ml-3 flex-shrink-0"
            @click="copyContinuationPrompt"
          >
            {{ step2Done ? 'Copied' : 'Copy' }}
          </v-btn>
        </div>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useDisplay } from 'vuetify'
import { useClipboard } from '@/composables/useClipboard'
import { useToast } from '@/composables/useToast'

const { copy: clipboardCopy } = useClipboard()
const { showToast } = useToast()

const props = defineProps({
  show: {
    type: Boolean,
    required: true,
  },
  retirementPrompt: {
    type: String,
    default: '',
  },
  continuationPrompt: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['close'])

const { mobile } = useDisplay()
const isMobile = computed(() => mobile.value)

const subagentsConfirmed = ref(false)
const step1Done = ref(false)
const step2Done = ref(false)

watch(() => props.show, (val) => {
  if (!val) {
    subagentsConfirmed.value = false
    step1Done.value = false
    step2Done.value = false
  }
})

async function copyRetirementPrompt() {
  const success = await clipboardCopy(props.retirementPrompt)
  if (success) {
    step1Done.value = true
    showToast({ message: 'Retirement prompt copied. Paste so the orchestrator saves state and stands down.', type: 'success' })
  } else {
    showToast({ message: 'Clipboard blocked. Select the prompt and press Ctrl+C to copy manually.', type: 'warning' })
  }
}

async function copyContinuationPrompt() {
  const success = await clipboardCopy(props.continuationPrompt)
  if (success) {
    step2Done.value = true
    showToast({ message: 'Continuation prompt copied. Paste in a fresh terminal to restore full context.', type: 'success' })
  } else {
    showToast({ message: 'Clipboard blocked. Select the prompt and press Ctrl+C to copy manually.', type: 'warning' })
  }
}

function handleClose() {
  emit('close')
}
</script>
