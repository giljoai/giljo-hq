/**
 * routerInjectionGuard.js — FE-9427
 *
 * Turns Vue's `injection "Symbol(router)" not found` and
 * `injection "Symbol(route location)" not found` warnings into test failures.
 *
 * WHY THIS EXISTS, AND WHY IT IS NARROWER THAN IT LOOKS
 *
 * `unresolvedAssetGuard.js` (FE-9397/FE-9403) draws its line at
 * ABSENCE vs DEGRADATION: a thing that failed to resolve IS NOT THERE, so every
 * assertion aimed at it may be lying, and only that kind is fatal. Its header
 * puts `injection not found` on the degradation side, as harness artifact.
 *
 * For the router specifically that classification is wrong on the guard's own
 * terms. `useRouter()` with no router installed does not return a degraded
 * router — it returns `undefined`. Every `router.push(...)` behind it is either
 * a TypeError the component swallows or a call site the test never reaches.
 * That is absence, which the sibling guard's own rule makes fatal.
 *
 * FE-9427 measured what that cost: 148 such warnings across 17 spec/component
 * pairs (LaunchTab, JobsTab via useJobActions, ProjectReviewModal, ProfilePage,
 * ProductForm, ProductsView), and in every one of them the component's entire
 * navigation path was inert. No assertion CHANGED when the router became real —
 * because no assertion reached the router at all. The tests were not lying about
 * what they asserted; they were silent about a whole behaviour, in specs that
 * read as though they covered it.
 *
 * SCOPE: exactly the two router keys, and nothing else about injection.
 *
 * This is deliberately not "all injections are fatal". Mounting a child without
 * its provider is a legitimate unit-testing move for many providers, and the
 * FE-9403 decision to reject a blanket policy stands. The two keys below are
 * singled out because vue-router is installed application-wide in production
 * (`main.js`), so a component that reaches for it can always have it — which
 * makes its absence under test a property of the test, never of the component.
 *
 * Measured on the way in: after FE-9427's conversion the whole suite emits zero
 * of these, so this guard reds nothing on arrival.
 *
 * WHY A DEFERRED THROW AND NOT A THROW INSIDE THE HANDLER
 *
 * Same reason as the sibling guard: Vue invokes `app.config.warnHandler` through
 * `callWithErrorHandling`, so an exception raised inside the handler is
 * swallowed into the app error handler instead of propagating. Throwing there
 * yields a guard that looks installed and silently is not. The handler only
 * records; tests/setup.js's global `afterEach` does the throwing.
 *
 * IF THIS GUARD FIRES ON YOUR SPEC
 *
 * Your component (or a composable it calls — `useJobActions` is the one that
 * catches people out, because the warning names the COMPONENT, not the
 * composable) uses `useRouter()`/`useRoute()` and your mount installed no
 * router. Install one, using the idiom every green spec here already uses:
 *
 *     import { createRouter, createMemoryHistory } from 'vue-router'
 *     const router = createRouter({
 *       history: createMemoryHistory(),
 *       routes: [{ path: '/tools', name: 'Tools', component: { template: '<div />' } }],
 *     })
 *     mount(Component, { global: { plugins: [vuetify, router] } })
 *
 * Declare the routes your component actually navigates to. Do NOT reach for a
 * catch-all (`/:pathMatch(.*)*`): it makes every destination match, so a
 * component that later pushes the wrong route still passes — which is the same
 * silent-pass shape this guard exists to remove.
 *
 * Mocking the `vue-router` MODULE (`vi.mock('vue-router', ...)`) is the other
 * legitimate answer and 60 specs in this tree already do it; those never warn,
 * so this guard never sees them.
 */

const ROUTER_INJECTION = /injection "(Symbol\((?:router|route location)\))" not found/

export function createRouterInjectionGuard() {
  const seen = new Set()

  /**
   * Record a warning. Returns true if it was ours (and therefore must not be
   * passed on to the sibling guard or to console.warn).
   */
  function record(msg) {
    const match = ROUTER_INJECTION.exec(String(msg))
    if (!match) return false
    seen.add(match[1])
    return true
  }

  function buildMessage(keys) {
    return [
      `FE-9427: a component was mounted without a router, so Vue could not resolve ${keys.join(' or ')}.`,
      '',
      '`useRouter()`/`useRoute()` returned `undefined` for this mount, which means',
      'every navigation path in the component under test is inert: a `router.push`',
      'either throws a TypeError the component swallows, or is simply never reached.',
      'Assertions can keep passing while the behaviour they imply does not run at all.',
      '',
      'Fix: install a real router in this mount —',
      "  const router = createRouter({ history: createMemoryHistory(), routes: [ ... ] })",
      '  mount(Component, { global: { plugins: [vuetify, router] } })',
      'declaring the routes your component actually navigates to (not a catch-all).',
      'Mocking the vue-router module for the whole spec is the other valid answer.',
      '',
      'Note: the warning names the COMPONENT, but the `useRouter()` call may live in',
      'a composable it calls from setup() — `useJobActions` is the usual culprit.',
    ].join('\n')
  }

  /**
   * Always drains. Returns the failure message, or null if nothing was seen.
   *
   * Returning rather than throwing lets tests/setup.js report this alongside an
   * unresolved-asset failure from the same test instead of one hiding the other,
   * and guarantees the recorded keys never leak into the next test.
   */
  function drainMessage() {
    if (seen.size === 0) return null
    const keys = [...seen].sort()
    seen.clear()
    return buildMessage(keys)
  }

  function assertNone() {
    const message = drainMessage()
    if (message) throw new Error(message)
  }

  return { record, drainMessage, assertNone }
}

/**
 * The instance tests/setup.js installs. Exported so a spec can prove the guard
 * works end to end against its own instance without the global `afterEach` also
 * firing on the way out.
 */
export const routerInjectionGuard = createRouterInjectionGuard()
