import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('@/components/common/BaseDialog.vue', () => ({
  default: { name: 'BaseDialog', template: '<div class="base-dialog-stub"><slot /></div>' },
}))

vi.mock('@/composables/useFormatDate', () => ({
  useFormatDate: () => ({ formatDateTime: (d) => String(d) }),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

vi.mock('@/services/api', () => ({
  default: {
    apiKeys: {
      list: vi.fn().mockResolvedValue({ data: [] }),
      delete: vi.fn().mockResolvedValue({ data: {} }),
    },
  },
}))

const globalStubs = {
  'v-icon': { template: '<i class="v-icon-stub"><slot /></i>' },
  'v-btn': {
    template: '<button class="v-btn-stub" v-bind="$attrs" @click="$emit(\'click\', $event)"><slot /></button>',
    emits: ['click'],
  },
  'v-card': { template: '<div class="v-card-stub"><slot /></div>' },
  'v-card-text': { template: '<div><slot /></div>' },
  'v-chip': { template: '<span class="v-chip-stub"><slot /></span>' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
  'v-alert': { template: '<div class="v-alert-stub"><slot /></div>' },
  'v-data-table': { template: '<div class="v-data-table-stub" />' },
}

async function mountManager() {
  const ApiKeyManager = (await import('@/components/ApiKeyManager.vue')).default
  const wrapper = mount(ApiKeyManager, {
    global: { stubs: globalStubs },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
})


describe('ApiKeyManager — view/revoke only (FE-9225 retirement of the configurator)', () => {
  it('does NOT render the legacy Configurator pill', async () => {
    const wrapper = await mountManager()
    expect(wrapper.find('[data-testid="apikey-configurator-btn"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Configurator')
  })

  it('does NOT mount AiToolConfigWizard', async () => {
    const wrapper = await mountManager()
    expect(wrapper.findComponent({ name: 'AiToolConfigWizard' }).exists()).toBe(false)
  })

  it('still renders its own view/revoke chrome', async () => {
    const wrapper = await mountManager()
    expect(wrapper.text()).toContain('API Keys')
    expect(wrapper.text()).toContain('View and revoke API keys used by AI coding agent integrations')
  })
})
