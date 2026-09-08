/**
 * IMP-0013 Phase 4 — regression fixtures for the 8 custom ESLint rules.
 *
 * Each rule gets at least one "bad" sample that MUST trigger and at least
 * one "good" sample that MUST NOT trigger. Uses ESLint's RuleTester which
 * registers its own describe/it; we call it at the top level so vitest's
 * suite-collection phase sees the assertions.
 */
import { RuleTester } from 'eslint'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const plugin = require('../../eslint-rules/index.cjs')
const vueParser = require('vue-eslint-parser')

const ruleTester = new RuleTester({
  languageOptions: {
    ecmaVersion: 2022,
    sourceType: 'module',
  },
})

// Separate tester wired with vue-eslint-parser so template-body expressions
// (v-if="..." etc.) are inspected — exercises the no-scattered-mode-checks
// rule's defineTemplateBodyVisitor path (FE-9147).
const vueRuleTester = new RuleTester({
  languageOptions: {
    parser: vueParser,
    ecmaVersion: 2022,
    sourceType: 'module',
  },
})

// Prime the no-orphaned-exports cache with a deterministic set so the test
// is hermetic (no disk scan).
plugin.rules['no-orphaned-exports']._setCache(new Set(['Used']))

ruleTester.run(
  'giljo-internal/no-manual-api-url-composition',
  plugin.rules['no-manual-api-url-composition'],
  {
    valid: [
      { code: 'const u = getApiBaseUrl()' },
      { code: 'const u = `${origin}/api`' },
      {
        code:
          '// eslint-allow giljo-internal/no-manual-api-url-composition\nconst u = `${proto}://${host}:${port}`',
      },
    ],
    invalid: [
      {
        code: 'const u = `${proto}://${host}:${port}`',
        errors: [{ messageId: 'manual' }],
      },
    ],
  },
)

ruleTester.run(
  'giljo-internal/no-vite-ignore-saas-import',
  plugin.rules['no-vite-ignore-saas-import'],
  {
    valid: [
      { code: "const m = import('./foo.js')" },
      { code: "const all = import.meta.glob('./modules/*.js')" },
    ],
    invalid: [
      {
        code: "const m = import(/* @vite-ignore */ pathString)",
        errors: [{ messageId: 'viteIgnore' }],
      },
    ],
  },
)

ruleTester.run(
  'giljo-internal/vue-router-install-after-routes',
  plugin.rules['vue-router-install-after-routes'],
  {
    valid: [
      {
        code: "router.addRoute({ path: '/x', component: X });\napp.use(router);",
      },
      { code: 'app.use(somePinia)' },
    ],
    invalid: [
      {
        code: "app.use(router);\nrouter.addRoute({ path: '/x', component: X });",
        errors: [{ messageId: 'ordering' }],
      },
    ],
  },
)

ruleTester.run(
  'giljo-internal/axios-interceptor-route-meta-aware',
  plugin.rules['axios-interceptor-route-meta-aware'],
  {
    valid: [
      {
        code:
          "apiClient.interceptors.response.use(null, (error) => {\n" +
          "  if (error.config?.meta?.requiresAuth === false) return Promise.reject(error);\n" +
          "  router.push('/login');\n" +
          "});",
      },
      { code: "router.push('/login')" },
    ],
    invalid: [
      {
        code:
          "apiClient.interceptors.response.use(null, (error) => {\n" +
          "  router.push('/login');\n" +
          "});",
        errors: [{ messageId: 'missingGuard' }],
      },
    ],
  },
)

ruleTester.run(
  'giljo-internal/no-speculative-layout-fallback',
  plugin.rules['no-speculative-layout-fallback'],
  {
    valid: [
      { code: "const layout = route.name === undefined ? 'AuthLayout' : pick(route)" },
      { code: "const layout = route.name || 'AuthLayout'" },
    ],
    invalid: [
      {
        code: "const layout = route.name === undefined ? 'DashboardLayout' : pick(route)",
        errors: [{ messageId: 'sideEffectFallback' }],
      },
      {
        code: "const layout = route.name || 'DashboardLayout'",
        errors: [{ messageId: 'sideEffectFallback' }],
      },
    ],
  },
)

ruleTester.run(
  'giljo-internal/no-orphaned-exports',
  plugin.rules['no-orphaned-exports'],
  {
    valid: [{ code: 'export function Used() {}' }],
    invalid: [
      {
        code: 'export function Orphan() {}',
        errors: [{ messageId: 'orphan' }],
      },
    ],
  },
)

ruleTester.run('giljo-internal/no-stale-todos', plugin.rules['no-stale-todos'], {
  valid: [
    // Recent date, within 30 days of "now"
    {
      code: '// TODO 2026-05-10 fix later',
      options: [{ now: '2026-05-13' }],
    },
    // Has project id → ok regardless of age
    { code: '// TODO BE-5042 (2024-01-01) tracked elsewhere' },
  ],
  invalid: [
    {
      code: '// TODO 2025-01-01 fix this someday',
      options: [{ now: '2026-05-13' }],
      errors: [{ messageId: 'stale' }],
    },
    {
      code: '// FIXME totally unattributed',
      errors: [{ messageId: 'anonymous' }],
    },
  ],
})

ruleTester.run(
  'giljo-internal/no-scattered-mode-checks',
  plugin.rules['no-scattered-mode-checks'],
  {
    valid: [
      { code: 'if (isSaas()) doThing()' },
      // The centralized accessor composable is allowlisted (real module — the
      // rule dropped the nonexistent useEditionCapabilities in FE-9147).
      {
        code: "if (mode === 'saas') doThing()",
        filename: '/x/composables/useGiljoMode.js',
      },
      // Delegating to a predicate carries no string literal → not a violation.
      {
        code: 'if (isCeModeValue(giljoMode.value)) doThing()',
        filename: '/x/components/Foo.vue.js',
      },
      // Nullish-coalesced comparison `(status?.mode ?? 'ce') === 'ce'` is a
      // LogicalExpression on the left — deliberately OUT of scope (not one of
      // the 3 closed gaps), so it must NOT be flagged.
      {
        code: "if ((status?.mode ?? 'ce') === 'ce') doThing()",
        filename: '/x/components/Foo.vue.js',
      },
    ],
    invalid: [
      {
        code: "if (mode === 'saas') doThing()",
        filename: '/x/components/Foo.vue.js',
        errors: [{ messageId: 'scattered' }],
      },
      {
        code: "if (GILJO_MODE === 'demo') skip()",
        filename: '/x/services/foo.js',
        errors: [{ messageId: 'scattered' }],
      },
      // Gap 1 — `.value` ref access: property is `value`, object ends in `mode`.
      {
        code: "if (giljoMode.value === 'ce') doThing()",
        filename: '/x/components/Foo.vue.js',
        errors: [{ messageId: 'scattered' }],
      },
      // Gap 2 — optional chaining: `status?.mode` is a ChainExpression.
      {
        code: "if (status?.mode === 'ce') doThing()",
        filename: '/x/components/Foo.vue.js',
        errors: [{ messageId: 'scattered' }],
      },
    ],
  },
)

// Gap 3 — Vue template expressions (v-if="giljoMode === 'ce'"). Requires the
// vue parser so the rule's template-body visitor fires (FE-9147).
vueRuleTester.run(
  'giljo-internal/no-scattered-mode-checks (template)',
  plugin.rules['no-scattered-mode-checks'],
  {
    valid: [
      {
        code: '<template><div v-if="isCeEdition">x</div></template>',
        filename: '/x/components/Foo.vue',
      },
    ],
    invalid: [
      {
        code: "<template><div v-if=\"giljoMode === 'ce'\">x</div></template>",
        filename: '/x/components/Foo.vue',
        errors: [{ messageId: 'scattered' }],
      },
    ],
  },
)

// FE-6006 unit 2: dialog-chrome lock-in
// NOTE: RuleTester uses plain JS parser; test code uses template literals
// whose contents are scanned as raw text by the rule's Program() hook.
ruleTester.run(
  'giljo-internal/no-vuetify-dialog-chrome',
  plugin.rules['no-vuetify-dialog-chrome'],
  {
    valid: [
      // v-card-title on a non-dialog card — NOT flagged
      {
        code: 'const t = `<v-card><v-card-title>Panel Header</v-card-title></v-card>`',
      },
      // v-card-actions on a settings panel — NOT flagged
      {
        code: 'const t = `<v-card><v-card-actions><v-btn>Save</v-btn></v-card-actions></v-card>`',
      },
      // text-medium-emphasis outside a dialog — NOT flagged
      {
        code: 'const t = `<span class="text-medium-emphasis">helper text</span>`',
      },
      // Correct pattern: .dlg-header inside v-dialog — NOT flagged
      {
        code: 'const t = `<v-dialog><v-card class="smooth-border"><div class="dlg-header"><span class="dlg-title">Title</span></div></v-card></v-dialog>`',
      },
      // File-level allowlist suppresses all reports
      {
        code:
          '// eslint-allow giljo-internal/no-vuetify-dialog-chrome\n' +
          'const t = `<v-dialog><v-card><v-card-title>Old style</v-card-title></v-card></v-dialog>`',
      },
    ],
    invalid: [
      // v-card-title inside a v-dialog — must be flagged
      {
        code: 'const t = `<v-dialog v-model="open"><v-card><v-card-title>Bad Title</v-card-title></v-card></v-dialog>`',
        errors: [{ messageId: 'cardTitle' }],
      },
      // v-card-actions inside a v-dialog — must be flagged
      {
        code: 'const t = `<v-dialog v-model="open"><v-card><v-card-actions><v-btn>OK</v-btn></v-card-actions></v-card></v-dialog>`',
        errors: [{ messageId: 'cardActions' }],
      },
      // text-medium-emphasis inside a v-dialog — must be flagged
      {
        code: 'const t = `<v-dialog><v-card><v-card-text><span class="text-medium-emphasis">hint</span></v-card-text></v-card></v-dialog>`',
        errors: [{ messageId: 'textMediumEmphasis' }],
      },
      // Both title and actions in same dialog — two errors
      {
        code: 'const t = `<v-dialog><v-card><v-card-title>Title</v-card-title><v-card-actions><v-btn>OK</v-btn></v-card-actions></v-card></v-dialog>`',
        errors: [{ messageId: 'cardTitle' }, { messageId: 'cardActions' }],
      },
    ],
  },
)

// FE-9553: the one-live-surface rule at the toast choke point.
//
// `filename` is load-bearing in every case below: this rule keys entirely on
// WHERE the toast is raised, so the same line of code is a violation in the
// socket store and perfectly correct in a view. The valid cases are therefore
// as important as the invalid ones -- a rule that flagged everywhere would be
// worse than no rule, since 203 of the 219 toast call sites in this app are
// legitimate user feedback.
ruleTester.run(
  'giljo-internal/no-toast-for-agent-events',
  plugin.rules['no-toast-for-agent-events'],
  {
    valid: [
      // A view may toast: it is reachable from a click.
      {
        code: 'function onClick() { showToast({ message: "saved" }) }',
        filename: '/app/frontend/src/views/ProjectsView.vue',
      },
      // A composable reached from a click may toast.
      {
        code: 'function act() { showToast({ message: "done" }) }',
        filename: '/app/frontend/src/composables/useJobActions.js',
      },
      // An axios response interceptor may toast: the response exists BECAUSE
      // the user made a request. Deliberately out of scope -- an earlier draft
      // of this rule flagged the lapsed-subscription toast, which is textbook
      // feedback for the user's own blocked write.
      {
        code: 'function surface() { showToast({ message: "reactivate" }) }',
        filename: '/app/frontend/src/saas/composables/installLicenseStateInterceptor.js',
      },
      // Specs are exempt: they assert about toasts.
      {
        code: 'showToast({ message: "x" })',
        filename: '/app/frontend/src/stores/websocket.spec.js',
      },
      // Non-toast calls in a covered file are untouched.
      {
        code: 'function f() { addNotification({ type: "lifecycle" }) }',
        filename: '/app/frontend/src/stores/eventRoutes/projectEventRoutes.js',
      },
    ],
    invalid: [
      // The socket store: a frame arrives whether or not anyone clicked.
      {
        code: 'function handleDisconnect() { showToast({ message: "Connection Lost" }) }',
        filename: '/app/frontend/src/stores/websocket.js',
        errors: [{ messageId: 'agentToast' }],
      },
      // A WebSocket event route.
      {
        code: 'function onEvent() { showToast({ message: "agent finished" }) }',
        filename: '/app/frontend/src/stores/eventRoutes/agentEventRoutes.js',
        errors: [{ messageId: 'agentToast' }],
      },
      // The router passes.
      {
        code: 'function pass() { showToast({ message: "routed" }) }',
        filename: '/app/frontend/src/stores/websocketEventRouter.js',
        errors: [{ messageId: 'agentToast' }],
      },
      // Reached through a composable object rather than a bare identifier.
      {
        code: 'function f() { useToast().showToast({ message: "x" }) }',
        filename: '/app/frontend/src/stores/websocket.js',
        errors: [{ messageId: 'agentToast' }],
      },
      // The imperative global, which module-scope code uses when no composable
      // is available -- the escape hatch the rule must also cover, or the
      // invariant is one `window.$toast` away from being bypassed.
      {
        code: 'function f() { window.$toast.warning("x") }',
        filename: '/app/frontend/src/stores/websocket.js',
        errors: [{ messageId: 'agentToast' }],
      },
    ],
  },
)
