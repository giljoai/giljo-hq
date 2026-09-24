/**
 * handover_dialog.spec.ts — FE-9643c
 *
 * The "+" on the Tasks list offers a "New Agent Handover" entry that opens a
 * dialog pre-filled from the account's live handover template, and refuses
 * to save while any of the three required sections is still an untouched
 * placeholder or genuinely empty.
 *
 * Edition scope: Both.
 */
import { test, expect } from '@playwright/test'
import { loginAsDefaultTestUser } from './helpers'

test.describe('New Agent Handover dialog', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsDefaultTestUser(page)
    await page.goto('/tasks')
    await page.waitForLoadState('networkidle')
  })

  test('the + menu offers New task and New Agent Handover, and the handover pre-fills from the template', async ({ page }) => {
    await page.click('[data-testid="add-task-menu-btn"]')
    await expect(page.locator('[data-testid="new-task-menu-item"]')).toBeVisible()
    await expect(page.locator('[data-testid="new-handover-menu-item"]')).toBeVisible()

    await page.click('[data-testid="new-handover-menu-item"]')

    await expect(page.locator('.dlg-title')).toContainText('New Agent Handover')
    await expect(page.locator('[data-test="handover-pill"]')).toBeVisible()
    await expect(page.locator('[data-test="handover-pill"]')).toContainText('HND')

    // Started from the template: the description textarea is not empty, and
    // the checklist starts incomplete (untouched placeholders never count).
    const description = page.locator('[data-test="handover-checklist"]').locator('..').locator('textarea')
    await expect(description).not.toHaveValue('')
    await expect(page.locator('[data-test="handover-gap-message"]')).toBeVisible()

    // An untouched dialog cannot save.
    const saveButton = page.getByRole('button', { name: /Create/i })
    await expect(saveButton).toBeDisabled()
  })

  test('write a handover, save it, and see it in the list with the HND pill', async ({ page }) => {
    const title = `E2E handover test ${Date.now()}`

    await page.click('[data-testid="add-task-menu-btn"]')
    await page.click('[data-testid="new-handover-menu-item"]')

    await page.locator('[data-test="edit-task-title"] input').fill(title)

    const description = page.locator('[data-test="handover-checklist"]').locator('..').locator('textarea')
    await description.fill(
      [
        '## Verify before trusting',
        '- checked with `npx vitest run`, all green',
        '',
        '## Waiting on the operator',
        '- nothing',
        '',
        '## Cannot testify',
        '- nothing',
      ].join('\n'),
    )

    await expect(page.locator('[data-test="handover-gap-message"]')).toHaveCount(0)
    const saveButton = page.getByRole('button', { name: /Create/i })
    await expect(saveButton).toBeEnabled()

    await saveButton.click()
    await expect(page.locator('.v-dialog')).not.toBeVisible()

    // The saved handover shows in the list with the HND taxonomy badge.
    const row = page.locator('tr', { hasText: title })
    await expect(row).toBeVisible()
    await expect(row.locator('.taxonomy-badge')).toContainText('HND')
  })
})
