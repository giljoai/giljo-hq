<!--
  BellPreferencesCard.vue — FE-9553

  The bell has no settings, and saying so is the point.

  It is the archive: past tense, accepts everything, durable, and since M3 it
  never alerts — a quiet unseen count and no pulse, because urgency lives in
  banners exclusively. There is nothing to tune, because every choice that
  could be offered here would be a choice about what to FORGET, and an archive
  you can configure to forget things is not one.

  So the card exists to state that and to offer the one action that is not a
  setting: marking everything seen.
-->
<template>
  <v-card variant="flat" class="smooth-border settings-card" data-test="bell-preferences">
    <v-card-text>
      <h3 class="text-body-large mb-1">The bell</h3>
      <p class="text-body-medium text-muted-a11y mb-0">
        Your history. Everything that happened lands here and stays, including anything you
        turned off above. It keeps a count of what you have not seen and never interrupts
        you.
      </p>
    </v-card-text>
    <v-card-actions>
      <v-spacer />
      <v-btn
        variant="text"
        :disabled="unseen === 0"
        data-test="bell-mark-all-seen-btn"
        @click="markAllSeen"
      >
        {{ unseen === 0 ? 'Nothing unseen' : `Mark all ${unseen} as seen` }}
      </v-btn>
    </v-card-actions>
  </v-card>
</template>

<script setup>
import { computed } from 'vue'

import { useNotificationStore } from '@/stores/notifications'

const notifications = useNotificationStore()

const unseen = computed(() => notifications.unreadCount)

/**
 * The button label carries the count and the button disables at zero, so the
 * control cannot be pressed to no effect. Cheaper than a toast confirming that
 * nothing happened.
 */
function markAllSeen() {
  notifications.markAllAsRead()
}
</script>
