import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('@/components/common/BaseDialog.vue', () => ({
  default: {
    name: 'BaseDialog',
    props: ['modelValue', 'title', 'confirmLabel'],
    emits: ['confirm', 'cancel'],
    template:
      '<div v-if="modelValue" class="base-dialog-stub"><h3 data-testid="dialog-title">{{ title }}</h3><slot /><button data-testid="dialog-confirm" @click="$emit(\'confirm\')">{{ confirmLabel }}</button></div>',
  },
}))
vi.mock('@/composables/useFormatDate', () => ({
  useFormatDate: () => ({ formatDateTime: (d) => String(d) }),
}))
const showToast = vi.fn()
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast }) }))
vi.mock('@/services/api', () => ({
  default: {
    connectedApps: {
      list: vi.fn(),
      logOut: vi.fn().mockResolvedValue({}),
      logOutAll: vi.fn().mockResolvedValue({}),
    },
  },
}))

import api from '@/services/api'

const APPS = [
  {
    id: 'a1',
    client_id: 'dcr-1',
    client_name: 'Claude Desktop',
    connected_at: '2026-10-01T10:00:00Z',
    last_used_at: '2026-10-28T10:00:00Z',
    last_ip: '203.0.113.9',
    last_user_agent: 'claude/1',
    mcp_client_name: 'claude-ai',
    mcp_client_version: '1.2.3',
    last_product_name: 'Giljo HQ',
    recent_ips: ['203.0.113.9', '198.51.100.4'],
  },
  {
    id: 'a2',
    client_id: 'dcr-2',
    client_name: 'ChatGPT',
    connected_at: '2026-10-02T10:00:00Z',
    last_used_at: null,
    last_ip: null,
    last_user_agent: null,
    mcp_client_name: null,
    recent_ips: [],
  },
]

const stubs = {
  'v-icon': { template: '<i><slot /></i>' },
  'v-btn': {
    template: '<button v-bind="$attrs" @click="$emit(\'click\', $event)"><slot /></button>',
    emits: ['click'],
  },
  'v-card': { template: '<div><slot /></div>' },
  'v-card-text': { template: '<div><slot /></div>' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
  'v-alert': { template: '<div v-bind="$attrs"><slot /></div>' },
}

async function mountManager() {
  const Comp = (await import('@/components/ConnectedAppsManager.vue')).default
  const wrapper = mount(Comp, { global: { stubs } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  api.connectedApps.list.mockResolvedValue({ data: APPS })
})

describe('ConnectedAppsManager', () => {
  it('lists each app with its name, last address and other addresses', async () => {
    const wrapper = await mountManager()
    const rows = wrapper.findAll('[data-testid="connected-app-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0].find('[data-testid="connected-app-name"]').text()).toBe('Claude Desktop')
    expect(rows[0].find('[data-testid="connected-app-ip"]').text()).toBe('203.0.113.9')
    expect(rows[0].text()).toContain('198.51.100.4')
    expect(rows[0].find('[data-testid="connected-app-subtitle"]').text()).toBe('(claude-ai 1.2.3)')
    expect(rows[0].find('[data-testid="connected-app-product"]').text()).toBe('Last worked on Giljo HQ')
    expect(rows[1].find('[data-testid="connected-app-product"]').exists()).toBe(false)
    expect(rows[1].find('[data-testid="connected-app-ip"]').text()).toBe('No address recorded yet')
    expect(rows[1].text()).toContain('Last used never')
  })

  it('shows the empty state when nothing is signed in', async () => {
    api.connectedApps.list.mockResolvedValue({ data: [] })
    const wrapper = await mountManager()
    expect(wrapper.find('[data-testid="connected-apps-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="connected-apps-logout-all"]').exists()).toBe(false)
  })

  it('logs one app out after confirmation, then reloads the list', async () => {
    const wrapper = await mountManager()
    await wrapper.findAll('[data-testid="connected-app-logout"]')[0].trigger('click')
    expect(wrapper.find('[data-testid="dialog-title"]').text()).toBe('Log out Claude Desktop?')
    expect(api.connectedApps.logOut).not.toHaveBeenCalled()

    api.connectedApps.list.mockResolvedValue({ data: [APPS[1]] })
    await wrapper.find('[data-testid="dialog-confirm"]').trigger('click')
    await flushPromises()

    expect(api.connectedApps.logOut).toHaveBeenCalledWith('a1')
    expect(wrapper.findAll('[data-testid="connected-app-row"]')).toHaveLength(1)
  })

  it('logs every app out from the Log out all button', async () => {
    const wrapper = await mountManager()
    await wrapper.find('[data-testid="connected-apps-logout-all"]').trigger('click')
    expect(wrapper.find('[data-testid="dialog-title"]').text()).toBe('Log out all apps?')
    await wrapper.find('[data-testid="dialog-confirm"]').trigger('click')
    await flushPromises()
    expect(api.connectedApps.logOutAll).toHaveBeenCalledTimes(1)
  })

  it('stays quiet when the first load fails, but reports a failed log out', async () => {
    api.connectedApps.list.mockRejectedValueOnce({ response: { status: 500 } })
    const wrapper = await mountManager()
    expect(showToast).not.toHaveBeenCalled()

    api.connectedApps.list.mockResolvedValue({ data: APPS })
    await wrapper.vm.$nextTick()
    api.connectedApps.logOutAll.mockRejectedValueOnce(new Error('boom'))
    const fresh = await mountManager()
    await fresh.find('[data-testid="connected-apps-logout-all"]').trigger('click')
    await fresh.find('[data-testid="dialog-confirm"]').trigger('click')
    await flushPromises()
    expect(showToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
  })
})

describe('ConnectedAppsManager display names', () => {
  const builtin = (over) => ({
    ...APPS[1],
    id: 'b',
    client_id: 'giljo-mcp-default',
    client_name: 'Giljo HQ (built-in)',
    ...over,
  })

  async function titles(apps) {
    api.connectedApps.list.mockResolvedValue({ data: apps })
    const wrapper = await mountManager()
    return wrapper.findAll('[data-testid="connected-app-row"]').map((row) => ({
      name: row.find('[data-testid="connected-app-name"]').text(),
      sub: row.find('[data-testid="connected-app-subtitle"]').exists()
        ? row.find('[data-testid="connected-app-subtitle"]').text()
        : null,
    }))
  }

  it('CE shared client: names the app by its MCP clientInfo and version, registered name as secondary', async () => {
    const [row] = await titles([builtin({ mcp_client_name: 'claude-code', mcp_client_version: '2.1.0', last_user_agent: 'ua/1' })])
    expect(row).toEqual({ name: 'claude-code 2.1.0', sub: '(Giljo HQ (built-in))' })
  })

  it('CE shared client without clientInfo: falls back to the user agent, then to the client name', async () => {
    const [byAgent] = await titles([builtin({ last_user_agent: 'codex-cli/0.9' })])
    expect(byAgent.name).toBe('codex-cli/0.9')
    const [byName] = await titles([builtin({})])
    expect(byName).toEqual({ name: 'Giljo HQ (built-in)', sub: null })
  })

  it('registered (SaaS DCR / CIMD) client: the registered name leads, clientInfo is secondary', async () => {
    const [row] = await titles([
      { ...APPS[0], client_name: 'Claude.ai', mcp_client_name: 'claude-ai', mcp_client_version: '1.0' },
    ])
    expect(row).toEqual({ name: 'Claude.ai', sub: '(claude-ai 1.0)' })
  })

  it('the confirm dialog uses the same title as the row', async () => {
    api.connectedApps.list.mockResolvedValue({
      data: [builtin({ mcp_client_name: 'claude-code', mcp_client_version: '2.1.0' })],
    })
    const wrapper = await mountManager()
    await wrapper.find('[data-testid="connected-app-logout"]').trigger('click')
    expect(wrapper.find('[data-testid="dialog-title"]').text()).toBe('Log out claude-code 2.1.0?')
  })
})
