import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('@/services/api', () => ({
  default: {
    apiKeys: {
      getActive: vi.fn().mockResolvedValue({ data: [] }),
      create: vi.fn().mockResolvedValue({ data: { api_key: 'gk_test' } }),
    },
  },
}))
vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({
      api: { host: 'localhost', port: '7272', protocol: 'http' },
      giljo_mode: 'saas',
    }),
  },
}))
vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn().mockResolvedValue(true) }),
}))
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

const globalStubs = {
  'v-text-field': { template: '<input />', props: ['modelValue'] },
  'v-icon': { template: '<i class="v-icon-stub"><slot /></i>' },
  'v-btn': { template: '<button><slot /></button>' },
  'v-progress-circular': { template: '<span />' },
  'v-alert': { template: '<div><slot /></div>' },
  'v-expand-transition': { template: '<div><slot /></div>' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
}

async function render(props) {
  const ConnectToolCard = (await import('@/components/setup/ConnectToolCard.vue')).default
  const wrapper = mount(ConnectToolCard, { props, global: { stubs: globalStubs } })
  await flushPromises()
  return wrapper
}

beforeEach(() => vi.clearAllMocks())

describe.each([
  ['claude', 'Claude', 'https://claude.ai/directory/giljo-hq', 'Open Settings, then Customize'],
  ['chatgpt', 'ChatGPT', 'https://chatgpt.com/plugins/plugin_asdk_app_6ad81df7a0608191a87c20051d37ffdf', 'Open Settings, then Plugins'],
])('ConnectToolCard directory method: %s', (toolId, label, url, firstStep) => {
  it('shows the header copy, the badge and the external primary button', async () => {
    const w = await render({ toolId })
    expect(w.text()).toContain(`Giljo HQ is in the ${label} directory. Connect from there, then sign in once.`)
    expect(w.find('[data-testid="directory-badge"]').text()).toBe('Sign-in, no key')
    const a = w.find('[data-testid="directory-open-btn"]')
    expect(a.text()).toBe(`Open in ${label} directory`)
    expect(a.attributes('href')).toBe(url)
    expect(a.attributes('target')).toBe('_blank')
    expect(a.attributes('rel')).toContain('noopener')
  })

  it('has a collapsed desktop fold-out with three steps', async () => {
    const w = await render({ toolId })
    const fold = w.find('[data-testid="directory-desktop-fold"]')
    expect(fold.exists()).toBe(true)
    expect(fold.element.tagName).toBe('DETAILS')
    expect(fold.attributes('open')).toBeUndefined()
    expect(fold.find('summary').text()).toBe(`On the ${label} desktop app`)
    const steps = fold.findAll('li')
    expect(steps).toHaveLength(3)
    expect(steps[0].text()).toBe(firstStep)
  })

  it('has no command block, no key flow, no fallback toggle', async () => {
    const w = await render({ toolId })
    expect(w.find('pre.config-code').exists()).toBe(false)
    expect(w.find('[data-testid="oauth-section"]').exists()).toBe(false)
    expect(w.find('[data-testid="web-endpoint-block"]').exists()).toBe(false)
    expect(w.find('[data-testid="fallback-toggle"]').exists()).toBe(false)
    expect(w.text()).not.toContain('Generate API Key')
    expect(w.text()).not.toContain('Paste')
  })

  it('keeps the Connected line: waiting, then connected', async () => {
    const waiting = await render({ toolId })
    expect(waiting.text()).toContain(`Waiting for ${label} to connect`)
    const done = await render({ toolId, connected: true, connectedNext: 'next' })
    expect(done.text()).toContain(`${label} connected.`)
  })
})
