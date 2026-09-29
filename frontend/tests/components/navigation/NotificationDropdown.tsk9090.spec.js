/**
 * Vitest spec — TSK-9090: notification bell deep-links project.* notifications
 * that carry project context in `payload.project_id` (not just legacy
 * `metadata.project_id`).
 *
 * BE-9085's project.pre_launch_workproduct notification stores project_id in its
 * validated `payload`. The bell previously only deep-linked rows with
 * `metadata.project_id`, so clicking a payload-only project notification did
 * nothing and it wasn't marked navigable. This verifies the generalized
 * `projectIdOf()` path: payload.project_id rows are navigable AND route to the
 * specific project, while legacy metadata.project_id rows keep working.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import NotificationDropdown from '@/components/navigation/NotificationDropdown.vue'

// ── Router mock — stable push spy so we can assert navigation args ────────────
const { pushSpy } = vi.hoisted(() => ({ pushSpy: vi.fn() }))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushSpy }),
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

// ── Fixtures ─────────────────────────────────────────────────────────────────
// BE-9085-style row: project_id lives in `payload`, no `metadata`, and the type
// is NOT in TYPE_ROUTE_MAP — so it deep-links only via the projectIdOf fallback.
const PAYLOAD_PROJECT_NOTIF = {
  id: 'notif-payload',
  type: 'project.pre_launch_workproduct',
  severity: 'warning',
  title: 'Project closed out without a launch approval',
  body: 'Verify manually',
  read: false,
  read_at: null,
  dismissed_at: null,
  created_at: '2026-07-08T00:00:00Z',
  timestamp: '2026-07-08T00:00:00Z',
  payload: { project_id: 'proj-payload-123', project_name: 'X', commit_count: 3 },
}

// Legacy Handover-0259 row: project_id in `metadata` (must still work).
const METADATA_PROJECT_NOTIF = {
  id: 'notif-metadata',
  type: 'some.legacy_project_notif',
  severity: 'info',
  title: 'Legacy project notice',
  body: '',
  read: false,
  read_at: null,
  dismissed_at: null,
  created_at: '2026-07-08T00:00:00Z',
  timestamp: '2026-07-08T00:00:00Z',
  metadata: { project_id: 'proj-metadata-456' },
}

function mountDropdown(initialNotifications) {
  return mount(NotificationDropdown, {
    global: {
      plugins: [
        createTestingPinia({
          createSpy: vi.fn,
          initialState: {
            notifications: { notifications: initialNotifications },
          },
        }),
      ],
    },
  })
}

describe('NotificationDropdown — TSK-9090: payload.project_id deep-link', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('marks a payload.project_id notification as navigable', () => {
    const wrapper = mountDropdown([PAYLOAD_PROJECT_NOTIF])
    const row = wrapper.find('.v-list-item')
    expect(row.classes()).toContain('notification-navigable')
  })

  it('clicking a payload.project_id notification routes to that specific project', async () => {
    const wrapper = mountDropdown([PAYLOAD_PROJECT_NOTIF])
    await wrapper.find('.v-list-item').trigger('click')
    // FE-9191: pre_launch_workproduct is a closeout-family notification, so it
    // now lands on the jobs tab (where the closeout pill and review live).
    // FE-9681: the project page is retired; it lands on the board card with
    // Jobs detail open (where the closeout status area lives).
    expect(pushSpy).toHaveBeenCalledWith({
      name: 'JobsViewport',
      query: { project: 'proj-payload-123', detail: '1' },
    })
  })

  it('still deep-links a legacy metadata.project_id notification (no regression)', async () => {
    const wrapper = mountDropdown([METADATA_PROJECT_NOTIF])
    await wrapper.find('.v-list-item').trigger('click')
    expect(pushSpy).toHaveBeenCalledWith({
      name: 'JobsViewport',
      query: { project: 'proj-metadata-456' },
    })
  })
})
