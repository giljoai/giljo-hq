import { describe, it, expect } from 'vitest'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'

import IntroVideoDialog from './IntroVideoDialog.vue'
import { ONBOARDING_INTRO_VIDEO } from '@/content/onboarding/videos'
import { withRealVuetify } from '../../../tests/helpers/realVuetify.js'

const DialogStub = defineComponent({
  name: 'DialogStub',
  emits: ['keydown', 'click:outside'],
  template: '<div class="dialog-stub"><slot /></div>',
})

const FAILURE = 'The video could not play. You can watch it later in Tools, Learning.'

function mountDialog(props = {}) {
  return mount(IntroVideoDialog, {
    props: { modelValue: true, gated: true, ...props },
    global: { stubs: { 'v-dialog': DialogStub } },
  })
}
const player = (w) => w.get('[data-testid="intro-video-player"]')
const cont = (w) => w.get('[data-testid="intro-video-continue"]')
const closeBtn = (w) => w.get('[data-testid="intro-video-close"]')
const dlg = (w) => w.findComponent(DialogStub)
const closed = (w) => w.emitted('close')?.length ?? 0

describe('IntroVideoDialog (first run, gated)', () => {
  it('says what it is and what to do', () => {
    const w = mountDialog()
    const text = w.text()
    expect(text).toContain('Welcome to Giljo HQ')
    expect(text).toContain('Watch this first. It takes under two minutes.')
    expect(cont(w).text()).toBe('Continue')
    expect(w.get('[data-testid="intro-video-hint"]').text()).toBe('Watch the video to continue')
  })

  it('close, Escape, click outside and Continue are inert before the video has ended', async () => {
    const w = mountDialog()
    expect(cont(w).attributes('disabled')).toBeDefined()
    expect(closeBtn(w).attributes('aria-disabled')).toBe('true')
    await closeBtn(w).trigger('click')
    await cont(w).trigger('click')
    dlg(w).vm.$emit('keydown', { key: 'Escape' })
    dlg(w).vm.$emit('click:outside', new Event('click'))
    expect(closed(w)).toBe(0)
  })

  it('everything closes it once the video has ended', async () => {
    const w = mountDialog()
    await player(w).trigger('ended')
    expect(cont(w).attributes('disabled')).toBeUndefined()
    expect(closeBtn(w).attributes('aria-disabled')).toBe('false')
    expect(w.find('[data-testid="intro-video-hint"]').exists()).toBe(false)
    await cont(w).trigger('click')
    expect(closed(w)).toBe(1)
    await closeBtn(w).trigger('click')
    expect(closed(w)).toBe(2)
    dlg(w).vm.$emit('keydown', { key: 'Escape' })
    expect(closed(w)).toBe(3)
    dlg(w).vm.$emit('click:outside', new Event('click'))
    expect(closed(w)).toBe(4)
  })

  it('other keys do not close it', async () => {
    const w = mountDialog()
    await player(w).trigger('ended')
    dlg(w).vm.$emit('keydown', { key: 'Enter' })
    expect(closed(w)).toBe(0)
  })

  it('a media error shows the failure line and enables Continue', async () => {
    const w = mountDialog()
    expect(w.find('[data-testid="intro-video-failure"]').exists()).toBe(false)
    await player(w).trigger('error')
    expect(w.get('[data-testid="intro-video-failure"]').text()).toBe(FAILURE)
    expect(cont(w).attributes('disabled')).toBeUndefined()
    await cont(w).trigger('click')
    expect(closed(w)).toBe(1)
  })

  it('a media error shows the video\'s transcript so the content is still readable', async () => {
    const w = mountDialog()
    expect(w.find('[data-testid="intro-video-transcript"]').exists()).toBe(false)
    await player(w).trigger('error')
    const t = w.get('[data-testid="intro-video-transcript"]')
    expect(t.text()).toContain(ONBOARDING_INTRO_VIDEO.transcript.slice(0, 40).trim())
  })

  it('a stall shows the transcript too, for a video opened from the pane (not gated)', async () => {
    const w = mountDialog({ gated: false })
    w.getComponent({ name: 'IntroVideoPlayer' }).vm.$emit('stalled')
    await w.vm.$nextTick()
    expect(w.find('[data-testid="intro-video-transcript"]').exists()).toBe(true)
    expect(w.find('[data-testid="intro-video-failure"]').exists()).toBe(true)
  })

  it('a stall shows the failure line and enables Continue', async () => {
    const w = mountDialog()
    w.getComponent({ name: 'IntroVideoPlayer' }).vm.$emit('stalled')
    await w.vm.$nextTick()
    expect(w.get('[data-testid="intro-video-failure"]').text()).toBe(FAILURE)
    expect(cont(w).attributes('disabled')).toBeUndefined()
  })

  it('opening it again starts the gate again', async () => {
    const w = mountDialog()
    await player(w).trigger('ended')
    await w.setProps({ modelValue: false })
    await w.setProps({ modelValue: true })
    expect(cont(w).attributes('disabled')).toBeDefined()
  })
})

describe('IntroVideoDialog (opened from Home or Tools)', () => {
  it('is titled with the video, has no Continue and closes at any time', async () => {
    const w = mountDialog({ gated: false })
    expect(w.text()).toContain(ONBOARDING_INTRO_VIDEO.title)
    expect(w.find('[data-testid="intro-video-continue"]').exists()).toBe(false)
    expect(w.find('[data-testid="intro-video-hint"]').exists()).toBe(false)
    await closeBtn(w).trigger('click')
    expect(closed(w)).toBe(1)
    dlg(w).vm.$emit('keydown', { key: 'Escape' })
    dlg(w).vm.$emit('click:outside', new Event('click'))
    expect(closed(w)).toBe(3)
  })
})

describe('IntroVideoDialog with the real Vuetify dialog', () => {
  it('is a named dialog', async () => {
    const real = await withRealVuetify([
      'VDialog',
      'VOverlay',
      'VCard',
      'VBtn',
      'VIcon',
      'VSpacer',
    ])
    try {
      const w = mount(IntroVideoDialog, {
        props: { modelValue: true, gated: true },
        global: { plugins: [real.plugin] },
        attachTo: document.body,
      })
      await w.vm.$nextTick()
      await new Promise((r) => setTimeout(r, 0))
      const dialog = document.body.querySelector('[role="dialog"]')
      expect(dialog).not.toBeNull()
      const labelId = dialog.getAttribute('aria-labelledby')
      expect(labelId).toBeTruthy()
      expect(document.getElementById(labelId).textContent).toContain('Welcome to Giljo HQ')
      w.unmount()
    } finally {
      real.restore()
    }
  })
})
