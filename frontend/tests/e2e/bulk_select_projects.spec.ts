/**
 * bulk_select_projects.spec.ts — FE-9641
 *
 * Projects list: one tick-box column drives every bulk action. Tick rows,
 * send them to archive, unarchive them, delete a ticked set after the
 * count-naming confirmation, and Chain two inactive projects through the
 * confirm step that shows the run order (cancel creates nothing).
 *
 * Edition scope: Both.
 */
import { test, expect, Page } from '@playwright/test'
import { loginAsDefaultTestUser, createTestProject, deleteTestProject, reportRateLimiting } from './helpers'

const rowCheckbox = (page: Page, name: string) => page.locator('tr', { hasText: name }).locator('input[type="checkbox"]')

// useProjectBulkActions shows the toast and only THEN awaits the list reload, so
// the toast is not a signal that the table has caught up. Wait for the reload
// itself before asserting on rows.
const listReloaded = (page: Page) =>
  page.waitForResponse((r) => r.url().includes('/api/v1/projects/') && r.request().method() === 'GET')

test.describe('Projects bulk select', () => {
  let names: string[]
  let createdIds: string[]

  test.beforeEach(async ({ page }) => {
    reportRateLimiting(page)
    await loginAsDefaultTestUser(page)
    const stamp = Date.now()
    names = [`E2E bulk project A ${stamp}`, `E2E bulk project B ${stamp}`]
    createdIds = []
    for (const name of names) createdIds.push(await createTestProject(page, { name }))
    await page.goto('/projects')
    await page.waitForLoadState('networkidle')
    await page.locator('input[aria-label="Search projects by name"]').fill(`${stamp}`)
    for (const name of names) await expect(page.locator('tr', { hasText: name })).toBeVisible()
  })

  // The chain test leaves its two projects (and their run) behind, and a failed
  // run leaves whatever it got to. Clear them so a rerun starts from the same
  // place every time; the stamped names already keep the runs from colliding.
  test.afterEach(async ({ page }) => {
    for (const id of createdIds) {
      try {
        await deleteTestProject(page, id)
      } catch {
        // Already deleted by the test itself, or the session is gone.
      }
    }
  })

  test('archive, view Archived, unarchive, then delete', async ({ page }) => {
    for (const name of names) await rowCheckbox(page, name).check()
    const bar = page.locator('[data-testid="bulk-action-bar"]')
    await expect(bar.locator('[data-testid="bulk-count"]')).toHaveText('2 selected')

    let reload = listReloaded(page)
    await bar.locator('[data-testid="bulk-archive"]').click()
    await expect(page.getByText('2 archived')).toBeVisible()
    await reload
    // Search reveals archived rows, badged; they are now marked Archived.
    for (const name of names) {
      await expect(page.locator('tr', { hasText: name }).locator('[data-test="project-archived-badge"]')).toBeVisible()
    }
    await expect(page.locator('.filter-cta-archive')).toHaveCount(0)

    for (const name of names) await rowCheckbox(page, name).check()
    reload = listReloaded(page)
    await bar.locator('[data-testid="bulk-unarchive"]').click()
    await expect(page.getByText('2 unarchived')).toBeVisible()
    await reload

    for (const name of names) await rowCheckbox(page, name).check()
    await bar.locator('[data-testid="bulk-delete"]').click()
    await expect(page.getByText('Delete 2 projects?', { exact: true })).toBeVisible()
    reload = listReloaded(page)
    await page.getByRole('button', { name: 'Delete 2' }).click()
    await expect(page.getByText('2 deleted')).toBeVisible()
    await reload
    for (const name of names) await expect(page.locator('tr', { hasText: name })).toHaveCount(0)
  })

  test('Chain shows the run order first; cancel creates nothing, start opens the chain', async ({ page }) => {
    // One tick-box column only: no link-mode button, no Linked column.
    await expect(page.locator('.filter-cta-link')).toHaveCount(0)
    await expect(page.getByRole('columnheader', { name: 'Linked' })).toHaveCount(0)

    for (const name of names) await rowCheckbox(page, name).check()
    await page.locator('[data-testid="bulk-chain"]').click()

    const order = page.locator('[data-testid="chain-order"] li')
    await expect(order).toHaveCount(2)
    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(page).toHaveURL(/\/projects/)

    await page.locator('[data-testid="bulk-chain"]').click()
    await page.getByRole('button', { name: 'Start chain (2)' }).click()
    // The chain's head project opens with the run in the query string.
    await expect(page).toHaveURL(/\/projects\/[^/?]+\?run=/)
  })
})
