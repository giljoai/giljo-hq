import { describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'


const copy = vi.fn().mockResolvedValue(true)
const showToast = vi.fn()
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast }) }))

const apiBase = vi.hoisted(() => ({ value: 'http://localhost:7272' }))
vi.mock('@/composables/useApiUrl', () => ({ getApiBaseUrl: () => apiBase.value }))

import ConnectAgentLink from '../ConnectAgentLink.vue'

const stubs = { 'v-icon': { template: '<i><slot /></i>' } }

describe('ConnectAgentLink', () => {
  it('uses the API base, not the frontend origin (dev serves the SPA on another port)', () => {
    apiBase.value = 'http://localhost:7272'
    const w = mount(ConnectAgentLink, { global: { stubs } })
    expect(w.get('[data-testid="connect-agent-link-url"]').text()).toBe('http://localhost:7272/connect.md')
  })

  it('falls back to the page origin when the API base is empty', () => {
    apiBase.value = ''
    const w = mount(ConnectAgentLink, { global: { stubs } })
    expect(w.get('[data-testid="connect-agent-link-url"]').text()).toBe(`${window.location.origin}/connect.md`)
    apiBase.value = 'http://localhost:7272'
  })

  it('shows the sentence and this server\'s connect.md address', () => {
    const w = mount(ConnectAgentLink, { global: { stubs } })
    expect(w.text()).toContain('Prefer to let your agent do it? Give it this link')
    expect(w.get('[data-testid="connect-agent-link-url"]').text()).toBe(
      'http://localhost:7272/connect.md',
    )
  })

  it('copy button copies the address', async () => {
    const w = mount(ConnectAgentLink, { global: { stubs } })
    await w.get('[data-testid="connect-agent-link-copy"]').trigger('click')
    await flushPromises()
    expect(copy).toHaveBeenCalledWith('http://localhost:7272/connect.md')
    expect(showToast).toHaveBeenCalledWith({ message: 'Copied to clipboard', type: 'success' })
  })
})
