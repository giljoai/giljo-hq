/**
 * fe9743_hub_thread_wide.spec.ts — FE-9743
 *
 * The open thread is capped at one shared max-width and left-aligned, and its header is
 * left-grouped: the copy control sits right after the title, Created / Last msg flow
 * with the other row 2 items, and a project thread does not repeat its title.
 *
 * Needs the local CE backend (:7272), a frontend on PLAYWRIGHT_TEST_BASE_URL, and
 * TEST_USER / TEST_PASSWORD. Set FE9743_SHOT_DIR to keep screenshots.
 *
 * Edition scope: Both.
 */
import { test, expect, Page } from '@playwright/test'
import { createTestProject, deleteTestProject, authHeaders } from './helpers'

const API = 'http://localhost:7272'
const SHOTS = process.env.FE9743_SHOT_DIR
const MAX_WIDTH = 1200

async function login(page: Page): Promise<void> {
  await page.goto('/login')
  await page.locator('[data-testid="email-input"] input').fill(process.env.TEST_USER || '')
  await page.locator('[data-testid="password-input"] input').fill(process.env.TEST_PASSWORD || '')
  await page.click('[data-testid="login-button"]')
  await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 10000 })
  await page.waitForLoadState('networkidle')
}

const VIEWPORTS = [
  { name: '1920x1080', width: 1920, height: 1080 },
  { name: '1280x800', width: 1280, height: 800 },
  { name: '900x900', width: 900, height: 900 },
]

test.describe('Hub thread view on wide screens (FE-9743)', () => {
  let projectId = ''
  const stamp = Date.now()

  test.afterEach(async ({ page }) => {
    if (!projectId) return
    try {
      await deleteTestProject(page, projectId)
    } catch {
      // already gone
    }
    projectId = ''
  })

  for (const vp of VIEWPORTS) {
    test(`project thread at ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height })
      await login(page)
      projectId = await createTestProject(page, { name: `FE-9743 project ${stamp}` })
      const created = await page.request.post(`${API}/api/v1/threads`, {
        headers: await authHeaders(page),
        data: { subject: `FE-9743 project ${stamp}`, project_id: projectId },
      })
      expect(created.ok()).toBeTruthy()
      const thread = await created.json()
      await page.request.post(`${API}/api/v1/threads/${thread.thread_id}/post`, {
        headers: await authHeaders(page),
        data: { content: 'wide screen check' },
      })
      await page.goto(`/hub?thread=${thread.thread_id}`)

      const view = page.locator('[data-testid="hub-thread-view"]')
      const header = page.locator('[data-testid="thread-header"]')
      await expect(header).toBeVisible()
      const viewBox = (await view.boundingBox())!
      const headerBox = (await header.boundingBox())!
      const back = (await page.locator('[data-testid="hub-back"]').boundingBox())!
      expect(viewBox.width).toBeLessThanOrEqual(MAX_WIDTH + 1)
      expect(headerBox.width).toBeLessThanOrEqual(MAX_WIDTH + 1)
      expect(Math.abs(headerBox.x - viewBox.x)).toBeLessThan(2)
      expect(back.x).toBeGreaterThanOrEqual(viewBox.x)

      const copy = header.locator('[data-testid="thread-header-copy"]')
      const lock = header.locator('[data-testid="thread-header-rename"]')
      await expect(copy).toHaveAttribute('aria-label', 'Copy join id')
      const copyBox = (await copy.boundingBox())!
      const lockBox = (await lock.boundingBox())!
      expect(copyBox.x - (lockBox.x + lockBox.width)).toBeLessThan(16)

      const dates = header.locator('[data-testid="thread-header-dates"]')
      const datesBox = (await dates.boundingBox())!
      expect(datesBox.x + datesBox.width).toBeLessThan(headerBox.x + headerBox.width - 8)

      const row2 = header.locator('[data-testid="thread-header-row2"]')
      await expect(row2.locator('[data-testid="thread-header-project-badge"]')).toHaveText(/\S+/)
      await expect(row2).not.toContainText(`FE-9743 project ${stamp}`)

      if (SHOTS) await page.screenshot({ path: `${SHOTS}/project_thread_${vp.name}.png`, fullPage: true })
    })
  }
})
