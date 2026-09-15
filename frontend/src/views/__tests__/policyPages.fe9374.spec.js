import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import Privacy from '@/views/Privacy.vue'
import Terms from '@/views/Terms.vue'


vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: async () => ({}),
    getGiljoMode: () => 'ce',
  },
}))

const mountOptions = {
  global: {
    stubs: {
      RouterLink: { template: '<a><slot /></a>' },
    },
  },
}

function renderedText(component) {
  return mount(component, mountOptions).text()
}

describe('FE-9374 policy page content guards (CE render)', () => {
  it('never mentions a Team tier (cancelled per ADR-009)', () => {
    expect(renderedText(Terms)).not.toMatch(/\bTeam\b/)
    expect(renderedText(Privacy)).not.toMatch(/\bTeam\b/)
  })

  it('keeps the neutral billing-provider wording in both pages', () => {
    expect(renderedText(Privacy)).toContain('Merchant of Record')
    expect(renderedText(Privacy).toLowerCase()).toContain('billing provider')
    expect(renderedText(Terms)).toContain('Merchant of Record')
    expect(renderedText(Terms).toLowerCase()).toContain('billing provider')
  })

  it('uses no em dashes in customer-facing policy text', () => {
    expect(renderedText(Privacy)).not.toContain('—')
    expect(renderedText(Terms)).not.toContain('—')
  })
})
