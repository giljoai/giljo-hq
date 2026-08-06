import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'

// FE-9339 — the inline cert-trust entry point on the connect card.
//
// A CE self-hoster running HTTPS pastes the connect command, their AI tool refuses
// on a certificate error, and the fix used to live only on Tools > Startup. This
// card is where they are standing when it fails, so it now offers the same modal
// inline. The link is gated twice, and the SaaS gate is the one that would embarrass
// us if it leaked: a hosted tenant has no server certificate to trust.

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

// jsdom serves the page from http://localhost:3000, so a config whose host matches
// resolves through buildServerUrl()'s same-host branch to window.location.origin
// (http) — that is the localhost default a self-hoster starts on. A different host
// with protocol https takes the out-of-band branch and composes an https URL.
const HTTP_API = { host: 'localhost', port: '7272', protocol: 'http', ssl_enabled: false }
const HTTPS_API = { host: 'giljo.example.com', port: 443, protocol: 'https', ssl_enabled: true }

let mountedWrappers = []
async function mountCard({ mode, api }) {
  fetchConfig.mockResolvedValue({ api, giljo_mode: mode })
  const ConnectToolCard = (await import('@/components/setup/ConnectToolCard.vue')).default
  const wrapper = mount(ConnectToolCard, {
    props: { toolId: 'claude_code' },
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
    // Copy leads with the symptom — the user does not yet know "certificate" is their problem.
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
