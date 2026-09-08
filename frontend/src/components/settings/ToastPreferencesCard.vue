<!--
  ToastPreferencesCard.vue — FE-9553

  The toast card: position and duration, UNCHANGED. The record says "EXISTS,
  keep" and this is a move, not a redesign — same two controls, same six
  positions, same 2-10 second range, same batched Reset/Save. The data-test
  hooks are kept verbatim so the specs that already cover them keep covering
  them.

  Extracted from ToolsView.vue because that file is at the 800-line guardrail
  and the four-card restructure cannot fit inside it. The batched Save stays
  batched here, deliberately unlike the save-on-change used by the preference
  cards: these two write to localStorage rather than the server, they are read
  together by one consumer, and there was never a reason to change what already
  worked.

  What the toast is FOR, since the card no longer sits alone under a header
  that explained it: feedback for the user's own action, past tense, gone in
  seconds. Since FE-9553 nothing an agent does can raise one.
-->
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
  // Sends only the notifications slice: updateSettings merges, and passing the
  // whole settings object back would hand the store its own state to
  // re-normalize for no reason.
  await settings.updateSettings({ notifications: { ...local } })
}
</script>
