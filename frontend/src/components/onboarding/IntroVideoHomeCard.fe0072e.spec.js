import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import IntroVideoHomeCard from './IntroVideoHomeCard.vue'
import IntroVideoDialog from './IntroVideoDialog.vue'
import { useUserStore } from '@/stores/user'

vi.mock('@/services/api', () => {
  const apiObj = { auth: {} }
  return { default: apiObj, api: apiObj }
})

const DAY = 24 * 60 * 60 * 1000
const ago = (days) => new Date(Date.now() - days * DAY).toISOString()

const mem = new Map()
function installMemoryStorage() {
  mem.clear()
  window.localStorage = {
    getItem: (k) => (mem.has(k) ? mem.get(k) : null),
    setItem: (k, v) => mem.set(k, String(v)),
    removeItem: (k) => mem.delete(k),
    clear: () => mem.clear(),
  }
}

function mountCard(user) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useUserStore().currentUser = { id: 'user-1', ...user }
  return mount(IntroVideoHomeCard, { global: { plugins: [pinia] } })
}
const card = (w) => w.find('[data-testid="intro-video-home-card"]')

describe('IntroVideoHomeCard', () => {
  beforeEach(installMemoryStorage)

  it('shows the label for an account of 29 days', () => {
    const w = mountCard({ created_at: ago(29), intro_video_seen: true })
    expect(card(w).exists()).toBe(true)
    expect(card(w).text()).toContain('Watch: How to get going (1:48)')
  })

  it('is absent for an account of 31 days', () => {
    const w = mountCard({ created_at: ago(31), intro_video_seen: true })
    expect(card(w).exists()).toBe(false)
  })

  it('is absent when created_at is missing', () => {
    const w = mountCard({ intro_video_seen: true })
    expect(card(w).exists()).toBe(false)
  })

  it('opens a dialog that can be closed at any time', async () => {
    const w = mountCard({ created_at: ago(3), intro_video_seen: true })
    const dialog = () => w.findComponent(IntroVideoDialog)
    expect(dialog().props('modelValue')).toBe(false)
    await w.get('[data-testid="intro-video-home-card-open"]').trigger('click')
    expect(dialog().props('modelValue')).toBe(true)
    expect(dialog().props('gated')).toBe(false)
    dialog().vm.$emit('close')
    await w.vm.$nextTick()
    expect(dialog().props('modelValue')).toBe(false)
  })

  it('the X hides it for good, and it stays hidden on the next mount', async () => {
    const w = mountCard({ created_at: ago(3), intro_video_seen: true })
    await w.get('[data-testid="intro-video-home-card-dismiss"]').trigger('click')
    expect(card(w).exists()).toBe(false)
    const again = mountCard({ created_at: ago(3), intro_video_seen: true })
    expect(card(again).exists()).toBe(false)
  })

  it('hiding is per person: another account on the same browser still sees it', async () => {
    const w = mountCard({ id: 'user-1', created_at: ago(3), intro_video_seen: true })
    await w.get('[data-testid="intro-video-home-card-dismiss"]').trigger('click')
    const other = mountCard({ id: 'user-2', created_at: ago(3), intro_video_seen: true })
    expect(card(other).exists()).toBe(true)
  })
})
