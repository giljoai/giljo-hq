import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import api from '@/services/api'
import configService from '@/services/configService'
import { getApiBaseUrl, getWsBaseUrl } from '@/composables/useApiUrl'
import {
  EXECUTION_MODE_DEFAULT_ASK,
  EXECUTION_MODE_DEFAULT_CHOICES,
} from '@/utils/executionModeDefault'

const POPOUT_SCOPE_CHOICES = ['all', 'actionable', 'off']
const POPOUT_SCOPE_DEFAULT = 'all'

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
  const settings = ref({
    notifications: { ...DEFAULT_NOTIFICATIONS },
    apiUrl: getApiBaseUrl(),
    wsUrl: getWsBaseUrl(),
  })

  const loading = ref(false)
  const error = ref(null)
  const agentSilenceThresholdMinutes = ref(10)
  const executionModeDefault = ref(EXECUTION_MODE_DEFAULT_ASK)
  const agentCheckinCadenceMinutes = ref(10)

  const fieldToggleConfig = ref(null)

  const notificationPosition = computed(() => settings.value.notifications?.position || 'bottom-right')
  const notificationDuration = computed(() => (settings.value.notifications?.duration || 5) * 1000)

  async function loadSettings() {
    loading.value = true
    error.value = null
    try {
      const savedSettings = localStorage.getItem('giljo_settings')
      if (savedSettings) {
        settings.value = normalizeSettingsPayload({
          ...settings.value,
          ...JSON.parse(savedSettings),
        })
      }

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

  const bannerLifecycleEnabled = ref(true)
  const bannerAdvisoriesInFold = ref(true)
  const popoutScope = ref(POPOUT_SCOPE_DEFAULT)

  function applyNotificationPrefs(prefs) {
    const source = prefs || {}
    bannerLifecycleEnabled.value =
      typeof source.banner_lifecycle_enabled === 'boolean' ? source.banner_lifecycle_enabled : true
    bannerAdvisoriesInFold.value =
      typeof source.banner_advisories_in_fold === 'boolean'
        ? source.banner_advisories_in_fold
        : true
    popoutScope.value = POPOUT_SCOPE_CHOICES.includes(source.popout_scope)
      ? source.popout_scope
      : POPOUT_SCOPE_DEFAULT
  }

  async function loadNotificationPrefs() {
    try {
      const response = await api.settings.getNotificationPrefs()
      applyNotificationPrefs(response?.data?.notification_preferences)
    } catch (err) {
      console.warn('[settings] notification preferences unavailable; using ruled defaults', err)
      applyNotificationPrefs(null)
    }
    return { bannerLifecycleEnabled: bannerLifecycleEnabled.value, bannerAdvisoriesInFold: bannerAdvisoriesInFold.value, popoutScope: popoutScope.value }
  }

  async function updateNotificationPrefs(partial) {
    const payload = {}
    if ('bannerLifecycleEnabled' in partial) {
      payload.banner_lifecycle_enabled = partial.bannerLifecycleEnabled
    }
    if ('bannerAdvisoriesInFold' in partial) {
      payload.banner_advisories_in_fold = partial.bannerAdvisoriesInFold
    }
    if ('popoutScope' in partial) {
      payload.popout_scope = partial.popoutScope
    }

    const response = await api.settings.updateNotificationPrefs(payload)
    applyNotificationPrefs(response?.data?.notification_preferences)
    return popoutScope.value
  }

  async function loadExecutionModeDefault() {
    try {
      const response = await api.settings.getExecutionModeDefault()
      const value = response?.data?.execution_mode_default
      executionModeDefault.value = EXECUTION_MODE_DEFAULT_CHOICES.includes(value)
        ? value
        : EXECUTION_MODE_DEFAULT_ASK
    } catch (err) {
      console.warn('[settings] execution-mode default unavailable; asking every time', err)
      executionModeDefault.value = EXECUTION_MODE_DEFAULT_ASK
    }
    return executionModeDefault.value
  }

  async function updateExecutionModeDefault(choice) {
    const response = await api.settings.updateExecutionModeDefault(choice)
    executionModeDefault.value = response.data.execution_mode_default
    return executionModeDefault.value
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

  watch(
    settings,
    () => {
      saveToLocalStorage()
    },
    { deep: true },
  )

  return {
    settings,
    loading,
    error,
    fieldToggleConfig,
    agentSilenceThresholdMinutes,
    agentCheckinCadenceMinutes,
    executionModeDefault,
    bannerLifecycleEnabled,
    bannerAdvisoriesInFold,
    popoutScope,
    loadNotificationPrefs,
    updateNotificationPrefs,

    notificationPosition,
    notificationDuration,

    loadExecutionModeDefault,
    updateExecutionModeDefault,
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
