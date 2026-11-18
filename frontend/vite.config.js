import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'
import { fileURLToPath, URL } from 'node:url'
import { resolve } from 'path'
import fs from 'fs'
import * as yaml from 'js-yaml'
import { sentryVitePlugin } from '@sentry/vite-plugin'

// Load frontend port from environment or use default
const FRONTEND_PORT = parseInt(process.env.VITE_FRONTEND_PORT || process.env.GILJO_FRONTEND_PORT || '7274', 10)

// Bind address comes from server.dashboard_host in config.yaml: the installer
// writes the LAN address there when the user chose LAN access. With no
// config.yaml, or no dashboard_host in it, the dev server stays on loopback.
let dashboardHost = '127.0.0.1'
try {
  const configPath = resolve(__dirname, '../config.yaml')
  if (fs.existsSync(configPath)) {
    const configData = yaml.load(fs.readFileSync(configPath, 'utf8'))
    dashboardHost = configData?.server?.dashboard_host || '127.0.0.1'
    console.log(`[Vite] v3.0 binding to: ${dashboardHost}:${FRONTEND_PORT}`)
  }
  // No log when config.yaml is absent: that is the NORMAL state during install
  // (frontend builds before config generation) and for contributor checkouts —
  // a "not found" line there reads as an error to fresh installers (v2.0.0.1 QA).
} catch (err) {
  console.warn('[Vite] Could not read config.yaml, binding to 127.0.0.1:', err.message)
}

const HOST = dashboardHost

// Derive API proxy target from config.yaml
// CRITICAL: For Playwright tests, always use localhost (same machine)
// For production, external_host is used by clients to reach the server
let apiHost = '127.0.0.1'
let apiPort = 7272
try {
  const configPath = resolve(__dirname, '../config.yaml')
  if (fs.existsSync(configPath)) {
    const configData = yaml.load(fs.readFileSync(configPath, 'utf8'))
    apiPort = parseInt(configData?.server?.api_port || 7272, 10)
    // ALWAYS use localhost for Vite dev proxy (same machine as backend)
    // external_host is for client-to-server connections, not dev proxy
    apiHost = '127.0.0.1'
  }
} catch (err) {
  console.warn('[Vite] Could not determine API proxy target, defaulting to 127.0.0.1:7272:', err.message)
}
const API_TARGET = `http://${apiHost}:${apiPort}`

// Build Sentry vite plugin config — only active in production SaaS/Demo builds
// when SENTRY_AUTH_TOKEN is present. No-ops silently otherwise.
function buildSentryPlugin(mode) {
  const authToken = process.env.SENTRY_AUTH_TOKEN
  const giljoMode = process.env.GILJO_MODE
  const org = process.env.SENTRY_ORG
  const project = process.env.SENTRY_PROJECT
  if (
    mode !== 'production' ||
    !authToken ||
    !giljoMode ||
    giljoMode === 'ce'
  ) {
    return null
  }
  return sentryVitePlugin({
    org,
    project,
    authToken,
    sourcemaps: {
      assets: ['./dist/**'],
      // Delete local .map files after upload — keeps them out of public CDN
      filesToDeleteAfterUpload: ['./dist/**/*.map'],
    },
  })
}

export default defineConfig(({ mode }) => ({
  plugins: [
    vue(),
    vuetify({ autoImport: true }),
    buildSentryPlugin(mode),
  ].filter(Boolean),
  build: {
    // Source maps for Sentry symbolication, but 'hidden' so the bundles carry
    // NO `//# sourceMappingURL=` comment — browsers never request the .map
    // files. The Sentry plugin still finds + uploads them by glob and deletes
    // them after upload (SaaS/private builds). On builds where the plugin does
    // NOT run (CE / no SENTRY_AUTH_TOKEN), the .map files stay on disk but are
    // unreferenced, so they are not downloaded by clients (fixes ~8MB of .map
    // transfer observed on the test box — perf-findings 2026-06-11).
    sourcemap: 'hidden',
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html')
      },
      output: {
        // SEC-0057: keep /*! ... */ licence notices (Vite drops them when minifying),
        // so vendored third-party code ships with its licence notice.
        comments: { legal: true },
        // Vite 8 (Rolldown) requires manualChunks as a function, not an
        // object. The function receives a module id (full path) and returns
        // a chunk name string, or undefined for default chunking.
        manualChunks: (id) => {
          if (id.includes('node_modules/vuetify')) return 'vuetify'
          if (
            id.includes('node_modules/vue/') ||
            id.includes('node_modules/vue-router/') ||
            id.includes('node_modules/pinia/')
          ) return 'vue-vendor'
        }
      }
    }
  },
  server: {
    port: FRONTEND_PORT,
    host: HOST,
    strictPort: false, // Allow fallback to alternative port if occupied
    proxy: {
      // Proxy API to backend to avoid CORS in development
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        secure: false,
        ws: true,
        // Fix (Post-0128e): Ensure cookies are forwarded for authentication
        // Browser cookies need to reach backend for JWT auth to work over LAN/WAN
        cookieDomainRewrite: '', // Don't rewrite cookie domains
        preserveHeaderKeyCase: true, // Preserve header casing
        configure: (proxy, _options) => {
          proxy.on('proxyReq', (proxyReq, req, _res) => {
            // Forward cookies for JWT auth
            if (req.headers.cookie) {
              proxyReq.setHeader('Cookie', req.headers.cookie)
            }
            // Forward real client IP so backend can detect remote clients
            const clientIp = req.socket?.remoteAddress?.replace('::ffff:', '')
            if (clientIp) {
              proxyReq.setHeader('X-Forwarded-For', clientIp)
            }
          })
        },
      },
      // WebSocket upgrades (ADR-001). The backend serves the socket at
      // /ws/{client_id} on the API root -- NOT under /api -- and in dev
      // getWsBaseUrl() returns '' so the app dials the Vite origin. Without a
      // rule here the upgrade matches nothing, hangs with no error, and no
      // WS-driven UI can be tested locally (INF-9573). Host is NOT rewritten: the
      // backend admits a cookie handshake whose Origin names the host it was sent
      // to, and the browser's Origin here is the Vite address.
      '/ws': {
        target: API_TARGET.replace(/^http/, 'ws'),
        changeOrigin: false,
        secure: false,
        ws: true,
      },
      // Agent-readable connect page (BE-9726): served by the backend, not the SPA.
      '/connect.md': {
        target: API_TARGET,
        changeOrigin: true,
        secure: false,
      },
      // MCP endpoints if used
      '/mcp': {
        target: API_TARGET,
        changeOrigin: true,
        secure: false,
        // Same cookie forwarding for MCP endpoints
        cookieDomainRewrite: '',
        preserveHeaderKeyCase: true,
        configure: (proxy, _options) => {
          proxy.on('proxyReq', (proxyReq, req, _res) => {
            if (req.headers.cookie) {
              proxyReq.setHeader('Cookie', req.headers.cookie)
            }
            const clientIp = req.socket?.remoteAddress?.replace('::ffff:', '')
            if (clientIp) {
              proxyReq.setHeader('X-Forwarded-For', clientIp)
            }
          })
        },
      },
    },
    fs: {
      // Strict mode stays on (Vite's default). Only the frontend itself and the
      // three docs UserGuideView.vue imports from ../docs may be served.
      allow: [
        __dirname,
        ...['PRODUCT_OVERVIEW.md', 'GETTING_STARTED.md', 'USER_GUIDE.md'].map((doc) => resolve(__dirname, '../docs', doc)),
      ]
    }
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  css: {
    preprocessorOptions: {
      scss: {
        api: 'modern-compiler',
        additionalData: `@use "@/styles/variables.scss" as *;`
      }
    }
  }
  // NOTE (FE-6015): the canonical vitest configuration lives in the dedicated
  // frontend/vitest.config.js, which vitest resolves with precedence over this
  // file. A `test` block here would be silently shadowed and drift out of sync
  // (it had already diverged — missing disableConsoleIntercept + include/exclude),
  // so it was removed to keep ONE canonical test config.
}))
