/**
 * fe9685_board_opens_compact.spec.ts — FE-9685
 *
 * A fresh browser opens the Jobs board Compact: every card folded to its one
 * line, a card that needs the operator too. Detailed opens them, Compact folds
 * them again.
 *
 * Needs the local CE stack (backend :7272, frontend :7274) and TEST_USER /
 * TEST_PASSWORD.
 *
 * Edition scope: Both.
 */
import { test, expect } from '@playwright/test'
import { loginAsDefaultTestUser, createTestProject, deleteTestProject, reportRateLimiting, authHeaders } from './helpers'

const API = 'http://localhost:7272'

test.describe('Jobs board default density (FE-9685)', () => {
  let projectId = ''
  let projectName = ''

  test.beforeEach(async ({ page }) => {
    reportRateLimiting(page)
    await loginAsDefaultTestUser(page)
    projectName = `E2E compact default ${Date.now()}`
    projectId = await createTestProject(page, { name: projectName })
    const activate = await page.request.post(`${API}/api/v1/projects/${projectId}/activate`, {
      headers: await authHeaders(page),
      data: { force: false },
    })
    expect(activate.ok()).toBeTruthy()
  })

  test.afterEach(async ({ page }) => {
    if (!projectId) return
    try {
      await deleteTestProject(page, projectId)
    } catch {
      // Session gone or already removed.
    }
  })

  test('opens Compact with the card folded; Detailed opens it; Compact folds it again', async ({ page }) => {
    await page.goto('/jobs-overview')
    await page.locator('[data-testid="jobs-side-staging"]').click()
    const card = page.locator('[data-testid="jobs-board-card-wrap"]').filter({ hasText: projectName })
    await expect(card).toBeVisible()

    await expect(page.locator('[data-testid="jobs-density-compact"]')).toHaveAttribute('aria-pressed', 'true')
    await expect(card.locator('[data-testid="jb-summary"]')).toBeVisible()
    await expect(card.locator('[data-testid="jb-footer"]')).toHaveCount(0)

    await page.locator('[data-testid="jobs-density-detailed"]').click()
    await expect(card.locator('[data-testid="jb-summary"]')).toHaveCount(0)
    await expect(card.locator('[data-testid="jb-footer"]')).toBeVisible()

    await page.locator('[data-testid="jobs-density-compact"]').click()
    await expect(card.locator('[data-testid="jb-summary"]')).toBeVisible()
  })
})
