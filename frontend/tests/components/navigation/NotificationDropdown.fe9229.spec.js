/**
 * Vitest spec — FE-9229: the pre-launch notification persists in the BELL, and
 * long titles wrap instead of being clipped.
 *
 * Two regressions are pinned here, both at the layer the bug lived (the bell's
 * render surface):
 *
 * 1. SURFACE. project.pre_launch_workproduct used to be emitted with
 *    surface="banner". SystemStatusBanner renders only its ALLOWED_TYPES
 *    allowlist of singleton `system.*` state, so a `project.*` row was silently
 *    discarded there and the notification rendered on no surface it was
 *    addressed to. It stayed reachable in the bell only because the bell ignores
 *    `surface` entirely. The emitter now says surface="bell" (pinned backend-side
 *    in test_be9085_prelaunch_workproduct_detection.py); this spec pins the other
 *    half of the contract — the bell actually renders such a row, durably.
 *
 * 2. TITLE CLIPPING. Vuetify's .v-list-item-title defaults to
 *    `white-space: nowrap` + `text-overflow: ellipsis`, and the title column is
 *    only ~255px wide inside the 440px dropdown. The enriched taxonomy-led titles
 *    measured 911px against that box — ~72% of the title was invisible. The fix
 *    is the .notification-title class (wrap + smaller + bold). jsdom does no
 *    layout, so the browser-measurable part was verified live in the dev app;
 *    what is pinned here is what jsdom CAN prove: the full untruncated title text
 *    reaches the DOM, and it carries the class that owns the wrap rules.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import NotificationDropdown from '@/components/navigation/NotificationDropdown.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('date-fns', () => ({ formatDistanceToNow: vi.fn(() => '2 minutes ago') }))
vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({ on: vi.fn(() => vi.fn()) }),
}))
vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ currentUser: { id: 'user-1' } }),
}))

// A realistic enriched row: the taxonomy-led title is what overflows the
// ~255px title column, and surface is the value the detector now emits.
const LONG_TITLE =
  'FE-9229 — Pre-launch notification banner flashes without persisting anywhere visible: recorded without an Implement click'

const BELL_PRELAUNCH_NOTIF = {
  id: 'notif-fe9229',
  type: 'project.pre_launch_workproduct',
  severity: 'warning',
  surface: 'bell',
  title: LONG_TITLE,
  body: 'It was closed out with 3 commits recorded, but it never passed the in-app Implement click.',
  read: false,
  read_at: null,
  dismissed_at: null,
  resolved_at: null,
  created_at: '2026-07-18T00:00:00Z',
  timestamp: '2026-07-18T00:00:00Z',
  payload: { project_id: 'proj-fe9229', project_name: 'X', commit_count: 3 },
}

function mountDropdown(initialNotifications) {
  return mount(NotificationDropdown, {
    global: {
      plugins: [
        createTestingPinia({
          createSpy: vi.fn,
          initialState: { notifications: { notifications: initialNotifications } },
        }),
      ],
    },
  })
}

describe('NotificationDropdown — FE-9229: bell persistence + title wrap', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders a surface="bell" project.pre_launch_workproduct row in the dropdown', () => {
    const wrapper = mountDropdown([BELL_PRELAUNCH_NOTIF])

    const rows = wrapper.findAll('.notification-item')
    expect(rows).toHaveLength(1)
    expect(wrapper.find('.notification-empty').exists()).toBe(false)
  })

  it('renders the FULL title — no JS-side truncation of long titles', () => {
    const wrapper = mountDropdown([BELL_PRELAUNCH_NOTIF])

    const title = wrapper.find('.v-list-item-title')
    // The whole string, not an ellipsised prefix.
    expect(title.text()).toBe(LONG_TITLE)
    expect(title.text()).not.toContain('…')
  })

  it('gives the title the wrap class instead of the clipping Vuetify defaults', () => {
    const wrapper = mountDropdown([BELL_PRELAUNCH_NOTIF])

    const title = wrapper.find('.v-list-item-title')
    // .notification-title owns white-space:normal / overflow:visible /
    // text-overflow:clip + the smaller bold size. Losing this class silently
    // restores the nowrap+ellipsis clip that hid ~72% of the title.
    expect(title.classes()).toContain('notification-title')
    // The old classes did nothing for size (they are undefined no-ops) but did
    // mark the title as non-bold; both are gone.
    expect(title.classes()).not.toContain('font-weight-medium')
  })

  it('still shows the empty state when there are no notifications (two-sided)', () => {
    const wrapper = mountDropdown([])

    expect(wrapper.findAll('.notification-item')).toHaveLength(0)
    expect(wrapper.find('.notification-empty').exists()).toBe(true)
  })
})
