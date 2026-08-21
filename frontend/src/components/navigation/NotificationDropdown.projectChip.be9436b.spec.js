/**
 * NotificationDropdown.projectChip.be9436b.spec.js — BE-9436b (frontend follow-through)
 *
 * The project chip on a notification row was gated on `notification.metadata?.project_name`,
 * but `metadata` is not a field on the server's `NotificationResponse` at all — it carries
 * `payload`. So the chip, and the project branch of the ARIA label, were dead for every
 * server-sourced row and fired only for the legacy in-memory shape. FE-9436 had already
 * wired the chip's NAVIGATION to `payload` (`projectRouteFor` reads `payload.project_id`);
 * only the name lookup was left behind. BE-9436b supplies `payload.project_name`, and this
 * spec is the proof the chip now reads it.
 *
 * WHY THIS MOUNTS THE REAL COMPONENT: the defect lived in a TEMPLATE BINDING — a `v-if`
 * naming the wrong field — which is exactly the class of bug a helper-level unit test
 * cannot see (FE-9419 shipped a prop that never bound, invisible to its own child spec).
 * Asserting `getProjectName()` in isolation would pass against the old template. So the
 * assertions below are on RENDERED OUTPUT.
 *
 * `v-menu` IS stubbed, and that is not the same compromise: Vuetify teleports menu content
 * out of the wrapper, and the stub only renders the slots inline. Every binding under test
 * — the `v-if`, the chip text, the `aria-label` — is still NotificationDropdown's own
 * template being evaluated for real.
 *
 * Edition scope: Both
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

import NotificationDropdown from './NotificationDropdown.vue'
import { useNotificationStore } from '@/stores/notifications'

// Renders both slots inline so the menu's content is inside the wrapper rather than
// teleported to document.body. Nothing under test is stubbed away by this.
const VMenuStub = {
  name: 'VMenu',
  template: '<div><slot name="activator" :props="{}" /><slot /></div>',
}

const PROJECT_NAME = 'Ledger reconciliation'

const serverRow = (overrides = {}) => ({
  id: 'n-1',
  type: 'closeout.approval_required',
  severity: 'warning',
  title: `${PROJECT_NAME}: closeout requires approval`,
  body: `${PROJECT_NAME}: 1 deferred finding(s) awaiting a user decision`,
  payload: { project_id: 'p-1', approval_id: 'a-1', reason_count: 1, project_name: PROJECT_NAME },
  surface: 'both',
  created_at: '2026-08-15T00:00:00Z',
  read_at: null,
  dismissed_at: null,
  resolved_at: null,
  dismissible: true,
  ...overrides,
})

/**
 * Mount first, THEN seed — deliberately, and it cost a debugging round to learn why.
 *
 * `tests/setup.js` installs ONE module-level pinia via `config.global.plugins`, and
 * `app.use(pinia)` is what makes it the active one. Seeding a store obtained before
 * mount therefore populates a *different* pinia than the component reads, and the
 * component renders its empty state while the seeded rows sit unread — four failures
 * that look like the chip is broken and are nothing of the kind. Passing an own pinia
 * "fixes" it only by double-providing over the global one, which Vue warns about.
 *
 * So: mount (activating the shared pinia), let the on-mount fetch settle, then seed.
 */
async function mountWith(rows) {
  const wrapper = mount(NotificationDropdown, {
    global: { stubs: { VMenu: VMenuStub } },
  })
  await flushPromises()

  const store = useNotificationStore()
  vi.spyOn(store, 'fetch').mockResolvedValue(undefined)
  store.notifications = rows
  await nextTick()
  return wrapper
}

describe('NotificationDropdown — project chip reads payload.project_name (BE-9436b)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    // No store access here: the shared pinia is not active until a mount runs
    // `app.use(pinia)`, so touching a store in beforeEach throws "no active Pinia"
    // and every test fails before it reaches an assertion. Each test's `mountWith`
    // ASSIGNS the full row array, so no test can inherit another's fixture anyway.
  })

  it('renders the chip for a SERVER row, which carries the name in payload', async () => {
    // RED against the old template: the v-if read metadata, which server rows never have.
    const wrapper = await mountWith([serverRow()])
    const chip = wrapper.find('.notification-project-chip')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain(PROJECT_NAME)
  })

  it('puts the project name in the row ARIA label for a server row', async () => {
    const wrapper = await mountWith([serverRow()])
    const item = wrapper.find('.notification-item')
    expect(item.attributes('aria-label')).toContain(`Click to view project ${PROJECT_NAME}`)
  })

  it('still renders the chip for a LEGACY in-memory row (metadata fallback kept)', async () => {
    // The fallback is not decoration: dropping it would break rows the store still
    // produces from the in-memory shape, trading one dead path for another.
    const legacy = serverRow({ payload: null, metadata: { project_name: 'Legacy project' } })
    const wrapper = await mountWith([legacy])
    expect(wrapper.find('.notification-project-chip').text()).toContain('Legacy project')
  })

  it('renders NO chip when neither source names a project', async () => {
    // The guard that keeps this from becoming "always show a chip": an unnamed row —
    // every approval row written before BE-9436b — must render exactly as it does today.
    const unnamed = serverRow({
      payload: { project_id: 'p-1', approval_id: 'a-1', reason_count: 1 },
    })
    const wrapper = await mountWith([unnamed])
    expect(wrapper.find('.notification-project-chip').exists()).toBe(false)
    expect(wrapper.find('.notification-item').attributes('aria-label')).not.toContain('view project')
  })
})
