/**
 * Playwright E2E Test: Tools -> Agents view switcher (FE-9643b)
 *
 * Tools -> Agents now switches between four views -- Roster (the default),
 * Behaviour, Handover template, and Orchestrator prompt -- via four square
 * icon-only buttons inside the toolbar's own control row (operator decisions
 * 1/2/7, 2026-09-23, approved mock:
 * /mnt/scraps/Orchestration/EM_113/handover_chain_mock_tools_agents.html).
 * Behaviour used to be a dialog; the orchestrator prompt used to live in the
 * account Danger Zone. This test proves the four views are actually
 * reachable end to end: the lit button, the `?tab=agents&view=...` URL, the
 * toolbar staying put (kebab + New template never disappear), and each
 * view's own content -- not just the unit-level wiring.
 *
 * Server Base URL: http://localhost:7272
 * Frontend Base URL: http://localhost:7274
 * Test User: TEST_USER env var (admin, so the Orchestrator prompt button
 * is reachable -- its endpoints are admin-only)
 */

import { test, expect } from '@playwright/test'
import { loginAsDefaultTestUser } from './helpers.ts'

const BASE_URL = 'http://localhost:7274'

test.describe('Tools -> Agents view switcher (FE-9643b)', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsDefaultTestUser(page)
  })

  test('switches between the four views, lighting the button and tracking the URL', async ({
    page,
  }) => {
    await page.goto(`${BASE_URL}/tools?tab=agents`)
    await page.waitForLoadState('networkidle')

    // Roster is the default view.
    await expect(page.locator('[data-testid="agents-view-roster"]')).toHaveAttribute(
      'data-active',
      'true',
    )
    await expect(page.locator('[data-testid="show-all-products"]')).toBeVisible()

    // Behaviour: a view now, not a dialog -- the five settings render inline,
    // the roster's own filters disappear, but the toolbar itself stays (kebab
    // and New template remain reachable, operator decision 2).
    await page.click('[data-testid="agents-view-behaviour"]')
    await expect(page).toHaveURL(/view=behaviour/)
    await expect(page.locator('[data-testid="agents-view-behaviour"]')).toHaveAttribute(
      'data-active',
      'true',
    )
    await expect(page.locator('[data-test="execution-mode-default-setting"]')).toBeVisible()
    await expect(page.locator('[data-testid="show-all-products"]')).toHaveCount(0)
    await expect(page.locator('[data-testid="product-bulk-menu"]')).toBeVisible()
    await expect(page.locator('[data-testid="new-template"]')).toBeVisible()

    // Handover template: the editor loads.
    await page.click('[data-testid="agents-view-handover"]')
    await expect(page).toHaveURL(/view=handover/)
    await expect(page.locator('[data-test="handover-template-textarea"]')).toBeVisible()

    // Orchestrator prompt: moved here from the account Danger Zone.
    await page.click('[data-testid="agents-view-prompt"]')
    await expect(page).toHaveURL(/view=prompt/)
    await expect(page.getByText('System Orchestrator Prompt')).toBeVisible()

    // Back to Roster: the URL param drops and the filters return.
    await page.click('[data-testid="agents-view-roster"]')
    await expect(page).not.toHaveURL(/view=/)
    await expect(page.locator('[data-testid="show-all-products"]')).toBeVisible()
  })

  test('the Danger Zone points an admin at the relocated prompt editor', async ({ page }) => {
    await page.goto(`${BASE_URL}/account/danger`)
    await page.waitForLoadState('networkidle')

    await expect(page.locator('[data-test="orchestrator-prompt-section"]')).toBeVisible()
    await page.click('[data-test="orchestrator-prompt-link"]')

    await expect(page).toHaveURL(/\/tools\?.*view=prompt/)
    await expect(page.getByText('System Orchestrator Prompt')).toBeVisible()
  })
})
