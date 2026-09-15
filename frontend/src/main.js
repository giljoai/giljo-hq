import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { pinia } from './stores'
import { initializeApiConfig } from './config/api'
import configService from './services/configService'
import setupService from './services/setupService'
import { initSentry } from './sentry'
import { applyNonceToApp, readCspNonce } from '@/composables/useCspNonce'
import { maybeReloadForChunkError } from '@/utils/chunkReload'

import 'vuetify/styles'
import { createVuetify } from 'vuetify'
import '@mdi/font/css/materialdesignicons.css'

import { draggable } from './directives/draggable'

import '@/styles/main.scss'
import '@/styles/global-tabs.scss'

import { darkTheme } from './config/theme'

const cspNonce = readCspNonce() || undefined

const vuetify = createVuetify({
  theme: {
    defaultTheme: 'dark',
    cspNonce,
    themes: {
      dark: darkTheme,
    },
  },
  icons: {
    defaultSet: 'mdi',
  },
  display: {
    mobileBreakpoint: 'md',
  },
  defaults: {
    VTextField: {
      spellcheck: 'true',
      autocorrect: 'on',
      autocapitalize: 'sentences',
    },
    VTextarea: {
      spellcheck: 'true',
      autocorrect: 'on',
      autocapitalize: 'sentences',
    },
  },
})

window.addEventListener('vite:preloadError', (event) => {
  event.preventDefault()
  maybeReloadForChunkError()
})

const app = createApp(App)

applyNonceToApp(app)

app.use(pinia)
app.use(vuetify)

app.directive('draggable', draggable)

localStorage.setItem('theme-preference', 'dark')
vuetify.theme.change('dark')
document.documentElement.setAttribute('data-theme', 'dark')

async function bootstrap() {
  try {
    await initializeApiConfig()
  } catch (error) {
    console.warn('[MAIN] Failed to initialize API config, using fallback:', error)
  }

  try {
    const status = await setupService.checkEnhancedStatus()
    if (status?.sentryDsn) {
      await initSentry(app, {
        dsn: status.sentryDsn,
        environment: status.environment || status.mode || 'unknown',
        tenantKey: null,
      })
    }
  } catch (error) {
    console.warn('[MAIN] Sentry init skipped:', error)
  }

  const saasRouteLoaders = import.meta.glob('@/saas/routes/index.js')
  const [saasRoutesLoader] = Object.values(saasRouteLoaders)
  if (saasRoutesLoader && configService.getGiljoMode() !== 'ce') {
    try {
      const saasRoutes = await saasRoutesLoader()
      saasRoutes.registerSaasRoutes()
    } catch (error) {
      console.warn('[MAIN] SaaS routes failed to register:', error)
    }
  }

  app.use(router)

  app.mount('#app')
}

bootstrap()
