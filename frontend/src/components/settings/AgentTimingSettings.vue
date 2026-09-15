<template>
  <div data-test="agent-timing-settings">
    <div class="ats-row">
      <v-text-field
        v-model.number="silenceMinutes"
        type="number"
        label="Agent Silence Threshold (minutes)"
        hint="Time without communication before an agent is marked as silent. Raise this for slow-inference models so they aren't falsely flagged."
        persistent-hint
        variant="outlined"
        density="compact"
        :min="1"
        :max="1440"
        :rules="RULES"
        :disabled="saving"
        data-test="silence-threshold-input"
        @update:model-value="saveSilence"
      />
    </div>

    <div class="ats-row">
      <v-text-field
        v-model.number="cadenceMinutes"
        type="number"
        label="Agent Check-in Cadence (minutes)"
        hint="How often waiting agents check in for new work. Agents on a harness with live wake signals use this as a heartbeat; all others sleep this long between checks."
        persistent-hint
        variant="outlined"
        density="compact"
        :min="1"
        :max="1440"
        :rules="RULES"
        :disabled="saving"
        data-test="checkin-cadence-input"
        @update:model-value="saveCadence"
      />
    </div>

    <p v-if="error" class="text-body-small mt-2" data-test="agent-timing-error">
      <v-icon size="16" color="error" class="mr-1">mdi-alert-circle</v-icon>
      Could not save that. The value on the server is unchanged.
    </p>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'

import { useSettingsStore } from '@/stores/settings'

const RULES = [
  (v) => (v >= 1 && v <= 1440) || 'Must be between 1 and 1440 minutes',
  (v) => Number.isInteger(v) || 'Must be a whole number',
]

const settings = useSettingsStore()
const silenceMinutes = ref(10)
const cadenceMinutes = ref(10)
const saving = ref(false)
const error = ref(false)

onMounted(async () => {
  try {
    silenceMinutes.value = await settings.loadAgentSilenceThreshold()
  } catch {
    // Leave the default; the field stays usable and a save still works.
  }
  try {
    cadenceMinutes.value = await settings.loadAgentCheckinCadence()
  } catch {
    // As above.
  }
})

function isValid(value) {
  return Number.isInteger(value) && value >= 1 && value <= 1440
}

async function commit(fn, value) {
  if (!isValid(value)) return
  saving.value = true
  error.value = false
  try {
    await fn(value)
  } catch {
    error.value = true
  } finally {
    saving.value = false
  }
}

function saveSilence() {
  return commit(settings.updateAgentSilenceThreshold, silenceMinutes.value)
}

function saveCadence() {
  return commit(settings.updateAgentCheckinCadence, cadenceMinutes.value)
}
</script>

<style scoped lang="scss">
.ats-row {
  max-width: 400px;
  margin-bottom: 12px;
}
</style>
