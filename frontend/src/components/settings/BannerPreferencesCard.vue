<!--
  BannerPreferencesCard.vue — FE-9553

  The title-bar banner card: the only actionable notification surface, and the
  only one whose settings can be got wrong in a way that hurts.

  THE ALWAYS-ON LINE IS TEXT, NOT A DISABLED SWITCH, and that is a ruling rather
  than a styling choice. Decisions, your-turn batons and mentions are always on,
  because a settings menu must never be able to unplug the doorbell for a
  decision the system is blocked on. A greyed-out switch would state the same
  fact while implying the control exists and is merely unavailable — which is a
  control that lies, which is exactly what must not ship.
  So the guarantee is written in words and there is nothing to click.

  Each toggle here means BELL-ONLY, never "gone". The lifecycle path writes its
  durable bell row unconditionally and advisories stay in the bell when they
  leave the fold, so both of these move an event between surfaces rather than
  deleting it.

  Extracted as its own component because ToolsView.vue is at the 800-line
  guardrail — the same reason FE-9555 extracted ExecutionModeDefaultSelect.
-->
<template>
  <v-card variant="flat" class="smooth-border settings-card" data-test="banner-preferences">
    <v-card-text>
      <h3 class="text-body-large mb-1">Title-bar banners</h3>
      <p class="text-body-medium text-muted-a11y mb-4">
        The one surface that asks you for something. Present tense, and it stays until you
        handle it.
      </p>

      <div class="pref-row pref-row--static" data-test="banner-always-on">
        <v-icon size="18" color="success" class="mr-3">mdi-check-circle</v-icon>
        <div>
          <div class="text-body-medium">Decisions, your turn, and mentions are always shown</div>
          <div class="text-body-small text-muted-a11y">
            These cannot be turned off. If the system is waiting on you, you will see it.
          </div>
        </div>
      </div>

      <div class="pref-row">
        <v-switch
          :model-value="settings.bannerLifecycleEnabled"
          color="primary"
          density="compact"
          hide-details
          inset
          :disabled="saving"
          aria-label="Show lifecycle events in the title bar"
          data-test="banner-lifecycle-toggle"
          @update:model-value="save('bannerLifecycleEnabled', $event)"
        />
        <div class="pref-row__label">
          <div class="text-body-medium">Lifecycle events</div>
          <div class="text-body-small text-muted-a11y">
            Projects starting and finishing. Turn this off and they go to the bell instead.
          </div>
        </div>
      </div>

      <div class="pref-row">
        <v-switch
          :model-value="settings.bannerAdvisoriesInFold"
          color="primary"
          density="compact"
          hide-details
          inset
          :disabled="saving"
          aria-label="Show advisories in the title bar"
          data-test="banner-advisories-toggle"
          @update:model-value="save('bannerAdvisoriesInFold', $event)"
        />
        <div class="pref-row__label">
          <div class="text-body-medium">Advisories</div>
          <div class="text-body-small text-muted-a11y">
            Updates available, health notices, reminders. Off means bell-only.
          </div>
        </div>
      </div>

      <p v-if="error" class="text-body-small mt-3" data-test="banner-prefs-error">
        <v-icon size="16" color="error" class="mr-1">mdi-alert-circle</v-icon>
        Could not save that. Your setting is unchanged.
      </p>
    </v-card-text>
  </v-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'

import { useSettingsStore } from '@/stores/settings'

const settings = useSettingsStore()
const saving = ref(false)
const error = ref(false)

onMounted(() => settings.loadNotificationPrefs())

/**
 * Save on change, matching the Agent Behaviour group's peers rather than
 * offering a Save button — one preference, one write, no half-applied state.
 *
 * The store mirrors what the server confirmed, so a rejected write leaves the
 * switch showing what the account actually holds rather than what was clicked.
 * The error line says the setting is UNCHANGED for that reason: it would be
 * worse to imply a save that did not happen.
 */
async function save(key, value) {
  saving.value = true
  error.value = false
  try {
    await settings.updateNotificationPrefs({ [key]: value })
  } catch {
    error.value = true
  } finally {
    saving.value = false
  }
}
</script>

<style scoped lang="scss">
.pref-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 0;

  &--static {
    align-items: center;
  }
}

.pref-row__label {
  padding-top: 2px;
}
</style>
