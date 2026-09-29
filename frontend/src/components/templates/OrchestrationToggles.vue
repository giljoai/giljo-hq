<template>
  <div class="setting-rows">
    <div class="setting-row">
      <div class="setting-row-text">
        <div class="setting-row-name">
          Require approval before closeout
          <v-tooltip location="bottom" max-width="340">
            <template #activator="{ props }">
              <v-icon v-bind="props" size="15" class="setting-row-info">mdi-information-outline</v-icon>
            </template>
            When enabled, the orchestrator pauses for your review before closing a project — but only if there are deferred findings to review. Clean closeouts proceed automatically.
          </v-tooltip>
        </div>
        <div class="setting-row-help">A project waits for your OK before it closes.</div>
      </div>
      <div class="setting-row-control">
        <v-switch
          v-model="closeoutModeHitl"
          color="primary"
          density="compact"
          hide-details
          aria-label="Require user approval before project closeout"
          data-testid="closeout-mode-toggle"
          @update:model-value="toggleCloseoutMode"
        />
      </div>
    </div>

    <div class="setting-row">
      <div class="setting-row-text">
        <div class="setting-row-name">
          Allow headless CLI self-advance
          <v-tooltip location="bottom" max-width="360">
            <template #activator="{ props }">
              <v-icon v-bind="props" size="15" class="setting-row-info">mdi-information-outline</v-icon>
            </template>
            This governs in-application, server-mediated launches only — the MCP launch_implementation tool that OAuth agent sessions use to advance a project from staging to building. Off (the default) keeps a human in the loop: the server refuses to authorize that launch until you press Implement yourself. Turning it on lets a trusted CLI/OAuth agent self-advance without a click — but only because your harness's own permission prompt for that call now counts as your approval; running that harness with a bypass/skip-permissions flag removes the ask, so only turn this on if you trust every session on this account to be asked honestly. It does not gate direct CLI interaction — an agent that reads a project and simply runs it locally never asks the server, so this toggle cannot reach it.
          </v-tooltip>
        </div>
        <div class="setting-row-help">Off by default. On lets your coding agent skip the Implement click.</div>
      </div>
      <div class="setting-row-control">
        <v-switch
          v-model="allowHeadless"
          color="primary"
          density="compact"
          hide-details
          aria-label="Allow a headless CLI agent to self-advance from staging to implementation"
          data-testid="headless-launch-toggle"
          @update:model-value="toggleHeadless"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/services/api'
import { useToast } from '@/composables/useToast'

const { showToast } = useToast()

const closeoutModeHitl = ref(true)

const allowHeadless = ref(false)

async function toggleCloseoutMode(enabled) {
  const newMode = enabled ? 'hitl' : 'autonomous'
  const previousValue = closeoutModeHitl.value
  closeoutModeHitl.value = enabled
  try {
    await api.settings.updateCloseoutMode(newMode)
    showToast({
      message: enabled
        ? 'User approval required before project closeout'
        : 'Orchestrator will close projects autonomously',
      type: 'success',
    })
  } catch {
    closeoutModeHitl.value = previousValue
    showToast({ message: 'Failed to save closeout setting.', type: 'error' })
  }
}

async function loadCloseoutMode() {
  try {
    const generalRes = await api.settings.getGeneral()
    const generalSettings = generalRes.data?.settings || {}
    if (generalSettings.closeout_mode) {
      closeoutModeHitl.value = generalSettings.closeout_mode === 'hitl'
    }
  } catch {
    // Default stays true (hitl)
  }
}

async function toggleHeadless(enabled) {
  const previousValue = allowHeadless.value
  allowHeadless.value = enabled
  try {
    await api.settings.updateHeadlessLaunch(enabled)
    showToast({
      message: enabled
        ? 'Headless mode on — a trusted CLI agent may self-advance to implementation'
        : 'HITL mode — the human Implement step is enforced',
      type: 'success',
    })
  } catch {
    allowHeadless.value = previousValue
    showToast({ message: 'Failed to save headless setting.', type: 'error' })
  }
}

async function loadHeadlessLaunch() {
  try {
    const res = await api.settings.getHeadlessLaunch()
    allowHeadless.value = !!res.data?.allow_headless_launch
  } catch {
    // Default stays false (HITL), matching the server default (BE-9670b)
  }
}

onMounted(() => {
  loadCloseoutMode()
  loadHeadlessLaunch()
})
</script>

<style scoped lang="scss">
/* FE-9616: the row chrome (name, help, right-aligned control) is the shared
   .setting-row pattern in main.scss. What stays here is what CANNOT live there:
   scoped CSS does not cross a component boundary, so these switch colours must
   travel with the markup -- the same boundary TemplatesTable.vue documents for
   its row toggles. */
.setting-row :deep(.v-switch .v-selection-control) {
  min-height: auto;
}

// Custom toggle colors for these HITL v-switches: green when ON, faded blue when OFF
// Duplicated into TemplatesTable.vue for the row-level template toggles (scoped CSS boundary)
.v-switch {
  :deep(.v-switch__thumb) {
    background-color: rgba(33, 150, 243, 0.4); // Faded blue when OFF
  }

  :deep(.v-switch__track) {
    background-color: rgba(33, 150, 243, 0.2); // Faded blue track when OFF
  }
}

.v-switch :deep(.v-selection-control--dirty) {
  .v-switch__thumb {
    background-color: rgb(var(--v-theme-success));
  }

  .v-switch__track {
    background-color: rgba(76, 175, 80, 0.3); // Green track when ON
  }
}
</style>
