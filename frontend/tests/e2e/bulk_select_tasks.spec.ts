/**
 * bulk_select_tasks.spec.ts — FE-9641
 *
 * Tasks list: tick rows, see the action bar, send them to archive, find them
 * under the "Archived" status filter, unarchive them, then delete them after
 * the count-naming confirmation.
 *
 * Edition scope: Both.
 */
import { test, expect, Page } from '@playwright/test'
import { loginAsDefaultTestUser, reportRateLimiting } from './helpers'

async function createTask(page: Page, title: string) {
  await page.click('[data-testid="add-task-menu-btn"]')
  await page.click('[data-testid="new-task-menu-item"]')
  // Scope the button to the open dialog. Vuetify moves the dialog's content
  // into the overlay container as it opens, so a page-wide match can resolve to
  // a node that is about to be re-parented and the click hits a detached
  // element. Waiting for the dialog first, then matching inside it, clicks the
  // button that is actually mounted.
  const dialog = page.locator('.v-dialog').filter({ has: page.locator('[data-test="edit-task-title"]') })
  await expect(dialog).toBeVisible()
  await dialog.locator('[data-test="edit-task-title"] input').fill(title)
  await dialog.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('.v-dialog')).not.toBeVisible()
}

const rowCheckbox = (page: Page, title: string) => page.locator('tr', { hasText: title }).locator('input[type="checkbox"]')

async function pickStatusFilter(page: Page, label: RegExp) {
  await page.locator('.filter-select').first().click()
  await page.getByRole('option', { name: label }).click()
}

test.describe('Tasks bulk select', () => {
  test.beforeEach(async ({ page }) => {
    reportRateLimiting(page)
    await loginAsDefaultTestUser(page)
    await page.goto('/tasks')
    await page.waitForLoadState('networkidle')
  })

  test('archive, find under Archived, unarchive, then delete a ticked set', async ({ page }) => {
    const stamp = Date.now()
    const titles = [`E2E bulk task A ${stamp}`, `E2E bulk task B ${stamp}`]
    for (const title of titles) await createTask(page, title)

    for (const title of titles) await rowCheckbox(page, title).check()
    const bar = page.locator('[data-testid="bulk-action-bar"]')
    await expect(bar).toBeVisible()
    await expect(bar.locator('[data-testid="bulk-count"]')).toHaveText('2 selected')

    await bar.locator('[data-testid="bulk-archive"]').click()
    await expect(page.getByText('2 archived')).toBeVisible()
    for (const title of titles) await expect(page.locator('tr', { hasText: title })).toHaveCount(0)

    // "Archived" lives in the status filter now; the old toggle is gone.
    await expect(page.locator('.filter-cta-archive')).toHaveCount(0)
    await pickStatusFilter(page, /^Archived \(\d+\)$/)
    for (const title of titles) await expect(page.locator('tr', { hasText: title })).toBeVisible()

    for (const title of titles) await rowCheckbox(page, title).check()
    await bar.locator('[data-testid="bulk-unarchive"]').click()
    await expect(page.getByText('2 unarchived')).toBeVisible()

    await page.locator('.filter-select').first().locator('.v-field__clearable').click()
    for (const title of titles) await rowCheckbox(page, title).check()
    await bar.locator('[data-testid="bulk-delete"]').click()
    await expect(page.getByText('Delete 2 tasks?', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Delete 2' }).click()
    await expect(page.getByText('2 deleted')).toBeVisible()
    for (const title of titles) await expect(page.locator('tr', { hasText: title })).toHaveCount(0)
  })
})
