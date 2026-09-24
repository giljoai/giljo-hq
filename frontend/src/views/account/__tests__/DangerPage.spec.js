import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'


const wsHandlers = new Map()
function emitWsEvent(type, payload) {
  const set = wsHandlers.get(type)
  if (set) set.forEach((h) => h(payload))
}
const wsOnMock = vi.fn((type, handler) => {
  if (!wsHandlers.has(type)) wsHandlers.set(type, new Set())
  wsHandlers.get(type).add(handler)
  return () => wsHandlers.get(type)?.delete(handler)
})
vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({ on: wsOnMock }),
}))

const exportMyDataMock = vi.fn()
vi.mock('@/services/api', () => ({
  default: {
    account: {
      exportMyData: (...args) => exportMyDataMock(...args),
    },
  },
}))

const showToastMock = vi.fn()
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

const routerPushMock = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPushMock }),
}))

const editionRef = { value: 'community' }
vi.mock('@/services/configService', () => ({
  default: {
    getEdition: () => editionRef.value,
  },
}))

const userIsAdminRef = { value: false }
vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    get isAdmin() {
      return userIsAdminRef.value
    },
  }),
}))


async function mountPage() {
  setActivePinia(createPinia())
  const { default: DangerPage } = await import('@/views/account/DangerPage.vue')
  return mount(DangerPage, {
    global: {
      stubs: {
        'v-icon': { template: '<i class="v-icon-stub"><slot /></i>' },
        'v-btn': {
          template:
            '<button class="v-btn-stub" :disabled="disabled || loading" @click="$emit(\'click\', $event)"><slot /></button>',
          props: ['disabled', 'loading', 'color', 'variant', 'size'],
          emits: ['click'],
        },
        'v-chip': { template: '<span class="v-chip-stub"><slot /></span>' },
        'v-progress-linear': {
          template: '<div class="v-progress-linear-stub" :data-value="modelValue" />',
          props: ['modelValue', 'indeterminate', 'color', 'height'],
        },
      },
    },
  })
}


describe('DangerPage — Download My Data section (BE-5062)', () => {
  beforeEach(() => {
    wsHandlers.clear()
    wsOnMock.mockClear()
    exportMyDataMock.mockReset()
    showToastMock.mockClear()
    routerPushMock.mockClear()
    editionRef.value = 'community'
    userIsAdminRef.value = false
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the Download My Data section in CE (edition=community)', async () => {
    editionRef.value = 'community'
    const wrapper = await mountPage()
    await flushPromises()
    expect(wrapper.find('[data-test="download-my-data-section"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="generate-export-btn"]').exists()).toBe(true)
  })

  it('renders the section in SaaS when the user is an org admin', async () => {
    editionRef.value = 'saas'
    userIsAdminRef.value = true
    const wrapper = await mountPage()
    await flushPromises()
    expect(wrapper.find('[data-test="download-my-data-section"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="generate-export-btn"]').exists()).toBe(true)
  })

  it('hides the section in SaaS when the user is NOT an org admin', async () => {
    editionRef.value = 'saas'
    userIsAdminRef.value = false
    const wrapper = await mountPage()
    await flushPromises()
    expect(wrapper.find('[data-test="download-my-data-section"]').exists()).toBe(false)
  })

  it('hides the section when edition is non-community and user is not an admin', async () => {
    editionRef.value = 'saas'
    userIsAdminRef.value = false
    const wrapper = await mountPage()
    await flushPromises()
    expect(wrapper.find('[data-test="download-my-data-section"]').exists()).toBe(false)
  })

  it('calls api.account.exportMyData() when Generate Export is clicked', async () => {
    exportMyDataMock.mockResolvedValue({
      data: {
        download_url: '/api/download/temp/abc123/tenant_export.zip',
        expires_at: '2026-05-14T15:00:00+00:00',
        model_counts: { products: 3, projects: 2 },
      },
    })
    const wrapper = await mountPage()
    await flushPromises()

    await wrapper.find('[data-test="generate-export-btn"]').trigger('click')
    await flushPromises()

    expect(exportMyDataMock).toHaveBeenCalledTimes(1)
  })

  it('updates the progress indicator on tenant:export_progress events', async () => {
    exportMyDataMock.mockImplementation(
      () =>
        new Promise(() => {
          /* never resolves during this test */
        }),
    )
    const wrapper = await mountPage()
    await flushPromises()
    await wrapper.find('[data-test="generate-export-btn"]').trigger('click')
    await flushPromises()

    emitWsEvent('tenant:export_progress', {
      type: 'tenant:export_progress',
      schema_version: '1.0',
      timestamp: '2026-05-14T14:30:00+00:00',
      data: {
        model: 'Project',
        current: 3,
        total: 10,
        records: 0,
        phase: 'exporting',
        tenant_key: 'tenant-1',
      },
    })
    await flushPromises()

    const status = wrapper.find('[data-test="export-progress-status"]')
    expect(status.exists()).toBe(true)
    expect(status.text()).toMatch(/Project/i)
    expect(status.text()).toContain('3')
    expect(status.text()).toContain('10')
  })

  it('shows the orchestrator-prompt pointer card for an admin', async () => {
    editionRef.value = 'community'
    userIsAdminRef.value = true
    const wrapper = await mountPage()
    await flushPromises()
    expect(wrapper.find('[data-test="orchestrator-prompt-section"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="orchestrator-prompt-link"]').exists()).toBe(true)
  })

  it('hides the orchestrator-prompt pointer card for a non-admin', async () => {
    editionRef.value = 'saas'
    userIsAdminRef.value = false
    const wrapper = await mountPage()
    await flushPromises()
    expect(wrapper.find('[data-test="orchestrator-prompt-section"]').exists()).toBe(false)
  })

  it('sends the admin to Tools > Agents > Orchestrator prompt', async () => {
    editionRef.value = 'community'
    userIsAdminRef.value = true
    const wrapper = await mountPage()
    await flushPromises()

    await wrapper.find('[data-test="orchestrator-prompt-link"]').trigger('click')

    expect(routerPushMock).toHaveBeenCalledWith({
      path: '/tools',
      query: { tab: 'agents', view: 'prompt' },
    })
  })

  it('shows a download link when the export completes', async () => {
    exportMyDataMock.mockResolvedValue({
      data: {
        download_url: '/api/download/temp/abc123/tenant_export.zip',
        expires_at: '2026-05-14T15:00:00+00:00',
        model_counts: { products: 3, projects: 2 },
      },
    })
    const wrapper = await mountPage()
    await flushPromises()
    await wrapper.find('[data-test="generate-export-btn"]').trigger('click')
    await flushPromises()

    const link = wrapper.find('[data-test="export-download-link"]')
    expect(link.exists()).toBe(true)
    expect(link.attributes('href')).toBe('/api/download/temp/abc123/tenant_export.zip')
  })
})
