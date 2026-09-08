import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import api from '@/services/api'
import configService from '@/services/configService'
import { getApiBaseUrl, getWsBaseUrl } from '@/composables/useApiUrl'
import {
  EXECUTION_MODE_DEFAULT_ASK,
  EXECUTION_MODE_DEFAULT_CHOICES,
} from '@/utils/executionModeDefault'

// FE-9553: the popout scope answers only "how much of the banner do I
// project". Mirrors POPOUT_SCOPE_CHOICES in the backend validator; a drift
// between the two shows up as a control that cannot save.
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
  // State
  const settings = ref({
    notifications: { ...DEFAULT_NOTIFICATIONS },
    apiUrl: getApiBaseUrl(),
    wsUrl: getWsBaseUrl(),
  })

  const loading = ref(false)
  const error = ref(null)
  const agentSilenceThresholdMinutes = ref(10)
  // FE-9555: the account's standing answer to the one question staging asks.
  // 'ask' is the default AND the fallback for every failure below -- see
  // loadExecutionModeDefault for why it can never fall back to a mode.
  const executionModeDefault = ref(EXECUTION_MODE_DEFAULT_ASK)
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

  /**
   * FE-9553. The per-user, SERVER-SIDE notification-model preferences.
   *
   * Distinct from `settings.notifications` above, which is the localStorage
   * blob holding toast position and duration. Deliberately not merged into it:
   * that blob's normalizer drops any key it does not recognise, so a server
   * preference parked there would be silently discarded on the next save, and
   * the two have opposite storage requirements anyway -- these follow the user
   * between machines, the toast geometry does not need to.
   *
   * Every default here is the RULED default rather than a falsy one, and that
   * matters more than it looks: an undefined preference renders a switch as
   * OFF, a user "fixes" the switch that looks off by turning it on, and a
   * transient network failure has silently rewritten a preference they never
   * held. Same reasoning as loadExecutionModeDefault below.
   */
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
    // An unrecognised scope falls back rather than being stored: the projector
    // treats an unknown value as its safe default, so keeping a typo here would
    // look saved and then quietly behave as something else.
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

  /**
   * Write ONLY the keys the caller passed.
   *
   * The server's per-key guards only help if the client actually sends one
   * key; a full-object write is the thing that clobbers siblings. Nothing is
   * applied optimistically -- the store mirrors what the server CONFIRMED, so
   * a coerced or refused write never leaves a control showing a value the
   * account does not hold, and a rejection leaves the previous value alone.
   */
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

  /**
   * FE-9555. Read the account's execution-mode default.
   *
   * Falls back to 'ask' on ANY failure -- a rejected request, or a value the
   * client does not recognise. This is deliberately not a propagated error: an
   * undefined ref renders the Tools -> Agents select blank, a user "fixes" the
   * blank by picking a mode, and they have silently turned OFF the asking that
   * ruling 6 exists to turn ON. Falling back to the safe choice keeps a transient
   * network failure from rewriting a preference.
   */
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
    // Mirror what the server CONFIRMED, not what was sent -- the server is the
    // one that validates the choice, and a write that was coerced or refused
    // must not leave the control showing a value the account does not hold.
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
    executionModeDefault,
    // FE-9553 notification-model preferences (server-side, per user)
    bannerLifecycleEnabled,
    bannerAdvisoriesInFold,
    popoutScope,
    loadNotificationPrefs,
    updateNotificationPrefs,

    // Getters
    notificationPosition,
    notificationDuration,

    // Actions
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
