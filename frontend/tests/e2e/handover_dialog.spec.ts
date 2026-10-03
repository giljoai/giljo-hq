/**
 * handover_dialog.spec.ts
 *
 * The "+" on the Tasks list offers a "New Agent Handover" entry that opens a
 * dialog with six plain, optional fields. Nothing is required; the filled
 * fields are saved under the agent headings.
 *
 * Edition scope: Both.
 */
import { test, expect } from '@playwright/test'
import { loginAsDefaultTestUser } from './helpers'

const FIELD_KEYS = ['prior-work', 'next-steps', 'please-validate', 'human-approvals', 'unknowns', 'links']

test.describe('New Agent Handover dialog', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsDefaultTestUser(page)
    await page.goto('/tasks')
    await page.waitForLoadState('networkidle')
  })

  test('the + menu offers New task and New Agent Handover, and the handover shows six empty optional fields', async ({ page }) => {
    await page.click('[data-testid="add-task-menu-btn"]')
    await expect(page.locator('[data-testid="new-task-menu-item"]')).toBeVisible()
    await expect(page.locator('[data-testid="new-handover-menu-item"]')).toBeVisible()

    await page.click('[data-testid="new-handover-menu-item"]')

    await expect(page.locator('.dlg-title')).toHaveText('Create new Handover')
    await expect(page.locator('[data-test="handover-pill"]')).toHaveCount(0)

    for (const key of FIELD_KEYS) {
      await expect(page.locator(`[data-test="handover-field-${key}"] textarea`)).toHaveValue('')
    }
    await expect(page.locator('[data-test="handover-checklist"]')).toHaveCount(0)
    await expect(page.locator('[data-test="handover-gap-message"]')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeEnabled()
  })

  test('write a handover with one field, save it, and see it in the list with the HND pill', async ({ page }) => {
    const title = `E2E handover test ${Date.now()}`

    await page.click('[data-testid="add-task-menu-btn"]')
    await page.click('[data-testid="new-handover-menu-item"]')

    await page.locator('[data-test="edit-task-title"] input').fill(title)
    await page.locator('[data-test="handover-field-prior-work"] textarea').fill('Stopped at the rebase.')

    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.locator('.v-dialog')).not.toBeVisible()

    const row = page.locator('tr', { hasText: title })
    await expect(row).toBeVisible()
    await expect(row.locator('.taxonomy-badge')).toContainText('HND')
  })
})
