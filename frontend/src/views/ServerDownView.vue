<template>
  <v-container fluid class="fill-height pa-0">
    <v-row class="align-center justify-center fill-height">
      <v-col cols="12" sm="8" md="6" lg="4">
        <v-card class="mx-auto smooth-border" elevation="8">
          <v-card-title class="text-headline-large text-center pa-6 error--text">
            <v-icon size="64" color="error" class="mb-4">mdi-server-off</v-icon>
            <div>Server Unreachable</div>
          </v-card-title>

          <v-card-text class="pa-6">
            <v-alert type="error" variant="tonal" class="mb-4">
              Unable to connect to {{ productName }}
            </v-alert>

            <p class="text-body-large mb-4">
              The server at <strong>{{ serverUrl }}</strong> is not responding.
            </p>

            <v-list density="compact" class="mb-4">
              <v-list-subheader>Possible causes:</v-list-subheader>
              <v-list-item>
                <template #prepend>
                  <v-icon size="small">mdi-circle-small</v-icon>
                </template>
                <v-list-item-title>Server is stopped or restarting</v-list-item-title>
              </v-list-item>
              <v-list-item>
                <template #prepend>
                  <v-icon size="small">mdi-circle-small</v-icon>
                </template>
                <v-list-item-title>Network connectivity issues</v-list-item-title>
              </v-list-item>
              <v-list-item>
                <template #prepend>
                  <v-icon size="small">mdi-circle-small</v-icon>
                </template>
                <v-list-item-title>Firewall blocking access</v-list-item-title>
              </v-list-item>
            </v-list>

            <v-divider class="my-4"></v-divider>

            <div class="text-center">
              <v-btn
                color="primary"
                size="large"
                prepend-icon="mdi-refresh"
                :loading="retrying"
                class="mb-2"
                @click="retryConnection"
              >
                Retry Connection
              </v-btn>

              <div class="text-body-small mt-2 text-muted-a11y">
                Last attempt: {{ lastAttempt }}
              </div>

              <v-progress-linear
                v-if="autoRetrying"
                :model-value="autoRetryProgress"
                color="primary"
                height="4"
                class="mt-4"
              ></v-progress-linear>
              <div v-if="autoRetrying" class="text-body-small mt-1 text-muted-a11y">
                Auto-retry in {{ autoRetrySeconds }}s...
              </div>
            </div>
          </v-card-text>

          <v-card-actions class="pa-6 pt-0">
            <v-btn variant="text" prepend-icon="mdi-logout" block @click="logout">
              Return to Login
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/services/api'
import { getApiBaseUrl } from '@/composables/useApiUrl'
import { PRODUCT_NAME } from '@/branding'

const productName = PRODUCT_NAME

const router = useRouter()
const retrying = ref(false)
const lastAttempt = ref(new Date().toLocaleTimeString())
const autoRetrying = ref(true)
const autoRetrySeconds = ref(10)
const autoRetryProgress = ref(100)

let autoRetryInterval = null
let autoRetryCountdown = null

const serverUrl = computed(() => {
  return getApiBaseUrl() || window.location.origin
})

const retryConnection = async () => {
  retrying.value = true
  lastAttempt.value = new Date().toLocaleTimeString()

  try {
    // Try to reach the server
    await api.setup.status()

    // Success! Redirect to appropriate page
    // Check if user is authenticated
    try {
      await api.auth.me()
      router.push('/')
    } catch {
      router.push('/login')
    }
  } catch {
    // Server still unreachable - reset auto-retry countdown
    autoRetrySeconds.value = 10
    autoRetryProgress.value = 100
  } finally {
    retrying.value = false
  }
}

const logout = () => {
  // Clear any local state
  localStorage.clear()
  sessionStorage.clear()

  // Redirect to login
  router.push('/login')
}

onMounted(() => {
  // Auto-retry every 10 seconds
  autoRetryInterval = setInterval(() => {
    retryConnection()
  }, 10000)

  // Countdown timer
  autoRetryCountdown = setInterval(() => {
    autoRetrySeconds.value -= 1
    autoRetryProgress.value = (autoRetrySeconds.value / 10) * 100

    if (autoRetrySeconds.value <= 0) {
      autoRetrySeconds.value = 10
      autoRetryProgress.value = 100
    }
  }, 1000)
})

onUnmounted(() => {
  if (autoRetryInterval) clearInterval(autoRetryInterval)
  if (autoRetryCountdown) clearInterval(autoRetryCountdown)
})
</script>

<style scoped>
.fill-height {
  min-height: 100vh;
}
</style>
