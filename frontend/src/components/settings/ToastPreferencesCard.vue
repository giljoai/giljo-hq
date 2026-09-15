<template>
  <v-card variant="flat" class="smooth-border settings-card" data-test="notification-settings">
    <v-card-text>
      <h3 class="text-body-large mb-1">Toasts</h3>
      <p class="text-body-medium text-muted-a11y mb-4">
        The brief confirmations of things you just did. They never carry anything an agent
        did — that is what the title bar and the bell are for.
      </p>

      <v-select
        v-model="local.position"
        :items="POSITIONS"
        label="Position"
        variant="outlined"
        density="compact"
        data-test="notification-position-select"
      />
      <v-slider
        v-model="local.duration"
        :min="2"
        :max="10"
        :step="1"
        label="Display duration (seconds)"
        thumb-label
        color="primary"
        class="mt-4"
      />
    </v-card-text>
    <v-card-actions>
      <v-spacer />
      <v-btn variant="text" data-test="reset-notification-btn" @click="reset">Reset</v-btn>
      <v-btn color="primary" variant="flat" data-test="save-notification-btn" @click="save">
        Save Changes
      </v-btn>
    </v-card-actions>
  </v-card>
</template>

<script setup>
import { onMounted, reactive } from 'vue'

import { useSettingsStore } from '@/stores/settings'

const POSITIONS = [
  { title: 'Top Left', value: 'top-left' },
  { title: 'Top Center', value: 'top-center' },
  { title: 'Top Right', value: 'top-right' },
  { title: 'Bottom Left', value: 'bottom-left' },
  { title: 'Bottom Center', value: 'bottom-center' },
  { title: 'Bottom Right', value: 'bottom-right' },
]

const DEFAULTS = { position: 'bottom-right', duration: 5 }

const settings = useSettingsStore()
const local = reactive({ ...DEFAULTS })

onMounted(async () => {
  await settings.loadSettings()
  Object.assign(local, settings.settings.notifications)
})

function reset() {
  Object.assign(local, DEFAULTS)
}

async function save() {
  await settings.updateSettings({ notifications: { ...local } })
}
</script>
