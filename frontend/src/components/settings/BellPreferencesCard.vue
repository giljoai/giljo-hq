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

function markAllSeen() {
  notifications.markAllAsRead()
}
</script>
