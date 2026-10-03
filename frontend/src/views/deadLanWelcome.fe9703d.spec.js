import { readFileSync } from 'fs'
import { resolve } from 'path'
import { describe, it, expect } from 'vitest'
import setupService from '@/services/setupService'

describe('dead setup and LAN plumbing', () => {
  it('the dashboard has no LAN welcome banner', () => {
    const view = readFileSync(resolve(__dirname, 'DashboardView.vue'), 'utf8')
    expect(view).not.toContain('giljo_lan_setup_complete')
    expect(view).not.toContain('generateLanGuide')
  })

  it('setupService has no checkStatus', () => {
    expect(setupService.checkStatus).toBeUndefined()
  })
})
