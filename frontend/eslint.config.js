import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import vueParser from 'vue-eslint-parser'
import globals from 'globals'
import { createRequire } from 'node:module'

// Local plugin (IMP-0013 Phase 4) — not published to npm.
const requireCjs = createRequire(import.meta.url)
const giljoInternal = requireCjs('./eslint-rules/index.cjs')

export default [
  {
    ignores: [
      'node_modules/',
      'dist/',
      'build/',
      'public/',
      '*.min.js',
      'vendor/',
      'coverage/',
      '__tests__/',
      'tests/',
      'playwright-report/',
      'test-results/',
      'src/types/**/*.ts',
      'src/**/*.ts',
      'src/integrations/**',
      'src/components/messages/**',
      'src/components/settings/ContextPriorityConfig.vue', // Uses lang="ts", needs TS parser in ESLint config
      'src/components/ui/**',
      'src/components/__tests__/StatusBadge.spec.js',
    ],
  },
  {
    files: ['src/**/*.{js,mjs,jsx,ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.node,
        ...globals.vitest,
      },
    },
    rules: {
      ...js.configs.recommended.rules,
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'no-debugger': 'error',
      'no-unused-vars': [
        'warn',
        {
          argsIgnorePattern: '^_|^e$|^err$|^error$|^props$|^emit$',
          varsIgnorePattern: '^_|^err|^e$|^error$|^props$|^emit$|^theme$',
        },
      ],
      'prefer-const': 'error',
      'prefer-template': 'error',
      'prefer-arrow-callback': 'error',
      'no-var': 'error',
      // IMP-0013 Phase 4: anti-pattern rules
      'giljo-internal/no-manual-api-url-composition': 'error',
      'giljo-internal/no-vite-ignore-saas-import': 'error',
      'giljo-internal/vue-router-install-after-routes': 'error',
      'giljo-internal/axios-interceptor-route-meta-aware': 'error',
      'giljo-internal/no-speculative-layout-fallback': 'error',
      // FE-6006 unit 2: dialog-chrome lock-in
      'giljo-internal/no-vuetify-dialog-chrome': 'error',
      // FE-3007c: a missing api endpoint must crash in dev, not silently no-op
      'giljo-internal/no-optional-call-on-api': 'error',
      // Hygiene rules — warn level
      'giljo-internal/no-orphaned-exports': 'warn',
      'giljo-internal/no-stale-todos': 'warn',
      'giljo-internal/no-scattered-mode-checks': 'warn',
    },
    plugins: {
      'giljo-internal': giljoInternal,
    },
  },
  {
    files: ['src/**/*.vue'],
    languageOptions: {
      parser: vueParser,
      parserOptions: {
        parser: '@babel/eslint-parser',
        requireConfigFile: false,
        sourceType: 'module',
        ecmaVersion: 2022,
        extraFileExtensions: ['.vue'],
        ecmaFeatures: {
          jsx: true,
          typescript: true,
        },
      },
      globals: {
        ...globals.browser,
        ...globals.node,
        ...globals.vitest,
      },
    },
    rules: {
      ...pluginVue.configs['recommended'].rules,
      'vue/multi-word-component-names': 'off',
      'vue/no-v-html': 'error',
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'no-debugger': 'error',
      'no-unused-vars': [
        'warn',
        {
          argsIgnorePattern: '^_|^e$|^err$|^error$|^props$|^emit$',
          varsIgnorePattern: '^_|^err|^e$|^error$|^props$|^emit$|^theme$',
        },
      ],
      'prefer-const': 'error',
      'prefer-template': 'error',
      'prefer-arrow-callback': 'error',
      'no-var': 'error',
      'giljo-internal/no-manual-api-url-composition': 'error',
      'giljo-internal/no-vite-ignore-saas-import': 'error',
      'giljo-internal/vue-router-install-after-routes': 'error',
      'giljo-internal/axios-interceptor-route-meta-aware': 'error',
      'giljo-internal/no-speculative-layout-fallback': 'error',
      // FE-6006 unit 2: dialog-chrome lock-in
      'giljo-internal/no-vuetify-dialog-chrome': 'error',
      // FE-3007c: a missing api endpoint must crash in dev, not silently no-op
      'giljo-internal/no-optional-call-on-api': 'error',
      'giljo-internal/no-orphaned-exports': 'warn',
      'giljo-internal/no-stale-todos': 'warn',
      'giljo-internal/no-scattered-mode-checks': 'warn',
    },
    plugins: {
      vue: pluginVue,
      'giljo-internal': giljoInternal,
    },
  },
  {
    // SEC-0003: these files intentionally use v-html and are audited to route
    // every value through the hardened useSanitizeMarkdown / sanitizeHtml
    // pipeline (see per-site justification comments in each file). The
    // vue/no-v-html rule is disabled here rather than via inline
    // `<!-- eslint-disable-next-line -->` comments because eslint-plugin-vue
    // v9.20 under ESLint flat config does not honour HTML-comment directives
    // (fixed in eslint-plugin-vue >=9.25). Keep this list MINIMAL -- any new
    // v-html site requires a separate reviewed entry.
    files: [
      'src/components/DatabaseConnection.vue',
      'src/components/hub/ThreadTimeline.vue',
      'src/components/memory/MemoryEntryRow.vue',
      'src/components/messages/BroadcastPanel.vue',
      'src/components/messages/MessageItem.vue',
      'src/views/UserGuideView.vue',
    ],
    rules: {
      'vue/no-v-html': 'off',
    },
  },
  {
    files: ['src/**/*.spec.js', 'src/__tests__/**/*.js'],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
        ...globals.vitest,
      },
    },
  },
]
