<template>
  <v-dialog v-model="showDialog" max-width="520" persistent scrollable>
    <v-card class="smooth-border">
      <div class="dlg-header">
        <v-icon class="dlg-icon" icon="mdi-license" />
        <span class="dlg-title">Commercial License Required</span>
        <v-btn icon variant="text" size="small" class="dlg-close" @click="dismiss">
          <v-icon icon="mdi-close" size="18" />
        </v-btn>
      </div>

      <v-divider />

      <v-card-text class="pa-4">
        <p class="text-body-large mb-4">
          This {{ productName }} installation has
          <strong>{{ userCount }} user accounts</strong>.
        </p>
        <p class="text-body-medium mb-4">
          The <strong>Community Edition</strong> is licensed for single-user use.
          Multi-user deployments require a Commercial License from GiljoAI LLC.
        </p>
        <p class="text-body-medium text-muted-a11y">
          Commercial Licenses may be obtained at no cost at GiljoAI LLC's discretion.
        </p>

        <v-alert type="info" variant="tonal" density="compact" class="mt-4">
          <template #text>
            Contact <strong>sales@giljo.ai</strong> to obtain a Commercial License.
          </template>
        </v-alert>
      </v-card-text>

      <v-divider />

      <div class="dlg-footer">
        <v-spacer />
        <v-btn color="primary" variant="flat" @click="dismiss">
          I Understand
        </v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import setupService from '@/services/setupService'
import configService from '@/services/configService'
import { PRODUCT_NAME } from '@/branding'

const STORAGE_KEY = 'giljo_license_dismissed_at'
const REMINDER_DAYS = 30

const showDialog = ref(false)
const userCount = ref(0)
const productName = PRODUCT_NAME

async function checkLicensing() {
  try {
    await configService.fetchConfig()
    if (configService.getGiljoMode() !== 'ce') return

    const data = await setupService.checkEnhancedStatus()
    const totalUsers = data.total_users_count || 0

    if (totalUsers <= 1) return

    userCount.value = totalUsers

    const dismissedAt = localStorage.getItem(STORAGE_KEY)
    if (dismissedAt) {
      const dismissedDate = new Date(dismissedAt)
      const now = new Date()
      const daysSince = (now - dismissedDate) / (1000 * 60 * 60 * 24)
      if (daysSince < REMINDER_DAYS) return
    }

    showDialog.value = true
  } catch {
    // Silently fail - don't block the app over licensing check
  }
}

function dismiss() {
  localStorage.setItem(STORAGE_KEY, new Date().toISOString())
  showDialog.value = false
}

onMounted(() => {
  checkLicensing()
})
</script>
