<template>
  <v-card variant="flat" class="smooth-border settings-card" data-test="popout-preferences">
    <v-card-text>
      <h3 class="text-body-large mb-1">Browser pop-ups</h3>
      <p class="text-body-medium text-muted-a11y mb-4">
        The same banners, delivered by your operating system when this app is hidden. While
        you are looking at it, the banner alone tells you.
      </p>

      <div class="pref-row pref-row--static" data-test="popout-permission-status">
        <v-icon size="18" :color="permission.color" class="mr-3">{{ permission.icon }}</v-icon>
        <div>
          <div class="text-body-medium">{{ permission.label }}</div>
          <div class="text-body-small text-muted-a11y">{{ permission.hint }}</div>
        </div>
      </div>

      <div v-if="canAsk" class="pref-row pref-row--static">
        <v-btn
          color="primary"
          variant="flat"
          :loading="asking"
          data-test="popout-request-permission-btn"
          @click="askForPermission"
        >
          Turn on pop-ups
        </v-btn>
      </div>

      <template v-if="permission.state !== 'denied' && permission.state !== 'unsupported'">
        <v-divider class="my-4" />
        <v-radio-group
          :model-value="settings.popoutScope"
          hide-details
          density="compact"
          :disabled="saving"
          data-test="popout-scope-group"
          @update:model-value="save"
        >
          <template #label>
            <span class="text-body-medium">How much to send</span>
          </template>
          <v-radio value="all" data-test="popout-scope-all">
            <template #label>
              <span>
                Everything a banner shows
                <span class="text-body-small text-muted-a11y">
                  — anything asking for you, plus projects starting and finishing
                </span>
              </span>
            </template>
          </v-radio>
          <v-radio value="actionable" data-test="popout-scope-actionable">
            <template #label>
              <span>
                Only things asking for you
                <span class="text-body-small text-muted-a11y">
                  — decisions, your turn, mentions
                </span>
              </span>
            </template>
          </v-radio>
          <v-radio value="off" data-test="popout-scope-off">
            <template #label><span>Nothing</span></template>
          </v-radio>
        </v-radio-group>
      </template>

      <p v-if="error" class="text-body-small mt-3" data-test="popout-prefs-error">
        <v-icon size="16" color="error" class="mr-1">mdi-alert-circle</v-icon>
        Could not save that. Your setting is unchanged.
      </p>
    </v-card-text>
  </v-card>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

import { useSettingsStore } from '@/stores/settings'

const settings = useSettingsStore()
const saving = ref(false)
const asking = ref(false)
const error = ref(false)

const permissionState = ref('default')

onMounted(() => {
  permissionState.value =
    typeof Notification === 'undefined' ? 'unsupported' : Notification.permission
  settings.loadNotificationPrefs()
})

const permission = computed(() => {
  switch (permissionState.value) {
    case 'granted':
      return {
        state: 'granted',
        icon: 'mdi-bell-ring-outline',
        color: 'success',
        label: 'Your browser allows pop-ups from this app',
        hint: 'Nothing else to do here.',
      }
    case 'denied':
      return {
        state: 'denied',
        icon: 'mdi-bell-off-outline',
        color: 'warning',
        label: 'Your browser is blocking pop-ups from this app',
        hint: 'To turn them on, open your browser’s site settings for this address and allow notifications. Nothing is lost meanwhile: everything still appears in the title bar and the bell.',
      }
    case 'unsupported':
      return {
        state: 'unsupported',
        icon: 'mdi-bell-off-outline',
        color: 'grey',
        label: 'This browser does not support pop-ups',
        hint: 'Everything still appears in the title bar and the bell.',
      }
    default:
      return {
        state: 'default',
        icon: 'mdi-bell-outline',
        color: 'info',
        label: 'Your browser has not been asked yet',
        hint: 'Until you ask it, nothing pops up. Use “Turn on pop-ups” below — your browser will ask you once, and only you can answer it.',
      }
  }
})

const canAsk = computed(
  () => permissionState.value === 'default' && settings.popoutScope !== 'off',
)

async function requestPermissionNow() {
  try {
    const answer = await Notification.requestPermission()
    permissionState.value = answer || Notification.permission
  } catch {
    permissionState.value =
      typeof Notification === 'undefined' ? 'unsupported' : Notification.permission
  }
}

async function askForPermission() {
  asking.value = true
  try {
    await requestPermissionNow()
  } finally {
    asking.value = false
  }
}

async function save(value) {
  saving.value = true
  error.value = false

  if (value !== 'off' && permissionState.value === 'default') {
    await requestPermissionNow()
  }

  try {
    await settings.updateNotificationPrefs({ popoutScope: value })
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
</style>
