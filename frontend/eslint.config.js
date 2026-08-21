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
  // FE-9430: adopt eslint-plugin-vue's own flat/recommended. Before this, the
  // .vue block spread `configs['recommended'].rules`, which is an eslintrc-style
  // object carrying only its own 8-rule layer -- the essential and
  // strongly-recommended layers arrive via `extends`, and flat config does not
  // follow `extends`. So 8 of the plugin's 118 rules were running. Spreading the
  // flat array here activates all of them.
  ...pluginVue.configs['flat/recommended'],
  {
    // FE-9430: Prettier owns formatting in this repo (.prettierrc + `npm run
    // format`), so the plugin's layout rules stay off -- otherwise eslint and
    // prettier fight over the same lines forever. This is the plugin's own
    // documented overlay for that choice, not a local invention. Measured: it
    // is the difference between 5782 and 138 warnings, and without it `npm run
    // lint` (which runs --fix) would rewrite the indentation and attribute
    // layout of 181 files on its first run.
    name: 'giljo/vue-layout-rules-off',
    rules: { ...pluginVue.configs['no-layout-rules'].rules },
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
      'vue/multi-word-component-names': 'off',
      // flat/recommended ships this at 'warn'; this repo treats an unsanitized
      // v-html as a hard error (see the SEC-0003 allowlist block below).
      'vue/no-v-html': 'error',
      // FE-9419: A prop named in PascalCase is unreachable from a kebab-case
      // template binding — Vue camelizes the attribute and never produces a
      // leading capital — so the prop silently keeps its default forever. That
      // shipped once (NavAvatarMenu's account-status badge, invisible in SaaS)
      // and cost a warning nobody was reading. flat/recommended carries this
      // rule at 'warn'; the line below raises it to error, which is the point.
      'vue/prop-name-casing': ['error', 'camelCase'],
      // FE-9430: Vuetify 3 v-data-table addresses per-column slots by DOTTED
      // name (`v-slot:item.status`). vue-eslint-parser parses the dot as a
      // directive modifier, which v-slot genuinely does not support — so every
      // Vuetify data table in the app reports as invalid. allowModifiers is the
      // rule's own published option for exactly this; the rule stays at error
      // and keeps all its other checks. 36 sites across 6 files.
      'vue/valid-v-slot': ['error', { allowModifiers: true }],
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
    // `<!-- eslint-disable-next-line -->` comments. That was originally forced:
    // eslint-plugin-vue v9.20 under flat config did not honour HTML-comment
    // directives. FE-9430 note: it is no longer forced — the plugin is now
    // v10, and flat/recommended brings in `vue/comment-directive`, so template
    // HTML-comment directives DO work again. This file-level block is kept
    // deliberately: it is reviewable in one place. Keep this list MINIMAL --
    // any new v-html site requires a separate reviewed entry.
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
    // FE-9430: the product-creation form is one object owned by
    // ProductForm.vue and edited field-by-field by its five tab children, which
    // receive it as a `form` prop and bind `v-model="form.<field>"`. That is a
    // deliberate shared-form design, not a defect: no site here reassigns the
    // prop, the object identity never changes under the children, and the
    // parent reassigns the whole ref itself when vision analysis returns.
    // shallowOnly keeps the rule at ERROR for the case that genuinely breaks in
    // Vue -- reassigning the prop -- while not reporting the 27 nested-field
    // bindings. Scoped to these five files ON PURPOSE (same shape as the
    // SEC-0003 block above): every other component, including anything written
    // later, still gets the full rule. Narrowing it globally would silence the
    // pattern in code nobody has written yet.
    files: ['src/components/products/product-form/*.vue'],
    rules: {
      'vue/no-mutating-props': ['error', { shallowOnly: true }],
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
