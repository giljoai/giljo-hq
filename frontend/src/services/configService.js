
import { getApiBaseUrl, getWsBaseUrl } from '@/composables/useApiUrl'

class ConfigService {
  constructor() {
    this.config = null
    this.fetchPromise = null
    this.debug = import.meta.env.VITE_CONFIG_DEBUG === 'true' || false
  }

  async fetchConfig() {
    if (this.config) {
      this.log('Using cached config', this.config)
      return this.config
    }

    if (this.fetchPromise) {
      this.log('Fetch already in progress, waiting...')
      return this.fetchPromise
    }

    this.fetchPromise = this._doFetch()

    try {
      const result = await this.fetchPromise
      if (!result?._fallback) {
        this.config = result
      }
      return result
    } finally {
      this.fetchPromise = null
    }
  }

  async _doFetch() {
    try {
      const base = getApiBaseUrl()
      const configUrl = base ? `${base}/api/v1/config/frontend` : '/api/v1/config/frontend'

      this.log(`Fetching config from ${configUrl}`)

      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 5000)

      try {
        const response = await fetch(configUrl, {
          signal: controller.signal,
          headers: {
            Accept: 'application/json',
          },
        })

        clearTimeout(timeoutId)

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`)
        }

        const config = await response.json()
        this.log('Config fetched successfully', config)

        if (!config.api) {
          throw new Error('Invalid config response structure')
        }

        return config
      } catch (fetchError) {
        clearTimeout(timeoutId)
        throw fetchError
      }
    } catch (error) {
      this.log('Failed to fetch config from backend', error)

      const fallbackBase = getApiBaseUrl() || window.location.origin
      const fallbackWs = getWsBaseUrl() || fallbackBase.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:')
      const fallbackUrl = new URL(fallbackBase)
      const fallbackConfig = {
        api: {
          host: fallbackUrl.hostname,
          port: fallbackUrl.port
            ? parseInt(fallbackUrl.port, 10)
            : fallbackUrl.protocol === 'https:'
              ? 443
              : 80,
          protocol: fallbackUrl.protocol.replace(':', ''),
        },
        websocket: {
          url: fallbackWs,
        },
        mode: 'unknown',
        security: {
          api_keys_required: false,
        },
        _fallback: true,
      }

      this.log('Using fallback config', fallbackConfig)
      return fallbackConfig
    }
  }


  getEdition() {
    return this.config?.edition || 'community'
  }

  getGiljoMode() {
    return this.config?.giljo_mode || 'unknown'
  }

  getVersion() {
    return this.config?.version || ''
  }

  isFallback() {
    return this.config?._fallback || false
  }

  getRawConfig() {
    return this.config
  }

  clearCache() {
    this.log('Clearing config cache')
    this.config = null
    this.fetchPromise = null
  }

  log(message, data = null) {
    if (this.debug) {
      console.warn(`[ConfigService] ${message}`, data || '')
    }
  }
}

const configService = new ConfigService()

export default configService
