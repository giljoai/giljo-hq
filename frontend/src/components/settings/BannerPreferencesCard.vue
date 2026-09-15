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
