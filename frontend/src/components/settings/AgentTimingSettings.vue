<template>
  <div data-test="agent-timing-settings" class="setting-rows">
    <div class="setting-row">
      <div class="setting-row-text">
        <div class="setting-row-name">
          Silence threshold
          <v-tooltip location="bottom" max-width="360">
            <template #activator="{ props: tipProps }">
              <v-icon v-bind="tipProps" size="15" class="setting-row-info"
                >mdi-information-outline</v-icon
              >
            </template>
            Time without communication before an agent is marked as silent. Raise this for
            slow-inference models so they aren't falsely flagged.
          </v-tooltip>
        </div>
        <div class="setting-row-help">Marked silent after this long with no word.</div>
      </div>
      <div class="setting-row-control">
        <v-text-field
          v-model.number="silenceMinutes"
          type="number"
          aria-label="Agent silence threshold in minutes"
          variant="solo"
          flat
          density="compact"
          hide-details="auto"
          :min="1"
          :max="1440"
          :rules="RULES"
          :disabled="saving"
          class="ats-number"
          data-test="silence-threshold-input"
          @update:model-value="saveSilence"
        />
        <span class="setting-row-unit">min</span>
      </div>
    </div>

    <div class="setting-row">
      <div class="setting-row-text">
        <div class="setting-row-name">
          Check-in cadence
          <v-tooltip location="bottom" max-width="360">
            <template #activator="{ props: tipProps }">
              <v-icon v-bind="tipProps" size="15" class="setting-row-info"
                >mdi-information-outline</v-icon
              >
            </template>
            How often waiting agents check in for new work. Agents on a harness with live wake
            signals use this as a heartbeat; all others sleep this long between checks.
          </v-tooltip>
        </div>
        <div class="setting-row-help">How often a waiting agent looks for work.</div>
      </div>
      <div class="setting-row-control">
        <v-text-field
          v-model.number="cadenceMinutes"
          type="number"
          aria-label="Agent check-in cadence in minutes"
          variant="solo"
          flat
          density="compact"
          hide-details="auto"
          :min="1"
          :max="1440"
          :rules="RULES"
          :disabled="saving"
          class="ats-number"
          data-test="checkin-cadence-input"
          @update:model-value="saveCadence"
        />
        <span class="setting-row-unit">min</span>
      </div>
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
@use '../../styles/design-tokens' as *;

/* Matches the row controls beside it: the same inset hairline the Role / Status
   boxes and the execution-mode select carry, at the narrow width a 1-1440
   number needs. */
.ats-number {
  flex: 0 0 84px;
}

.ats-number :deep(.v-field) {
  box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255, 255, 255, 0.1));
  border-radius: $border-radius-default;
}

.ats-number :deep(input) {
  text-align: center;
}
</style>
