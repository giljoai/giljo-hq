/**
 * fe9742_hub_thread_view.spec.ts — FE-9742
 *
 * The open thread as two frames: a two-row main frame with ONE "Copy join id" control, and
 * a collapsible agent roster frame carrying the scope note. Collapsed state survives a
 * reload. A project thread shows its taxonomy badge and title with no label words; a
 * standalone thread shows a muted "General".
 *
 * Needs the local CE backend (:7272), a frontend on PLAYWRIGHT_TEST_BASE_URL, and
 * TEST_USER / TEST_PASSWORD. Set FE9742_SHOT_DIR to keep screenshots.
 *
 * Edition scope: Both.
 */
import { test, expect, Page } from '@playwright/test'
import { createTestProject, deleteTestProject, authHeaders } from './helpers'

const API = 'http://localhost:7272'
const SHOTS = process.env.FE9742_SHOT_DIR

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

const shot = (page: Page, name: string) =>
  SHOTS ? page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true }) : Promise.resolve(undefined)

test.describe('Hub thread view frames (FE-9742)', () => {
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

  test('project thread: two-row frame, roster collapses and stays collapsed after a reload', async ({ page }) => {
    projectId = await createTestProject(page, { name: `FE-9742 project ${stamp}` })
    const thread = await createThread(page, { subject: `FE-9742 project ${stamp}`, project_id: projectId })
    await page.request.post(`${API}/api/v1/threads/${thread.thread_id}/post`, {
      headers: await authHeaders(page),
      data: { content: 'compact row' },
    })
    await page.goto(`/hub?thread=${thread.thread_id}`)

    const header = page.locator('[data-testid="thread-header"]')
    const row1 = header.locator('[data-testid="thread-header-row1"]')
    const row2 = header.locator('[data-testid="thread-header-row2"]')
    await expect(row1.locator('[data-testid="thread-header-copy"]')).toHaveAttribute('aria-label', 'Copy join id')
    await expect(header.locator('[data-testid="thread-header-id"]')).toHaveCount(0)
    await expect(header).not.toContainText('join_thread')
    await expect(row2.locator('[data-testid="thread-header-project-badge"]')).toHaveText(/\S+/)
    await expect(row2).not.toContainText('Project:')
    await expect(row2).not.toContainText('Product:')

    const roster = page.locator('[data-testid="thread-roster"]')
    await expect(roster.locator('[data-testid="thread-roster-scope"]')).toContainText('project record')
    const headerBox = await header.boundingBox()
    const rosterBox = await roster.boundingBox()
    expect(rosterBox!.y).toBeGreaterThan(headerBox!.y + headerBox!.height - 1)
    await shot(page, 'project_expanded')

    await roster.locator('[data-testid="thread-roster-toggle"]').click()
    await expect(roster.locator('[data-testid="thread-roster-scope"]')).toHaveCount(0)
    await shot(page, 'project_collapsed')

    await page.reload()
    await expect(page.locator('[data-testid="thread-roster-toggle"]')).toHaveText(/Expand/)
    await page.locator('[data-testid="thread-roster-toggle"]').click()
    await expect(page.locator('[data-testid="thread-roster-toggle"]')).toHaveText(/Collapse/)
  })

  test('standalone thread: muted General and the product name', async ({ page }) => {
    const products = await (await page.request.get(`${API}/api/v1/products/`, { headers: await authHeaders(page) })).json()
    const thread = await createThread(page, { subject: `FE-9742 general ${stamp}`, product_id: products[0]?.id })
    await page.goto(`/hub?thread=${thread.thread_id}`)

    const row2 = page.locator('[data-testid="thread-header-row2"]')
    await expect(row2.locator('[data-testid="thread-header-general"]')).toHaveText('General')
    await expect(row2.locator('[data-testid="thread-header-product"]')).toHaveText(products[0].name)
    await expect(page.locator('[data-testid="thread-roster-scope"]')).toContainText('next poll')
    await shot(page, 'standalone')
  })
})
