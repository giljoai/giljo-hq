import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'


const fetchConfig = vi.fn()
vi.mock('@/services/configService', () => ({
  default: { fetchConfig: (...a) => fetchConfig(...a) },
}))
vi.mock('@/services/api', () => ({
  default: {
    apiKeys: {
      getActive: vi.fn().mockResolvedValue({ data: [] }),
      create: vi.fn().mockResolvedValue({ data: { api_key: 'gk_test' } }),
    },
  },
}))
vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn().mockResolvedValue(true) }),
}))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

const globalStubs = {
  'v-text-field': { template: '<input class="v-text-field-stub" />', props: ['modelValue'] },
  'v-icon': { template: '<i class="v-icon-stub"><slot /></i>' },
  'v-btn': {
    template: '<button class="v-btn-stub" @click="$emit(\'click\', $event)"><slot /></button>',
    emits: ['click'],
  },
  'v-progress-circular': { template: '<span />' },
  'v-alert': { template: '<div><slot /></div>' },
  'v-expand-transition': { template: '<div><slot /></div>' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
  SetupStep2KeyFlow: { template: '<div data-test="key-flow-stub" />' },
  CertTrustModal: {
    props: ['modelValue'],
    template: '<div v-if="modelValue" data-test="cert-modal-open" />',
  },
}

const HTTP_API = { host: 'localhost', port: '7272', protocol: 'http', ssl_enabled: false }
const HTTPS_API = { host: 'giljo.example.com', port: 443, protocol: 'https', ssl_enabled: true }

let mountedWrappers = []
async function mountCard({ mode, api, toolId = 'claude_code' }) {
  fetchConfig.mockResolvedValue({ api, giljo_mode: mode })
  const ConnectToolCard = (await import('@/components/setup/ConnectToolCard.vue')).default
  const wrapper = mount(ConnectToolCard, {
    props: { toolId },
    global: { stubs: globalStubs },
  })
  mountedWrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  fetchConfig.mockReset()
})

afterEach(() => {
  mountedWrappers.forEach((w) => w.unmount())
  mountedWrappers = []
})

describe('ConnectToolCard — FE-9339 inline cert-trust link', () => {
  it('CE + https server URL: shows the link (the user who is about to hit the error)', async () => {
    const wrapper = await mountCard({ mode: 'ce', api: HTTPS_API })
    expect(wrapper.find('[data-testid="server-url-field"]').text()).toContain('https://')
    const link = wrapper.find('[data-testid="cert-trust-link"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toContain('Tool rejecting the connection?')
  })

  it('CE + http server URL (the localhost default): no link — there is no certificate problem', async () => {
    const wrapper = await mountCard({ mode: 'ce', api: HTTP_API })
    expect(wrapper.find('[data-testid="server-url-field"]').text()).not.toContain('https://')
    expect(wrapper.find('[data-testid="cert-trust-link"]').exists()).toBe(false)
  })

  it('SaaS + https: never renders — a hosted tenant has no server certificate to trust', async () => {
    const wrapper = await mountCard({ mode: 'saas', api: HTTPS_API })
    expect(wrapper.find('[data-testid="cert-trust-link"]').exists()).toBe(false)
  })

  it('SaaS + http: never renders', async () => {
    const wrapper = await mountCard({ mode: 'saas', api: HTTP_API })
    expect(wrapper.find('[data-testid="cert-trust-link"]').exists()).toBe(false)
  })

  it('clicking the link opens the shared CertTrustModal from inside the card', async () => {
    const wrapper = await mountCard({ mode: 'ce', api: HTTPS_API })
    expect(wrapper.find('[data-test="cert-modal-open"]').exists()).toBe(false)

    await wrapper.find('[data-testid="cert-trust-link"]').trigger('click')
    await nextTick()

    expect(wrapper.find('[data-test="cert-modal-open"]').exists()).toBe(true)
  })

  it('the link is keyboard-reachable (Enter opens the modal)', async () => {
    const wrapper = await mountCard({ mode: 'ce', api: HTTPS_API })
    await wrapper.find('[data-testid="cert-trust-link"]').trigger('keydown.enter')
    await nextTick()
    expect(wrapper.find('[data-test="cert-modal-open"]').exists()).toBe(true)
  })
})

describe('ConnectToolCard — FE-9383 Node/TLS note', () => {
  it('CE + https: states the failure in terms of Node clients and the trust store', async () => {
    const wrapper = await mountCard({ mode: 'ce', api: HTTPS_API, toolId: 'opencode' })
    const note = wrapper.find('[data-testid="node-tls-note"]')
    expect(note.exists()).toBe(true)
    expect(note.text()).toContain('OpenCode')
    expect(note.text()).toContain('trust store')
  })

  it('CE + http (localhost default): stays silent — there is no certificate to trust', async () => {
    const wrapper = await mountCard({ mode: 'ce', api: HTTP_API, toolId: 'opencode' })
    expect(wrapper.find('[data-testid="node-tls-note"]').exists()).toBe(false)
  })

  it('SaaS: never renders — a hosted tenant has no server certificate of its own', async () => {
    const wrapper = await mountCard({ mode: 'saas', api: HTTPS_API, toolId: 'opencode' })
    expect(wrapper.find('[data-testid="node-tls-note"]').exists()).toBe(false)
  })

  it('never offers disabling TLS verification as the fix', async () => {
    const wrapper = await mountCard({ mode: 'ce', api: HTTPS_API, toolId: 'opencode' })
    const text = wrapper.text()
    expect(text).not.toContain('NODE_TLS_REJECT_UNAUTHORIZED')
    expect(text).not.toContain('--insecure')
    expect(text).not.toContain('rejectUnauthorized')
    expect(text.toLowerCase()).not.toContain('disable certificate')
  })
})
