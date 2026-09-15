import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const apiMock = vi.hoisted(() => ({
  settings: {
    getNotificationPrefs: vi.fn(),
    updateNotificationPrefs: vi.fn(),
  },
}))

vi.mock('@/services/api', () => ({ default: apiMock, api: apiMock }))

import { withRealVuetify } from '../../../tests/helpers/realVuetify.js'

import BannerPreferencesCard from './BannerPreferencesCard.vue'
import PopoutPreferencesCard from './PopoutPreferencesCard.vue'

function prefs(overrides = {}) {
  return {
    data: {
      notification_preferences: {
        banner_lifecycle_enabled: true,
        banner_advisories_in_fold: true,
        popout_scope: 'all',
        ...overrides,
      },
    },
  }
}

let realVuetify = null

async function mountCard(component) {
  realVuetify = await withRealVuetify([
    'VSwitch',
    'VRadioGroup',
    'VRadio',
    'VSelectionControl',
    'VSelectionControlGroup',
    'VInput',
    'VLabel',
    'VIcon',
  ])
  const wrapper = mount(component, { global: { plugins: [realVuetify.plugin] } })
  await flushPromises()
  return wrapper
}

function restoreVuetify() {
  realVuetify?.restore()
  realVuetify = null
}

function stubPermission(state) {
  if (state === 'unsupported') {
    delete global.Notification
    return
  }
  global.Notification = vi.fn()
  global.Notification.permission = state
  global.Notification.requestPermission = vi.fn()
}

describe('BannerPreferencesCard — the controls write the preferences', () => {
  afterEach(() => restoreVuetify())

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMock.settings.getNotificationPrefs.mockResolvedValue(prefs())
    apiMock.settings.updateNotificationPrefs.mockResolvedValue(prefs())
  })

  it('loads the preferences on mount rather than assuming defaults', async () => {
    await mountCard(BannerPreferencesCard)

    expect(apiMock.settings.getNotificationPrefs).toHaveBeenCalledTimes(1)
  })

  it('turning lifecycle events off writes exactly that one key', async () => {
    const wrapper = await mountCard(BannerPreferencesCard)

    await wrapper.find('[data-test="banner-lifecycle-toggle"] input').setValue(false)
    await flushPromises()

    expect(apiMock.settings.updateNotificationPrefs).toHaveBeenCalledWith({
      banner_lifecycle_enabled: false,
    })
  })

  it('turning advisories off writes exactly that one key', async () => {
    const wrapper = await mountCard(BannerPreferencesCard)

    await wrapper.find('[data-test="banner-advisories-toggle"] input').setValue(false)
    await flushPromises()

    expect(apiMock.settings.updateNotificationPrefs).toHaveBeenCalledWith({
      banner_advisories_in_fold: false,
    })
  })

  it('states the always-on guarantee, and offers NO switch for it', async () => {
    const wrapper = await mountCard(BannerPreferencesCard)
    const alwaysOn = wrapper.find('[data-test="banner-always-on"]')

    expect(alwaysOn.exists()).toBe(true)
    expect(alwaysOn.text()).toMatch(/always shown/i)
    expect(alwaysOn.find('input').exists()).toBe(false)
  })

  it('a rejected write surfaces an error saying the setting is unchanged', async () => {
    apiMock.settings.updateNotificationPrefs.mockRejectedValueOnce(new Error('boom'))
    const wrapper = await mountCard(BannerPreferencesCard)

    await wrapper.find('[data-test="banner-lifecycle-toggle"] input').setValue(false)
    await flushPromises()

    expect(wrapper.find('[data-test="banner-prefs-error"]').exists()).toBe(true)
  })
})

describe('PopoutPreferencesCard — permission is status, never a toggle we own', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMock.settings.getNotificationPrefs.mockResolvedValue(prefs())
    apiMock.settings.updateNotificationPrefs.mockResolvedValue(prefs())
    stubPermission('granted')
  })

  afterEach(() => {
    restoreVuetify()
    delete global.Notification
  })

  it('shows the scope control when the browser has granted permission', async () => {
    const wrapper = await mountCard(PopoutPreferencesCard)

    expect(wrapper.find('[data-test="popout-scope-group"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="popout-permission-status"]').text()).toMatch(/allows/i)
  })

  it('shows the scope control when permission has not been asked for yet', async () => {
    stubPermission('default')
    const wrapper = await mountCard(PopoutPreferencesCard)

    expect(wrapper.find('[data-test="popout-scope-group"]').exists()).toBe(true)
  })

  it('renders NO scope control when the browser has BLOCKED us', async () => {
    stubPermission('denied')
    const wrapper = await mountCard(PopoutPreferencesCard)

    expect(wrapper.find('[data-test="popout-scope-group"]').exists()).toBe(false)
    const status = wrapper.find('[data-test="popout-permission-status"]').text()
    expect(status).toMatch(/blocking/i)
    expect(status).toMatch(/site settings/i)
    expect(status).toMatch(/bell/i)
  })

  it('renders NO scope control when the browser has no Notification API at all', async () => {
    stubPermission('unsupported')
    const wrapper = await mountCard(PopoutPreferencesCard)

    expect(wrapper.find('[data-test="popout-scope-group"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="popout-permission-status"]').text()).toMatch(
      /does not support/i,
    )
  })

  it('choosing a scope writes exactly that key', async () => {
    const wrapper = await mountCard(PopoutPreferencesCard)

    await wrapper.find('[data-test="popout-scope-actionable"] input').setValue(true)
    await flushPromises()

    expect(apiMock.settings.updateNotificationPrefs).toHaveBeenCalledWith({
      popout_scope: 'actionable',
    })
  })

  it('offers exactly three scopes -- no independent category matrix', async () => {
    const wrapper = await mountCard(PopoutPreferencesCard)

    for (const value of ['all', 'actionable', 'off']) {
      expect(wrapper.find(`[data-test="popout-scope-${value}"]`).exists()).toBe(true)
    }
    expect(wrapper.findAll('[data-test^="popout-scope-"]')).toHaveLength(4)
  })
})

describe('PopoutPreferencesCard — asking for permission is the one gesture that can (FE-9553d)', () => {
  afterEach(() => restoreVuetify())

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMock.settings.getNotificationPrefs.mockResolvedValue(prefs())
    apiMock.settings.updateNotificationPrefs.mockResolvedValue(prefs())
    stubPermission('default')
  })

  it('ASKS the browser when the operator turns pop-outs on', async () => {
    const wrapper = await mountCard(PopoutPreferencesCard)

    await wrapper.find('[data-test="popout-scope-actionable"] input').setValue(true)
    await flushPromises()

    expect(global.Notification.requestPermission).toHaveBeenCalled()
  })

  it('asks when choosing "everything a banner shows" too', async () => {
    apiMock.settings.getNotificationPrefs.mockResolvedValue(prefs({ popout_scope: 'off' }))
    const wrapper = await mountCard(PopoutPreferencesCard)

    await wrapper.find('[data-test="popout-scope-all"] input').setValue(true)
    await flushPromises()

    expect(global.Notification.requestPermission).toHaveBeenCalled()
  })

  it('does NOT ask when the operator turns pop-outs OFF', async () => {
    const wrapper = await mountCard(PopoutPreferencesCard)

    await wrapper.find('[data-test="popout-scope-off"] input').setValue(true)
    await flushPromises()

    expect(global.Notification.requestPermission).not.toHaveBeenCalled()
  })

  it('reflects a GRANTED answer in the card without needing a reload', async () => {
    global.Notification.requestPermission = vi.fn(async () => 'granted')
    const wrapper = await mountCard(PopoutPreferencesCard)
    expect(wrapper.find('[data-test="popout-permission-status"]').text()).toMatch(/not been asked/i)

    await wrapper.find('[data-test="popout-scope-actionable"] input').setValue(true)
    await flushPromises()

    expect(wrapper.find('[data-test="popout-permission-status"]').text()).toMatch(/allows/i)
  })

  it('reflects a DENIED answer, and withdraws the scope control', async () => {
    global.Notification.requestPermission = vi.fn(async () => 'denied')
    const wrapper = await mountCard(PopoutPreferencesCard)

    await wrapper.find('[data-test="popout-scope-actionable"] input').setValue(true)
    await flushPromises()

    expect(wrapper.find('[data-test="popout-permission-status"]').text()).toMatch(/blocking/i)
    expect(wrapper.find('[data-test="popout-scope-group"]').exists()).toBe(false)
  })

  it('still saves the preference even when the browser refuses', async () => {
    global.Notification.requestPermission = vi.fn(async () => 'denied')
    const wrapper = await mountCard(PopoutPreferencesCard)

    await wrapper.find('[data-test="popout-scope-actionable"] input').setValue(true)
    await flushPromises()

    expect(apiMock.settings.updateNotificationPrefs).toHaveBeenCalledWith({
      popout_scope: 'actionable',
    })
  })

  it('does not ask again when permission is ALREADY granted', async () => {
    stubPermission('granted')
    const wrapper = await mountCard(PopoutPreferencesCard)

    await wrapper.find('[data-test="popout-scope-all"] input').setValue(true)
    await flushPromises()

    expect(global.Notification.requestPermission).not.toHaveBeenCalled()
  })
})

describe('PopoutPreferencesCard — the ask is reachable on default settings (FE-9592)', () => {
  afterEach(() => {
    restoreVuetify()
    delete global.Notification
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMock.settings.getNotificationPrefs.mockResolvedValue(prefs({ popout_scope: 'all' }))
    apiMock.settings.updateNotificationPrefs.mockResolvedValue(prefs())
    stubPermission('default')
  })

  it('offers a control that ASKS, without the operator changing any setting', async () => {
    global.Notification.requestPermission = vi.fn(async () => 'granted')
    const wrapper = await mountCard(PopoutPreferencesCard)

    const button = wrapper.find('[data-test="popout-request-permission-btn"]')
    expect(button.exists()).toBe(true)

    await button.trigger('click')
    await flushPromises()

    expect(global.Notification.requestPermission).toHaveBeenCalled()
  })

  it('says what actually happens instead of promising an ask that cannot come', async () => {
    const wrapper = await mountCard(PopoutPreferencesCard)

    const status = wrapper.find('[data-test="popout-permission-status"]').text()
    expect(status).not.toMatch(/first time/i)
    expect(status).toMatch(/turn on pop-ups/i)
  })

  it('shows the granted answer straight away, and withdraws the ask', async () => {
    global.Notification.requestPermission = vi.fn(async () => 'granted')
    const wrapper = await mountCard(PopoutPreferencesCard)

    await wrapper.find('[data-test="popout-request-permission-btn"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="popout-permission-status"]').text()).toMatch(/allows/i)
    expect(wrapper.find('[data-test="popout-request-permission-btn"]').exists()).toBe(false)
  })

  it('does not save anything: the scope was already the operator\'s choice', async () => {
    global.Notification.requestPermission = vi.fn(async () => 'granted')
    const wrapper = await mountCard(PopoutPreferencesCard)

    await wrapper.find('[data-test="popout-request-permission-btn"]').trigger('click')
    await flushPromises()

    expect(apiMock.settings.updateNotificationPrefs).not.toHaveBeenCalled()
  })

  it('offers NO ask when the operator has chosen to receive nothing', async () => {
    apiMock.settings.getNotificationPrefs.mockResolvedValue(prefs({ popout_scope: 'off' }))
    const wrapper = await mountCard(PopoutPreferencesCard)

    expect(wrapper.find('[data-test="popout-request-permission-btn"]').exists()).toBe(false)
  })

  it('offers NO ask once the browser has already answered', async () => {
    for (const state of ['granted', 'denied']) {
      stubPermission(state)
      const wrapper = await mountCard(PopoutPreferencesCard)

      expect(wrapper.find('[data-test="popout-request-permission-btn"]').exists()).toBe(false)
      restoreVuetify()
    }
  })

  it('offers NO ask in a browser with no Notification API at all', async () => {
    stubPermission('unsupported')
    const wrapper = await mountCard(PopoutPreferencesCard)

    expect(wrapper.find('[data-test="popout-request-permission-btn"]').exists()).toBe(false)
  })

  it('survives a browser that throws instead of answering', async () => {
    global.Notification.requestPermission = vi.fn(() => {
      throw new Error('not allowed here')
    })
    const wrapper = await mountCard(PopoutPreferencesCard)

    await wrapper.find('[data-test="popout-request-permission-btn"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="popout-request-permission-btn"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="popout-permission-status"]').text()).toMatch(/not been asked/i)
  })
})
