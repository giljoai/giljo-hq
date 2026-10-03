/**
 * Test suite for NetworkSettingsTab.vue component
 *
 * Read-only Host IP / Port rows (real responding address, not config external_host),
 * one line pointing at the user guide for HTTPS via a reverse proxy, and the cookie
 * domain whitelist. Built-in HTTPS (toggle, certificate upload) is gone.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import NetworkSettingsTab from '@/components/settings/tabs/NetworkSettingsTab.vue'

describe('NetworkSettingsTab.vue', () => {
  let vuetify
  let wrapper

  const RouterLinkStub = { props: ['to'], template: '<a><slot /></a>' }

  const mountTab = (props = {}) =>
    mount(NetworkSettingsTab, {
      props: {
        serverHostDisplay: '192.0.2.100',
        serverPort: 7272,
        loading: false,
        ...props,
      },
      global: {
        plugins: [vuetify],
        stubs: { RouterLink: RouterLinkStub },
      },
    })

  beforeEach(() => {
    vuetify = createVuetify({ components, directives })
    // The tab makes no request of its own; a spy proves it stays that way.
    global.fetch = vi.fn()
  })

  afterEach(() => {
    if (wrapper) wrapper.unmount()
    vi.clearAllMocks()
  })

  describe('Component Rendering', () => {
    it('renders with the new props', () => {
      wrapper = mountTab()
      expect(wrapper.exists()).toBe(true)
    })

    it('displays title "Network Configuration"', async () => {
      wrapper = mountTab()
      await wrapper.vm.$nextTick()
      expect(wrapper.text()).toContain('Network Configuration')
    })

    it('uses the simplified "Server Configuration" heading (no "from Installation")', async () => {
      wrapper = mountTab()
      await wrapper.vm.$nextTick()
      expect(wrapper.text()).toContain('Server Configuration')
      expect(wrapper.text()).not.toContain('Server Configuration from Installation')
    })

    it('keeps the installation/config.yaml explanatory note', async () => {
      wrapper = mountTab()
      await wrapper.vm.$nextTick()
      expect(wrapper.text()).toContain('Network settings are configured during installation')
      expect(wrapper.text()).toContain('config.yaml')
    })
  })

  describe('Server info rows (read-only Host IP / Port)', () => {
    it('renders Host IP and Port as read-only rows, not editable fields', async () => {
      wrapper = mountTab({ serverHostDisplay: '192.0.2.100', serverPort: 7272 })
      await wrapper.vm.$nextTick()

      const host = wrapper.find('[data-test="server-host"]')
      const port = wrapper.find('[data-test="server-port"]')
      expect(host.exists()).toBe(true)
      expect(port.exists()).toBe(true)
      expect(host.text()).toBe('192.0.2.100')
      expect(port.text()).toBe('7272')

      // The old editable-looking text fields are gone.
      expect(wrapper.find('[data-test="external-host-field"]').exists()).toBe(false)
      expect(wrapper.find('[data-test="api-port-field"]').exists()).toBe(false)
      expect(wrapper.find('[data-test="frontend-port-field"]').exists()).toBe(false)
    })

    it('shows multiple host IPs verbatim when the server answers on several', async () => {
      wrapper = mountTab({ serverHostDisplay: '192.0.2.100, 198.51.100.5' })
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[data-test="server-host"]').text()).toBe('192.0.2.100, 198.51.100.5')
    })

    it('hides server info while loading', async () => {
      wrapper = mountTab({ loading: true })
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[data-test="server-info"]').exists()).toBe(false)
    })
  })

  describe('HTTPS pointer (the app serves plain HTTP; TLS comes from a reverse proxy)', () => {
    it('shows one line pointing at a reverse proxy and the user guide', async () => {
      wrapper = mountTab()
      await wrapper.vm.$nextTick()
      const line = wrapper.find('[data-test="https-guide-link"]')
      expect(line.exists()).toBe(true)
      expect(line.text()).toContain('Want HTTPS? Put a reverse proxy such as Caddy in front')
      expect(line.text()).toContain('user guide')
    })

    it('has no certificate, toggle or upload controls and makes no SSL request', async () => {
      wrapper = mountTab()
      await wrapper.vm.$nextTick()
      for (const hook of [
        'https-status-section',
        'ssl-toggle',
        'ssl-needs-cert-hint',
        'cert-provision-section',
        'cert-upload-btn',
        'cert-ref-btn',
        'cert-status',
        'http-context-cue',
      ]) {
        expect(wrapper.find(`[data-test="${hook}"]`).exists()).toBe(false)
      }
      expect(wrapper.text()).not.toContain('HTTPS Encryption')
      expect(global.fetch).not.toHaveBeenCalled()
    })

    it('no longer renders the CORS section or the dead Save Changes button', async () => {
      wrapper = mountTab()
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[data-test="cors-origins-section"]').exists()).toBe(false)
      expect(wrapper.find('[data-test="save-button"]').exists()).toBe(false)
    })
  })

  describe('Reload button', () => {
    it('has a Reload button that emits refresh', async () => {
      wrapper = mountTab()
      await wrapper.vm.$nextTick()
      const reloadButton = wrapper.find('[data-test="reload-button"]')
      expect(reloadButton.exists()).toBe(true)
      expect(reloadButton.text()).toContain('Reload')

      await reloadButton.trigger('click')
      expect(wrapper.emitted('refresh')).toBeTruthy()
      expect(wrapper.emitted('refresh').length).toBe(1)
    })

    it('Reload button also emits reload-domains (FE-6245)', async () => {
      wrapper = mountTab()
      await wrapper.vm.$nextTick()
      const reloadButton = wrapper.find('[data-test="reload-button"]')
      await reloadButton.trigger('click')
      expect(wrapper.emitted('reload-domains')).toBeTruthy()
    })
  })

  // FE-6245: Cookie Domain Whitelist moved from Security tab to Network tab
  describe('Cookie Domain Whitelist', () => {
    const mountWithDomains = (cookieDomains = [], extra = {}) =>
      mountTab({ cookieDomains, ...extra })

    it('renders the cookie whitelist section', async () => {
      wrapper = mountWithDomains()
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[data-test="cookie-whitelist-section"]').exists()).toBe(true)
      expect(wrapper.text()).toContain('Cookie Domain Whitelist')
    })

    it('shows empty state when no domains are configured', async () => {
      wrapper = mountWithDomains([])
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[data-test="cookie-empty-state"]').exists()).toBe(true)
      expect(wrapper.text()).toContain('No domain names configured')
    })

    it('renders the add-domain input', async () => {
      wrapper = mountWithDomains()
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[data-test="cookie-new-domain-input"]').exists()).toBe(true)
    })

    it('emits add-domain with the trimmed value on addCookieDomain call', async () => {
      wrapper = mountWithDomains()
      await wrapper.vm.$nextTick()
      wrapper.vm.newCookieDomain = 'new.example.com'
      await wrapper.vm.$nextTick()
      wrapper.vm.addCookieDomain()
      await wrapper.vm.$nextTick()
      expect(wrapper.emitted('add-domain')).toBeTruthy()
      expect(wrapper.emitted('add-domain')[0]).toEqual(['new.example.com'])
    })

    it('clears the input after a successful add', async () => {
      wrapper = mountWithDomains()
      await wrapper.vm.$nextTick()
      wrapper.vm.newCookieDomain = 'new.example.com'
      wrapper.vm.addCookieDomain()
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.newCookieDomain).toBe('')
    })

    it('does not emit add-domain for an empty input', async () => {
      wrapper = mountWithDomains()
      await wrapper.vm.$nextTick()
      wrapper.vm.addCookieDomain()
      expect(wrapper.emitted('add-domain')).toBeFalsy()
    })

    it('emits remove-domain when removeCookieDomain is called', async () => {
      wrapper = mountWithDomains(['app.example.com'])
      await wrapper.vm.$nextTick()
      wrapper.vm.removeCookieDomain('app.example.com')
      await wrapper.vm.$nextTick()
      expect(wrapper.emitted('remove-domain')).toBeTruthy()
      expect(wrapper.emitted('remove-domain')[0]).toEqual(['app.example.com'])
    })

    it('rejects IP address input and sets cookieDomainError', async () => {
      wrapper = mountWithDomains()
      await wrapper.vm.$nextTick()
      wrapper.vm.newCookieDomain = '192.0.2.1'
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.cookieDomainError).toContain('IP addresses are not allowed')
    })

    it('rejects invalid domain format', async () => {
      wrapper = mountWithDomains()
      await wrapper.vm.$nextTick()
      wrapper.vm.newCookieDomain = 'invalid..domain'
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.cookieDomainError).toContain('Invalid domain format')
    })

    it('accepts valid domain names', async () => {
      wrapper = mountWithDomains()
      await wrapper.vm.$nextTick()
      wrapper.vm.newCookieDomain = 'valid.example.com'
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.cookieDomainError).toBe('')
    })

    it('does not emit add-domain for a duplicate domain', async () => {
      wrapper = mountWithDomains(['app.example.com'])
      await wrapper.vm.$nextTick()
      wrapper.vm.newCookieDomain = 'app.example.com'
      // Flush the pending watch so it fires and clears prior errors first;
      // then addCookieDomain runs and sets the duplicate error without the
      // watch overwriting it on the SAME tick.
      await wrapper.vm.$nextTick()
      wrapper.vm.addCookieDomain()
      // Assert synchronously before the next tick (newCookieDomain was not
      // changed during addCookieDomain, so the watch does not re-fire).
      expect(wrapper.emitted('add-domain')).toBeFalsy()
      expect(wrapper.vm.cookieDomainError).toContain('already')
    })

    it('shows loading indicator when cookieLoading is true', async () => {
      wrapper = mountWithDomains([], { cookieLoading: true })
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[data-test="cookie-loading-indicator"]').exists()).toBe(true)
    })

    it('renders the cookie feedback alert when cookieFeedback is set', async () => {
      wrapper = mountTab({
        cookieDomains: [],
        cookieFeedback: { type: 'success', message: 'Domain added.' },
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[data-test="cookie-feedback-alert"]').exists()).toBe(true)
      expect(wrapper.text()).toContain('Domain added.')
    })
  })
})
