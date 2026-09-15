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

const certModalStub = {
  name: 'CertTrustModal',
  props: ['modelValue'],
  emits: ['update:modelValue', 'continue'],
  template: '<div v-if="modelValue" data-test="cert-modal-open" />',
}

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
  CertTrustModal: certModalStub,
}

const HTTPS_API = { host: 'giljo.example.com', port: 443, protocol: 'https', ssl_enabled: true }

let mountedWrappers = []
async function openCertModal() {
  fetchConfig.mockResolvedValue({ api: HTTPS_API, giljo_mode: 'ce' })
  const ConnectToolCard = (await import('@/components/setup/ConnectToolCard.vue')).default
  const wrapper = mount(ConnectToolCard, {
    props: { toolId: 'claude_code' },
    global: { stubs: globalStubs },
  })
  mountedWrappers.push(wrapper)
  await flushPromises()
  await wrapper.find('[data-testid="cert-trust-link"]').trigger('click')
  await nextTick()
  return wrapper
}

beforeEach(() => {
  fetchConfig.mockReset()
  localStorage.setItem.mockClear()
  sessionStorage.clear()
})

afterEach(() => {
  mountedWrappers.forEach((w) => w.unmount())
  mountedWrappers = []
})

describe('ConnectToolCard — FE-9339 "don\'t show again" reaches storage', () => {
  it('ticking the box and continuing persists cert_modal_never for this device', async () => {
    const wrapper = await openCertModal()

    wrapper.findComponent(certModalStub).vm.$emit('continue', true)
    await nextTick()

    expect(localStorage.setItem).toHaveBeenCalledWith('cert_modal_never', '1')
  })

  it('continuing without ticking marks it dismissed for the session only', async () => {
    const wrapper = await openCertModal()

    wrapper.findComponent(certModalStub).vm.$emit('continue', false)
    await nextTick()

    expect(localStorage.setItem).not.toHaveBeenCalledWith('cert_modal_never', '1')
    expect(sessionStorage.getItem('cert_modal_dismissed')).toBe('1')
  })
})
