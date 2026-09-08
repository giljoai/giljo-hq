/**
 * FE-9553 — the signal router and the one-live-surface rule.
 *
 * The product had grown four notification surfaces with overlapping jobs. The
 * ruled model gives each exactly one job, keyed on WHO caused the event:
 *
 *   toast   past tense, the USER's own action, seconds      "your click worked"
 *   banner  present tense, the AGENTS' action, until handled  the only actionable surface
 *   popout  the banner, delivered when the app is hidden
 *   bell    past tense, anything, durable                     the archive, never alerts
 *
 * The binding rule: every event lives on exactly ONE live surface (toast XOR
 * banner). This suite pins the half of that rule that can be enforced at the
 * signal layer, and it is deliberately written to FAIL on pre-FE-9553 code:
 * there was no classifier at all, and every sink was wired independently, so a
 * single `thread_message` could land on five surfaces with nothing arbitrating.
 *
 * routeNotificationSignal is a FOURTH independent pass over the same raw WS
 * events, alongside routeGlobalActivityEvent (FE-9501b) and
 * routeProductActivityEvent (FE-9502d). Same reason those two are not just
 * another EVENT_MAP entry: it needs every event regardless of which project or
 * product is open, and it writes only to surface state.
 *
 * WHY THE TOAST ASSERTIONS MOCK useToast LOCALLY: frontend/tests/setup.js:636
 * mocks '@/composables/useToast' globally, returning a FRESH vi.fn() on every
 * useToast() call. A spec that asserts through that global mock is asserting on
 * a spy nothing ever called -- it passes whether or not the code under test
 * toasts. Every toast assertion here therefore installs its own hoisted shared
 * spy, so a regression that starts toasting an agent event fails HERE.
 *
 * Edition Scope: Both
 */
import { readdirSync, readFileSync } from 'fs'
import { join, relative, resolve } from 'path'

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const toastSpy = vi.hoisted(() => vi.fn())
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: toastSpy }),
}))

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ currentUser: { tenant_key: 'tk_1', id: 'user-1' } }),
}))

import {
  SIGNAL_ACTIONABLE,
  SIGNAL_ADVISORY,
  SIGNAL_LIFECYCLE,
  classifySignal,
  routeNotificationSignal,
} from '@/stores/notificationSignalRouter'

/** Every event type the router is expected to have an opinion about. */
const ACTIONABLE_CASES = [
  ['agent:status_changed', { user_approval_id: 'ap-1' }],
  ['agent:status_changed', { decided_option_id: 'opt-1' }],
  // DIRECTED: requires_action AND aimed at a participant. A broadcast is
  // deliberately absent from this list -- see the dedicated test below.
  ['thread_message', { requires_action: true, to_participant: 'user-1', thread_id: 'th-1' }],
]

const LIFECYCLE_CASES = [
  ['project:staging_complete', { project_id: 'p-1' }],
  ['project:implementation_launched', { project_id: 'p-1' }],
  ['project:launched', { project_id: 'p-1' }],
  ['agent:created', { project_id: 'p-1' }],
  ['agent:removed', { project_id: 'p-1' }],
  ['sequence:updated', { run_id: 'r-1' }],
]

const ADVISORY_CASES = [
  ['system:update_available', {}],
  ['agent:health_alert', { severity: 'critical' }],
  ['agent:silent', { job_id: 'j-1' }],
  ['agent:auto_failed', { job_id: 'j-1' }],
]

describe('classifySignal — the ruled surface assignment (FE-9553)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    toastSpy.mockClear()
  })

  it.each(ACTIONABLE_CASES)(
    'classifies %s as ACTIONABLE, and actionable always goes to the banner',
    (type, payload) => {
      const signal = classifySignal(type, payload)
      expect(signal.kind).toBe(SIGNAL_ACTIONABLE)
      expect(signal.surface).toBe('banner')
    },
  )

  it.each(LIFECYCLE_CASES)('classifies %s as LIFECYCLE', (type, payload) => {
    expect(classifySignal(type, payload).kind).toBe(SIGNAL_LIFECYCLE)
  })

  it.each(ADVISORY_CASES)('classifies %s as ADVISORY (bell, never the banner fold by default is a M4 pref -- here: never actionable)', (type, payload) => {
    const signal = classifySignal(type, payload)
    expect(signal.kind).toBe(SIGNAL_ADVISORY)
    expect(signal.kind).not.toBe(SIGNAL_ACTIONABLE)
  })

  it('a BROADCAST action-request is NOT actionable, only a directed one is (BE-9197)', () => {
    // FE-9586 aligned this. A broadcast requires_action post is "whoever picks
    // it up" and obligates nobody in particular, so it raises no actionable
    // signal -- it keeps its durable bell row and nothing else. The server's
    // directed-action query had always excluded broadcasts; the client's signal
    // gate contradicted that, and THIS classifier contradicted it for longer,
    // because I keyed on requires_action alone while the gate moved on.
    //
    // It was harmless only because nothing consulted the classifier on that
    // path yet. This test is what stops the disagreement coming back: the
    // classifier and getSignal now have to answer the same way.
    const broadcast = classifySignal('thread_message', { requires_action: true, thread_id: 'th-1' })
    expect(broadcast?.kind).not.toBe(SIGNAL_ACTIONABLE)

    const directed = classifySignal('thread_message', {
      requires_action: true,
      to_participant: 'user-1',
      thread_id: 'th-1',
    })
    expect(directed.kind).toBe(SIGNAL_ACTIONABLE)
  })

  it('a plain agent:status_changed with no approval fields is LIFECYCLE, not ACTIONABLE', () => {
    // The distinction the whole model rests on: the same event type is a
    // decision the system blocks on, or routine progress, depending on payload.
    expect(classifySignal('agent:status_changed', { job_id: 'j-1' }).kind).toBe(SIGNAL_LIFECYCLE)
  })

  it('never returns "toast" as a surface for ANY classified event type', () => {
    const every = [...ACTIONABLE_CASES, ...LIFECYCLE_CASES, ...ADVISORY_CASES]
    for (const [type, payload] of every) {
      expect(classifySignal(type, payload).surface).not.toBe('toast')
    }
  })

  it('returns null for an unknown event type rather than inventing a surface', () => {
    expect(classifySignal('totally:not:an:event', {})).toBeNull()
  })
})

describe('the one-live-surface rule: an agent-initiated event produces NO toast (FE-9553 DoD)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    toastSpy.mockClear()
  })

  it.each([...ACTIONABLE_CASES, ...LIFECYCLE_CASES, ...ADVISORY_CASES])(
    '%s routes without ever calling showToast',
    async (type, payload) => {
      await routeNotificationSignal({ type, data: payload })
      expect(toastSpy).not.toHaveBeenCalled()
    },
  )

  it('the router has no toast path at all -- not even for a critical advisory', async () => {
    await routeNotificationSignal({
      type: 'agent:health_alert',
      data: { severity: 'critical', job_id: 'j-1' },
    })
    expect(toastSpy).not.toHaveBeenCalled()
  })
})

describe('the one-live-surface rule: a user action produces NO banner (FE-9553 DoD)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    toastSpy.mockClear()
  })

  // The banner is present tense about the AGENTS' action. The only writer of
  // banner rows is lifecycleBannerStore.announce(), so "a user action produces
  // no banner" is really the claim that announce() is reachable ONLY from the
  // WebSocket ingress and never from a click path.
  //
  // This is asserted structurally rather than through a spy, because a spy on
  // a store nothing wired up cannot fail -- it would pass whether or not the
  // invariant held. The repo already pins invariants this way where the claim
  // is about module boundaries (see the url-composition grep tests).
  it('lifecycleBannerStore.announce is called only from the WS event routes, never from a click path', () => {
    const srcRoot = resolve(__dirname, '../../src')

    const callers = []
    const walk = (dir) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, entry.name)
        if (entry.isDirectory()) {
          walk(full)
          continue
        }
        if (!/\.(js|vue)$/.test(entry.name)) continue
        if (/\.spec\.js$/.test(entry.name)) continue
        // The store defines announce; it is not a caller of itself.
        if (entry.name === 'lifecycleBannerStore.js') continue

        const text = readFileSync(full, 'utf8')
        // Whole-token match: `announce(` would also hit `announceFoo(`, and a
        // substring match is a known trap here. Anchor on the call through the
        // store or the shared helper.
        if (/\bannounceLifecycleMoment\s*\(/.test(text) || /\.announce\s*\(/.test(text)) {
          callers.push(relative(srcRoot, full).replace(/\\/g, '/'))
        }
      }
    }
    walk(srcRoot)

    // Every caller must live under the WebSocket ingress. A component, a view
    // or a click-driven composable appearing here means a user action can now
    // raise a banner, which the model forbids.
    const offenders = callers.filter((p) => !p.startsWith('stores/eventRoutes/'))
    expect(offenders).toEqual([])

    // CHECKER-MUST-FIRE: if the walk found nothing at all, the filter above is
    // vacuously satisfied and this test proves nothing. The known-positive is
    // projectEventRoutes.js, the one legitimate caller.
    expect(callers).toContain('stores/eventRoutes/projectEventRoutes.js')
  })

  it('classifySignal has no mapping that yields a toast surface, for any input', () => {
    // Structural restatement of "toast XOR banner": this module can assign
    // banner or bell and nothing else, so no future event type can be routed
    // to a toast by classification.
    const surfaces = new Set()
    for (const [type, payload] of [...ACTIONABLE_CASES, ...LIFECYCLE_CASES, ...ADVISORY_CASES]) {
      surfaces.add(classifySignal(type, payload).surface)
    }
    expect([...surfaces].sort()).toEqual(['banner', 'bell'])
  })
})

describe('the router is tenant-scoped like its three sibling passes (FE-9553)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    toastSpy.mockClear()
  })

  it('drops a cross-tenant event', async () => {
    const routed = await routeNotificationSignal({
      type: 'project:staging_complete',
      data: { project_id: 'p-1', tenant_key: 'tk_someone_else' },
    })
    expect(routed).toBe(false)
  })

  it('routes an event carrying no tenant_key at all (same permissive default as defaultShouldRoute)', async () => {
    const routed = await routeNotificationSignal({
      type: 'project:staging_complete',
      data: { project_id: 'p-1' },
    })
    expect(routed).toBe(true)
  })
})
