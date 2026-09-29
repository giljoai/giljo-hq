/**
 * fe9680_all_products_board.spec.ts — FE-9680
 *
 * The Jobs board shows every product: land on All with two products each
 * holding an activated project, see two groups, fold one, narrow to a product
 * tab, widen to All again.
 *
 * Needs the local CE stack (backend :7272, frontend :7274) and TEST_USER /
 * TEST_PASSWORD. Written in a cloud session without the stack; the EM runs
 * it live before merge.
 *
 * Edition scope: Both.
 */
import { test, expect, Page } from '@playwright/test'
import { loginAsDefaultTestUser, openBoardCardsDetailed, createTestProject, deleteTestProject, reportRateLimiting, authHeaders } from './helpers'

const API = 'http://localhost:7272'

async function createProduct(page: Page, name: string): Promise<string> {
  const res = await page.request.post(`${API}/api/v1/products/`, {
    headers: await authHeaders(page),
    data: { name, description: 'E2E product for the all-products Jobs board' },
  })
  expect(res.ok()).toBeTruthy()
  const body = await res.json()
  return body.id || body.product?.id
}

async function activate(page: Page, projectId: string): Promise<void> {
  const res = await page.request.post(`${API}/api/v1/projects/${projectId}/activate`, {
    headers: await authHeaders(page),
    data: { force: false },
  })
  expect(res.ok()).toBeTruthy()
}

test.describe('Jobs board, all products', () => {
  const projectIds: string[] = []
  let secondProductId = ''
  const stamp = Date.now()
  const nameA = `E2E all-products A ${stamp}`
  const nameB = `E2E all-products B ${stamp}`
  const secondProductName = `E2E product ${stamp}`

  test.beforeEach(async ({ page }) => {
    reportRateLimiting(page)
    await openBoardCardsDetailed(page)
    await loginAsDefaultTestUser(page)
    const a = await createTestProject(page, { name: nameA })
    projectIds.push(a)
    await activate(page, a)
    secondProductId = await createProduct(page, secondProductName)
    const b = await createTestProject(page, { name: nameB, product_id: secondProductId })
    projectIds.push(b)
    await activate(page, b)
  })

  test.afterEach(async ({ page }) => {
    for (const id of projectIds.splice(0)) {
      try {
        await deleteTestProject(page, id)
      } catch {
        // Already removed or session gone.
      }
    }
    if (secondProductId) {
      try {
        await page.request.delete(`${API}/api/v1/products/${secondProductId}`, { headers: await authHeaders(page) })
      } catch {
        // Best effort.
      }
    }
  })

  test('lands on All with one group per product, folds, narrows and widens', async ({ page }) => {
    await page.goto('/jobs-overview')

    const allTab = page.locator('[data-testid="product-tab-all"]')
    await expect(allTab).toBeVisible()
    await expect(allTab).toHaveAttribute('aria-selected', 'true')

    // Both activated projects wait on the Staging side, one group each.
    const stagingSide = page.locator('[data-testid="jobs-side-staging"]')
    if ((await stagingSide.getAttribute('aria-pressed')) !== 'true') await stagingSide.click()
    // Only OUR groups are asserted: the tenant may have other products in flight.
    const groups = page.locator('[data-testid="jobs-product-group"]')
    await expect(groups.filter({ hasText: nameA })).toHaveCount(1)
    const groupB = groups.filter({ hasText: secondProductName })
    await expect(groupB).toHaveCount(1)
    await expect(groupB.locator('[data-testid="jobs-board-card-wrap"]').filter({ hasText: nameB })).toBeVisible()

    // Fold the second product: its card goes, its header stays.
    await groupB.locator('[data-testid="jobs-product-group-fold"]').click()
    await expect(groupB.locator('[data-testid="jobs-board-card-wrap"]')).toHaveCount(0)
    await expect(groupB.locator('[data-testid="jobs-product-group-name"]')).toHaveText(secondProductName)

    // A product tab narrows the board: no groups, only that product's card.
    await page.locator(`[data-testid="product-tab-${secondProductId}"]`).click()
    await expect(page.locator('[data-testid="jobs-product-group"]')).toHaveCount(0)
    await expect(page.locator('[data-testid="jobs-board-card-wrap"]').filter({ hasText: nameB })).toBeVisible()
    await expect(page.locator('[data-testid="jobs-board-card-wrap"]').filter({ hasText: nameA })).toHaveCount(0)

    // All widens it again: both of OUR groups are back (other products may be
    // in flight on this tenant, so never assert a global count).
    await allTab.click()
    await expect(page.locator('[data-testid="jobs-product-group"]').filter({ hasText: nameA })).toHaveCount(1)
    await expect(page.locator('[data-testid="jobs-product-group"]').filter({ hasText: secondProductName })).toHaveCount(1)

    // The All tab is a Jobs-page thing: it is gone on the Projects list.
    await page.goto('/projects')
    await expect(page.locator('[data-testid="product-tab-all"]')).toHaveCount(0)
  })
})
