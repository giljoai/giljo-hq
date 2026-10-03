import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import ConnectionDebugDialog from './ConnectionDebugDialog.vue'
import { useWebSocketStore } from '@/stores/websocket'

describe('ConnectionDebugDialog status look', () => {
  it.each([
    ['connected', 'success', 'mdi-wifi'],
    ['connecting', 'warning', 'mdi-wifi-sync'],
    ['reconnecting', 'warning', 'mdi-wifi-sync'],
    ['disconnected', 'error', 'mdi-wifi-off'],
    ['something-else', 'grey', 'mdi-help-circle'],
  ])('%s -> %s %s', (state, color, icon) => {
    const pinia = createTestingPinia({ createSpy: vi.fn, stubActions: true })
    const store = useWebSocketStore(pinia)
    store.connectionStatus = state
    const wrapper = mount(ConnectionDebugDialog, {
      props: { modelValue: false },
      global: { plugins: [pinia], directives: { draggable: {} } },
    })
    expect(wrapper.vm.chipColor).toBe(color)
    expect(wrapper.vm.icon).toBe(icon)
  })
})
