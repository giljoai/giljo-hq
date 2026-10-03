import { readFileSync } from 'fs'
import { resolve } from 'path'
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('@/services/api', () => {
  const api = { settings: { getDatabase: vi.fn().mockResolvedValue({ data: { host: 'db', port: 5432, name: 'n', user: 'u' } }) } }
  return { default: api, api }
})

import DatabaseConnection from '@/components/DatabaseConnection.vue'

describe('Database panel labels', () => {
  it('describes the live connection, not installation config', async () => {
    const wrapper = mount(DatabaseConnection, { props: { showTitle: true, showInfoBanner: true } })
    await flushPromises()
    expect(wrapper.text()).toContain('Database Connection')
    expect(wrapper.text()).toContain('connected to right now')
    expect(wrapper.text()).not.toContain('configured during installation')
  })

  it('the Settings screen uses those labels and does not say "Reload from Config"', () => {
    const view = readFileSync(resolve(__dirname, '../views/SystemSettings.vue'), 'utf8')
    expect(view).not.toContain('Reload from Config')
    expect(view).not.toContain('Database settings are configured during installation')
    expect(view).not.toContain('PostgreSQL Database Configuration')
  })
})
