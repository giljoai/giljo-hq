/**
 * notificationPreferenceCards.spec.js — FE-9553 M4
 *
 * The control half of "every toggle proven to gate its surface". The gate
 * itself is proven at the stores (tests/stores/lifecycleBell.fe9553.spec.js:
 * flip the preference, the banner row stops being announced and the bell row
 * still lands). What is proven HERE is the other half of that sentence: that
 * the control the operator actually touches writes the preference the gate
 * reads. Neither half is worth much alone -- a gate nothing sets, or a switch
 * wired to nothing, would each pass its own suite.
 *
 * Also pinned: the two places these cards must NOT offer a control, because
 * both would be controls that lie.
 *   - The always-on guarantee is TEXT. Decisions, your-turn and mentions cannot
 *     be switched off, so there is no switch -- not a disabled one, which would
 *     imply the control exists and is merely unavailable.
 *   - A BLOCKED browser permission renders no scope control at all. We cannot
 *     grant or revoke that permission; a setting we cannot honour must not look
 *     live.
 *
 * Edition Scope: Both
 */
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

/**
 * These cards are mounted with REAL Vuetify form controls.
 *
 * The flat stubs in tests/setup.js render a v-switch as a bare
 * `<input type="checkbox">` and a v-radio-group as a div, so `setValue()` sets
 * a DOM value and no `update:model-value` is ever emitted -- meaning the
 * handler under test never runs and a "the control writes the preference"
 * assertion cannot pass at all. My first draft failed for exactly that reason.
 *
 * Asserting through the real controls is the point of this suite: it is the
 * only way to prove the SWITCH is wired to the preference rather than that a
 * function exists which would write it if called. FE-9366's withRealVuetify is
 * the sanctioned way to opt in, and the name list covers each control's
 * internals as its header warns.
 */
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

    // The data-test attribute lands on the switch's ROOT element, not its
    // <input>, so setValue() on the attribute selector targets a div and does
    // nothing. Reaching the input is what actually emits the change.
    await wrapper.find('[data-test="banner-lifecycle-toggle"] input').setValue(false)
    await flushPromises()

    // One key, not the whole object: a full-object write is what clobbers
    // siblings, and the server's per-key guards only help if the client sends
    // one key.
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
    // No control at all inside that row -- not a disabled one. A greyed switch
    // would imply the setting exists and is temporarily unavailable.
    expect(alwaysOn.find('input').exists()).toBe(false)
  })

  it('a rejected write surfaces an error saying the setting is unchanged', async () => {
    apiMock.settings.updateNotificationPrefs.mockRejectedValueOnce(new Error('boom'))
    const wrapper = await mountCard(BannerPreferencesCard)

    // The data-test attribute lands on the switch's ROOT element, not its
    // <input>, so setValue() on the attribute selector targets a div and does
    // nothing. Reaching the input is what actually emits the change.
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
    // Not-yet-asked is not blocked: the setting is real, it just has not been
    // exercised, and the browser asks the first time there is something to send.
    stubPermission('default')
    const wrapper = await mountCard(PopoutPreferencesCard)

    expect(wrapper.find('[data-test="popout-scope-group"]').exists()).toBe(true)
  })

  it('renders NO scope control when the browser has BLOCKED us', async () => {
    stubPermission('denied')
    const wrapper = await mountCard(PopoutPreferencesCard)

    expect(wrapper.find('[data-test="popout-scope-group"]').exists()).toBe(false)
    // And says so, with what to do about it, plus the reassurance that nothing
    // is lost -- the banner and the bell still carry everything.
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

    // Click the radio's input rather than setting the group's value: it is what
    // the operator does, and it is what makes the group emit.
    await wrapper.find('[data-test="popout-scope-actionable"] input').setValue(true)
    await flushPromises()

    expect(apiMock.settings.updateNotificationPrefs).toHaveBeenCalledWith({
      popout_scope: 'actionable',
    })
  })

  it('offers exactly three scopes -- no independent category matrix', async () => {
    // The record is explicit that this control can only ever answer "how much
    // of the banner do I project". A fourth position would be the settings grid
    // starting to grow back.
    const wrapper = await mountCard(PopoutPreferencesCard)

    for (const value of ['all', 'actionable', 'off']) {
      expect(wrapper.find(`[data-test="popout-scope-${value}"]`).exists()).toBe(true)
    }
    expect(wrapper.findAll('[data-test^="popout-scope-"]')).toHaveLength(4) // 3 radios + the group
  })
})

describe('PopoutPreferencesCard — asking for permission is the one gesture that can (FE-9553d)', () => {
  // THE DEFECT, found live on a fresh CE install during the operator
  // walkthrough. Notification.permission stayed "default" forever, so pop-outs
  // could never fire at all -- and it was a consequence of FE-9553's own
  // ruling 4a rather than an oversight elsewhere.
  //
  // The only requestPermission call lived in fireNotification, which by ruling
  // 4a runs ONLY when document.hidden. Chrome silently ignores a permission
  // request from a hidden tab, so the prompt never appeared: the request could
  // only happen at the exact moment the browser refuses to honour it.
  // Chicken-and-egg, invisible, and unreachable by any amount of using the app.
  //
  // Choosing a scope here is a real user gesture in a visible tab, which is
  // precisely the condition a browser will honour -- so this is where the ask
  // belongs. It is also the honest place: the operator has just said they want
  // pop-outs, so being asked for permission follows from what they did rather
  // than arriving unexplained.
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
    // Starts from 'off' deliberately: 'all' is the stored default, so selecting
    // it from a card that already shows it selected changes nothing and emits
    // nothing. My first version of this test did exactly that and failed for
    // its own setup rather than for the behaviour -- a radio you re-select is
    // not a gesture.
    apiMock.settings.getNotificationPrefs.mockResolvedValue(prefs({ popout_scope: 'off' }))
    const wrapper = await mountCard(PopoutPreferencesCard)

    await wrapper.find('[data-test="popout-scope-all"] input').setValue(true)
    await flushPromises()

    expect(global.Notification.requestPermission).toHaveBeenCalled()
  })

  it('does NOT ask when the operator turns pop-outs OFF', async () => {
    // The standing rule from FE-9553: asking a browser for a capability the
    // operator has just declined is how a site gets permanently blocked, and
    // the request is irreversible from our side.
    const wrapper = await mountCard(PopoutPreferencesCard)

    await wrapper.find('[data-test="popout-scope-off"] input').setValue(true)
    await flushPromises()

    expect(global.Notification.requestPermission).not.toHaveBeenCalled()
  })

  it('reflects a GRANTED answer in the card without needing a reload', async () => {
    // My original card read the permission once on mount, with a comment
    // arguing a poll would be wasteful because the operator cannot change it
    // without leaving the page. That reasoning is now wrong by construction:
    // this card itself changes it. The displayed state must follow.
    global.Notification.requestPermission = vi.fn(async () => 'granted')
    const wrapper = await mountCard(PopoutPreferencesCard)
    expect(wrapper.find('[data-test="popout-permission-status"]').text()).toMatch(/not been asked/i)

    await wrapper.find('[data-test="popout-scope-actionable"] input').setValue(true)
    await flushPromises()

    expect(wrapper.find('[data-test="popout-permission-status"]').text()).toMatch(/allows/i)
  })

  it('reflects a DENIED answer, and withdraws the scope control', async () => {
    // The honest half. A denied permission must not be left looking like a
    // working setting -- the operator turned pop-outs on and the browser said
    // no, so the card has to say so rather than showing a scope they chose that
    // cannot take effect.
    global.Notification.requestPermission = vi.fn(async () => 'denied')
    const wrapper = await mountCard(PopoutPreferencesCard)

    await wrapper.find('[data-test="popout-scope-actionable"] input').setValue(true)
    await flushPromises()

    expect(wrapper.find('[data-test="popout-permission-status"]').text()).toMatch(/blocking/i)
    expect(wrapper.find('[data-test="popout-scope-group"]').exists()).toBe(false)
  })

  it('still saves the preference even when the browser refuses', async () => {
    // The setting is the operator's, and it outlives this browser: they may be
    // signed in elsewhere, or grant permission here later. Refusing to store
    // their choice because THIS browser said no would silently lose it.
    global.Notification.requestPermission = vi.fn(async () => 'denied')
    const wrapper = await mountCard(PopoutPreferencesCard)

    await wrapper.find('[data-test="popout-scope-actionable"] input').setValue(true)
    await flushPromises()

    expect(apiMock.settings.updateNotificationPrefs).toHaveBeenCalledWith({
      popout_scope: 'actionable',
    })
  })

  it('does not ask again when permission is ALREADY granted', async () => {
    // requestPermission on an already-answered permission is a no-op, but
    // calling it anyway is noise in the one place a browser is watching for
    // abuse. Nothing to gain, so do not.
    stubPermission('granted')
    const wrapper = await mountCard(PopoutPreferencesCard)

    await wrapper.find('[data-test="popout-scope-all"] input').setValue(true)
    await flushPromises()

    expect(global.Notification.requestPermission).not.toHaveBeenCalled()
  })
})

describe('PopoutPreferencesCard — the ask is reachable on default settings (FE-9592)', () => {
  // THE DEFECT, found by reading the card against its own code on 2026-09-06
  // and confirmed live on the SaaS test stack with a wrapper on
  // window.Notification recording every pop-out constructed. 8,490 passing
  // tests never saw it, because every existing test for the ask CHANGES the
  // scope first.
  //
  // FE-9553d put the request on a scope change, which a browser honours. But
  // the stored scope already defaults to 'all', so an operator happy with the
  // default never changes the radio, never triggers save(), and is never
  // asked -- while the card told them the browser would ask on its own, which
  // it cannot: the signal path only runs while the tab is hidden, and a hidden
  // tab's permission request is silently ignored.
  //
  // The fix is a labelled control of its own. These tests pin the reachable
  // path WITHOUT touching the radio -- that is the whole point of them.
  afterEach(() => {
    restoreVuetify()
    delete global.Notification
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    // The stored default. Never overridden in this block: a test that changes
    // the scope would be testing FE-9553d's path all over again.
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
    // The old copy: "It will ask the first time there is something to send you
    // while the app is hidden." Nothing in the product can produce that.
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
    // The standing restraint from FE-9553, unchanged: asking for a capability
    // the operator has just declined is how a site gets permanently blocked,
    // and the request cannot be withdrawn from our side.
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
    // Some embeddings throw outright, and older ones hand back a callback
    // rather than a promise. Neither may leave the card stuck mid-ask.
    global.Notification.requestPermission = vi.fn(() => {
      throw new Error('not allowed here')
    })
    const wrapper = await mountCard(PopoutPreferencesCard)

    await wrapper.find('[data-test="popout-request-permission-btn"]').trigger('click')
    await flushPromises()

    // Still 'default', so the control is still there to try again.
    expect(wrapper.find('[data-test="popout-request-permission-btn"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="popout-permission-status"]').text()).toMatch(/not been asked/i)
  })
})
