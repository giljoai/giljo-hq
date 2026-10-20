import { executionModeDefaultApi, handoverTemplateApi } from '../settingsApi.js'
import { notificationPrefsApi } from '../notificationPrefsApi.js'

export const createSettingsApi = (apiClient) => ({
  get: () => apiClient.get('/api/v1/config/'),

  getDatabase: () => apiClient.get('/api/v1/config/database'),
  testDatabase: () => apiClient.get('/api/v1/config/health/database'),

  getGeneral: () => apiClient.get('/api/v1/settings/general'),
  updateCloseoutMode: (mode) => apiClient.put('/api/v1/settings/closeout-mode', { closeout_mode: mode }),
  getAgentSilenceThreshold: () =>
    apiClient.get('/api/v1/settings/system/agent-silence-threshold'),
  updateAgentSilenceThreshold: (minutes) =>
    apiClient.put('/api/v1/settings/system/agent-silence-threshold', {
      agent_silence_threshold_minutes: minutes,
    }),
  getAgentCheckinCadence: () =>
    apiClient.get('/api/v1/settings/system/agent-checkin-cadence'),
  updateAgentCheckinCadence: (minutes) =>
    apiClient.put('/api/v1/settings/system/agent-checkin-cadence', {
      agent_checkin_cadence_minutes: minutes,
    }),

  getCookieDomains: () => apiClient.get('/api/v1/user/settings/cookie-domains'),
  addCookieDomain: (domain) => apiClient.post('/api/v1/user/settings/cookie-domains', { domain }),
  removeCookieDomain: (domain) =>
    apiClient.delete('/api/v1/user/settings/cookie-domains', { data: { domain } }),

  ...executionModeDefaultApi,
  ...handoverTemplateApi,
  ...notificationPrefsApi,

  getHeadlessLaunch: () => apiClient.get('/api/v1/user/settings/headless-launch'),
  updateHeadlessLaunch: (allow) =>
    apiClient.put('/api/v1/user/settings/headless-launch', { allow_headless_launch: allow }),
})

export const createHealthApi = (apiClient) => ({
  check: () => apiClient.get('/health'),
})

export const createSetupApi = (apiClient) => ({
  status: () => apiClient.get('/api/setup/status'),
})

export const createGitApi = (apiClient) => ({
  getSettings: () => apiClient.get('/api/git/settings'),
  toggle: (enabled) => apiClient.post('/api/git/toggle', { enabled }),
})
