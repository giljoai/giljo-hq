import { describe, it, expect, beforeEach, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

import NotificationDropdown from './NotificationDropdown.vue'
import { useNotificationStore } from '@/stores/notifications'

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
  })

  it('renders the chip for a SERVER row, which carries the name in payload', async () => {
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
    const legacy = serverRow({ payload: null, metadata: { project_name: 'Legacy project' } })
    const wrapper = await mountWith([legacy])
    expect(wrapper.find('.notification-project-chip').text()).toContain('Legacy project')
  })

  it('renders NO chip when neither source names a project', async () => {
    const unnamed = serverRow({
      payload: { project_id: 'p-1', approval_id: 'a-1', reason_count: 1 },
    })
    const wrapper = await mountWith([unnamed])
    expect(wrapper.find('.notification-project-chip').exists()).toBe(false)
    expect(wrapper.find('.notification-item').attributes('aria-label')).not.toContain('view project')
  })
})
