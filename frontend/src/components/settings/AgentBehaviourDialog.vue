<template>
  <v-dialog
    :model-value="modelValue"
    max-width="640px"
    scrollable
    retain-focus
    @update:model-value="close"
  >
    <v-card v-draggable class="smooth-border abd-card" data-test="agent-behaviour-dialog">
      <div class="dlg-header">
        <v-icon class="dlg-icon">mdi-cog-outline</v-icon>
        <span class="dlg-title">Agent behaviour</span>
        <v-tooltip location="bottom" max-width="360">
          <template #activator="{ props: tipProps }">
            <v-icon v-bind="tipProps" size="small" class="abd-help">mdi-help-circle-outline</v-icon>
          </template>
          <span
            >Settings that modify how agents operate in the application. They belong to your
            account, not to a product, so every product runs under the same five answers. Each one
            saves the moment you change it.</span
          >
        </v-tooltip>
        <v-btn icon variant="text" class="dlg-close" aria-label="Close" @click="close(false)">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </div>

      <v-card-text>
        <p class="abd-subtitle">How agents behave for this account. Applies to every product.</p>
        <div class="setting-rows">
          <ExecutionModeDefaultSelect />
          <AgentTimingSettings />
          <OrchestrationToggles />
        </div>
      </v-card-text>

      <div class="dlg-footer abd-footer">
        <span class="abd-footer-note">Changes save as you make them.</span>
        <v-spacer />
        <v-btn variant="text" data-test="agent-behaviour-close" @click="close(false)">Close</v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import api from '@/services/api'
import { useSettingsStore } from '@/stores/settings'
import { EXECUTION_MODE_DEFAULT_ASK } from '@/utils/executionModeDefault'
import ExecutionModeDefaultSelect from '@/components/settings/ExecutionModeDefaultSelect.vue'
import AgentTimingSettings from '@/components/settings/AgentTimingSettings.vue'
import OrchestrationToggles from '@/components/templates/OrchestrationToggles.vue'

const DEFAULT_SILENCE_MINUTES = 10
const DEFAULT_CHECKIN_MINUTES = 10

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'update:changedCount'])

const settingsStore = useSettingsStore()

const executionMode = ref(EXECUTION_MODE_DEFAULT_ASK)
const silenceMinutes = ref(DEFAULT_SILENCE_MINUTES)
const cadenceMinutes = ref(DEFAULT_CHECKIN_MINUTES)
const closeoutHitl = ref(true)
const allowHeadless = ref(true)

const changedCount = computed(
  () =>
    [
      executionMode.value !== EXECUTION_MODE_DEFAULT_ASK,
      silenceMinutes.value !== DEFAULT_SILENCE_MINUTES,
      cadenceMinutes.value !== DEFAULT_CHECKIN_MINUTES,
      closeoutHitl.value !== true,
      allowHeadless.value !== true,
    ].filter(Boolean).length,
)

async function loadCounts() {
  try {
    executionMode.value = await settingsStore.loadExecutionModeDefault()
  } catch {
    executionMode.value = EXECUTION_MODE_DEFAULT_ASK
  }
  try {
    silenceMinutes.value = await settingsStore.loadAgentSilenceThreshold()
  } catch {
    silenceMinutes.value = DEFAULT_SILENCE_MINUTES
  }
  try {
    cadenceMinutes.value = await settingsStore.loadAgentCheckinCadence()
  } catch {
    cadenceMinutes.value = DEFAULT_CHECKIN_MINUTES
  }
  try {
    const general = (await api.settings.getGeneral())?.data?.settings || {}
    closeoutHitl.value = general.closeout_mode ? general.closeout_mode === 'hitl' : true
  } catch {
    closeoutHitl.value = true
  }
  try {
    const res = await api.settings.getHeadlessLaunch()
    allowHeadless.value = !!res?.data?.allow_headless_launch
  } catch {
    allowHeadless.value = true
  }
  emit('update:changedCount', changedCount.value)
}

function close(value) {
  emit('update:modelValue', !!value)
}

onMounted(loadCounts)

watch(
  () => props.modelValue,
  (open, wasOpen) => {
    if (wasOpen && !open) loadCounts()
  },
)
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.abd-card {
  background: $elevation-raised;
}

.abd-help {
  color: var(--text-muted);
  cursor: help;
  margin-left: 8px;
}

.abd-subtitle {
  color: var(--text-muted);
  font-size: 0.8125rem;
  margin-bottom: 4px;
}

.abd-footer {
  justify-content: space-between;
}

.abd-footer-note {
  color: var(--text-muted);
  font-size: 0.75rem;
}
</style>
