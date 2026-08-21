import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import api from '@/services/api'
import configService from '@/services/configService'
import { getApiBaseUrl, getWsBaseUrl } from '@/composables/useApiUrl'

const DEFAULT_NOTIFICATIONS = {
  position: 'bottom-right',
  duration: 5,
}

function normalizeNotifications(notifications = {}) {
  const { position, duration } = { ...DEFAULT_NOTIFICATIONS, ...notifications }
  return { position, duration }
}

function normalizeSettingsPayload(payload = {}) {
  return {
    ...payload,
    notifications: normalizeNotifications(payload.notifications),
  }
}

export const useSettingsStore = defineStore('settings', () => {
  // State
  const settings = ref({
    notifications: { ...DEFAULT_NOTIFICATIONS },
    apiUrl: getApiBaseUrl(),
    wsUrl: getWsBaseUrl(),
  })

  const loading = ref(false)
  const error = ref(null)
  const agentSilenceThresholdMinutes = ref(10)
  // FE-9296b: account-level agent check-in cadence (replaced the per-project slider)
  const agentCheckinCadenceMinutes = ref(10)

  // Field toggle configuration (Handover 0048, 0820)
  const fieldToggleConfig = ref(null)

  // Getters
  const notificationPosition = computed(() => settings.value.notifications?.position || 'bottom-right')
  const notificationDuration = computed(() => (settings.value.notifications?.duration || 5) * 1000)

  // Actions
  async function loadSettings() {
    loading.value = true
    error.value = null
    try {
      // Load from localStorage first
      const savedSettings = localStorage.getItem('giljo_settings')
      if (savedSettings) {
        settings.value = normalizeSettingsPayload({
          ...settings.value,
          ...JSON.parse(savedSettings),
        })
      }

      // Then try to load from server. GET /api/v1/config/ reads config.yaml,
      // a self-hosted CE-only concept; it is CE-gated and 404s in SaaS/hosted
      // mode (SEC-0005a). Skip the call there so we don't log a noisy 404 — the
      // localStorage values above are the source of truth in SaaS.
      try {
        await configService.fetchConfig()
        if (configService.getGiljoMode() === 'ce') {
          const response = await api.settings.get()
          settings.value = normalizeSettingsPayload({
            ...settings.value,
            ...response.data,
          })

          saveToLocalStorage()
        }
      } catch {
        // Using local settings, server not available
      }
    } catch (err) {
      error.value = err.message
      console.error('Failed to load settings:', err)
    } finally {
      loading.value = false
    }
  }

  async function saveSettings() {
    loading.value = true
    error.value = null
    try {
      // Save to localStorage immediately
      saveToLocalStorage()
    } catch (err) {
      error.value = err.message
      console.error('Failed to save settings:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  function updateSetting(key, value) {
    if (settings.value[key] !== undefined) {
      settings.value[key] = value
      saveToLocalStorage()
    }
  }

  async function updateSettings(partial) {
    settings.value = normalizeSettingsPayload({ ...settings.value, ...partial })
    saveToLocalStorage()
  }

  async function loadAgentSilenceThreshold() {
    const response = await api.settings.getAgentSilenceThreshold()
    agentSilenceThresholdMinutes.value = response.data.agent_silence_threshold_minutes
    return agentSilenceThresholdMinutes.value
  }

  async function updateAgentSilenceThreshold(minutes) {
    const response = await api.settings.updateAgentSilenceThreshold(minutes)
    agentSilenceThresholdMinutes.value = response.data.agent_silence_threshold_minutes
    return agentSilenceThresholdMinutes.value
  }

  async function loadAgentCheckinCadence() {
    const response = await api.settings.getAgentCheckinCadence()
    agentCheckinCadenceMinutes.value = response.data.agent_checkin_cadence_minutes
    return agentCheckinCadenceMinutes.value
  }

  async function updateAgentCheckinCadence(minutes) {
    const response = await api.settings.updateAgentCheckinCadence(minutes)
    agentCheckinCadenceMinutes.value = response.data.agent_checkin_cadence_minutes
    return agentCheckinCadenceMinutes.value
  }

  function saveToLocalStorage() {
    localStorage.setItem('giljo_settings', JSON.stringify(settings.value))
  }

  function resetSettings() {
    settings.value = {
      notifications: { ...DEFAULT_NOTIFICATIONS },
      apiUrl: getApiBaseUrl(),
      wsUrl: getWsBaseUrl(),
    }
    saveToLocalStorage()
  }

  function clearError() {
    error.value = null
  }

  // Field Toggle Configuration Actions (Handover 0048, 0820)
  async function fetchFieldToggleConfig() {
    try {
      const response = await api.users.getFieldToggleConfig()
      fieldToggleConfig.value = response.data
    } catch (err) {
      console.error('Failed to fetch field toggle config:', err)
      throw err
    }
  }

  async function updateFieldToggleConfig(config) {
    try {
      const response = await api.users.updateFieldToggleConfig(config)
      fieldToggleConfig.value = response.data
    } catch (err) {
      console.error('Failed to update field toggle config:', err)
      throw err
    }
  }

  async function resetFieldToggleConfig() {
    try {
      const response = await api.users.resetFieldToggleConfig()
      fieldToggleConfig.value = response.data
    } catch (err) {
      console.error('Failed to reset field toggle config:', err)
      throw err
    }
  }

  // Watch for settings changes
  watch(
    settings,
    () => {
      saveToLocalStorage()
    },
    { deep: true },
  )

  return {
    // State
    settings,
    loading,
    error,
    fieldToggleConfig,
    agentSilenceThresholdMinutes,
    agentCheckinCadenceMinutes,

    // Getters
    notificationPosition,
    notificationDuration,

    // Actions
    loadSettings,
    saveSettings,
    updateSetting,
    updateSettings,
    loadAgentSilenceThreshold,
    updateAgentSilenceThreshold,
    loadAgentCheckinCadence,
    updateAgentCheckinCadence,
    resetSettings,
    clearError,
    fetchFieldToggleConfig,
    updateFieldToggleConfig,
    resetFieldToggleConfig,
  }
})
