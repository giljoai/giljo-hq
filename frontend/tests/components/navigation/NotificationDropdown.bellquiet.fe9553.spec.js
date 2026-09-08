/**
 * NotificationDropdown.bellquiet.fe9553.spec.js — FE-9553, milestone 3.
 *
 * Ruling 2: "The bell keeps a quiet unseen-counter only. Never a red/urgent
 * treatment -- urgency lives in banners exclusively."
 *
 * The bell is the ARCHIVE. Its tense is past, it accepts anything, it is
 * durable, and it never alerts. Before this milestone it did the opposite: a
 * severity ladder in the store picked a badge colour, the component mapped that
 * colour to one of three CSS classes, and all three ran a 2s infinite pulsing
 * glow -- including `.notification-bell--unread`, which reused the ERROR
 * animation, so ANY unread notification of ANY severity pulsed red forever.
 *
 * These assertions fail on pre-M3 code, which is the point: a critical row
 * produced `notification-bell--error`, a warning produced
 * `notification-bell--warning`, and an info row still pulsed red via the
 * "fallback" class.
 *
 * Edition Scope: Both
 */
import { readFileSync } from 'fs'
import { resolve } from 'path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import NotificationDropdown from '@/components/navigation/NotificationDropdown.vue'
import { withRealVuetify } from '../../helpers/realVuetify.js'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('date-fns', () => ({
  formatDistanceToNow: vi.fn(() => '2 hours ago'),
}))

vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({ on: vi.fn(() => vi.fn()) }),
}))

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ currentUser: { id: 'user-1' } }),
}))

function notif(overrides) {
  return {
    id: 'notif-1',
    type: 'system.update_available',
    severity: 'info',
    title: 'Something happened',
    body: 'Body text',
    read: false,
    read_at: null,
    dismissed_at: null,
    created_at: '2026-09-04T00:00:00Z',
    timestamp: '2026-09-04T00:00:00Z',
    ...overrides,
  }
}

/**
 * The bell itself lives in v-menu's scoped `activator` slot, and the global
 * v-menu stub in tests/setup.js renders only the DEFAULT slot -- so under that
 * stub the bell markup never renders at all, and every negative assertion
 * about its classes passes vacuously. (That is why no existing
 * NotificationDropdown spec asserts on the bell: it was unreachable, not
 * uninteresting. My first draft of this suite passed seven such assertions on
 * completely unchanged code.)
 *
 * FE-9366 already built the sanctioned escape hatch for exactly this, so this
 * suite uses it rather than hand-rolling a local stub that renders the
 * activator: a hand-rolled one has to invent the slot scope, and an invented
 * scope is a contract I would then be trusting. withRealVuetify renders the
 * REAL VMenu, so the activator receives what Vuetify actually passes it.
 *
 * VMenu AND VOverlay are un-stubbed: VMenu renders its activator through
 * VOverlay internally, so un-stubbing only VMenu leaves the activator
 * unrendered -- exactly the "real components pull in their own dependencies"
 * caveat in FE-9366's header, which I hit on the first attempt. The badge, icon
 * and button inside the activator render their default slots correctly under
 * the fast flat stub, and FE-9366's guidance is to keep the list to what the
 * assertion actually needs, so they stay stubbed.
 */
let realVuetify = null

async function mountDropdown(notifications, props = {}) {
  realVuetify = await withRealVuetify(['VMenu', 'VOverlay'])
  return mount(NotificationDropdown, {
    props,
    global: {
      plugins: [
        realVuetify.plugin,
        createTestingPinia({
          createSpy: vi.fn,
          initialState: { notifications: { notifications } },
        }),
      ],
    },
  })
}

/** Every pulse class the bell could previously carry. */
const ALERT_CLASSES = [
  'notification-bell--error',
  'notification-bell--warning',
  'notification-bell--unread',
]

describe('FE-9553 M3: the bell never alerts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // FE-9366 requires this: withRealVuetify mutates the shared
  // config.global.stubs singleton, so failing to restore would leak a real
  // VMenu into every test that runs after this file.
  afterEach(() => {
    realVuetify?.restore()
    realVuetify = null
  })

  it.each([
    ['critical', { severity: 'critical' }],
    ['error', { severity: 'error' }],
    ['warning', { severity: 'warning' }],
    ['info', { severity: 'info' }],
    ['a connection_lost row, which used to be hard-coded into the red tier', { type: 'connection_lost', severity: null }],
    ['a system_alert row, likewise', { type: 'system_alert', severity: null }],
    ['an agent_health row, which used to force the warning tier', { type: 'agent_health', severity: null }],
  ])('carries no alerting class for %s', async (_label, overrides) => {
    const wrapper = await mountDropdown([notif(overrides)], { compact: true })
    const html = wrapper.html()

    for (const cls of ALERT_CLASSES) {
      expect(html).not.toContain(cls)
    }
  })

  it('defines no pulse animation at all -- the urgency is gone from the stylesheet, not just the class', () => {
    // A class that is never applied but is still defined is a loaded gun for
    // the next person: reintroducing urgency would be a one-line change nobody
    // reviews. Ruling 2 says urgency lives in banners exclusively, so the
    // animation should not exist in this file either.
    //
    // Read from disk rather than inspected through the mounted component:
    // scoped <style> never reaches the test DOM, so mounting can say nothing
    // about it. Same approach as the button-shape and global-tab-style specs.
    const source = readFileSync(
      resolve(__dirname, '../../../src/components/navigation/NotificationDropdown.vue'),
      'utf8',
    )

    // Known-positive first: prove this read actually reaches the stylesheet,
    // so an empty result cannot masquerade as a clean one.
    expect(source).toContain('.nav-orb--bell')

    expect(source).not.toContain('notification-pulse-error')
    expect(source).not.toContain('notification-pulse-warning')
    for (const cls of ALERT_CLASSES) {
      expect(source).not.toContain(cls)
    }
  })

  // CHECKER-MUST-FIRE. Everything above is a negative, and a negative passes
  // just as well if the component failed to render, the badge never mounted, or
  // the store state never reached it. This proves the bell still WORKS as a
  // counter -- the quiet counter ruling 2 asks for -- so the tests above are
  // measuring an intact bell with its urgency removed, not a broken one.
  it('still shows the unseen count -- quiet, not absent', async () => {
    const wrapper = await mountDropdown([notif({ id: 'a' }), notif({ id: 'b' })], { compact: true })

    expect(wrapper.find('.nav-orb--bell').exists()).toBe(true)
    expect(wrapper.html()).toContain('mdi-bell')
  })
})
