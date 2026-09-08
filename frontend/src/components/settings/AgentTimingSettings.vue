<!--
  AgentTimingSettings.vue — FE-9553

  The agent silence threshold and check-in cadence, RELOCATED out of the
  Notifications tab.

  They were never notification settings. They tune how agents behave — when one
  counts as silent, how often a waiting one looks for work — and they sat under
  Notifications only because that is where the first one happened to be added.
  The record's instruction is that each tab should mean one thing, so they move
  to Tools -> Agents, into the Agent Behaviour Settings group FE-9555 created
  for exactly this class of control ("settings that modify how agents operate").

  Extracted as a component rather than moved as markup for two reasons: it
  removes ~40 lines from ToolsView.vue, which sits at the 800-line guardrail
  with no headroom, and the Agents tab is not eager-rendered, so owning its own
  load keeps the values correct whether or not that tab has ever been opened.

  SAVE-ON-CHANGE, unlike the Notifications tab's batched Save button. Every peer
  in the Agent Behaviour group (the execution-mode default, both orchestration
  toggles) commits on change, and leaving these two behind a Save button that
  lives on a different tab is how the relocation would have produced two
  controls with no way to commit them.
-->
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

    <!-- FE-9296b: the account-level check-in cadence that replaced the
         per-project auto check-in slider. -->
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
  // Guarded individually: an unguarded await here used to abort the rest of
  // ToolsView's onMounted when either read failed, taking unrelated loads down
  // with it. Owning the load locally is what lets each one fail alone.
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

/** Only commit a value the rules accept — a rejected keystroke is not a save. */
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
