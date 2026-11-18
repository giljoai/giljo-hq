import { describe, expect, it } from 'vitest'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'

import VideosLibraryDialog from './VideosLibraryDialog.vue'
import IntroVideoDialog from './IntroVideoDialog.vue'
import { ONBOARDING_INTRO_VIDEO, ONBOARDING_LESSONS, ONBOARDING_SETUP_HELPER } from '@/content/onboarding/videos'

const DialogStub = defineComponent({
  name: 'DialogStub',
  props: ['modelValue'],
  template: '<div v-if="modelValue" class="dialog-stub"><slot /></div>',
})
const stubs = { 'v-dialog': DialogStub, 'v-icon': { template: '<i><slot /></i>' }, 'v-btn': { template: '<button v-bind="$attrs"><slot /></button>' } }

function mountLibrary(props = {}) {
  return mount(VideosLibraryDialog, { props: { modelValue: true, ...props }, global: { stubs } })
}
const rows = (w) => w.findAll('[data-testid^="library-video-"]')
const player = (w) => w.findComponent(IntroVideoDialog)

describe('Videos and animations: the library', () => {
  it('is titled "Videos and animations"', () => {
    expect(mountLibrary().get('[data-testid="videos-library-title"]').text()).toBe('Videos and animations')
  })

  it('lists the six hosted videos in order: the start video, setup, lessons 1 to 4', () => {
    const w = mountLibrary()
    expect(rows(w).map((r) => r.attributes('data-testid'))).toEqual([
      'library-video-how-to-get-going',
      'library-video-setup',
      'library-video-lesson01',
      'library-video-lesson02',
      'library-video-lesson03',
      'library-video-lesson04',
    ])
    const expected = [ONBOARDING_INTRO_VIDEO, ONBOARDING_SETUP_HELPER, ...ONBOARDING_LESSONS].map((v) => v.title)
    expect(rows(w).map((r) => r.get('.library-row-title').text())).toEqual(expected)
  })

  it('each row shows its length, computed from the registry seconds as m:ss', () => {
    const w = mountLibrary()
    const lengths = rows(w).map((r) => r.get('.library-row-length').text())
    expect(lengths).toEqual(['1:48', '0:42', '0:48', '0:41', '0:47', '0:57'])
  })

  it('a row opens the shared closable player with that video; closing it returns to the list', async () => {
    const w = mountLibrary()
    expect(player(w).props('modelValue')).toBe(false)
    await w.get('[data-testid="library-video-lesson03"]').trigger('click')
    expect(player(w).props('modelValue')).toBe(true)
    expect(player(w).props('gated')).toBe(false)
    expect(player(w).props('video').id).toBe('lesson03')
    player(w).vm.$emit('close')
    await w.vm.$nextTick()
    expect(player(w).props('modelValue')).toBe(false)
    expect(rows(w)).toHaveLength(6)
  })

  it('has one entry for the animated tour, which asks for it and closes the library', async () => {
    const w = mountLibrary()
    const tour = w.get('[data-testid="library-tour"]')
    expect(tour.text()).toContain('How it works (animated tour)')
    await tour.trigger('click')
    expect(w.emitted('open-tour')).toHaveLength(1)
    expect(w.emitted('close')).toHaveLength(1)
  })

  it('the close button asks to close', async () => {
    const w = mountLibrary()
    await w.get('[data-testid="videos-library-close"]').trigger('click')
    expect(w.emitted('close')).toHaveLength(1)
  })
})
