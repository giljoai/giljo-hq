import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const apiMock = vi.hoisted(() => ({
  settings: { getNotificationPrefs: vi.fn(), updateNotificationPrefs: vi.fn() },
}))
vi.mock('@/services/api', () => ({ default: apiMock, api: apiMock }))

import BannerPreferencesCard from './BannerPreferencesCard.vue'

const nativeSwitch = {
  props: ['modelValue', 'disabled'],
  emits: ['update:modelValue'],
  template:
    '<input type="checkbox" v-bind="$attrs" :checked="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.checked)" />',
}

describe('BannerPreferencesCard: a failed save', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMock.settings.getNotificationPrefs.mockResolvedValue({
      data: { notification_preferences: { banner_lifecycle_enabled: true, banner_advisories_in_fold: true } },
    })
    apiMock.settings.updateNotificationPrefs.mockRejectedValue(
      Object.assign(new Error('x'), { response: { status: 500, data: { message: 'save refused' } } }),
    )
  })

  for (const testId of ['banner-lifecycle-toggle', 'banner-advisories-toggle']) {
    it(`${testId}: the switch shows the real value again and the next click asks again`, async () => {
      const wrapper = mount(BannerPreferencesCard, { global: { stubs: { 'v-switch': nativeSwitch } } })
      await flushPromises()
      const input = wrapper.find(`[data-test="${testId}"]`)
      expect(input.element.checked).toBe(true)

      input.element.click()
      await input.trigger('change')
      await flushPromises()
      expect(wrapper.find('[data-test="banner-prefs-error"]').exists()).toBe(true)
      expect(input.element.checked).toBe(true)

      input.element.click()
      await input.trigger('change')
      await flushPromises()
      const sent = apiMock.settings.updateNotificationPrefs.mock.calls.map(([payload]) => Object.values(payload)[0])
      expect(sent).toEqual([false, false])
    })
  }
})
