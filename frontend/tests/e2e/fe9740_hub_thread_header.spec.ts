/**
 * fe9740_hub_thread_header.spec.ts — FE-9740
 *
 * The open thread's header and timeline: every message carries its date, Created is
 * primary-text and Last msg is the accent yellow, the product name always and the project
 * (badge + title) on a project-bound thread, no product retag menu, and (FE-9742) the
 * scope note as the last line of the roster frame under the header.
 *
 * Needs the local CE backend (:7272), a frontend on PLAYWRIGHT_TEST_BASE_URL, and
 * TEST_USER / TEST_PASSWORD. Logs in through the real form on the frontend under test.
 *
 * Edition scope: Both.
 */
import { test, expect, Page } from '@playwright/test'
import { createTestProject, deleteTestProject, authHeaders } from './helpers'

const API = 'http://localhost:7272'

async function login(page: Page): Promise<void> {
  await page.goto('/login')
  await page.locator('[data-testid="email-input"] input').fill(process.env.TEST_USER || '')
  await page.locator('[data-testid="password-input"] input').fill(process.env.TEST_PASSWORD || '')
  await page.click('[data-testid="login-button"]')
  await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 10000 })
  await page.waitForLoadState('networkidle')
}

async function createThread(page: Page, body: Record<string, unknown>): Promise<{ thread_id: string; chat_id: string }> {
  const res = await page.request.post(`${API}/api/v1/threads`, { headers: await authHeaders(page), data: body })
  expect(res.ok()).toBeTruthy()
  return res.json()
}

test.describe('Hub thread header (FE-9740)', () => {
  let projectId = ''
  const stamp = Date.now()

  test.beforeEach(async ({ page }) => {
    await login(page)
  })

  test.afterEach(async ({ page }) => {
    if (!projectId) return
    try {
      await deleteTestProject(page, projectId)
    } catch {
      // already gone
    }
    projectId = ''
  })

  test('general thread: dated message, coloured dates, product name, no retag, note in the roster frame', async ({ page }) => {
    const products = await (await page.request.get(`${API}/api/v1/products/`, { headers: await authHeaders(page) })).json()
    const product = products[0]
    const thread = await createThread(page, { subject: `FE-9740 general ${stamp}`, product_id: product?.id })
    await page.request.post(`${API}/api/v1/threads/${thread.thread_id}/post`, {
      headers: await authHeaders(page),
      data: { content: 'dated message' },
    })

    await page.goto(`/hub?thread=${thread.thread_id}`)
    const header = page.locator('[data-testid="thread-header"]')
    await expect(header).toBeVisible()

    await expect(page.locator('[data-testid="message-time"]').first()).toHaveText(/[A-Z][a-z]{2} \d{1,2}, \d{4}, \d{2}:\d{2}/)

    const created = header.locator('[data-testid="thread-dates-created"]')
    const last = header.locator('[data-testid="thread-dates-last-message"]')
    const colour = (loc: typeof created) => loc.evaluate((el) => getComputedStyle(el).color)
    const primary = await header.locator('[data-testid="thread-header-title"]').evaluate((el) => getComputedStyle(el).color)
    expect(await colour(created)).toBe(primary)
    expect(await colour(last)).not.toBe(primary)
    expect(await colour(last)).toBe('rgb(255, 195, 0)')

    await expect(header.locator('[data-testid="thread-header-product"]')).toHaveText(product.name)
    await expect(header.locator('[data-testid="thread-header-project"]')).toHaveCount(0)
    await expect(header.locator('[data-testid="thread-header-retag"]')).toHaveCount(0)

    const roster = page.locator('[data-testid="thread-roster"]')
    await expect(roster.locator('[data-testid="thread-roster-scope"]')).toContainText('next poll')
    await expect(header.locator('[data-testid="thread-header-scope"]')).toHaveCount(0)

    await page.screenshot({ path: process.env.FE9740_SHOT_DIR ? `${process.env.FE9740_SHOT_DIR}/general.png` : undefined })
  })

  test('project thread: project badge and title', async ({ page }) => {
    projectId = await createTestProject(page, { name: `FE-9740 project ${stamp}` })
    const thread = await createThread(page, { subject: `FE-9740 project ${stamp}`, project_id: projectId })
    await page.goto(`/hub?thread=${thread.thread_id}`)
    const header = page.locator('[data-testid="thread-header"]')
        await expect(header.locator('[data-testid="thread-header-project-badge"]')).toHaveText(/\S+/)
    await expect(header.locator('[data-testid="thread-header-project"]')).toContainText(`FE-9740 project ${stamp}`)
    await page.screenshot({ path: process.env.FE9740_SHOT_DIR ? `${process.env.FE9740_SHOT_DIR}/project.png` : undefined })
  })
})
