import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('@/services/api', () => ({
  default: {
    apiKeys: {
      getActive: vi.fn().mockResolvedValue({ data: [] }),
      create: vi.fn().mockResolvedValue({ data: { api_key: 'gk_test_key_123' } }),
    },
  },
}))

let mockGiljoMode = 'saas'
vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockImplementation(() =>
      Promise.resolve({
        api: { host: 'localhost', port: '7272', protocol: 'http' },
        giljo_mode: mockGiljoMode,
      }),
    ),
  },
}))
vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn().mockResolvedValue(true) }),
}))
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

const globalStubs = {
  'v-text-field': { template: '<input class="v-text-field-stub" />', props: ['modelValue'] },
  'v-icon': { template: '<i class="v-icon-stub"><slot /></i>' },
  'v-btn': { template: '<button class="v-btn-stub"><slot /></button>' },
  'v-progress-circular': { template: '<span />' },
  'v-alert': { template: '<div><slot /></div>' },
  'v-expand-transition': { template: '<div><slot /></div>' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
}

async function render(toolId, mode) {
  mockGiljoMode = mode
  const ConnectToolCard = (await import('@/components/setup/ConnectToolCard.vue')).default
  const wrapper = mount(ConnectToolCard, { props: { toolId }, global: { stubs: globalStubs } })
  await flushPromises()
  return wrapper.html()
}

beforeEach(() => {
  mockGiljoMode = 'saas'
})

describe('ConnectToolCard: existing four cards render unchanged', () => {
  for (const mode of ['saas', 'ce']) {
    for (const toolId of ['claude_code', 'codex_cli', 'opencode', 'generic']) {
      it(`${toolId} (${mode})`, async () => {
        expect(await render(toolId, mode)).toMatchSnapshot()
      })
    }
  }
})
