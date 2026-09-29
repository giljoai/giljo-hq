/**
 * jobs_nav_one_landing.spec.ts — FE-9655e
 *
 * The Jobs menu item opens the Jobs board, and keeps opening the board when the
 * viewed product tab changes. Two product tabs are opened over REST: the default
 * product, which gets a project, and a second product that has nothing at all.
 * Before this project those two tabs made "Jobs" mean two different screens.
 *
 * Also walks the legacy URLs: /jobs and /launch both land on the board.
 *
 * No agents are spawned here, so no agent name is involved.
 *
 * Needs the local CE stack (backend :7272, frontend :7274) and TEST_USER /
 * TEST_PASSWORD.
 *
 * Edition scope: Both.
 */
import { test, expect } from '@playwright/test'
import {
  loginAsDefaultTestUser, openBoardCardsDetailed,
  createTestProject,
  deleteTestProject,
  reportRateLimiting,
  authHeaders,
} from './helpers'

const API = 'http://localhost:7272'

test.describe('Jobs nav — one landing', () => {
  let projectId = ''
  let secondProductId = ''

  test.beforeEach(async ({ page }) => {
    reportRateLimiting(page)
    await openBoardCardsDetailed(page)
    await loginAsDefaultTestUser(page)
    const headers = await authHeaders(page)
    const stamp = Date.now()

    // This test lands on /home (WelcomeView), which auto-opens the setup
    // wizard over the whole page whenever the shared test user's own
    // onboarding is incomplete (WelcomeView.vue onMounted: `!setupComplete.value`).
    // The wizard overlay then intercepts the Jobs nav click. That per-user
    // progress is unrelated to this spec's assertions, so force it complete
    // the same way "Skip, I'll do this later" does server-side.
    const setupState = await page.request.patch(`${API}/api/auth/me/setup-state`, {
      headers,
      data: { setup_complete: true },
    })
    expect(setupState.ok(), `setup-state PATCH returned ${setupState.status()}`).toBeTruthy()

    projectId = await createTestProject(page, { name: `E2E jobs landing ${stamp}` })

    // A second product, opened as a tab, with no projects and nothing in flight.
    const created = await page.request.post(`${API}/api/v1/products/`, {
      headers,
      data: { name: `E2E empty product ${stamp}`, description: 'Second tab for the Jobs landing walk' },
    })
    expect(created.ok(), `product create returned ${created.status()}`).toBeTruthy()
    secondProductId = (await created.json()).id
    // is_active is what puts a product in the tab strip.
    await page.request.post(`${API}/api/v1/products/${secondProductId}/activate`, { headers })
  })

  test.afterEach(async ({ page }) => {
    const headers = await authHeaders(page).catch(() => null)
    if (projectId) await deleteTestProject(page, projectId).catch(() => undefined)
    if (headers && secondProductId) {
      await page.request.delete(`${API}/api/v1/products/${secondProductId}`, { headers }).catch(() => undefined)
    }
    projectId = ''
    secondProductId = ''
  })

  test('Jobs opens the board, and stays the board across product tabs', async ({ page }) => {
    await page.goto('/home')

    const jobsItem = page.locator('.nav-items').getByText('Jobs', { exact: true })
    await expect(jobsItem).toBeVisible()
    await jobsItem.click()
    await expect(page).toHaveURL(/\/jobs-overview/)

    const tabs = page.locator('[data-testid="product-tab-strip"] [data-testid^="product-tab-"]')
    await expect(tabs.first()).toBeVisible()

    // Switch to the empty product: the board stays the destination and shows its
    // own empty state rather than sending the user to another screen.
    await page.locator(`[data-testid="product-tab-${secondProductId}"]`).click()
    await expect(page).toHaveURL(/\/jobs-overview/)
    await expect(page.locator('[data-testid="jobs-board-empty"]')).toBeVisible()

    // Leave the board, come back through the nav on the empty tab: still the board.
    await page.goto('/projects')
    await jobsItem.click()
    await expect(page).toHaveURL(/\/jobs-overview/)

    // Switch back to the product that has a project: same landing.
    await page.locator('[data-testid="product-tab-strip"] [data-testid^="product-tab-"]').first().click()
    await expect(page).toHaveURL(/\/jobs-overview/)
    await page.goto('/home')
    await jobsItem.click()
    await expect(page).toHaveURL(/\/jobs-overview/)
  })

  test('the legacy /jobs and /launch URLs land on the board', async ({ page }) => {
    await page.goto('/jobs')
    await expect(page).toHaveURL(/\/jobs-overview/)

    await page.goto('/launch')
    await expect(page).toHaveURL(/\/jobs-overview/)

    await page.goto('/launch?via=jobs')
    await expect(page).toHaveURL(/\/jobs-overview/)
  })
})
