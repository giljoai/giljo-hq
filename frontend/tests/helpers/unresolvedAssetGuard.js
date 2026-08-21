/**
 * unresolvedAssetGuard.js — FE-9397 (components) + FE-9403 (directives)
 *
 * Turns Vue's "Failed to resolve component" and "Failed to resolve directive"
 * warnings into test failures.
 *
 * "Asset" is Vue's own word for the pair: both messages come out of the same
 * `resolveAsset` in runtime-core, which is why one guard covers both. (This file
 * was `unresolvedComponentGuard.js` until FE-9403 widened it; the old name
 * described half the job.)
 *
 * WHY THIS EXISTS
 *
 * tests/setup.js mocks the `vuetify` module, so `createVuetify()` returns a
 * no-op `install` and NOTHING Vuetify registers a component. What makes
 * `<v-card>` work under test is not Vuetify — it is the hand-written kebab-case
 * map in `config.global.stubs`, because Vue Test Utils pre-registers a
 * placeholder component for every key present in that map. The effective
 * resolution rule for this whole tier is therefore "is the tag one of the
 * strings someone typed into tests/setup.js?", and a Vuetify tag that nobody
 * added simply does not resolve. Directives resolve the same way, from
 * `config.global.directives`.
 *
 * Vue reports both as a `console.warn`, and until FE-9397 nothing treated either
 * as fatal — so a control could be absent from the test DOM for as long as it
 * liked behind a green suite.
 *
 * THE TWO HALVES FAIL DIFFERENTLY, AND THE DIRECTIVE HALF IS THE QUIETER ONE
 *
 * An unresolved COMPONENT does NOT render nothing. It degrades to a native
 * unknown element:
 *
 *     <v-btn-toggle modelvalue="a" class="the-toggle">
 *       <button class="v-btn" value="a">Alpha</button>
 *     </v-btn-toggle>
 *
 * The tag renders, `class` survives, and default-slot children still render —
 * so `find('.the-toggle').exists()` is `true` and a text assertion still
 * passes. What silently disappears is everything the component itself
 * contributes: props become dead lowercased attributes with no reactivity
 * (`modelvalue="a"` — `v-model` does nothing), events never fire, named and
 * scoped slots never execute, internally-generated DOM never appears, and none
 * of Vuetify's own classes are added. That is why the failure is so quiet: the
 * corpse keeps the right shape.
 *
 * An unresolved DIRECTIVE (FE-9403) has no corpse at all. It simply never runs.
 * There is no inert element, no surviving class, no slot children — nothing in
 * the DOM records that the directive was ever asked for. Everything it was
 * responsible for is absent, and the element around it looks perfectly normal.
 *
 * One consequence worth knowing before you read a warning as evidence: Vue's
 * compiler hoists `resolveDirective(...)` into the render-function prologue, so
 * the warning fires whenever the *template* renders — even if the element
 * carrying the directive is behind a false `v-if` or stubbed away and never
 * rendered at all. A warning proves the template was rendered, not that the
 * directive-bearing element was.
 *
 * WHY A DEFERRED THROW AND NOT A THROW INSIDE THE HANDLER
 *
 * Vue invokes `app.config.warnHandler` through `callWithErrorHandling`, so an
 * exception raised inside the handler is swallowed into the app error handler
 * instead of propagating. Throwing there yields a guard that looks installed
 * and silently is not — the exact defect class this file exists to close. The
 * handler therefore only records, and `assertNone()` (wired to a global
 * `afterEach` in tests/setup.js) does the throwing, which vitest reports
 * reliably as a test failure.
 *
 * WHAT THIS GUARD DELIBERATELY DOES NOT DO (FE-9403, decided with data)
 *
 * It does not make every Vue warning fatal. That option was measured: 24 of 396
 * spec files warn about something today, and almost all of it is harness
 * artifact (`injection not found` from mounting a child without its provider;
 * `Extraneous non-props attributes` caused by the flat stubs in tests/setup.js
 * declaring no props) rather than product signal. Worse, the single loudest
 * warning in the suite — ~974 `App already provides property with key
 * "Symbol(pinia)"` — never reaches `warnHandler` at all, because VTU installs
 * plugins before applying `global.config`. A blanket "all warnings are fatal"
 * policy would therefore have been structurally blind to its own biggest
 * category while reddening two dozen files for reasons no user would care
 * about.
 *
 * The line drawn here is absence vs degradation: a resolution failure means the
 * thing under test IS NOT THERE, so every assertion aimed at it may be lying. A
 * prop-type warning means it is there and something about it is off — the
 * assertion is still testing something real. Only the first kind is fatal.
 *
 * ONE CORRECTION TO THE PARAGRAPH ABOVE (FE-9427)
 *
 * The measurement and the absence-vs-degradation line both stand. What was
 * wrong was placing the ROUTER injections on the degradation side: `useRouter()`
 * with no router installed returns `undefined`, not a degraded router, so by
 * this file's own rule they belong on the fatal side. FE-9427 measured 148 of
 * them across 17 spec/component pairs and found the navigation path of six
 * components entirely inert — not asserted-and-lying, but never exercised at
 * all. They are now fatal, in a sibling guard scoped to exactly those two keys:
 * tests/helpers/routerInjectionGuard.js. Every OTHER `injection not found`
 * keeps the behaviour this header describes, and the rejection of a blanket
 * "all warnings are fatal" policy is unchanged.
 *
 * IF THIS GUARD FIRES ON YOUR SPEC
 *
 * It is telling you something is missing from your test DOM. Register it:
 * a component goes in `config.global.stubs` in tests/setup.js (or a
 * `global.stubs` entry for that one mount); a directive goes in
 * `config.global.directives`. Do not delete the guard, and do not reach for
 * `withRealVuetify()` (tests/helpers/realVuetify.js) unless you specifically
 * need real slot behaviour; that helper solves a different problem.
 */

const RESOLUTION_FAILURE = /Failed to resolve (component|directive):\s*([^\s\n]+)/

const FIX_ADVICE = {
  component: 'add it to `config.global.stubs` in tests/setup.js, or pass it via\n`global.stubs` for this mount.',
  directive: 'add it to `config.global.directives` in tests/setup.js, or pass it\nvia `global.directives` for this mount.',
}

function buildMessage(entries) {
  const lines = ['FE-9397/FE-9403: Vue could not resolve the following.', '']

  for (const kind of ['component', 'directive']) {
    const names = entries.filter((e) => e.kind === kind).map((e) => e.name)
    if (names.length === 0) continue
    const label = names.length === 1 ? kind : `${kind}s`
    lines.push(`Unresolved ${label}: ${names.join(', ')}`)
    lines.push(`  Fix: ${FIX_ADVICE[kind]}`)
    lines.push('')
  }

  lines.push(
    'An unresolved component does not render nothing — it renders as an inert',
    'unknown element, so default-slot children and classes survive while props,',
    'events, and the component\'s own DOM do not. An unresolved directive leaves',
    'nothing behind at all: it simply never runs. Either way assertions can keep',
    'passing while the thing they target is effectively absent, which is why this',
    'is a failure rather than a console warning.',
  )

  return lines.join('\n')
}

export function createUnresolvedAssetGuard() {
  // Keyed by kind + name so a component and a directive sharing a name are
  // reported as the two distinct problems they are.
  const seen = new Map()

  function warnHandler(msg, _instance, trace) {
    const match = RESOLUTION_FAILURE.exec(msg)
    if (match) {
      const [, kind, name] = match
      seen.set(`${kind} ${name}`, { kind, name })
      return
    }
    // Every other Vue warning keeps its existing behaviour — this guard is
    // scoped to resolution failures and must not swallow anything else.
    console.warn(`[Vue warn]: ${msg}${trace ? `\n${trace}` : ''}`)
  }

  function drainEntries() {
    const entries = [...seen.values()].sort(
      (a, b) => a.name.localeCompare(b.name) || a.kind.localeCompare(b.kind),
    )
    seen.clear()
    return entries
  }

  /**
   * The unresolved names, sorted. Kept name-only (not kind-qualified) because
   * that is what a spec proving the guard end to end wants to assert on.
   */
  function drain() {
    return drainEntries().map((e) => e.name)
  }

  function assertNone() {
    const entries = drainEntries()
    if (entries.length === 0) return
    throw new Error(buildMessage(entries))
  }

  return { warnHandler, drain, drainEntries, assertNone }
}

/**
 * The instance tests/setup.js installs. Exported so a spec can prove the guard
 * works end-to-end (render a genuinely unresolvable tag or directive, then drain
 * this same instance) without the global `afterEach` also firing on the way out.
 */
export const unresolvedAssetGuard = createUnresolvedAssetGuard()
